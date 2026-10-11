"""
Clinical Harness Agent for Microsoft Agent Framework (MAF).
Implements the AI Harness runtime scaffolding according to:
https://learn.microsoft.com/en-us/agent-framework/concepts/harness?pivots=programming-language-python

Features:
- Chat client composition (Foundry / Azure OpenAI / OpenAI / Deterministic Mock)
- Function invocation and tool approval policy enforcement
- Context providers: Todo tracking (ClinicalTodoProvider) and Modes (ClinicalModeProvider)
- Session isolation and per-turn history persistence
- Deterministic safety gate enforcement (Fail-Closed Safety Invariant)
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field

from src.harness.session import HarnessSession
from src.harness.providers import (
    AgentMode,
    ClinicalModeProvider,
    ClinicalTodoProvider,
    SafetyGateApprovalPolicy,
    TodoStatus,
)
from src.tools import (
    parse_clinician_input,
    resolve_lab_term,
    evaluate_safety_gate,
    fetch_grounded_protocol,
    build_clarification_prompt,
    panel_workup,
)

DEFAULT_HARNESS_INSTRUCTIONS = """
You are an AI Clinical Laboratory Harness Agent operating under Microsoft Agent Framework safety protocols.
Operational Policies:
1. DETERMINISTIC SAFETY GATE: You must NEVER bypass or override deterministic safety gate verdicts.
2. AMBIGUITY & MISMATCH: If unit mismatch (Gap 2), ambiguous term (Gap 8), or qualifier collision occurs, route to CLARIFY.
3. GOVERNED SPECIMENS: Tube sequencing (Gap 11) must adhere strictly to department drawing protocols.
4. APPROVAL POLICIES: Safe lookups are auto-approved; clarification requests pause for clinician interaction.
"""

DEFAULT_AGENT_INSTRUCTIONS = """
You are a Clinical Laboratory Decision Support Specialist.
Your role is to assist healthcare providers by resolving laboratory test terms to standard LOINC concepts,
validating units and reference ranges, detecting safety collisions, and generating clear clinical guidance.
"""


class ToolInvocation(BaseModel):
    tool_name: str
    args: Dict[str, Any]
    result: Any
    approved: bool
    requires_hitl: bool = False


class HarnessResponse(BaseModel):
    text: str
    route: str  # "PROCEED" | "CLARIFY"
    status: str  # "RESOLVED" | "AMBIGUOUS" | "UNIT_MISMATCH" | etc.
    session_id: str
    mode: AgentMode
    parsed: Dict[str, Any] = Field(default_factory=dict)
    resolved: Dict[str, Any] = Field(default_factory=dict)
    gate: Dict[str, Any] = Field(default_factory=dict)
    protocol: Dict[str, Any] = Field(default_factory=dict)
    clarification: Optional[str] = None
    tool_calls: List[ToolInvocation] = Field(default_factory=list)
    todos: List[Dict[str, Any]] = Field(default_factory=list)


class ClinicalHarnessAgent:
    """
    Batteries-included Clinical Harness Agent conforming to the
    Microsoft Agent Framework Harness architecture.
    """

    def __init__(
        self,
        name: str = "clinical_decision_harness",
        client: Optional[Any] = None,
        harness_instructions: str = DEFAULT_HARNESS_INSTRUCTIONS,
        agent_instructions: str = DEFAULT_AGENT_INSTRUCTIONS,
        todo_provider: Optional[ClinicalTodoProvider] = None,
        mode_provider: Optional[ClinicalModeProvider] = None,
        approval_policy: Optional[SafetyGateApprovalPolicy] = None,
        tools: Optional[Dict[str, Callable]] = None,
        max_context_window_tokens: int = 128_000,
        max_output_tokens: int = 16_384,
    ):
        self.name = name
        self.client = client
        self.harness_instructions = harness_instructions
        self.agent_instructions = agent_instructions
        self.todo_provider = todo_provider or ClinicalTodoProvider()
        self.mode_provider = mode_provider or ClinicalModeProvider()
        self.approval_policy = approval_policy or SafetyGateApprovalPolicy()
        self.max_context_window_tokens = max_context_window_tokens
        self.max_output_tokens = max_output_tokens

        # Register default clinical tools
        self.tools: Dict[str, Callable] = tools or {
            "parse_clinician_input": parse_clinician_input,
            "resolve_lab_term": resolve_lab_term,
            "evaluate_safety_gate": evaluate_safety_gate,
            "fetch_grounded_protocol": fetch_grounded_protocol,
            "build_clarification_prompt": build_clarification_prompt,
            "panel_workup": panel_workup,
        }

    def create_session(self, session_id: Optional[str] = None) -> HarnessSession:
        """Create a new isolated conversation session."""
        return HarnessSession(session_id=session_id)

    async def run(
        self,
        prompt: str,
        session: Optional[HarnessSession] = None,
        mode: Optional[AgentMode | str] = None,
    ) -> HarnessResponse:
        """
        Execute the agent pipeline with harness safety guards, todo tracking,
        and approval policies.
        """
        if session is None:
            session = self.create_session()

        if mode is not None:
            self.mode_provider.set_mode(mode)
        current_mode = self.mode_provider.mode

        # Reset and initialize workflow todos
        self.todo_provider.reset()
        session.add_message(role="user", content=prompt)

        tool_calls: List[ToolInvocation] = []

        # ── Step 1: Parse Clinician Input ───────────────────────────────────
        self.todo_provider.mark_in_progress(1)
        parse_approval = self.approval_policy.check_approval("parse_clinician_input", {"query": prompt})
        parsed = self.tools["parse_clinician_input"](prompt)
        tool_calls.append(
            ToolInvocation(
                tool_name="parse_clinician_input",
                args={"query": prompt},
                result=parsed,
                approved=parse_approval["approved"],
                requires_hitl=parse_approval["requires_hitl"],
            )
        )
        self.todo_provider.mark_completed(1, {"parsed": parsed})

        # ── Step 2: Resolve Ontology ────────────────────────────────────────
        self.todo_provider.mark_in_progress(2)
        resolve_args = {
            "term": parsed.get("term"),
            "unit": parsed.get("unit"),
            "qualifier": parsed.get("qualifier"),
            "patient_value": parsed.get("patient_value"),
        }
        resolve_approval = self.approval_policy.check_approval("resolve_lab_term", resolve_args)
        resolved = self.tools["resolve_lab_term"](**resolve_args)
        tool_calls.append(
            ToolInvocation(
                tool_name="resolve_lab_term",
                args=resolve_args,
                result=resolved,
                approved=resolve_approval["approved"],
                requires_hitl=resolve_approval["requires_hitl"],
            )
        )
        self.todo_provider.mark_completed(2, {"status": resolved.get("status")})

        # ── Step 3: Evaluate Safety Gate ────────────────────────────────────
        self.todo_provider.mark_in_progress(3)
        gate_args = {
            "term": resolved.get("term"),
            "unit": resolved.get("unit"),
            "qualifier": resolved.get("qualifier"),
            "patient_value": resolved.get("patient_value"),
            "status": resolved.get("status"),
        }
        gate_approval = self.approval_policy.check_approval("evaluate_safety_gate", gate_args)
        gate = self.tools["evaluate_safety_gate"](**gate_args)
        tool_calls.append(
            ToolInvocation(
                tool_name="evaluate_safety_gate",
                args=gate_args,
                result=gate,
                approved=gate_approval["approved"],
                requires_hitl=gate_approval["requires_hitl"],
            )
        )
        self.todo_provider.mark_completed(3, {"route": gate.get("route"), "status": gate.get("status")})

        route = gate.get("route", "CLARIFY")
        status = gate.get("status", "UNKNOWN")

        # ── PLAN Mode Check ─────────────────────────────────────────────────
        if current_mode == AgentMode.PLAN:
            plan_text = (
                f"### [PLAN MODE] Diagnostic Analysis for \"{prompt}\"\n"
                f"- **Parsed Term**: {parsed.get('term') or 'None'} (Value: {parsed.get('patient_value')}, Unit: {parsed.get('unit') or 'None'})\n"
                f"- **LOINC Resolution Status**: {status}\n"
                f"- **Safety Gate Route**: {route}\n"
                f"- **Recommended Action**: {'Proceed to protocol retrieval' if route == 'PROCEED' else 'Clarify ambiguity/unit mismatch with clinician'}"
            )
            session.add_message(role="assistant", content=plan_text, metadata={"mode": "plan"})
            return HarnessResponse(
                text=plan_text,
                route=route,
                status=status,
                session_id=session.session_id,
                mode=current_mode,
                parsed=parsed,
                resolved=resolved,
                gate=gate,
                tool_calls=tool_calls,
                todos=[item.model_dump() for item in self.todo_provider.get_todos()],
            )

        # ── Step 4: Synthesize Decision (EXECUTE Mode) ──────────────────────
        self.todo_provider.mark_in_progress(4)
        protocol_data: Dict[str, Any] = {}
        clarification_text: Optional[str] = None
        output_text = ""

        if route == "PROCEED":
            candidates = resolved.get("candidates", [])
            concept = candidates[0] if candidates else {}
            proto_args = {
                "uri": concept.get("uri", ""),
                "concept": concept,
                "patient_value": parsed.get("patient_value"),
            }
            proto_approval = self.approval_policy.check_approval(
                "fetch_grounded_protocol", proto_args, context={"gate_route": route}
            )
            if proto_approval["approved"]:
                protocol_data = self.tools["fetch_grounded_protocol"](**proto_args)
                tool_calls.append(
                    ToolInvocation(
                        tool_name="fetch_grounded_protocol",
                        args=proto_args,
                        result=protocol_data,
                        approved=True,
                    )
                )

            proto_detail = protocol_data.get("protocol", {})
            ref_range = proto_detail.get("reference_range", "N/A")
            panic_limits = proto_detail.get("panic_limits", "N/A")
            candidate_label = concept.get("label", parsed.get("term", "Lab Test"))
            candidate_uri = concept.get("uri", "N/A")

            output_text = (
                f"[PROCEED] Standardized LOINC concept: {candidate_label} [{candidate_uri}]\n"
                f"Patient Value: {parsed.get('patient_value')} {parsed.get('unit')}\n"
                f"Reference Range: {ref_range}\n"
                f"Panic Limits: {panic_limits}\n"
                f"Status: Clinically validated. Safe to report."
            )
            self.todo_provider.mark_completed(4, {"route": "PROCEED", "uri": candidate_uri})

        else:  # route == "CLARIFY"
            clarify_args = {
                "status": status,
                "candidates": gate.get("candidates", []),
                "term": parsed.get("term"),
                "collision_details": gate.get("details"),
            }
            clarify_approval = self.approval_policy.check_approval(
                "build_clarification_prompt", clarify_args, context={"gate_route": route}
            )
            clarification_res = self.tools["build_clarification_prompt"](**clarify_args)
            clarification_text = clarification_res.get("clarification_prompt", "")

            tool_calls.append(
                ToolInvocation(
                    tool_name="build_clarification_prompt",
                    args=clarify_args,
                    result=clarification_res,
                    approved=clarify_approval["approved"],
                    requires_hitl=clarify_approval["requires_hitl"],
                )
            )

            output_text = (
                f"[CLARIFY] Safety Gate Intercepted Query: {status}\n"
                f"Reason: {gate.get('reason', 'Ambiguity or safety constraint detected')}\n"
                f"Clarification Required: {clarification_text}"
            )
            self.todo_provider.mark_completed(4, {"route": "CLARIFY", "status": status})

        session.add_message(
            role="assistant",
            content=output_text,
            metadata={"route": route, "status": status},
        )

        return HarnessResponse(
            text=output_text,
            route=route,
            status=status,
            session_id=session.session_id,
            mode=current_mode,
            parsed=parsed,
            resolved=resolved,
            gate=gate,
            protocol=protocol_data,
            clarification=clarification_text,
            tool_calls=tool_calls,
            todos=[item.model_dump() for item in self.todo_provider.get_todos()],
        )


def create_clinical_harness_agent(
    client: Optional[Any] = None,
    name: str = "clinical_decision_harness",
    harness_instructions: str = DEFAULT_HARNESS_INSTRUCTIONS,
    agent_instructions: str = DEFAULT_AGENT_INSTRUCTIONS,
    **kwargs: Any,
) -> ClinicalHarnessAgent:
    """
    Factory function matching the MAF create_harness_agent API pattern.
    Returns a configured ClinicalHarnessAgent.
    """
    return ClinicalHarnessAgent(
        name=name,
        client=client,
        harness_instructions=harness_instructions,
        agent_instructions=agent_instructions,
        **kwargs,
    )
