"""The two closed SideStage workflow registrations."""

from sidestage.copilot.workflows.template import (
    TemplateWorkflow,
    register_template_workflow,
)
from sidestage.copilot.workflows.two_call import (
    TwoCallWorkflow,
    register_two_call_workflow,
)

__all__ = [
    "TemplateWorkflow",
    "TwoCallWorkflow",
    "register_template_workflow",
    "register_two_call_workflow",
]
