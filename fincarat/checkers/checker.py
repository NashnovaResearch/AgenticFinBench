"""Deterministic claim-to-truth comparison."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

from fincarat.schema import (
    AtomicClaim,
    ClaimType,
    Comparator,
    ComparatorKind,
    TruthFact,
)

from .base import (
    CheckStatus,
    ComponentCheck,
    DeterministicAssessment,
    aggregate_status,
)
from .derived import DerivationError, DerivedOperation, recompute
from .dimensions import (
    DimensionError,
    check_currency,
    check_unit,
    normalize_measure,
    parse_unit,
)
from .entities import check_entity
from .numbers import NumericParseError, compare_decimals
from .periods import check_period
from .temporal import check_time


class DeterministicChecker:
    def check(
        self,
        claim: AtomicClaim,
        truth: TruthFact,
        comparator: Comparator,
        *,
        entity_aliases: tuple[str, ...] = (),
        expected_ticker: str | None = None,
        expected_market: str | None = None,
        time_tolerance: timedelta = timedelta(0),
        derived_operation: DerivedOperation | None = None,
        derived_inputs: tuple[Decimal, ...] | None = None,
    ) -> DeterministicAssessment:
        if claim.claim_type not in {ClaimType.NUMERIC_FACT, ClaimType.DERIVED_NUMERIC}:
            check = ComponentCheck(
                component="routing",
                status=CheckStatus.NOT_APPLICABLE,
                code="routing.semantic_claim",
                detail="This deterministic bundle currently handles numeric claim types.",
            )
            return DeterministicAssessment(
                claim_id=claim.claim_id,
                reference_fact_id=truth.fact_id,
                status=CheckStatus.NOT_APPLICABLE,
                checks=(check,),
            )

        checks = (
            check_entity(
                claim.subject,
                truth.entity,
                aliases=entity_aliases,
                expected_ticker=expected_ticker,
                expected_market=expected_market,
            ),
            _check_metric(claim.predicate_or_metric, truth.metric_or_predicate),
            check_unit(claim.unit, truth.unit),
            check_currency(
                _effective_currency(claim.currency, claim.unit),
                _effective_currency(truth.currency, truth.unit),
            ),
            check_period(claim.financial_period, truth.financial_period),
            check_time(claim.as_of, truth.as_of, tolerance=time_tolerance),
            self._check_value(
                claim,
                truth,
                comparator,
                derived_operation=derived_operation,
                derived_inputs=derived_inputs,
            ),
        )
        return DeterministicAssessment(
            claim_id=claim.claim_id,
            reference_fact_id=truth.fact_id,
            status=aggregate_status(checks),
            checks=checks,
        )

    def _check_value(
        self,
        claim: AtomicClaim,
        truth: TruthFact,
        comparator: Comparator,
        *,
        derived_operation: DerivedOperation | None,
        derived_inputs: tuple[Decimal, ...] | None,
    ) -> ComponentCheck:
        try:
            observed = normalize_measure(claim.value, claim.unit)
            if claim.claim_type == ClaimType.DERIVED_NUMERIC:
                if derived_operation is None or derived_inputs is None:
                    return _value_insufficient(
                        "derived.inputs_missing",
                        "Derived claims require a whitelisted operation and frozen inputs.",
                    )
                expected = recompute(derived_operation, derived_inputs)
            else:
                expected_value = comparator.expected
                if expected_value is None:
                    expected_value = truth.value
                expected = normalize_measure(expected_value, truth.unit)

            lower = (
                normalize_measure(comparator.lower_bound, truth.unit)
                if comparator.lower_bound is not None
                else None
            )
            upper = (
                normalize_measure(comparator.upper_bound, truth.unit)
                if comparator.upper_bound is not None
                else None
            )
            effective_comparator = comparator
            if (
                comparator.kind == ComparatorKind.ABSOLUTE_TOLERANCE
                and comparator.absolute_tolerance is not None
            ):
                effective_comparator = comparator.model_copy(
                    update={
                        "absolute_tolerance": normalize_measure(
                            comparator.absolute_tolerance,
                            truth.unit,
                        )
                    }
                )
            return compare_decimals(
                observed,
                effective_comparator,
                expected=expected,
                lower_bound=lower,
                upper_bound=upper,
            )
        except (DimensionError, NumericParseError, DerivationError) as exc:
            return _value_insufficient("numeric.normalization_failed", str(exc))


def _effective_currency(currency: str | None, unit: str | None) -> str | None:
    if currency is not None:
        return currency
    try:
        spec = parse_unit(unit)
    except DimensionError:
        return None
    return spec.currency if spec else None


def _normalize_metric(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold())


def _check_metric(observed: str | None, expected: str) -> ComponentCheck:
    if observed is None:
        return ComponentCheck(
            component="metric",
            status=CheckStatus.INSUFFICIENT,
            code="metric.missing",
            expected=expected,
            detail="The claim has no structured metric.",
        )
    matches = _normalize_metric(observed) == _normalize_metric(expected)
    return ComponentCheck(
        component="metric",
        status=CheckStatus.PASS if matches else CheckStatus.FAIL,
        code="metric.match" if matches else "metric.mismatch",
        observed=observed,
        expected=expected,
        detail="Metric identifiers match." if matches else "Metric identifiers do not match.",
    )


def _value_insufficient(code: str, detail: str) -> ComponentCheck:
    return ComponentCheck(
        component="numeric_value",
        status=CheckStatus.INSUFFICIENT,
        code=code,
        detail=detail,
    )
