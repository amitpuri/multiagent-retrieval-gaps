"""
A2A JSON-RPC binding (protocol 0.3.0) for the agent servers — the interface the
AgentCard's ``url`` names.

Only ``message/send`` is supported: every answer is produced in one turn by the
deterministic gate plus the role agents, so the server replies with a single
``Message`` rather than a long-running ``Task``. The card says
``streaming: false`` and ``pushNotifications: false``; the task and streaming
methods return ``UnsupportedOperationError``.

The reply carries two parts: the answer text, and a ``data`` part holding the
same body ``POST /api/v1/query`` returns (route, status, attested flag,
clarification), so an A2A client gets the gate decision without parsing text.
The A2A ``contextId`` is the server's session id.

Each framework server mounts :func:`handle_body` at :data:`A2A_PATH` with its own
query function, so the binding is identical on ADK, Strands and MAF.
"""
from __future__ import annotations

import inspect
import json
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional, Union

A2A_PATH = "/a2a"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
UNSUPPORTED_OPERATION = -32004
CONTENT_TYPE_NOT_SUPPORTED = -32005

#: A2A methods this server knows but does not offer (no tasks, no streaming, no push).
UNSUPPORTED_METHODS = frozenset({
    "message/stream", "tasks/get", "tasks/cancel", "tasks/resubscribe",
    "tasks/pushNotificationConfig/set", "tasks/pushNotificationConfig/get",
    "tasks/pushNotificationConfig/list", "tasks/pushNotificationConfig/delete",
    "agent/getAuthenticatedExtendedCard",
})

#: ``query(prompt, session_id)`` → the REST query response body (dict); may be async.
QueryFn = Callable[[str, Optional[str]], Union[Dict[str, Any], Awaitable[Dict[str, Any]]]]


class A2AError(Exception):
    """A JSON-RPC error raised by a query function (e.g. invalid prompt)."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


def _error(request_id: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _prompt(message: Any) -> str:
    if not isinstance(message, dict) or message.get("role") != "user" or not isinstance(message.get("parts"), list):
        raise A2AError(INVALID_PARAMS, "params.message must be a user Message with parts")
    texts = [p.get("text", "") for p in message["parts"] if isinstance(p, dict) and p.get("kind") == "text"]
    if not texts:
        raise A2AError(CONTENT_TYPE_NOT_SUPPORTED, "only text parts are accepted (defaultInputModes: text/plain)")
    return "\n".join(t for t in texts if t)


def reply(body: Dict[str, Any], context_id: Optional[str] = None) -> Dict[str, Any]:
    """The A2A ``Message`` for a REST query response body."""
    text = body.get("text") or ""
    if body.get("clarification") and body["clarification"] not in text:
        text = f"{text}\n\n{body['clarification']}".strip()
    return {
        "kind": "message",
        "role": "agent",
        "messageId": str(uuid.uuid4()),
        "contextId": body.get("session_id") or context_id,
        "parts": [{"kind": "text", "text": text}, {"kind": "data", "data": body}],
    }


async def handle_jsonrpc(payload: Any, query: QueryFn) -> Dict[str, Any]:
    """Answer one A2A JSON-RPC request with ``query``; never raises."""
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str):
        return _error(payload.get("id") if isinstance(payload, dict) else None, INVALID_REQUEST,
                      "not a JSON-RPC 2.0 request")
    request_id, method = payload.get("id"), payload["method"]
    if method in UNSUPPORTED_METHODS:
        return _error(request_id, UNSUPPORTED_OPERATION,
                      f"{method} is not supported: this agent answers message/send in one turn")
    if method != "message/send":
        return _error(request_id, METHOD_NOT_FOUND, f"unknown method {method}")
    params = payload.get("params") or {}
    try:
        message = params.get("message") if isinstance(params, dict) else None
        prompt = _prompt(message)
        context_id = message.get("contextId")
        body = query(prompt, context_id)
        if inspect.isawaitable(body):
            body = await body
    except A2AError as exc:
        return _error(request_id, exc.code, exc.message, exc.data)
    except Exception as exc:  # the gate failed closed somewhere: report, never a bare 500
        return _error(request_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
    return {"jsonrpc": "2.0", "id": request_id, "result": reply(body, context_id)}


async def handle_body(raw: bytes, query: QueryFn) -> Dict[str, Any]:
    """Answer a raw HTTP request body; malformed JSON becomes a ``PARSE_ERROR`` response."""
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return _error(None, PARSE_ERROR, "request body is not valid JSON")
    return await handle_jsonrpc(payload, query)
