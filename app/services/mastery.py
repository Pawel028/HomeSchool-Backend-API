"""Deterministic mastery model (24_PROGRESS_RULES, ADR-017). Pure functions, no database access.

Score update for the k-th evidence item (n = items before it):
    n == 0 : score = value
    n  > 0 : alpha = min(1, max(alpha_min, 1 / (n + 1)) * weight);  score += alpha * (value - score)
Confidence = min(1, n_after / confidence_full_n).
Status: not_started | emerging | developing | secure (thresholds below).
The state is always recomputed by replaying the ordered evidence log, so replays give identical results.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

PARAMS = {
    "alpha_min": 0.2,
    "emerging_max": 0.4,
    "secure_min": 0.7,
    "confidence_min": 0.6,
    "confidence_full_n": 5,
    "min_evidence_for_secure": 3,
    "min_days_for_secure": 2,
    "trend_threshold": 0.05,
}
BASE_WEIGHTS = {"activity": 1.0, "observation": 1.0, "assessment": 1.5, "baseline": 0.8}
INDEPENDENCE_FACTORS = {"independent": 1.0, "prompted": 0.7, "assisted": 0.5}
RATING_VALUES = {"trying": 0.3, "with_help": 0.6, "independent": 1.0}
SOURCES = tuple(BASE_WEIGHTS)


@dataclass(frozen=True)
class Item:
    value: float
    weight: float
    day: date | int  # calendar day in the family timezone (an int is accepted for test vectors)
    occurred_at: datetime | None = None


@dataclass(frozen=True)
class State:
    n: int
    score: float
    confidence: float
    distinct_days: int
    status: str
    alpha: float


def evidence_weight(source: str, independence: str) -> float:
    return BASE_WEIGHTS[source] * INDEPENDENCE_FACTORS[independence]


def status_for(n: int, score: float, confidence: float, distinct_days: int) -> str:
    p = PARAMS
    if n == 0:
        return "not_started"
    if score < p["emerging_max"]:
        return "emerging"
    if (
        score >= p["secure_min"]
        and confidence >= p["confidence_min"]
        and n >= p["min_evidence_for_secure"]
        and distinct_days >= p["min_days_for_secure"]
    ):
        return "secure"
    return "developing"


def replay(items: Sequence[Item]) -> list[State]:
    """State after each evidence item, in order."""
    states: list[State] = []
    score = 0.0
    days: set = set()
    for n, it in enumerate(items):
        if n == 0:
            alpha = 1.0
            score = it.value
        else:
            alpha = min(1.0, max(PARAMS["alpha_min"], 1.0 / (n + 1)) * it.weight)
            score = score + alpha * (it.value - score)
        days.add(it.day)
        after = n + 1
        conf = min(1.0, after / PARAMS["confidence_full_n"])
        states.append(State(after, score, conf, len(days), status_for(after, score, conf, len(days)), alpha))
    return states


def final_state(items: Sequence[Item]) -> State | None:
    s = replay(items)
    return s[-1] if s else None


def trend(score_start: float, score_end: float) -> str:
    delta = score_end - score_start
    if delta >= PARAMS["trend_threshold"]:
        return "up"
    if delta <= -PARAMS["trend_threshold"]:
        return "down"
    return "flat"


def independence_for_session(hints_used: int, parent_assist: bool) -> str:
    if parent_assist:
        return "assisted"
    if hints_used > 0:
        return "prompted"
    return "independent"
