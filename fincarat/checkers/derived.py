"""Whitelisted financial derivations; arbitrary expressions are never evaluated."""

from __future__ import annotations

from decimal import Decimal, DivisionByZero, InvalidOperation
from enum import StrEnum


class DerivedOperation(StrEnum):
    GROWTH_RATE = "growth_rate"
    RATIO = "ratio"
    DIFFERENCE = "difference"
    SUM = "sum"
    PERCENTAGE_POINT_CHANGE = "percentage_point_change"


class DerivationError(ValueError):
    pass


def recompute(operation: DerivedOperation, inputs: tuple[Decimal, ...]) -> Decimal:
    try:
        if operation == DerivedOperation.GROWTH_RATE:
            _require_arity(operation, inputs, 2)
            current, previous = inputs
            if previous == 0:
                raise DerivationError("growth rate is undefined when the previous value is zero")
            return (current - previous) / abs(previous)
        if operation == DerivedOperation.RATIO:
            _require_arity(operation, inputs, 2)
            numerator, denominator = inputs
            if denominator == 0:
                raise DerivationError("ratio is undefined when the denominator is zero")
            return numerator / denominator
        if operation in {DerivedOperation.DIFFERENCE, DerivedOperation.PERCENTAGE_POINT_CHANGE}:
            _require_arity(operation, inputs, 2)
            current, previous = inputs
            return current - previous
        if operation == DerivedOperation.SUM:
            if not inputs:
                raise DerivationError("sum requires at least one input")
            return sum(inputs, start=Decimal(0))
    except (DivisionByZero, InvalidOperation) as exc:
        raise DerivationError(f"invalid decimal operation: {exc}") from exc
    raise DerivationError(f"unsupported derivation: {operation}")


def _require_arity(
    operation: DerivedOperation,
    inputs: tuple[Decimal, ...],
    expected: int,
) -> None:
    if len(inputs) != expected:
        raise DerivationError(
            f"{operation.value} requires {expected} inputs, received {len(inputs)}"
        )
