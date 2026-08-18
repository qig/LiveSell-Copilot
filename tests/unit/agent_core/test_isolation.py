from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = REPOSITORY_ROOT / "src"


def test_agent_core_imports_and_runs_without_m1_or_m2_modules_or_fixtures() -> None:
    script = textwrap.dedent(
        """
        import builtins
        import importlib.abc
        import io
        import os
        import sys

        BLOCKED_MODULES = (
            "sidestage.app",
            "sidestage.config",
            "sidestage.domain",
            "sidestage.fixtures",
            "sidestage.marketplace",
            "sidestage.storage",
            "sidestage.streaming",
            "sidestage.web",
            "sidestage.copilot",
            "sidestage.livesell",
        )
        BLOCKED_FIXTURES = (
            "fixtures/sellers.json",
            "fixtures/chat_messages.json",
        )

        class BlockM1M2Imports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if any(
                    fullname == blocked or fullname.startswith(blocked + ".")
                    for blocked in BLOCKED_MODULES
                ):
                    raise AssertionError(f"M3A imported forbidden module: {fullname}")
                return None

        def guarded_open(original):
            def wrapper(file, *args, **kwargs):
                candidate = os.fspath(file).replace(os.sep, "/")
                if any(candidate.endswith(blocked) for blocked in BLOCKED_FIXTURES):
                    raise AssertionError(f"M3A opened forbidden fixture: {candidate}")
                return original(file, *args, **kwargs)
            return wrapper

        sys.meta_path.insert(0, BlockM1M2Imports())
        builtins.open = guarded_open(builtins.open)
        io.open = guarded_open(io.open)

        from sidestage.agent_core import (
            AgentProfile,
            AgentTask,
            DeadlinePolicy,
            QueuePolicy,
            TerminalToolSchema,
            register_profile,
        )
        from sidestage.agent_core.evaluation import generate_workload
        from pathlib import Path

        profile = AgentProfile(
            adapter_id="isolated.adapter",
            profile_version="1.0.0",
            system_policy="Choose one terminal tool.",
            input_schema={
                "type": "object",
                "properties": {"prompt": {"type": "string"}},
                "required": ["prompt"],
                "additionalProperties": False,
            },
            terminal_tools=(
                TerminalToolSchema(
                    name="finish",
                    description="Finish the isolated task.",
                    parameters_schema={
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                        "additionalProperties": False,
                    },
                ),
            ),
            queue_policy=QueuePolicy(capacity=2, max_concurrency=1),
            deadline_policy=DeadlinePolicy(
                default_timeout_ms=1_000,
                max_timeout_ms=5_000,
            ),
            model_config_ref="scripted-v1",
            max_model_input_bytes=1_024,
        )
        registered = register_profile(profile)
        task = AgentTask(
            task_id="isolated-task",
            adapter_id=profile.adapter_id,
            profile_version=profile.profile_version,
            profile_digest=registered.digest,
            deadline_monotonic_s=103.0,
            model_input={"prompt": "hello"},
            correlation_metadata={"trace_id": "isolated-trace"},
        )

        projection = registered.project_model_request(task, now_monotonic_s=100.0)
        assert projection.to_provider_dict()["input"] == {"prompt": "hello"}

        workload = generate_workload(
            Path("fixtures/agent_core/pressure_v1.json"),
            seed=20260817,
            model_mode="scripted",
            implementation_commit="isolation-audit",
            worktree_dirty=False,
        )
        assert len(workload.tasks) == 20
        assert workload.manifest["evaluation_scope"] == "agent_core"
        assert not any(
            loaded == blocked or loaded.startswith(blocked + ".")
            for loaded in sys.modules
            for blocked in BLOCKED_MODULES
        )
        """
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SOURCE_ROOT)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
