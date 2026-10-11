"""
MAF Harness Context Providers and Middleware.
Implements Todo Tracking, Operating Modes (Plan vs. Execute), and Tool Approval Policies
as specified in Microsoft Agent Framework Harness.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AgentMode(str, Enum):
    PLAN = "plan"
    EXECUTE = "execute"


class TodoStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class TodoItem(BaseModel):
    id: int
    title: str
    description: str = ""
    status: TodoStatus = TodoStatus.PENDING
    details: Optional[Dict[str, Any]] = None


class ClinicalTodoProvider:
    """Manages clinical decision workflow todos/planning state."""

    DEFAULT_WORKFLOW_STEPS = [
        (1, "Parse clinician input", "Extract lab term, patient value, and units/qualifiers"),
        (2, "Resolve ontology", "Match query to standard LOINC candidates and concepts"),
        (3, "Evaluate Safety Gate", "Deterministic validation against gaps 2, 5, 8, 11"),
        (4, "Synthesize Decision", "Fetch protocol range if PROCEED, or construct HITL clarification"),
    ]

    def __init__(self):
        self.todos: List[TodoItem] = []
        self.reset()

    def reset(self) -> None:
        """Reset to the default diagnostic workflow steps."""
        self.todos = [
            TodoItem(id=step_id, title=title, description=desc)
            for step_id, title, desc in self.DEFAULT_WORKFLOW_STEPS
        ]

    def get_todos(self) -> List[TodoItem]:
        """Return the current list of todos."""
        return list(self.todos)

    def mark_in_progress(self, step_id: int) -> Optional[TodoItem]:
        """Set a todo item status to in_progress."""
        for item in self.todos:
            if item.id == step_id:
                item.status = TodoStatus.IN_PROGRESS
                return item
        return None

    def mark_completed(self, step_id: int, details: Optional[Dict[str, Any]] = None) -> Optional[TodoItem]:
        """Mark a todo item as completed."""
        for item in self.todos:
            if item.id == step_id:
                item.status = TodoStatus.COMPLETED
                if details:
                    item.details = details
                return item
        return None

    def mark_failed(self, step_id: int, reason: str = "") -> Optional[TodoItem]:
        """Mark a todo item as failed."""
        for item in self.todos:
            if item.id == step_id:
                item.status = TodoStatus.FAILED
                item.details = {"error": reason}
                return item
        return None

    def format_todos(self) -> str:
        """Render a formatted markdown checklist of todos."""
        lines = ["### Clinical Decision Workflow Todos:"]
        icons = {
            TodoStatus.PENDING: "[ ]",
            TodoStatus.IN_PROGRESS: "[>]",
            TodoStatus.COMPLETED: "[x]",
            TodoStatus.FAILED: "[!]",
        }
        for item in self.todos:
            icon = icons.get(item.status, "[ ]")
            line = f"- {icon} **Step {item.id}**: {item.title}"
            if item.description:
                line += f" — *{item.description}*"
            lines.append(line)
        return "\n".join(lines)


class ClinicalModeProvider:
    """Manages agent operating modes (Plan vs. Execute)."""

    def __init__(self, initial_mode: AgentMode = AgentMode.EXECUTE):
        self._mode: AgentMode = initial_mode

    @property
    def mode(self) -> AgentMode:
        return self._mode

    def set_mode(self, mode: AgentMode | str) -> AgentMode:
        if isinstance(mode, str):
            mode = AgentMode(mode.lower())
        self._mode = mode
        return self._mode

    def is_plan_mode(self) -> bool:
        return self._mode == AgentMode.PLAN

    def is_execute_mode(self) -> bool:
        return self._mode == AgentMode.EXECUTE


class SafetyGateApprovalPolicy:
    """
    Approval policy for tool invocations in the clinical harness.
    Enforces standing approvals for read-only lookups, and flags
    safety-critical actions or clarifications.
    """

    STANDING_APPROVALS = {
        "parse_clinician_input",
        "resolve_lab_term",
        "evaluate_safety_gate",
        "panel_workup",
    }

    def __init__(self, require_clarification_approval: bool = True):
        self.require_clarification_approval = require_clarification_approval

    def check_approval(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Determines if a tool call is approved automatically or requires human approval.
        Returns:
            {
                "approved": bool,
                "reason": str,
                "requires_hitl": bool
            }
        """
        if tool_name in self.STANDING_APPROVALS:
            return {
                "approved": True,
                "reason": f"Tool '{tool_name}' has standing auto-approval.",
                "requires_hitl": False,
            }

        if tool_name == "fetch_grounded_protocol":
            # Protocol fetching is approved if safety gate passed
            gate_route = (context or {}).get("gate_route")
            if gate_route == "CLARIFY":
                return {
                    "approved": False,
                    "reason": "Safety gate routed to CLARIFY: cannot fetch protocol without resolving ambiguity.",
                    "requires_hitl": True,
                }
            return {
                "approved": True,
                "reason": "Protocol retrieval approved under validated safety gate route.",
                "requires_hitl": False,
            }

        if tool_name == "build_clarification_prompt":
            return {
                "approved": True,
                "reason": "Clarification generation auto-approved for HITL clinician interaction.",
                "requires_hitl": self.require_clarification_approval,
            }

        # Default fallback
        return {
            "approved": True,
            "reason": f"Tool '{tool_name}' auto-approved under default harness policy.",
            "requires_hitl": False,
        }
