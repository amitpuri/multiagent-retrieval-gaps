"""
The A2A JSON-RPC binding (``ontogate.a2a``): ``message/send`` returns one agent
Message carrying the answer text and the gate decision as data; every other
request gets a JSON-RPC error, never an exception.
"""
import asyncio
import json

import pytest

from ontogate import a2a

BODY = {"session_id": "s-1", "text": "[CLARIFY] which specimen?", "route": "CLARIFY",
        "status": "AMBIGUOUS", "attested": False, "clarification": "Serum or CSF?"}


def send(payload, query=lambda prompt, context_id: dict(BODY, prompt=prompt, ctx=context_id)):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return asyncio.run(a2a.handle_body(raw, query))


def message(*parts, context_id=None):
    msg = {"kind": "message", "role": "user", "messageId": "m-1", "parts": list(parts)}
    if context_id:
        msg["contextId"] = context_id
    return {"jsonrpc": "2.0", "id": 7, "method": "message/send", "params": {"message": msg}}


def test_message_send_returns_an_agent_message_with_text_and_decision():
    response = send(message({"kind": "text", "text": "glucose 5.2"}, context_id="ctx-9"))
    assert response["id"] == 7 and "error" not in response
    result = response["result"]
    assert result["kind"] == "message" and result["role"] == "agent" and result["messageId"]
    assert result["contextId"] == "s-1"  # the server's session id
    text, data = result["parts"]
    assert text == {"kind": "text", "text": "[CLARIFY] which specimen?\n\nSerum or CSF?"}
    assert data["kind"] == "data" and data["data"]["route"] == "CLARIFY"
    assert data["data"]["prompt"] == "glucose 5.2" and data["data"]["ctx"] == "ctx-9"


def test_async_query_functions_are_awaited():
    async def query(prompt, context_id):
        return dict(BODY, text=prompt)
    result = send(message({"kind": "text", "text": "Hb 13.5 g/dL"}), query)["result"]
    assert result["parts"][0]["text"].startswith("Hb 13.5 g/dL")


@pytest.mark.parametrize("payload, code", [
    (b"{not json", a2a.PARSE_ERROR),
    ({"id": 1, "method": "message/send"}, a2a.INVALID_REQUEST),
    ({"jsonrpc": "2.0", "id": 1, "method": "message/stream", "params": {}}, a2a.UNSUPPORTED_OPERATION),
    ({"jsonrpc": "2.0", "id": 1, "method": "tasks/get", "params": {"id": "t"}}, a2a.UNSUPPORTED_OPERATION),
    ({"jsonrpc": "2.0", "id": 1, "method": "no/such", "params": {}}, a2a.METHOD_NOT_FOUND),
    ({"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {}}, a2a.INVALID_PARAMS),
    (message({"kind": "file", "file": {"uri": "gs://x"}}), a2a.CONTENT_TYPE_NOT_SUPPORTED),
])
def test_bad_requests_get_jsonrpc_errors(payload, code):
    assert send(payload)["error"]["code"] == code


def test_query_failures_become_errors_not_exceptions():
    def broken(prompt, context_id):
        raise RuntimeError("gate unavailable")
    error = send(message({"kind": "text", "text": "x"}), broken)["error"]
    assert error["code"] == a2a.INTERNAL_ERROR and "gate unavailable" in error["message"]


def test_query_can_reject_a_prompt_as_invalid_params():
    def strict(prompt, context_id):
        raise a2a.A2AError(a2a.INVALID_PARAMS, "prompt too long")
    assert send(message({"kind": "text", "text": "x"}), strict)["error"] == {
        "code": a2a.INVALID_PARAMS, "message": "prompt too long"}
