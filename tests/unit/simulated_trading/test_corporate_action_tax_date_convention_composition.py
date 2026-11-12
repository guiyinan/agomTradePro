from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.simulated_trading import corporate_action_tax_date_convention_composition as composition

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
KEY = "config_center.simulated_trading.dividend_tax_date_conventions"
SCHEMA = "simulated-dividend-tax-date-conventions.v1"


def _policy(**changes: object) -> dict[str, object]:
    policy: dict[str, object] = {
        "convention_id": "fixture-convention",
        "version": "fixture-v1",
        "physical_account_id": 41,
        "canonical_account_id": "simulated-account-41",
        "owner_user_id": 7,
        "exchange": "XSHG",
        "purchase_open_session_offset": 1,
        "sale_open_session_offset": 0,
        "trade_window_start": "2026-01-01",
        "trade_window_end": "2026-10-31",
        "valid_from": (NOW - timedelta(days=1)).isoformat(),
        "valid_until": (NOW + timedelta(days=1)).isoformat(),
        "approval_ref": "synthetic-test-approval",
    }
    policy.update(changes)
    return policy


def _payload(*policies: dict[str, object], enabled: object = True) -> dict[str, object]:
    return {
        "schema_version": SCHEMA,
        "enabled": enabled,
        "policies": list(policies),
    }


def _evidence(value: object, **changes: Any) -> ActiveRuntimeValueEvidence:
    evidence = ActiveRuntimeValueEvidence(
        environment="development",
        definition_key=KEY,
        value=value,
        profile_id="profile-1",
        profile_key="development",
        profile_version=3,
        profile_content_hash="a" * 64,
        snapshot_id="snapshot-1",
        snapshot_hash="b" * 64,
        created_at=NOW - timedelta(days=30),
        known_at=NOW - timedelta(days=30),
        activated_at=NOW - timedelta(hours=1),
        snapshot_generated_at=NOW,
        effective_at=NOW - timedelta(hours=1),
        as_of=NOW,
    )
    return replace(evidence, **changes)


def _read(
    monkeypatch: pytest.MonkeyPatch,
    evidence: ActiveRuntimeValueEvidence | None,
    *,
    account_kind: str = "simulated",
    physical_account_id: int = 41,
    canonical_account_id: str = "simulated-account-41",
    owner_user_id: int = 7,
) -> composition.ConfiguredSimulatedDividendTaxDateConvention:
    monkeypatch.setattr(
        composition,
        "read_active_runtime_value_evidence",
        lambda **_kwargs: evidence,
    )
    return composition.read_current_simulated_dividend_tax_date_convention(
        environment="development",
        as_of=NOW,
        account_kind=account_kind,
        physical_account_id=physical_account_id,
        canonical_account_id=canonical_account_id,
        owner_user_id=owner_user_id,
    )


def test_current_explicit_rule_preserves_runtime_provenance_and_server_known_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _payload(_policy())
    evidence = _evidence(value)

    configured = _read(monkeypatch, evidence)

    assert configured.convention.known_at == evidence.known_at
    assert configured.convention.canonical_account_id == "simulated-account-41"
    assert configured.environment == "development"
    assert configured.profile_id == evidence.profile_id
    assert configured.profile_key == evidence.profile_key
    assert configured.profile_version == evidence.profile_version
    assert configured.profile_content_hash == evidence.profile_content_hash
    assert configured.snapshot_id == evidence.snapshot_id
    assert configured.snapshot_hash == evidence.snapshot_hash
    assert configured.created_at == evidence.created_at
    assert configured.activated_at == evidence.activated_at
    assert configured.snapshot_generated_at == evidence.snapshot_generated_at
    assert configured.effective_at == evidence.effective_at
    assert configured.as_of == NOW


def test_missing_runtime_value_blocks_without_history_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(composition.SimulatedDividendTaxDateConventionUnavailable):
        _read(monkeypatch, None)


