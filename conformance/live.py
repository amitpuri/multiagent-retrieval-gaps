"""
Live competency-question runner (plan P11.C2): ask a deployed agent every
competency question its knowledge release can answer, and fail on any wrong
gate decision.

    python conformance/live.py --endpoint https://<service> [--token <bearer>]
    python conformance/live.py --asgi adk|strands|maf     # same checks in-process, offline

The runner first reads the service's A2A AgentCard (``/.well-known/agent-card.json``):
the served domains select which scenarios apply (overlay scenarios describe
knowledge a deployed pack does not hold), and the served bundle hash must equal
the local release — otherwise the expectations do not describe that service.
Each question is sent to ``POST /api/v1/query`` in a fresh session; the
returned ``status`` and ``route`` must match the scenario and fail closed. The
first question is also asked through the card's ``url`` (A2A JSON-RPC
``message/send``), which must return the same decision — the card may only
advertise an interface that answers.
The report (``dist/conformance/live-<label>.json``) is keyed by the bundle and
skills-lock hashes it was run against.

``--asgi`` blanks every model credential before importing the framework's
server, so a local .env can never trigger a paid model call.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

REPO = Path(__file__).resolve().parent.parent
FRAMEWORK_DIRS = {"adk": "google-adk-agents", "strands": "strands-agents", "maf": "agent-framework"}
SERVER_MODULES = {"adk": "src.harness.server", "strands": "src.server", "maf": "src.harness.server"}
OFFLINE_ENV = {
    "GEMINI_API_KEY": "", "GOOGLE_API_KEY": "", "ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": "",
    "AZURE_OPENAI_API_KEY": "", "AZURE_OPENAI_ENDPOINT": "", "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT": "",
    "FOUNDRY_PROJECT_ENDPOINT": "", "STRANDS_OFFLINE_MODE": "true", "MAF_OFFLINE_MODE": "true",
    "HARNESS_API_TOKENS": "",
}


def applicable_cases(domains: List[str]) -> List[Dict[str, Any]]:
    """Competency questions a deployment of ``domains`` can answer (no overlays)."""
    cases = []
    for path in sorted((REPO / "config" / "scenarios").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if data.get("overlay") or data.get("domain", "laboratory_medicine") not in domains:
            continue
        for tc in data.get("test_cases", []):
            cases.append({"case": f"{path.stem}/{tc['id']}", "tc": tc})
    return cases


def _canonical_attests(query: str) -> bool:
    """True if the canonical pipeline attests this query's value (PASS)."""
    from ontogate import tools as T
    from ontogate.parsing import parse_clinician_text
    parsed = parse_clinician_text(query)
    if parsed.get("patient_value") is None:
        return False
    population = parsed.get("population") or {}
    gate = T.evaluate_safety_gate(term=parsed["term"], unit=parsed["unit"], qualifier=parsed["qualifier"],
                                  patient_value=parsed["patient_value"], sex=population.get("sex", ""),
                                  age_band=population.get("age_band", ""), department=parsed.get("department", ""),
                                  panel_id=parsed.get("panel_id") or "")
    uri = (gate.get("details") or {}).get("resolved_uri")
    if gate["route"] != "PROCEED" or not uri:
        return False
    verdict = T.attest_computation(value=parsed["patient_value"], uri=uri, unit=parsed["unit"],
                                   sex=population.get("sex", ""), age_band=population.get("age_band", ""))
    return verdict.get("verdict") == "PASS"


