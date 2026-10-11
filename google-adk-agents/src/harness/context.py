"""
Context window and conversation history management for the Google ADK Agent Harness.
Implements Step 3: catching tool outputs, formatting Gemini Content structures,
sliding window budgeting, and OKF progressive disclosure indexing.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from google.genai import types

from src.harness.session import HarnessSession, SessionMessage


class ContextWindowManager:
    """
    Manages token budgeting, conversation message formatting, and
    progressive disclosure of clinical knowledge within the model context window.
    """

    def __init__(
        self,
        max_context_turns: int = 20,
        max_estimated_chars: int = 100_000,
        system_instruction: Optional[str] = None,
    ):
        self.max_context_turns = max_context_turns
        self.max_estimated_chars = max_estimated_chars
        self.system_instruction = system_instruction or (
            "You are a Clinical Decision Support Harness Agent operating under strict deterministic "
            "safety gating and canonical ontology grounding (LOINC/OKF). You must never guess unverified "
            "units or colliding reference intervals. Use provided MCP tools to resolve terms, evaluate safety gates, "
            "fetch protocols, and verify computations."
        )

    def format_history_for_gemini(self, session: HarnessSession) -> List[types.Content]:
        """
        Converts the session messages into a sequence of google.genai.types.Content
        objects adhering to Gemini's required role sequence:
            user → model (with function_call parts) → user (with function_response parts) → model

        tool responses MUST use role="user" containing
        Part.from_function_response(...) parts, NOT role="tool".
        Submitting role="tool" causes Gemini to reject the request on turn 2.

        Applies sliding window pruning if the turn count exceeds budget.
        """
        messages = session.messages
        if len(messages) > self.max_context_turns:
            # Preserve initial user inquiry (Turn 0) and the most recent (max_context_turns - 1) turns
            messages = [messages[0]] + messages[-(self.max_context_turns - 1):]

        contents: List[types.Content] = []

        for msg in messages:
            if msg.role == "user":
                parts = [types.Part.from_text(text=msg.content)]
                contents.append(types.Content(role="user", parts=parts))

            elif msg.role == "model":
                parts: List[types.Part] = []
                if msg.content:
                    parts.append(types.Part.from_text(text=msg.content))
                for tc in msg.tool_calls:
                    parts.append(
                        types.Part.from_function_call(
                            name=tc.tool_name,
                            args=tc.args,
                        )
                    )
                if parts:
                    contents.append(types.Content(role="model", parts=parts))

            elif msg.role == "tool":
                # Gemini requires function responses in role="user" Content,
                # each wrapped in Part.from_function_response.
                # The sequence is: model (function_call) → user (function_response).
                parts = []
                for tr in msg.tool_responses:
                    tool_name = tr.get("tool_name", "tool")
                    raw_result = tr.get("result", {})
                    # Ensure result is a dict for function response
                    res_dict = raw_result if isinstance(raw_result, dict) else {"result": raw_result}
                    parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response=res_dict,
                        )
                    )
                if parts:
                    # role MUST be "user" here — not "tool"
                    contents.append(types.Content(role="user", parts=parts))

        return contents

    def append_tool_result_to_session(
        self,
        session: HarnessSession,
        tool_name: str,
        result: Any,
        call_id: Optional[str] = None,
    ) -> SessionMessage:
        """
        Step 3 Core: Catches the tool output and appends it to the running conversation history.
        """
        return session.add_tool_response(
            tool_name=tool_name,
            result=result,
            call_id=call_id,
            metadata={"status": result.get("status") if isinstance(result, dict) else "SUCCESS"},
        )

    def build_progressive_disclosure_summary(self, domain_index: Optional[Dict[str, Any]] = None) -> str:
        """
        OKF Progressive Disclosure: Injects a compact high-level summary of available
        domains and departments into prompt context without polluting the window
        with full protocol and reference range dictionaries.
        """
        if not domain_index:
            return (
                "[Knowledge Index: Available Departments]\n"
                "- Hematology (e.g., Hemoglobin, Leukocytes)\n"
                "- Clinical Biochemistry (e.g., Total/Ionized Calcium, Glucose, Troponin)\n"
                "- Microbiology (e.g., CSF Gram Stain, Culture)\n"
                "Query MCP tools by canonical LOINC URI to progressively disclose reference protocols."
            )
        departments = domain_index.get("departments", [])
        return f"[Knowledge Index]: Active departments: {', '.join(departments)}. Call resolve_lab_term to ground terms."
