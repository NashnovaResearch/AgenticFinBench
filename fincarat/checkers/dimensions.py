"""Unit, scale, and currency normalization for financial values."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .base import CheckStatus, ComponentCheck
from .numbers import parse_number

_CURRENCY_ALIASES = {
    "cny": "CNY",
    "rmb": "CNY",
    "人民币": "CNY",
    "usd": "USD",
    "us$": "USD",
    "美元": "USD",
    "hkd": "HKD",
    "港元": "HKD",
    "eur": "EUR",
    "欧元": "EUR",
    "gbp": "GBP",
    "英镑": "GBP",
    "jpy": "JPY",
    "日元": "JPY",
}
_SCALES = {
    "ones": Decimal(1),
    "unit": Decimal(1),
    "thousand": Decimal("1e3"),
    "k": Decimal("1e3"),
    "万": Decimal("1e4"),
    "million": Decimal("1e6"),
    "m": Decimal("1e6"),
    "亿": Decimal("1e8"),
    "billion": Decimal("1e9"),
    "bn": Decimal("1e9"),
    "trillion": Decimal("1e12"),
    "tn": Decimal("1e12"),
    "万亿": Decimal("1e12"),
}
_SIMPLE_UNITS = {
    "percent": ("ratio", Decimal("0.01"), "percent"),
    "%": ("ratio", Decimal("0.01"), "percent"),
    "percentage_point": ("percentage_point", Decimal("0.01"), "percentage_point"),
    "pp": ("percentage_point", Decimal("0.01"), "percentage_point"),
    "basis_point": ("ratio", Decimal("0.0001"), "basis_point"),
    "bps": ("ratio", Decimal("0.0001"), "basis_point"),
    "share": ("share", Decimal(1), "share"),
    "shares": ("share", Decimal(1), "share"),
    "股": ("share", Decimal(1), "share"),
    "lot": ("lot", Decimal(1), "lot"),
    "手": ("lot", Decimal(1), "lot"),
    "dimensionless": ("dimensionless", Decimal(1), "dimensionless"),
}


class DimensionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class UnitSpec:
    dimension: str
    multiplier: Decimal
    canonical: str
    currency: str | None = None


def canonical_currency(value: str | None) -> str | None:
    if value is None:
        return None
    key = re.sub(r"\s+", "", value).lower()
    if key in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[key]
    if re.fullmatch(r"[a-z]{3}", key):
        return key.upper()
    raise DimensionError(f"unknown currency: {value!r}")


def parse_unit(value: str | None) -> UnitSpec | None:
    if value is None or not value.strip():
        return None
    normalized = re.sub(r"[\s-]+", "_", value.strip()).lower()
    if normalized in _SIMPLE_UNITS:
        dimension, multiplier, canonical = _SIMPLE_UNITS[normalized]
        return UnitSpec(dimension=dimension, multiplier=multiplier, canonical=canonical)

    parts = normalized.split("_")
    currency = None
    scale = Decimal(1)
    remainder: list[str] = []
    for part in parts:
        if part in _CURRENCY_ALIASES and currency is None:
            currency = _CURRENCY_ALIASES[part]
        elif part in _SCALES:
            scale *= _SCALES[part]
        else:
            remainder.append(part)

    if currency is not None and not remainder:
        return UnitSpec(
            dimension="currency",
            multiplier=scale,
            canonical=currency,
            currency=currency,
        )
    if len(remainder) == 1 and remainder[0] in {"share", "shares", "股"}:
        return UnitSpec(
            dimension="share",
            multiplier=scale,
            canonical="share",
        )
    raise DimensionError(f"unknown or ambiguous unit: {value!r}")


def normalize_measure(value: object, unit: str | None) -> Decimal:
    parsed = parse_number(value)
    spec = parse_unit(unit)
    unit_multiplier = spec.multiplier if spec else Decimal(1)

    if parsed.explicit_scale != 1 and unit_multiplier != 1:
        raise DimensionError("scale is encoded in both value and unit")
    if parsed.is_percent:
        if spec and spec.dimension not in {"ratio", "percentage_point"}:
            raise DimensionError("percent sign conflicts with the declared unit")
        multiplier = Decimal("0.01")
    else:
        multiplier = unit_multiplier
    return parsed.amount * parsed.explicit_scale * multiplier


def check_unit(observed: str | None, expected: str | None) -> ComponentCheck:
    if observed is None and expected is None:
        return ComponentCheck(
            component="unit",
            status=CheckStatus.NOT_APPLICABLE,
            code="unit.absent",
            detail="Neither side declares a unit.",
        )
    if observed is None or expected is None:
        return ComponentCheck(
            component="unit",
            status=CheckStatus.INSUFFICIENT,
            code="unit.missing",
            observed=observed,
            expected=expected,
            detail="Only one side declares a unit.",
        )
    try:
        observed_spec = parse_unit(observed)
        expected_spec = parse_unit(expected)
    except DimensionError as exc:
        return ComponentCheck(
            component="unit",
            status=CheckStatus.INSUFFICIENT,
            code="unit.unknown",
            observed=observed,
            expected=expected,
            detail=str(exc),
        )
    assert observed_spec is not None and expected_spec is not None
    compatible = (
        observed_spec.dimension == expected_spec.dimension
        and observed_spec.currency == expected_spec.currency
    )
    return ComponentCheck(
        component="unit",
        status=CheckStatus.PASS if compatible else CheckStatus.FAIL,
        code="unit.compatible" if compatible else "unit.incompatible",
        observed=observed,
        expected=expected,
        detail=(
            "Units share a dimension and have a deterministic conversion."
            if compatible
            else "Units have different dimensions or embedded currencies."
        ),
    )


def check_currency(observed: str | None, expected: str | None) -> ComponentCheck:
    if observed is None and expected is None:
        return ComponentCheck(
            component="currency",
            status=CheckStatus.NOT_APPLICABLE,
            code="currency.absent",
            detail="Neither side declares a currency.",
        )
    if observed is None or expected is None:
        return ComponentCheck(
            component="currency",
            status=CheckStatus.INSUFFICIENT,
            code="currency.missing",
            observed=observed,
            expected=expected,
            detail="Only one side declares a currency.",
        )
    try:
        actual = canonical_currency(observed)
        target = canonical_currency(expected)
    except DimensionError as exc:
        return ComponentCheck(
            component="currency",
            status=CheckStatus.INSUFFICIENT,
            code="currency.unknown",
            observed=observed,
            expected=expected,
            detail=str(exc),
        )
    matches = actual == target
    return ComponentCheck(
        component="currency",
        status=CheckStatus.PASS if matches else CheckStatus.FAIL,
        code="currency.match" if matches else "currency.mismatch",
        observed=actual,
        expected=target,
        detail="Currency codes match." if matches else "Currency codes do not match.",
    )
