"""Locale-tolerant numeric parsing and comparator logic."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from fincarat.schema import Comparator, ComparatorKind

from .base import CheckStatus, ComponentCheck

_SCALE_SUFFIXES = {
    "k": Decimal("1e3"),
    "thousand": Decimal("1e3"),
    "m": Decimal("1e6"),
    "mn": Decimal("1e6"),
    "mm": Decimal("1e6"),
    "million": Decimal("1e6"),
    "b": Decimal("1e9"),
    "bn": Decimal("1e9"),
    "billion": Decimal("1e9"),
    "t": Decimal("1e12"),
    "tn": Decimal("1e12"),
    "trillion": Decimal("1e12"),
    "万": Decimal("1e4"),
    "亿": Decimal("1e8"),
    "万亿": Decimal("1e12"),
}
_SUFFIX_PATTERN = re.compile(
    r"(?P<suffix>trillion|billion|million|thousand|万亿|bn|mn|mm|tn|亿|万|[kmbt])$",
    re.IGNORECASE,
)
_CURRENCY_MARKS = str.maketrans("", "", "$€£¥￥")


class NumericParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedNumber:
    amount: Decimal
    explicit_scale: Decimal = Decimal(1)
    is_percent: bool = False

    @property
    def normalized(self) -> Decimal:
        multiplier = Decimal("0.01") if self.is_percent else Decimal(1)
        return self.amount * self.explicit_scale * multiplier


def parse_number(value: object) -> ParsedNumber:
    if isinstance(value, bool) or value is None:
        raise NumericParseError("boolean and null values are not numeric")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise NumericParseError("numeric value must be finite")
        return ParsedNumber(value)
    if isinstance(value, int):
        return ParsedNumber(Decimal(value))
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NumericParseError("numeric value must be finite")
        return ParsedNumber(Decimal(str(value)))
    if not isinstance(value, str):
        raise NumericParseError(f"unsupported numeric type: {type(value).__name__}")

    text = value.strip().translate(_CURRENCY_MARKS).replace(",", "").replace("，", "")
    text = re.sub(r"\s+", "", text)
    if not text:
        raise NumericParseError("numeric string is empty")

    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    is_percent = text.endswith("%") or text.endswith("％")
    if is_percent:
        text = text[:-1]

    scale = Decimal(1)
    suffix_match = _SUFFIX_PATTERN.search(text)
    if suffix_match:
        suffix = suffix_match.group("suffix").lower()
        scale = _SCALE_SUFFIXES[suffix]
        text = text[: suffix_match.start()]

    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise NumericParseError(f"cannot parse numeric value: {value!r}") from exc
    if not amount.is_finite():
        raise NumericParseError("numeric value must be finite")
    if negative:
        amount = -amount
    return ParsedNumber(amount=amount, explicit_scale=scale, is_percent=is_percent)


def compare_decimals(
    observed: Decimal,
    comparator: Comparator,
    *,
    expected: Decimal | None = None,
    lower_bound: Decimal | None = None,
    upper_bound: Decimal | None = None,
) -> ComponentCheck:
    if comparator.kind == ComparatorKind.SEMANTIC:
        return ComponentCheck(
            component="numeric_value",
            status=CheckStatus.NOT_APPLICABLE,
            code="numeric.semantic",
            observed=str(observed),
            detail="Semantic comparators are routed to a semantic judge.",
        )
    if comparator.kind == ComparatorKind.SET_MEMBERSHIP:
        return ComponentCheck(
            component="numeric_value",
            status=CheckStatus.NOT_APPLICABLE,
            code="numeric.set_membership",
            observed=str(observed),
            detail="Set membership is not a numeric comparator.",
        )

    passed = False
    detail = ""
    rendered_expected: str | None = None
    if comparator.kind == ComparatorKind.RANGE:
        if lower_bound is None or upper_bound is None:
            return _insufficient(observed, "numeric.range_missing", "Range bounds are missing.")
        passed = lower_bound <= observed <= upper_bound
        rendered_expected = f"[{lower_bound}, {upper_bound}]"
        detail = "Observed value is inside the inclusive range." if passed else "Outside range."
    elif expected is None:
        return _insufficient(observed, "numeric.expected_missing", "Expected value is missing.")
    elif comparator.kind == ComparatorKind.EXACT:
        passed = observed == expected
        rendered_expected = str(expected)
        detail = "Exact numeric match." if passed else "Exact numeric mismatch."
    elif comparator.kind == ComparatorKind.ABSOLUTE_TOLERANCE:
        tolerance = comparator.absolute_tolerance
        if tolerance is None:
            return _insufficient(
                observed,
                "numeric.tolerance_missing",
                "Absolute tolerance is missing.",
            )
        delta = abs(observed - expected)
        passed = delta <= tolerance
        rendered_expected = f"{expected} ± {tolerance}"
        detail = f"Absolute difference is {delta}."
    else:
        tolerance = comparator.relative_tolerance
        if tolerance is None:
            return _insufficient(
                observed,
                "numeric.tolerance_missing",
                "Relative tolerance is missing.",
            )
        delta = abs(observed - expected)
        relative_error = Decimal(0) if delta == 0 else Decimal("Infinity")
        if expected != 0:
            relative_error = delta / abs(expected)
        passed = relative_error <= tolerance
        rendered_expected = f"{expected} (relative tolerance {tolerance})"
        detail = f"Relative error is {relative_error}."

    return ComponentCheck(
        component="numeric_value",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        code="numeric.match" if passed else "numeric.mismatch",
        observed=str(observed),
        expected=rendered_expected,
        detail=detail,
    )


def _insufficient(observed: Decimal, code: str, detail: str) -> ComponentCheck:
    return ComponentCheck(
        component="numeric_value",
        status=CheckStatus.INSUFFICIENT,
        code=code,
        observed=str(observed),
        detail=detail,
    )
