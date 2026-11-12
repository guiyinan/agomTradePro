"""Policy-provenance checks for record-date ownership replay composition."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.simulated_trading import corporate_action_ownership_history_composition as composition
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from core.integration.config_center_runtime import ActiveRuntimeValueEvidence

_AS_OF = datetime(2026, 11, 12, 0, 0, tzinfo=UTC)
_KNOWN_AT = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)


def test_unchanged_timezone_policy_keeps_semantic_identity_across_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new observation clock must not create a new tax assessment obligation."""
    evidence = _runtime_evidence({"SZSE": "Asia/Shanghai"})
    monkeypatch.setattr(
        composition,
        "get_active_runtime_value_evidence",
        lambda **kwargs: replace(evidence, as_of=kwargs["as_of"]),
    )
    reader = composition._RuntimeExchangeTimezonePolicyReader("development")
    first = reader.read_exchange_timezone_policy(exchange="SZSE", as_of=_AS_OF)
    second = reader.read_exchange_timezone_policy(
        exchange="SZSE",
        as_of=_AS_OF + timedelta(seconds=1),
    )
    assert first == second


def _runtime_evidence(value: object) -> ActiveRuntimeValueEvidence:
    """Build one immutable versioned runtime evidence fixture."""

    return ActiveRuntimeValueEvidence(
        environment="development",
        definition_key="config_center.market.exchange_timezone_map",
        value=value,
        profile_id="market-clock-profile-7",
        profile_key="market-clock-profile",
        profile_version=7,
        profile_content_hash="a" * 64,
        snapshot_id="market-clock-snapshot-7",
        snapshot_hash="b" * 64,
        created_at=_KNOWN_AT,
        known_at=_KNOWN_AT,
        activated_at=_KNOWN_AT,
        snapshot_generated_at=_KNOWN_AT,
        effective_at=_KNOWN_AT,
        as_of=_AS_OF,
    )


def test_timezone_policy_reader_binds_timezone_to_exact_snapshot_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Select the exact exchange entry and retain profile/snapshot identity."""

    evidence = _runtime_evidence({"SZSE": "Asia/Shanghai", "SSE": "Asia/Shanghai"})
    monkeypatch.setattr(
        composition,
        "get_active_runtime_value_evidence",
        lambda **kwargs: evidence,
    )
    reader = composition._RuntimeExchangeTimezonePolicyReader("development")

    policy = reader.read_exchange_timezone_policy(exchange="SZSE", as_of=_AS_OF)

    assert policy.exchange == "SZSE"
    assert policy.timezone_name == "Asia/Shanghai"
    assert policy.policy_id.endswith(":market-clock-snapshot-7")
    assert len(policy.policy_sha256) == 64


def test_timezone_policy_reader_blocks_missing_exchange_or_malformed_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing or loosely typed mappings cannot supply the record-date boundary."""

    evidence = _runtime_evidence({"SSE": "Asia/Shanghai"})
    monkeypatch.setattr(
        composition,
        "get_active_runtime_value_evidence",
        lambda **kwargs: evidence,
    )
    reader = composition._RuntimeExchangeTimezonePolicyReader("development")

    with pytest.raises(SimulatedTradeExecutionBlocked) as missing:
        reader.read_exchange_timezone_policy(exchange="SZSE", as_of=_AS_OF)
    assert missing.value.code == "CORPORATE_ACTION_OWNERSHIP_POLICY_UNAVAILABLE"

    evidence = _runtime_evidence({"SZSE": 8})
    monkeypatch.setattr(
        composition,
        "get_active_runtime_value_evidence",
        lambda **kwargs: evidence,
    )
    with pytest.raises(SimulatedTradeExecutionBlocked) as malformed:
        reader.read_exchange_timezone_policy(exchange="SZSE", as_of=_AS_OF)
    assert malformed.value.code == "CORPORATE_ACTION_OWNERSHIP_POLICY_UNAVAILABLE"
