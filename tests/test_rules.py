"""Pure-function tests: mastery model, streak rule, content scoring. Vectors are the shared contract (api-contracts)."""

import json
from pathlib import Path

import pytest

from app.services import content, mastery, streak

HERE = Path(__file__).parent
ROOT = HERE.parent


def _load(name):
    return json.loads((HERE / "vectors" / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("scenario", _load("mastery-vectors.json")["scenarios"], ids=lambda s: s["name"])
def test_mastery_vectors(scenario):
    items = [
        mastery.Item(value=e["value"], weight=mastery.evidence_weight(e["source"], e["independence"]), day=e["day"])
        for e in scenario["evidence"]
    ]
    states = mastery.replay(items)
    assert len(states) == len(scenario["evidence"])
    for e, st in zip(scenario["evidence"], states):
        exp = e["expected"]
        assert mastery.BASE_WEIGHTS[e["source"]] == pytest.approx(exp["base_weight"])
        assert mastery.INDEPENDENCE_FACTORS[e["independence"]] == pytest.approx(exp["factor"])
        assert mastery.evidence_weight(e["source"], e["independence"]) == pytest.approx(exp["weight"])
        assert st.alpha == pytest.approx(exp["alpha"], abs=1e-9)
        assert st.score == pytest.approx(exp["score"], abs=1e-9)
        assert st.confidence == pytest.approx(exp["confidence"], abs=1e-9)
        assert st.distinct_days == exp["distinct_days"]
        assert st.status == exp["status"], f"evidence {e['n']}"


def test_replay_is_deterministic_and_order_defines_state():
    items = [mastery.Item(1.0, 1.0, 1), mastery.Item(0.0, 1.0, 2), mastery.Item(1.0, 0.7, 3)]
    assert mastery.replay(items) == mastery.replay(list(items))
    assert mastery.final_state([]) is None


def test_independence_levels():
    assert mastery.independence_for_session(0, False) == "independent"
    assert mastery.independence_for_session(2, False) == "prompted"
    assert mastery.independence_for_session(0, True) == "assisted"
    assert mastery.independence_for_session(3, True) == "assisted"


def test_trend_thresholds():
    assert (
        mastery.trend(0.5, 0.56) == "up" and mastery.trend(0.5, 0.44) == "down" and mastery.trend(0.5, 0.52) == "flat"
    )


@pytest.mark.parametrize("scenario", _load("streak-vectors.json")["scenarios"], ids=lambda s: s["name"])
def test_streak_vectors(scenario):
    assert streak.streak_from_days(scenario["days"]) == scenario["expected"]


def test_streak_today_in_progress_never_breaks_the_chain():
    assert streak.streak_from_days(["done", "done", "planned"]) == 2


def test_streak_forgiveness_is_once_per_rolling_week():
    # two misses six days apart: the second one breaks the chain
    days = ["done", "planned", "done", "done", "done", "done", "done", "planned", "done"]
    assert streak.streak_from_days(days) == 6


def _launch_activities():
    return json.loads((ROOT / "seed" / "launch-bundle.json").read_text(encoding="utf-8"))


def test_launch_bundle_activities_are_valid():
    b = _launch_activities()
    known = {s["code"] for s in b["skills"]}
    for a in b["activities"]:
        assert content.validate_activity(a, known) == [], a["slug"]


def test_vendored_schema_matches_api_contracts_when_available():
    sibling = ROOT.parent / "api-contracts" / "schemas" / "activity-content.schema.json"
    if not sibling.exists():
        pytest.skip("api-contracts is not checked out next to this repo")
    assert sibling.read_text(encoding="utf-8") == content.SCHEMA_PATH.read_text(encoding="utf-8"), (
        "run scripts/sync_contracts.py"
    )


STEP = {
    "single_choice": {
        "id": "a",
        "type": "single_choice",
        "prompt": "?",
        "options": [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}],
        "correct": ["x"],
    },
    "numeric": {"id": "n", "type": "numeric_input", "prompt": "?", "answer": 5, "tolerance": 0.5},
    "seq": {
        "id": "s",
        "type": "sequence_order",
        "prompt": "?",
        "items": [{"id": "1", "label": "1"}, {"id": "2", "label": "2"}],
        "correct_order": ["1", "2"],
    },
    "pairs": {
        "id": "p",
        "type": "match_pairs",
        "prompt": "?",
        "left": [{"id": "l1", "label": "a"}, {"id": "l2", "label": "b"}],
        "right": [{"id": "r1", "label": "a"}, {"id": "r2", "label": "b"}],
        "pairs": [["l1", "r1"], ["l2", "r2"]],
    },
    "multi": {
        "id": "m",
        "type": "multi_choice",
        "prompt": "?",
        "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
        "correct": ["a", "b"],
        "partial_credit": True,
    },
    "text": {"id": "t", "type": "short_text", "prompt": "?", "accepted": ["Cat", "kitten"]},
}


def test_scoring_per_step_type():
    S = STEP
    assert content.score_step(S["single_choice"], "x") == 1.0 and content.score_step(S["single_choice"], "y") == 0.0
    assert content.score_step(S["numeric"], 5.4) == 1.0 and content.score_step(S["numeric"], "7") == 0.0
    assert content.score_step(S["numeric"], "abc") == 0.0
    assert content.score_step(S["seq"], ["1", "2"]) == 1.0 and content.score_step(S["seq"], ["2", "1"]) == 0.0
    assert content.score_step(S["pairs"], [["l1", "r1"], ["l2", "r2"]]) == 1.0
    assert (
        content.score_step(S["pairs"], [["l1", "r1"], ["l2", "r1"]]) == 0.0
    )  # one right, one wrong: (1-1)/2, never negative
    assert content.score_step(S["pairs"], [["l1", "r2"], ["l2", "r1"]]) == 0.0
    assert content.score_step(S["multi"], ["a", "b"]) == 1.0 and content.score_step(S["multi"], ["a"]) == 0.5
    assert content.score_step(S["multi"], ["a", "c"]) == 0.0
    assert content.score_step(S["text"], " kitten ") == 1.0 and content.score_step(S["text"], "dog") == 0.0


def test_unanswered_and_unscored_steps_give_no_score():
    assert content.score_step(STEP["single_choice"], None) is None
    assert content.score_step({**STEP["single_choice"], "scored": False}, "x") is None
    assert content.score_step({"id": "i", "type": "instruction", "text": "hi"}, "x") is None


def test_public_definition_strips_answer_keys():
    d = {
        "steps": [
            dict(STEP["single_choice"]),
            dict(STEP["numeric"]),
            dict(STEP["seq"]),
            dict(STEP["pairs"]),
            dict(STEP["text"]),
        ]
    }
    pub = json.dumps(content.public_definition(d))
    for key in ('"correct"', '"answer"', '"accepted"', '"correct_order"', '"pairs"', '"tolerance"'):
        assert key not in pub
    assert '"options"' in pub and '"left"' in pub  # everything the child needs stays
    assert "correct" in json.dumps(d)  # the original is not mutated
