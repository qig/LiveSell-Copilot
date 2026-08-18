from __future__ import annotations

import asyncio
import json

import pytest

from sidestage.agent_core import (
    CoreFailureCode,
    ModelResponse,
    ModelTerminalCall,
    RunStatus,
    ScriptedModelRunner,
)
from sidestage.copilot.profile import register_livesell_reply_agent
from tests.unit.test_livesell_profile import make_reply_task, valid_reply_response


@pytest.mark.parametrize(
    ("response", "failure_code"),
    [
        (
            ModelResponse(model_id="scripted", text="free text", terminal_calls=()),
            CoreFailureCode.MISSING_TERMINAL_CALL,
        ),
        (
            ModelResponse(
                model_id="scripted",
                terminal_calls=(
                    valid_reply_response().terminal_calls[0],
                    valid_reply_response().terminal_calls[0],
                ),
            ),
            CoreFailureCode.MULTIPLE_TERMINAL_CALLS,
        ),
        (
            ModelResponse(
                model_id="scripted",
                terminal_calls=(
                    ModelTerminalCall(tool_name="send_reply", arguments_json="{}"),
                ),
            ),
            CoreFailureCode.UNKNOWN_TOOL,
        ),
        (
            ModelResponse(
                model_id="scripted",
                terminal_calls=(
                    ModelTerminalCall(
                        tool_name="request_reply_send",
                        arguments_json=json.dumps(
                            {
                                "reply_text": "It is $160.",
                                "answer_category": "price",
                                "claims": [
                                    {
                                        "reply_span": "not in reply",
                                        "evidence_ids": ["evd_price_profile"],
                                    }
                                ],
                            }
                        ),
                    ),
                ),
            ),
            CoreFailureCode.MALFORMED_ARGUMENTS,
        ),
    ],
)
def test_livesell_core_failures_never_retry_or_return_intent(
    response: ModelResponse,
    failure_code: CoreFailureCode,
) -> None:
    runner = ScriptedModelRunner([response])
    handle = register_livesell_reply_agent(
        runner,
        model_config_ref="luna-fast-v1",
        monotonic=lambda: 100.0,
    )

    result = asyncio.run(handle.run(make_reply_task()))

    assert result.status is RunStatus.FAILED
    assert result.terminal_intent is None
    assert result.failure.code is failure_code
    assert len(runner.calls) == 1


def test_per_show_dispatch_is_fifo_and_never_exceeds_four_active_calls() -> None:
    class BlockingRunner:
        def __init__(self) -> None:
            self.calls = []
            self.release = {}

        async def run(self, invocation):
            question_id = invocation.request.model_input.to_dict()["question"]["question_id"]
            self.calls.append(question_id)
            event = self.release.setdefault(question_id, asyncio.Event())
            await event.wait()
            return valid_reply_response()

    async def exercise() -> None:
        runner = BlockingRunner()
        handle = register_livesell_reply_agent(
            runner,
            model_config_ref="luna-fast-v1",
        )
        tasks = [
            asyncio.create_task(
                handle.run(
                    make_reply_task(
                        question_id=f"qst_fifo_{index}",
                        show_id="show_velocity",
                    ).model_copy(
                        update={"deadline_monotonic_s": asyncio.get_running_loop().time() + 4}
                    )
                )
            )
            for index in range(5)
        ]
        for _ in range(100):
            if len(runner.calls) == 4:
                break
            await asyncio.sleep(0.001)
        assert runner.calls == ["qst_fifo_0", "qst_fifo_1", "qst_fifo_2", "qst_fifo_3"]

        runner.release["qst_fifo_0"].set()
        for _ in range(100):
            if len(runner.calls) == 5:
                break
            await asyncio.sleep(0.001)
        assert runner.calls[-1] == "qst_fifo_4"
        assert runner.calls == [f"qst_fifo_{index}" for index in range(5)]
        for event in runner.release.values():
            event.set()
        results = await asyncio.gather(*tasks)
        assert all(result.status is RunStatus.SUCCEEDED for result in results)

    asyncio.run(exercise())


def test_sixty_fifth_task_for_one_show_is_rejected_before_provider_work() -> None:
    class BlockingRunner:
        def __init__(self) -> None:
            self.calls = []
            self.release = asyncio.Event()

        async def run(self, invocation):
            self.calls.append(
                invocation.request.model_input.to_dict()["question"]["question_id"]
            )
            await self.release.wait()
            return valid_reply_response()

    async def exercise() -> None:
        runner = BlockingRunner()
        handle = register_livesell_reply_agent(runner, model_config_ref="luna-fast-v1")
        loop = asyncio.get_running_loop()
        tasks = [
            asyncio.create_task(
                handle.run(
                    make_reply_task(
                        question_id=f"qst_capacity_{index}",
                        show_id="show_velocity",
                    ).model_copy(update={"deadline_monotonic_s": loop.time() + 4})
                )
            )
            for index in range(64)
        ]
        await asyncio.sleep(0.02)
        rejected = await handle.run(
            make_reply_task(
                question_id="qst_capacity_64",
                show_id="show_velocity",
            ).model_copy(update={"deadline_monotonic_s": loop.time() + 4})
        )

        assert rejected.status is RunStatus.FAILED
        assert rejected.failure.code is CoreFailureCode.QUEUE_FULL
        assert len(runner.calls) == 4
        runner.release.set()
        await asyncio.gather(*tasks)

    asyncio.run(exercise())
