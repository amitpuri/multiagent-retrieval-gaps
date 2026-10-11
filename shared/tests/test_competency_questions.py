"""
Competency questions: every ``test_cases`` entry in ``config/scenarios/*.yaml``
is executed against the real gate. The scenario files are the acceptance oracle
for the ontology; a scenario whose overlay or expectations drift fails here.

Supported expectations: expected_gap, expected_route, expected_concept,
expected_candidates, expected_readings, expected_missing,
expected_population_readings, expected_departments, expected_tube_order.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from ontogate.config import load_scenario_extension
from ontogate.parsing import parse_clinician_text
from ontogate.paths import scenarios_dir
from ontogate.tools import evaluate_safety_gate, panel_workup


def _cases() -> List[Any]:
    out = []
    for path in sorted(scenarios_dir().glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for tc in data.get("test_cases", []) or []:
            out.append(pytest.param(path, tc, id=f"{path.stem}::{tc['id']}"))
    return out


def run_case(path: Path, tc: Dict[str, Any]) -> Dict[str, Any]:
    """Parse → gate (→ panel workup) for one competency question."""
    registry = load_scenario_extension(path)
    parsed = parse_clinician_text(tc["input_text"], registry)
    population = parsed.get("population") or {}
    verdict = evaluate_safety_gate(
        term=parsed["term"], unit=parsed["unit"], qualifier=parsed["qualifier"],
        patient_value=parsed["patient_value"], sex=population.get("sex", ""),
        age_band=population.get("age_band", ""), department=parsed.get("department", ""),
        panel_id=parsed.get("panel_id") or "", registry=registry,
    )
    workup = None
    if verdict["route"] == "PROCEED" and parsed.get("panel_id"):
        workup = panel_workup(parsed["panel_id"], parsed.get("department", ""), registry=registry)
    return {"parsed": parsed, "verdict": verdict, "workup": workup}


@pytest.mark.parametrize("path,tc", _cases())
def test_competency_question(path: Path, tc: Dict[str, Any]) -> None:
    """A scenario test case holds against the deterministic gate."""
    out = run_case(path, tc)
    verdict, details = out["verdict"], out["verdict"]["details"]

    expected_status = "RESOLVED" if tc.get("expected_gap") in (None, "NONE") else tc["expected_gap"]
    assert verdict["status"] == expected_status, (verdict["status"], verdict["gate_message"], out["parsed"])
    if "expected_route" in tc:
        assert verdict["route"] == tc["expected_route"]

    if "expected_concept" in tc:
        assert details.get("resolved_uri") == tc["expected_concept"]
    if "expected_candidates" in tc:
        assert sorted(c["uri"] for c in verdict["candidates"]) == sorted(tc["expected_candidates"])
    if "expected_readings" in tc:
        assert details.get("readings") == tc["expected_readings"]
    if "expected_missing" in tc:
        assert sorted(details.get("missing", [])) == sorted(tc["expected_missing"])
    if "expected_population_readings" in tc:
        assert details.get("population_readings") == tc["expected_population_readings"]

    if "expected_departments" in tc or "expected_tube_order" in tc:
        assert out["workup"] is not None and out["workup"]["status"] == "RESOLVED"
        tubes = out["workup"]["tubes"]
        if "expected_departments" in tc:
            assert [t["department"] for t in tubes] == tc["expected_departments"]
        if "expected_tube_order" in tc:
            assert [(t["tube"], t["department"]) for t in tubes] == [
                (e["tube"], e["department"]) for e in tc["expected_tube_order"]
            ]

    # Fail-closed invariant on every competency question.
    assert (verdict["route"] == "PROCEED") == (verdict["status"] == "RESOLVED")
