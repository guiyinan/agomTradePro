"""Strict codec coverage for Portfolio-owned R5 outcome evidence."""

from __future__ import annotations

from datetime import timedelta

import pytest

from apps.portfolio.application.r5_relative_value_outcome import (
    R5PortfolioOutcomePersistenceDraft,
)
from apps.portfolio.domain.r5_relative_value_outcome import R5PortfolioOutcomeSeal
from apps.portfolio.infrastructure.r5_relative_value_outcome_codec import (
    R5PortfolioOutcomeCodecError,
    decode_r5_portfolio_outcome,
    encode_r5_portfolio_outcome,
)
from tests.unit.portfolio.test_r5_relative_value_outcome_persistence import (
    _fixed_income,
    _source,
)


def _outcome(monkeypatch: pytest.MonkeyPatch) -> R5PortfolioOutcomeSeal:
    fixed_income = _fixed_income(monkeypatch)
    source = _source(fixed_income)
    return R5PortfolioOutcomePersistenceDraft(source, fixed_income).to_outcome(
        recorded_at=source.outcome_available_at + timedelta(seconds=1)
    )


def test_codec_round_trips_every_exact_field(monkeypatch: pytest.MonkeyPatch) -> None:
    outcome = _outcome(monkeypatch)

    assert decode_r5_portfolio_outcome(encode_r5_portfolio_outcome(outcome)) == outcome


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("liquidity_breached", 0),
        ("target_cost", 0.01),
        ("recorded_at", "2026-08-01T00:00:00"),
        ("content_hash", "0" * 64),
    ],
)
def test_codec_rejects_wrong_types_or_semantics(
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    bad_value: object,
) -> None:
    payload = encode_r5_portfolio_outcome(_outcome(monkeypatch))
    payload[field_name] = bad_value

    with pytest.raises(R5PortfolioOutcomeCodecError):
        decode_r5_portfolio_outcome(payload)


def test_codec_rejects_missing_extra_and_noncanonical_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = encode_r5_portfolio_outcome(_outcome(monkeypatch))
    missing = dict(payload)
    missing.pop("observation_id")
    extra = {**payload, "unexpected": True}
    noncanonical = {**payload, "target_cost": "0.0100"}

    for candidate in (missing, extra, noncanonical):
        with pytest.raises(R5PortfolioOutcomeCodecError):
            decode_r5_portfolio_outcome(candidate)
