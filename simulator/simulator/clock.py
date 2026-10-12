"""Simulator clock.

Time starts at the end of the seeded history and moves only when a caller
advances or sets it. Metrics and costs include instants before `now`.
This module does not read the wall clock.
"""

from datetime import date, datetime, timedelta

from simulator.metrics import HISTORY_END, history_start


def initial_now() -> datetime:
    return HISTORY_END


def last_observed_day(now: datetime) -> date:
    return now.date() - timedelta(days=1)


def require_clock(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be UTC")
    if now <= history_start():
        raise ValueError("clock is before seeded history")
