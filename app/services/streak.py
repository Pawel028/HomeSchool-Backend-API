"""Streak rule (24_PROGRESS_RULES): count of completed days in an unbroken chain in the family timezone.

- Days with nothing planned neither extend nor break the chain (rest days).
- One missed planned day per rolling 7 days is forgiven automatically.
- The evaluation day itself never breaks the chain while it is still in progress.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

DONE, PLANNED, REST = "done", "planned", "rest"


def streak_from_days(days: Sequence[str]) -> int:
    """days is oldest to newest; the last entry is the evaluation day. Values: done | planned (missed) | rest."""
    count = 0
    last_forgiven: int | None = None  # index of the most recently forgiven (later) missed day
    for idx in range(len(days) - 1, -1, -1):
        d = days[idx]
        if d == DONE:
            count += 1
        elif d == REST:
            continue
        elif idx == len(days) - 1:
            continue  # today is not over: not a miss yet
        else:  # planned but missed
            if last_forgiven is not None and last_forgiven - idx < 7:
                break
            last_forgiven = idx
    return count


def compute_streak(today: date, completed_days: set[date], planned_days: set[date], lookback: int = 120) -> int:
    seq: list[str] = []
    for i in range(lookback, -1, -1):
        d = today - timedelta(days=i)
        if d in completed_days:
            seq.append(DONE)
        elif d in planned_days:
            seq.append(PLANNED)
        else:
            seq.append(REST)
    return streak_from_days(seq)
