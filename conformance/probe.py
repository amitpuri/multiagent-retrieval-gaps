"""
Conformance probe: run every competency question through ONE framework's own
tool wrappers and print a normalised JSON result per case.

Run from a framework directory (its ``src`` package is imported), or with
``--framework ontogate`` for the canonical reference:

    cd google-adk-agents && python ../conformance/probe.py --framework adk --out adk.json

Each case runs the pipeline an agent runs: parse → resolve → gate, then on
PROCEED the protocol fetch, attestation and panel workup. Only decision-relevant
fields are kept (no A2A envelopes, ids or timestamps) so outputs are comparable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parent.parent
FRAMEWORK_DIRS = {"adk": "google-adk-agents", "strands": "strands-agents", "maf": "agent-framework"}


def _tools(framework: str):
    if framework == "ontogate":
        sys.path.insert(0, str(REPO / "shared"))
        import ontogate.tools as tools
        return tools
    sys.path.insert(0, str(REPO / FRAMEWORK_DIRS[framework]))
    import src.tools as tools  # the framework's own wrappers
    return tools


def _cases() -> List[Dict[str, Any]]:
    import yaml
    out = []
    for path in sorted((REPO / "config" / "scenarios").glob("*.yaml")):
        for tc in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("test_cases", []):
            out.append({"scenario": path, "tc": tc})
    return out


def run(framework: str) -> List[Dict[str, Any]]:
    tools = _tools(framework)
    from ontogate.config import load_scenario_extension, set_default_registry

    results = []
    for case in _cases():
        path, tc = case["scenario"], case["tc"]
        # The wrappers serve the default registry: point it at the scenario's pack + overlay.
        set_default_registry(None)  # the scenario's base is the configured pack, not the previous case
        set_default_registry(load_scenario_extension(path))
        parsed = tools.parse_clinician_input(raw_text=tc["input_text"])
        population = parsed.get("population") or {}
        resolved = tools.resolve_lab_term(term=parsed["term"], unit=parsed.get("unit") or "",
                                          qualifier=parsed.get("qualifier") or "")
        gate = tools.evaluate_safety_gate(
            term=parsed["term"], unit=parsed.get("unit") or "", qualifier=parsed.get("qualifier") or "",
            patient_value=parsed.get("patient_value"), status=resolved["status"],
            sex=population.get("sex", ""), age_band=population.get("age_band", ""),
            department=parsed.get("department") or "", panel_id=parsed.get("panel_id") or "")
        details = gate.get("details") or {}
        record: Dict[str, Any] = {
            "case": f"{path.stem}/{tc['id']}",
            "parsed": {k: parsed.get(k) for k in ("term", "unit", "qualifier", "patient_value", "population",
                                                  "department", "panel_id")},
            "resolve_status": resolved["status"],
            "status": gate["status"],
            "route": gate["route"],
            "resolved_uri": details.get("resolved_uri"),
            "candidates": sorted(c["uri"] for c in gate.get("candidates") or []),
            "missing": sorted(details.get("missing") or []),
            "readings": details.get("readings"),
            "population_readings": details.get("population_readings"),
            "clarification": bool(gate.get("clarification_prompt")),
        }
        uri = details.get("resolved_uri")
        if gate["route"] == "PROCEED" and uri:
            protocol = tools.fetch_grounded_protocol(uri=uri)
            record["protocol_status"] = protocol.get("status")
            if parsed.get("patient_value") is not None:
                attested = tools.attest_computation(value=parsed["patient_value"], uri=uri,
                                                    unit=parsed.get("unit") or "",
                                                    sex=population.get("sex", ""),
                                                    age_band=population.get("age_band", ""))
                record["attestation"] = {k: attested.get(k) for k in ("verdict", "classification", "badge")}
        if gate["route"] == "PROCEED" and parsed.get("panel_id"):
            workup = tools.panel_workup(panel=parsed["panel_id"], department=parsed.get("department") or "")
            record["workup"] = [(t["tube"], t["department"]) for t in workup.get("tubes", [])]
        results.append(record)
    set_default_registry(None)
    results.append({"case": "_agent_card", **_agent_card(framework)})
    return results


SERVER_MODULES = {"adk": "src.harness.server", "strands": "src.server", "maf": "src.harness.server"}


def _agent_card(framework: str) -> Dict[str, Any]:
    """The AgentCard the framework's server publishes, minus what legitimately differs (URL, label)."""
    from ontogate.agent_cards import agent_card, entrypoint_role
    if framework == "ontogate":
        card = agent_card(entrypoint_role(), "http://testserver/")
    else:
        import importlib
        from fastapi.testclient import TestClient
        app = importlib.import_module(SERVER_MODULES[framework]).app
        response = TestClient(app).get("/.well-known/agent-card.json")
        response.raise_for_status()
        card = response.json()
    card = dict(card)
    card.pop("url", None)
    card.pop("documentationUrl", None)
    for ext in card.get("capabilities", {}).get("extensions", []):
        ext.get("params", {}).pop("framework", None)
    return {"agent_card": card}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--framework", required=True, choices=["ontogate", *FRAMEWORK_DIRS])
    parser.add_argument("--out", required=True, help="JSON file to write (stdout is left to the framework)")
    args = parser.parse_args()
    Path(args.out).write_text(json.dumps(run(args.framework), sort_keys=True, indent=1, default=str),
                              encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
