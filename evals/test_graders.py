"""
The answer graders (P13.3) accept a grounded answer and reject each failure
they exist to catch. Fixture answers stand in for model output.
"""
import pytest

from graders import BADGE, facts_for, grade


@pytest.fixture(scope="module")
def hb():
    return facts_for("Hb 13.5 | g/dL")


@pytest.fixture(scope="module")
def calcium():
    return facts_for("Calcium 4.8 | mg/dL")


@pytest.fixture(scope="module")
def hb_no_unit():
    return facts_for("Hb 13.5")


def _good_hb(facts):
    return ("Hemoglobin (loinc:718-7) 13.5 g/dL " + BADGE + ": normal for an adult female, low for an adult male "
            "(adult male 13.8-17.2 g/dL; adult female 12.1-15.1 g/dL). " + " ".join(facts.caveats))


def test_facts_come_from_the_canonical_pipeline(hb, calcium):
    assert hb.route == "PROCEED" and hb.resolved_uri == "loinc:718-7" and hb.attested and hb.caveats
    assert calcium.route == "CLARIFY" and calcium.facet_values == {"fraction": ["total", "ionized"]}


def test_grounded_answer_passes(hb):
    assert grade(_good_hb(hb), hb)["passed"]


def test_invented_number_fails_grounding(hb):
    result = grade(_good_hb(hb) + " Expect 14.2 g/dL next week.", hb)
    assert result["grounded_numbers"] is False and not result["passed"]


def test_missing_caveat_fails(hb):
    answer = _good_hb(hb).replace(hb.caveats[0], "")
    assert grade(answer, hb)["caveat_compliance"] is False


def test_badge_without_attestation_fails(calcium):
    assert grade("Total calcium is critically low " + BADGE + ". Was this total or ionized?", calcium)["badge_integrity"] is False


def test_badge_missing_after_pass_fails(hb):
    assert grade(_good_hb(hb).replace(BADGE, ""), hb)["badge_integrity"] is False


def test_other_uri_fails_single_uri(hb):
    assert grade(_good_hb(hb) + " See also loinc:4548-4.", hb)["single_uri"] is False


def test_precise_clarification_passes(calcium):
    answer = ("The value 4.8 mg/dL reads differently for the two calcium tests (loinc:17861-6, loinc:17864-0). "
              "Was this total calcium or ionized calcium?")
    assert grade(answer, calcium)["passed"]


def test_suggesting_an_answer_fails(calcium):
    result = grade("This is probably total calcium. Was it total or ionized?", calcium)
    assert result["no_suggestion"] is False and not result["passed"]


def test_clarification_must_offer_every_value(calcium):
    assert grade("Was this total calcium?", calcium)["clarification_precision"] is False


def test_unit_clarification_offers_candidate_units(hb_no_unit):
    good = "Hb can mean hemoglobin or HbA1c. Which unit was reported: g/dL, g/L or %?"
    assert grade(good, hb_no_unit)["passed"]
    assert grade("Which unit was reported: g/dL?", hb_no_unit)["clarification_precision"] is False
