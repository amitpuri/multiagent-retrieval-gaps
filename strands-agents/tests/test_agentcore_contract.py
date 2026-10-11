"""
Amazon Bedrock AgentCore Runtime contract: the container listens on 8080 and
serves GET /ping and POST /invocations; the attestation badge is earned, never assumed.
"""
import os
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("STRANDS_OFFLINE_MODE", "true")
from src.server import app  # noqa: E402

client = TestClient(app)


def test_ping_reports_healthy():
    response = client.get("/ping")
    assert response.status_code == 200 and response.json() == {"status": "Healthy"}


def test_invocations_runs_the_gated_pipeline():
    body = client.post("/invocations", json={"prompt": "Hb 13.5 | g/dL"}).json()
    assert body["route"] == "PROCEED" and body["attested"] is True and "[Attested ✓]" in body["text"]


def test_badge_requires_a_reported_value():
    body = client.post("/invocations", json={"prompt": "CSF Emergency Panel"}).json()
    assert body["route"] == "PROCEED" and body["attested"] is False and "[Attested" not in body["text"]


def test_clarify_never_carries_the_badge():
    body = client.post("/invocations", json={"prompt": "Calcium 4.8 | mg/dL"}).json()
    assert body["route"] == "CLARIFY" and body["attested"] is False and body["clarification"]


def test_image_listens_on_the_agentcore_port():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "ENV PORT=8080" in dockerfile and "EXPOSE 8080" in dockerfile and "/ping" in dockerfile