@pytest.mark.parametrize(
    "value",
    [
        {"schema_version": SCHEMA, "enabled": True},
        {"schema_version": "unknown", "enabled": True, "policies": [_policy()]},
        {"schema_version": SCHEMA, "enabled": 1, "policies": [_policy()]},
        {"schema_version": SCHEMA, "enabled": True, "policies": []},
        {"schema_version": SCHEMA, "enabled": True, "policies": (_policy(),)},
        {
            "schema_version": SCHEMA,
            "enabled": True,
            "policies": [
                _policy(),
            ],
            "extra": 1,
        },
    ],
)
def test_strict_top_level_configuration_rejects_incomplete_or_coerced_json(
    monkeypatch: pytest.MonkeyPatch,
    value: object,
) -> None:
    with pytest.raises(composition.SimulatedDividendTaxDateConventionUnavailable):
        _read(monkeypatch, _evidence(value))


@pytest.mark.parametrize(
    "changes",
    [
        {"purchase_open_session_offset": True},
        {"owner_user_id": "7"},
        {"trade_window_start": "2026-1-1"},
        {"valid_from": "2026-11-11T12:00:00"},
        {"known_at": (NOW - timedelta(days=31)).isoformat()},
        {"unrecognized": "value"},
    ],
)
def test_strict_policy_rows_reject_unknown_missing_and_ill_typed_values(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, object],
) -> None:
    with pytest.raises(composition.SimulatedDividendTaxDateConventionUnavailable):
        _read(monkeypatch, _evidence(_payload(_policy(**changes))))


def test_disabled_or_inactive_rule_blocks_current_read(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(composition.SimulatedDividendTaxDateConventionUnavailable):
        _read(monkeypatch, _evidence(_payload(_policy(), enabled=False)))

    expired = _policy(valid_until=(NOW - timedelta(microseconds=1)).isoformat())
    with pytest.raises(composition.SimulatedDividendTaxDateConventionUnavailable):
        _read(monkeypatch, _evidence(_payload(expired)))


def test_duplicate_canonical_selector_blocks_before_scope_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mismatched_owner = _policy(physical_account_id=99, owner_user_id=88)
    with pytest.raises(composition.SimulatedDividendTaxDateConventionUnavailable) as error:
        _read(monkeypatch, _evidence(_payload(_policy(), mismatched_owner)))

    assert "duplicate" in str(error.value).lower()


@pytest.mark.parametrize(
    "scope",
    [
        {"physical_account_id": 99},
        {"owner_user_id": 8},
        {"account_kind": "real"},
        {"canonical_account_id": "simulated-account-999"},
    ],
)
def test_current_policy_must_match_exact_simulated_account_scope(
    monkeypatch: pytest.MonkeyPatch,
    scope: dict[str, object],
) -> None:
    request: dict[str, object] = {
        "account_kind": "simulated",
        "physical_account_id": 41,
        "canonical_account_id": "simulated-account-41",
        "owner_user_id": 7,
    }
    request.update(scope)
    with pytest.raises(composition.SimulatedDividendTaxDateConventionUnavailable):
        _read(
            monkeypatch,
            _evidence(_payload(_policy())),
            account_kind=request["account_kind"],
            physical_account_id=request["physical_account_id"],
            canonical_account_id=request["canonical_account_id"],
            owner_user_id=request["owner_user_id"],
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"environment": "production"},
        {"definition_key": "config_center.other"},
        {"as_of": NOW - timedelta(seconds=1)},
        {"snapshot_generated_at": NOW + timedelta(seconds=1)},
        {
            "activated_at": NOW - timedelta(hours=1),
            "effective_at": NOW - timedelta(hours=1),
            "snapshot_generated_at": NOW - timedelta(hours=2),
        },
        {"known_at": datetime(2026, 10, 1)},
        {"snapshot_hash": "not-a-digest"},
    ],
)
def test_runtime_evidence_must_be_current_aware_and_complete(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, object],
) -> None:
    with pytest.raises(composition.SimulatedDividendTaxDateConventionUnavailable):
        _read(monkeypatch, _evidence(_payload(_policy()), **changes))
