"""Timezone-safe comparison of financial observation times."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .base import CheckStatus, ComponentCheck


def check_time(
    observed: date | datetime | None,
    expected: date | datetime | None,
    *,
    tolerance: timedelta = timedelta(0),
) -> ComponentCheck:
    if tolerance < timedelta(0):
        raise ValueError("time tolerance must not be negative")
    if observed is None and expected is None:
        return ComponentCheck(
            component="as_of",
            status=CheckStatus.NOT_APPLICABLE,
            code="time.absent",
            detail="Neither side declares an as_of time.",
        )
    if observed is None or expected is None:
        return ComponentCheck(
            component="as_of",
            status=CheckStatus.INSUFFICIENT,
            code="time.missing",
            observed=observed.isoformat() if observed else None,
            expected=expected.isoformat() if expected else None,
            detail="Only one side declares an as_of time.",
        )
    if isinstance(observed, datetime) != isinstance(expected, datetime):
        observed_date = observed.date() if isinstance(observed, datetime) else observed
        expected_date = expected.date() if isinstance(expected, datetime) else expected
        day_delta = abs(observed_date - expected_date)
        matches = day_delta <= tolerance
        return ComponentCheck(
            component="as_of",
            status=CheckStatus.PASS if matches else CheckStatus.FAIL,
            code="time.calendar_date_match" if matches else "time.calendar_date_mismatch",
            observed=observed.isoformat(),
            expected=expected.isoformat(),
            detail=(
                f"Compared calendar dates because only one side supplied a time; "
                f"difference is {day_delta}."
            ),
        )
    if not isinstance(observed, datetime) and not isinstance(expected, datetime):
        day_delta = abs(observed - expected)
        matches = day_delta <= tolerance
        return ComponentCheck(
            component="as_of",
            status=CheckStatus.PASS if matches else CheckStatus.FAIL,
            code="time.date_match" if matches else "time.date_mismatch",
            observed=observed.isoformat(),
            expected=expected.isoformat(),
            detail=f"Calendar-date difference is {day_delta}; tolerance is {tolerance}.",
        )
    assert isinstance(observed, datetime) and isinstance(expected, datetime)
    if observed.tzinfo is None or expected.tzinfo is None:
        return ComponentCheck(
            component="as_of",
            status=CheckStatus.INSUFFICIENT,
            code="time.naive",
            observed=observed.isoformat(),
            expected=expected.isoformat(),
            detail="Both timestamps must include a UTC offset.",
        )
    delta = abs(observed - expected)
    matches = delta <= tolerance
    return ComponentCheck(
        component="as_of",
        status=CheckStatus.PASS if matches else CheckStatus.FAIL,
        code="time.match" if matches else "time.mismatch",
        observed=observed.isoformat(),
        expected=expected.isoformat(),
        detail=f"Absolute timestamp difference is {delta}; tolerance is {tolerance}.",
    )
