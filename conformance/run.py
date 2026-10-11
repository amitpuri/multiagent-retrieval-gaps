"""
Cross-cloud conformance runner (plan P13.1 gate parity, P13.8 second domain).

Runs ``probe.py`` once per framework — each in its own process, because every
framework names its package ``src`` — and fails unless ADK (GCP), Strands
(AWS) and MAF (Azure) return exactly the canonical ``ontogate`` decision for
every competency question in ``config/scenarios`` (both domain packs), and
every decision meets its scenario's expectations.

    python conformance/run.py                 # all frameworks, report in dist/conformance/
    python conformance/run.py --frameworks adk maf
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Sequence

REPO = Path(__file__).resolve().parent.parent
FRAMEWORK_DIRS = {"ontogate": "shared", "adk": "google-adk-agents", "strands": "strands-agents",
                  "maf": "agent-framework"}
CLOUD = {"adk": "gcp", "strands": "aws", "maf": "azure", "ontogate": "core"}


def probe(framework: str) -> List[Dict[str, Any]]:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / f"{framework}.json"
        env = {**os.environ, "ONTOGATE_REPO_ROOT": str(REPO), "PYTHONIOENCODING": "utf-8"}
        env.pop("ONTOGATE_SKILL_STORE", None)
        proc = subprocess.run(
            [sys.executable, str(REPO / "conformance" / "probe.py"), "--framework", framework, "--out", str(out)],
            cwd=REPO / FRAMEWORK_DIRS[framework], env=env, capture_output=True, text=True, timeout=600,
        )
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(f"{framework} probe failed:\n{proc.stderr[-4000:]}")
        return json.loads(out.read_text(encoding="utf-8"))


def _expectation_failures(record: Dict[str, Any], tc: Dict[str, Any]) -> List[str]:
    failures = []
    expected_status = "RESOLVED" if tc.get("expected_gap") in (None, "NONE") else tc["expected_gap"]
    if record["status"] != expected_status:
        failures.append(f"status {record['status']} != {expected_status}")
    if "expected_route" in tc and record["route"] != tc["expected_route"]:
        failures.append(f"route {record['route']} != {tc['expected_route']}")
    if "expected_concept" in tc and record["resolved_uri"] != tc["expected_concept"]:
        failures.append(f"concept {record['resolved_uri']} != {tc['expected_concept']}")
    if "expected_candidates" in tc and record["candidates"] != sorted(tc["expected_candidates"]):
        failures.append(f"candidates {record['candidates']} != {sorted(tc['expected_candidates'])}")
    if (record["route"] == "PROCEED") != (record["status"] == "RESOLVED"):
        failures.append("fail-closed invariant broken")
    if record.get("attestation") and record["attestation"]["verdict"] == "PASS" \
            and record["attestation"]["badge"] != "[Attested ✓]":
        failures.append("PASS attestation without badge")
    return failures


def run(frameworks: Sequence[str]) -> Dict[str, Any]:
    import yaml
    expectations = {}
    for path in sorted((REPO / "config" / "scenarios").glob("*.yaml")):
        for tc in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("test_cases", []):
            expectations[f"{path.stem}/{tc['id']}"] = tc

    reference = {r["case"]: r for r in probe("ontogate")}
    report: Dict[str, Any] = {"cases": len(reference), "frameworks": {}, "expectation_failures": {}}
    for case, record in reference.items():
        failures = _expectation_failures(record, expectations[case])
        if failures:
            report["expectation_failures"][case] = failures
    for framework in frameworks:
        results = {r["case"]: r for r in probe(framework)}
        divergences = {}
        for case, expected in reference.items():
            actual = results.get(case)
            if actual is None:
                divergences[case] = "missing"
                continue
            diff = {k: {"core": expected[k], framework: actual.get(k)} for k in expected if actual.get(k) != expected[k]}
            if diff:
                divergences[case] = diff
        report["frameworks"][framework] = {"cloud": CLOUD[framework], "cases": len(results),
                                           "divergences": divergences}
    report["conforms"] = not report["expectation_failures"] and all(
        not f["divergences"] for f in report["frameworks"].values())
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--frameworks", nargs="+", default=["adk", "strands", "maf"],
                        choices=["adk", "strands", "maf"])
    args = parser.parse_args(argv)
    report = run(args.frameworks)
    dest = REPO / "dist" / "conformance"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for framework, result in report["frameworks"].items():
        state = "conforms" if not result["divergences"] else f"{len(result['divergences'])} divergence(s)"
        print(f"{framework:8} ({result['cloud']}): {result['cases']} cases, {state}")
    for case, failures in report["expectation_failures"].items():
        print(f"expectation failed: {case}: {'; '.join(failures)}")
    print("CONFORMS" if report["conforms"] else "DOES NOT CONFORM", f"(report: {dest / 'report.json'})")
    return 0 if report["conforms"] else 1


if __name__ == "__main__":
    sys.exit(main())
