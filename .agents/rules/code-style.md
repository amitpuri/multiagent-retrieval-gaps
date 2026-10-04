---
trigger: always_on
---

# Code Style & Conventions

Applies to all Python files in this repository.

---

## Imports

- Use `from __future__ import annotations` at the top of every module.
- Group imports: stdlib → third-party → internal (`src.*`), separated by blank lines.
- Internal imports use the `src.` prefix (never relative `.` imports at module level).

## Type Annotations

- All function signatures must have full type annotations (arguments + return type).
- Use `Dict`, `List`, `Optional` from `typing` (not bare `dict`/`list` for compatibility).
- Pydantic models use `Field(default_factory=...)` for mutable defaults.

## Docstrings

- Every public class and function has a one-line summary docstring.
- Longer explanations go after a blank line in the docstring body.
- Do not duplicate what is obvious from the type signature.

## Agent Nodes

- Agent node functions follow the signature: `(node_input: Dict[str, Any]) -> Event`
- They must not have side effects beyond populating `node_input` keys and returning an `Event`.
- Nodes are named `<role>_node`, factory functions are named `create_<role>_agent`.

## Tests

- Test files are in `tests/` and named `test_<feature>.py`.
- Each test function has a one-line docstring describing the invariant being tested.
- No LLM calls in `tests/test_gate.py` — use only deterministic tool calls.
- Use `pytest` fixtures and parametrize for repeated assertion patterns.

## MCP Tools

- Tool functions are thin wrappers: delegate immediately to `src/tools.py` or `src/core/`.
- Never put business logic directly in `mcp_server.py` tool bodies.
- Tool names in `@mcp_server.tool(name=...)` must match the `CLINICAL_MCP_TOOLS` dict key exactly.
