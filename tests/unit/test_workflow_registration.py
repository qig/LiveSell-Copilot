from sidestage.agent_core import ScriptedModelRunner
from sidestage.copilot.analysis import EVIDENCE_PLANNER_ADAPTER_ID
from sidestage.copilot.profile import (
    LIVESSELL_ADAPTER_ID,
    LIVESSELL_TEMPLATE_ADAPTER_ID,
)
from sidestage.copilot.workflows import (
    register_template_workflow,
    register_two_call_workflow,
)


def test_template_workflow_registers_only_evidence_template_agent() -> None:
    workflow = register_template_workflow(
        ScriptedModelRunner([]),
        model_config_ref="template-fast-v1",
    )

    assert (
        workflow.evidence_template_agent.registered_profile.profile.adapter_id
        == LIVESSELL_TEMPLATE_ADAPTER_ID
    )
    assert set(workflow.__dataclass_fields__) == {"evidence_template_agent"}


def test_two_call_workflow_registers_distinct_planner_and_drafter_agents() -> None:
    workflow = register_two_call_workflow(
        ScriptedModelRunner([]),
        model_config_ref="two-call-fast-v1",
    )

    planner = workflow.evidence_planner_agent.registered_profile.profile
    drafter = workflow.reply_drafter_agent.registered_profile.profile
    assert planner.adapter_id == EVIDENCE_PLANNER_ADAPTER_ID
    assert drafter.adapter_id == LIVESSELL_ADAPTER_ID
    assert planner.adapter_id != drafter.adapter_id
    assert set(workflow.__dataclass_fields__) == {
        "evidence_planner_agent",
        "evidence_planner",
        "reply_drafter_agent",
    }