def check(client: Any, label: str, local_release: Dict[str, Any]) -> Dict[str, Any]:
    card_response = client.get("/.well-known/agent-card.json")
    card_response.raise_for_status()
    card = card_response.json()
    params = card["capabilities"]["extensions"][0]["params"]
    report: Dict[str, Any] = {
        "label": label,
        "served_bundle_sha256": params.get("bundle_sha256"),
        "served_skills_lock_sha256": params.get("skills_lock_sha256"),
        "domains": params.get("domains", []),
        "failures": {},
    }
    if params.get("bundle_sha256") != local_release.get("bundle_sha256"):
        report["failures"]["_release"] = (f"service serves bundle {params.get('bundle_sha256')}, local release is "
                                          f"{local_release.get('bundle_sha256')}: redeploy or check out that release")
        report["conforms"] = False
        return report
    cases = applicable_cases(report["domains"])
    report["cases"] = len(cases)
    for case in cases:
        tc = case["tc"]
        response = client.post("/api/v1/query", json={"prompt": tc["input_text"], "session_id": f"cq-{uuid.uuid4()}"})
        if response.status_code != 200:
            report["failures"][case["case"]] = f"HTTP {response.status_code}"
            continue
        body = response.json()
        expected_status = "RESOLVED" if tc.get("expected_gap") in (None, "NONE") else tc["expected_gap"]
        problems = []
        if body.get("status") != expected_status:
            problems.append(f"status {body.get('status')} != {expected_status}")
        if "expected_route" in tc and body.get("route") != tc["expected_route"]:
            problems.append(f"route {body.get('route')} != {tc['expected_route']}")
        if (body.get("route") == "PROCEED") != (body.get("status") == "RESOLVED"):
            problems.append("fail-closed invariant broken")
        if body.get("route") == "CLARIFY" and not body.get("clarification"):
            problems.append("CLARIFY without a clarification question")
        # Invariant 5: the badge is earned by a deterministic attestation, on PROCEED only.
        if ("[Attested ✓]" in str(body.get("text", ""))) != bool(body.get("attested")):
            problems.append("[Attested ✓] badge does not match the attested flag")
        if body.get("attested") and (body.get("route") != "PROCEED" or not _canonical_attests(tc["input_text"])):
            problems.append("attested=true without a passing deterministic attestation")
        if problems:
            report["failures"][case["case"]] = "; ".join(problems)
    if cases:
        problem = _a2a_problem(client, card, cases[0]["tc"]["input_text"])
        if problem:
            report["failures"]["_a2a"] = problem
    report["conforms"] = not report["failures"]
    return report


def _a2a_problem(client: Any, card: Dict[str, Any], prompt: str) -> Optional[str]:
    """Ask ``prompt`` via REST and via the card's A2A ``url``; describe any disagreement."""
    from urllib.parse import urlparse
    if card.get("preferredTransport") != "JSONRPC":
        return f"card advertises transport {card.get('preferredTransport')!r}, expected JSONRPC"
    rest = client.post("/api/v1/query", json={"prompt": prompt, "session_id": f"cq-{uuid.uuid4()}"}).json()
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {"message": {
        "kind": "message", "role": "user", "messageId": str(uuid.uuid4()), "parts": [{"kind": "text", "text": prompt}]}}}
    response = client.post(urlparse(card["url"]).path or "/", json=rpc)
    if response.status_code != 200:
        return f"A2A url answered HTTP {response.status_code}"
    body = response.json()
    if "error" in body:
        return f"A2A error {body['error']}"
    data = next((p["data"] for p in body["result"].get("parts", []) if p.get("kind") == "data"), {})
    if (data.get("route"), data.get("status")) != (rest.get("route"), rest.get("status")):
        return (f"A2A decision {data.get('route')}/{data.get('status')} != REST "
                f"{rest.get('route')}/{rest.get('status')}")
    return None


def _asgi_client(framework: str):
    os.environ.update(OFFLINE_ENV)
    os.chdir(REPO / FRAMEWORK_DIRS[framework])
    sys.path.insert(0, str(REPO / FRAMEWORK_DIRS[framework]))
    import importlib
    from fastapi.testclient import TestClient
    return TestClient(importlib.import_module(SERVER_MODULES[framework]).app)


def _http_client(endpoint: str, token: Optional[str]):
    import httpx
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.Client(base_url=endpoint.rstrip("/"), headers=headers, timeout=120)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--endpoint", help="base URL of a deployed service")
    target.add_argument("--asgi", choices=sorted(FRAMEWORK_DIRS), help="run against a framework's app in-process")
    parser.add_argument("--token", default=os.environ.get("HARNESS_API_TOKEN"), help="bearer token, if required")
    parser.add_argument("--out", help="report path (default dist/conformance/live-<label>.json)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows consoles: never crash on ✓ or —
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    sys.path.insert(0, str(REPO / "shared"))
    from ontogate.release import current_release
    local = current_release()
    label = args.asgi or args.endpoint.split("//", 1)[-1].split("/", 1)[0]
    client = _asgi_client(args.asgi) if args.asgi else _http_client(args.endpoint, args.token)
    report = check(client, label, local)
    report["local_bundle_sha256"] = local.get("bundle_sha256")
    report["local_skills_lock_sha256"] = local.get("skills_lock_sha256")
    out = Path(args.out) if args.out else REPO / "dist" / "conformance" / f"live-{label.replace(':', '_')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for case, problem in report["failures"].items():
        print(f"FAIL {case}: {problem}")
    print(f"{label}: {report.get('cases', 0)} competency question(s), "
          f"{'conforms' if report['conforms'] else f'{len(report['failures'])} failure(s)'} (report: {out})")
    return 0 if report["conforms"] else 1


if __name__ == "__main__":
    sys.exit(main())
