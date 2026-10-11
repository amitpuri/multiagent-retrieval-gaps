"""
The live competency-question runner (P11.C2), exercised offline: each
framework's own server answers every applicable question correctly, and the
runner refuses a service that serves a different knowledge release.
"""
import subprocess
import sys
from pathlib import Path

import pytest

import live

REPO = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("framework", ["adk", "strands", "maf"])
def test_server_answers_every_applicable_question(framework, tmp_path):
    proc = subprocess.run([sys.executable, str(REPO / "conformance" / "live.py"), "--asgi", framework,
                           "--out", str(tmp_path / "report.json")], capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]


class _Response:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class _StaleService:
    def get(self, path):
        return _Response({"capabilities": {"extensions": [{"params": {
            "bundle_sha256": "0" * 64, "skills_lock_sha256": "1" * 64, "domains": ["laboratory_medicine"]}}]}})

    def post(self, path, json):
        raise AssertionError("no question may be asked of a service serving another release")


def test_runner_refuses_a_different_knowledge_release():
    report = live.check(_StaleService(), "stale", {"bundle_sha256": "f" * 64})
    assert not report["conforms"] and "_release" in report["failures"]


def test_overlay_and_other_domain_scenarios_are_not_asked_of_a_deployment():
    cases = {c["case"].split("/")[0] for c in live.applicable_cases(["laboratory_medicine"])}
    assert "scenario_a_hemoglobin" in cases
    assert "scenario_d_troponin" not in cases            # overlay: not in the deployed pack
    assert "scenario_f_cardiology_troponin" not in cases  # another domain pack
