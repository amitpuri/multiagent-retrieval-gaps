"""
Cross-cloud conformance as a test: ADK (GCP), Strands (AWS) and MAF (Azure)
return the canonical decision for every competency question of both domain
packs. See conformance/run.py.
"""
import pytest

from run import run


@pytest.fixture(scope="module")
def report():
    return run(["adk", "strands", "maf"])


def test_every_case_meets_its_scenario_expectations(report):
    assert report["expectation_failures"] == {}


@pytest.mark.parametrize("framework", ["adk", "strands", "maf"])
def test_framework_matches_the_canonical_core(report, framework):
    result = report["frameworks"][framework]
    assert result["cases"] == report["cases"]
    assert result["divergences"] == {}


def test_both_domain_packs_are_covered(report):
    assert report["cases"] >= 35


def test_runner_detects_a_divergent_framework(monkeypatch):
    """A framework that routes one case differently makes the run fail."""
    import run as runner
    real_probe = runner.probe
    reference = real_probe("ontogate")

    def fake_probe(framework):
        if framework == "ontogate":
            return reference
        records = [dict(r) for r in reference]
        records[0]["route"] = "PROCEED" if records[0]["route"] == "CLARIFY" else "CLARIFY"
        return records

    monkeypatch.setattr(runner, "probe", fake_probe)
    report = runner.run(["maf"])
    assert not report["conforms"]
    assert list(report["frameworks"]["maf"]["divergences"]) == [reference[0]["case"]]
