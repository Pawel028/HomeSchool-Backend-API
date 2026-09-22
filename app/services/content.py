"""Activity content: JSON Schema + semantic validation, and auto-scoring of answers.

The JSON Schema is the canonical copy from api-contracts (schemas/activity-content.schema.json), vendored at
app/content/activity.schema.json. scripts/sync_contracts.py refreshes it; a test fails if it drifts.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "content" / "activity.schema.json"
AUTO_TYPES = {"single_choice", "multi_choice", "numeric_input", "short_text", "sequence_order", "match_pairs"}
UNSCORED_TYPES = {"instruction", "media_prompt", "audio_record", "photo_evidence", "timer_task", "reflection"}
SKILL_RE = re.compile(r"^[A-Z]{3}\.[A-Z0-9]+\.[A-Z0-9]+$")


@lru_cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def _where(path) -> str:
    return "/".join(str(p) for p in path) or "(root)"


def _explain(e) -> list[str]:
    """One readable line per problem. For a step that matches none of the step types, report the errors of the branch
    for its own type instead of dumping the whole step."""
    if e.validator == "oneOf" and e.context and isinstance(e.instance, dict) and "type" in e.instance:
        branches = e.schema.get("oneOf", [])
        k = next(
            (
                i
                for i, b in enumerate(branches)
                if b.get("properties", {}).get("type", {}).get("const") == e.instance["type"]
            ),
            None,
        )
        if k is None:
            return [f"{_where(e.path)}: unknown step type {e.instance['type']!r}"]
        subs = [c for c in e.context if c.schema_path and c.schema_path[0] == k]
        if subs:
            return [f"{_where(e.path)}/{_where(c.path)}: {c.message[:160]}".replace("/(root)", "") for c in subs]
    return [f"{_where(e.path)}: {e.message[:160]}"]


def is_scored(step: dict[str, Any]) -> bool:
    """A step produces evidence if it is auto-scorable (and not switched off) or is a parent checklist."""
    t = step["type"]
    if t == "parent_checklist":
        return True
    if t not in AUTO_TYPES or step.get("scored") is False:
        return False
    if t == "short_text":
        return bool(step.get("accepted"))
    return True


def validate_activity(
    activity: dict[str, Any], known_skills: set[str] | None = None, known_levels: list[str] | None = None
) -> list[str]:
    """Returns a list of problems (empty when valid)."""
    problems = [line for e in _validator().iter_errors(activity) for line in _explain(e)]
    if problems:
        return problems
    order = known_levels or ["L1", "L2", "L3", "L4", "L5"]
    if order.index(activity["level_from"]) > order.index(activity["level_to"]):
        problems.append("level_from is above level_to")
    ids = [s["id"] for s in activity["steps"]]
    if len(ids) != len(set(ids)):
        problems.append("step ids must be unique")
    skills = set(activity["skills"])
    if known_skills is not None:
        for code in skills - known_skills:
            problems.append(f"unknown skill {code}")
    for step in activity["steps"]:
        sid, t = step["id"], step["type"]
        if t in ("single_choice", "multi_choice"):
            opt_ids = {o["id"] for o in step["options"]}
            correct = step.get("correct", [])
            if is_scored(step) and not correct:
                problems.append(f"{sid}: scored {t} needs 'correct' (or set scored=false)")
            if not set(correct) <= opt_ids:
                problems.append(f"{sid}: 'correct' refers to unknown option")
        if t == "sequence_order":
            item_ids = {i["id"] for i in step["items"]}
            if set(step["correct_order"]) != item_ids or len(step["correct_order"]) != len(item_ids):
                problems.append(f"{sid}: correct_order must list every item exactly once")
        if t == "match_pairs":
            left = {i["id"] for i in step["left"]}
            right = {i["id"] for i in step["right"]}
            for a, b in step["pairs"]:
                if a not in left or b not in right:
                    problems.append(f"{sid}: pair {a},{b} refers to an unknown item")
        if t == "parent_checklist":
            if not SKILL_RE.match(step["skill_code"]):
                problems.append(f"{sid}: invalid skill_code")
            elif known_skills is not None and step["skill_code"] not in known_skills:
                problems.append(f"{sid}: unknown skill {step['skill_code']}")
        for code in step.get("skills", []):
            if known_skills is not None and code not in known_skills:
                problems.append(f"{sid}: unknown skill {code}")
    return problems


def step_skills(step: dict[str, Any], activity_skills: list[str]) -> list[str]:
    if step["type"] == "parent_checklist":
        return [step["skill_code"]]
    return list(step.get("skills") or activity_skills)


def public_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Strips answer keys so the client never receives the correct answers."""
    out = json.loads(json.dumps(definition))
    for step in out.get("steps", []):
        for key in ("correct", "answer", "accepted", "correct_order", "pairs", "tolerance"):
            step.pop(key, None)
    return out


def score_step(step: dict[str, Any], answer: Any) -> float | None:
    """0..1 for an auto-scored step; None when the step is not auto-scored or was not answered."""
    t = step["type"]
    if t not in AUTO_TYPES or step.get("scored") is False or answer is None:
        return None
    if t == "single_choice":
        return 1.0 if isinstance(answer, str) and [answer] == step.get("correct") else 0.0
    if t == "multi_choice":
        correct = set(step["correct"])
        given = set(answer) if isinstance(answer, list) else set()
        if step.get("partial_credit"):
            wrong = len(given - correct)
            return max(0.0, (len(given & correct) - wrong) / len(correct))
        return 1.0 if given == correct else 0.0
    if t == "numeric_input":
        try:
            return 1.0 if abs(float(answer) - float(step["answer"])) <= float(step.get("tolerance", 0)) else 0.0
        except (TypeError, ValueError):
            return 0.0
    if t == "short_text":
        accepted = [a.strip().lower() for a in step.get("accepted", [])]
        if not accepted:
            return None
        return 1.0 if isinstance(answer, str) and answer.strip().lower() in accepted else 0.0
    if t == "sequence_order":
        return 1.0 if answer == step["correct_order"] else 0.0
    if t == "match_pairs":
        expected = {tuple(p) for p in step["pairs"]}
        given = {tuple(p) for p in answer if isinstance(p, list) and len(p) == 2} if isinstance(answer, list) else set()
        if not expected:
            return None
        return max(0.0, (len(given & expected) - len(given - expected)) / len(expected))
    return None
