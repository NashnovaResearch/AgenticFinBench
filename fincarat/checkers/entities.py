"""Entity and security-code matching without fuzzy guessing."""

from __future__ import annotations

import re
import unicodedata

from fincarat.schema import Subject

from .base import CheckStatus, ComponentCheck


def normalize_entity_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def check_entity(
    observed: Subject | None,
    expected_name: str,
    *,
    aliases: tuple[str, ...] = (),
    expected_ticker: str | None = None,
    expected_market: str | None = None,
) -> ComponentCheck:
    if observed is None:
        return ComponentCheck(
            component="entity",
            status=CheckStatus.INSUFFICIENT,
            code="entity.missing",
            expected=expected_name,
            detail="The claim has no structured subject.",
        )

    accepted_names = {normalize_entity_name(expected_name)}
    accepted_names.update(normalize_entity_name(alias) for alias in aliases)
    name_matches = normalize_entity_name(observed.name) in accepted_names
    ticker_matches = (
        expected_ticker is None
        or observed.ticker is None
        or observed.ticker.casefold() == expected_ticker.casefold()
    )
    market_matches = (
        expected_market is None
        or observed.market is None
        or observed.market.casefold() == expected_market.casefold()
    )
    matches = name_matches and ticker_matches and market_matches
    observed_text = observed.name
    if observed.ticker:
        observed_text += f" ({observed.ticker})"
    if observed.market:
        observed_text += f" [{observed.market}]"
    return ComponentCheck(
        component="entity",
        status=CheckStatus.PASS if matches else CheckStatus.FAIL,
        code="entity.match" if matches else "entity.mismatch",
        observed=observed_text,
        expected=expected_name,
        detail=(
            "Entity identity matches the registry."
            if matches
            else "Name, ticker, or market conflicts with the registry."
        ),
    )
