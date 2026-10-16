"""Canonical financial-period comparison."""

from __future__ import annotations

import re

from .base import CheckStatus, ComponentCheck


class PeriodParseError(ValueError):
    pass


def normalize_period(value: str) -> str:
    text = value.strip().upper()
    basis = ""
    if "ADJUSTED" in text or "NON-GAAP" in text:
        basis = "ADJUSTED:"
    elif "GAAP" in text:
        basis = "GAAP:"
    text = re.sub(r"\b(ADJUSTED|NON-GAAP|GAAP)\b", "", text)
    compact = re.sub(r"[\s_./-]+", "", text)

    patterns = (
        (r"(?:FY|FISCALYEAR)(\d{4})", lambda match: f"FY{match.group(1)}"),
        (r"(\d{4})(?:FY|FISCALYEAR)", lambda match: f"FY{match.group(1)}"),
        (r"(\d{4})Q([1-4])", lambda match: f"{match.group(1)}Q{match.group(2)}"),
        (r"Q([1-4])(\d{4})", lambda match: f"{match.group(2)}Q{match.group(1)}"),
        (r"([1-4])Q(\d{2})", lambda match: f"20{match.group(2)}Q{match.group(1)}"),
        (r"(\d{4})H([12])", lambda match: f"{match.group(1)}H{match.group(2)}"),
        (r"H([12])(\d{4})", lambda match: f"{match.group(2)}H{match.group(1)}"),
        (r"(?:CY|CALENDARYEAR)(\d{4})", lambda match: f"CY{match.group(1)}"),
        (r"TTM", lambda _: "TTM"),
        (r"LTM", lambda _: "TTM"),
    )
    for pattern, render in patterns:
        match = re.fullmatch(pattern, compact)
        if match:
            return basis + render(match)
    raise PeriodParseError(f"unknown financial period: {value!r}")


def check_period(observed: str | None, expected: str | None) -> ComponentCheck:
    if observed is None and expected is None:
        return ComponentCheck(
            component="financial_period",
            status=CheckStatus.NOT_APPLICABLE,
            code="period.absent",
            detail="Neither side declares a financial period.",
        )
    if observed is None or expected is None:
        return ComponentCheck(
            component="financial_period",
            status=CheckStatus.INSUFFICIENT,
            code="period.missing",
            observed=observed,
            expected=expected,
            detail="Only one side declares a financial period.",
        )
    try:
        actual = normalize_period(observed)
        target = normalize_period(expected)
    except PeriodParseError as exc:
        return ComponentCheck(
            component="financial_period",
            status=CheckStatus.INSUFFICIENT,
            code="period.unknown",
            observed=observed,
            expected=expected,
            detail=str(exc),
        )
    matches = actual == target
    return ComponentCheck(
        component="financial_period",
        status=CheckStatus.PASS if matches else CheckStatus.FAIL,
        code="period.match" if matches else "period.mismatch",
        observed=actual,
        expected=target,
        detail="Financial periods match." if matches else "Financial periods do not match.",
    )
