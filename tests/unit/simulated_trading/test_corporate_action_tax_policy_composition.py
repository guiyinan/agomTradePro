from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import cast

import pytest

from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.simulated_trading.corporate_action_tax_policy_composition import (
    SIMULATED_DIVIDEND_TAX_POLICY_KEY,
    SimulatedDividendTaxPolicyUnavailable,
    read_current_simulated_dividend_tax_policy,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    STATUTORY_REVISION_SET_SCHEMA,
    SimulatedDividendTaxExchange,
    SimulatedDividendTaxInstrumentKind,
    SimulatedDividendTaxPersona,
)

_NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)
_REVISION_SHA = "a" * 64


def _tax_policy_json(
    *,
    source_identity: str | None = None,
    source_sha256: str = _REVISION_SHA,
) -> dict[str, object]:
    """Build complete synthetic policy JSON accepted by the existing decoder."""

    return {
        "schema_version": "simulated_trading.deferred_dividend_tax_policy.v1",
        "policy_id": "synthetic-tax-policy",
        "version": "synthetic-v1",
        "effective_from": "2025-01-01",
        "effective_through": "2025-12-31",
        "source_identity": (
            f"{STATUTORY_REVISION_SET_SCHEMA}:{_REVISION_SHA}"
            if source_identity is None
            else source_identity
        ),
        "source_sha256": source_sha256,
        "bands": [
            {
                "band_id": "synthetic-short",
                "maximum_holding_months": 12,
                "taxable_dividend_ratio": "1",
                "withholding_rate": "0.2",
            },
            {
                "band_id": "synthetic-long",
                "maximum_holding_months": None,
                "taxable_dividend_ratio": "0",
                "withholding_rate": "0",
            },
        ],
        "currency_quantum": "0.01",
        "rounding_mode": "ROUND_HALF_UP",
    }


def _policy_row(**changes: object) -> dict[str, object]:
    """Build one explicit synthetic candidate row without legal-source claims."""

    row: dict[str, object] = {
        "candidate_id": "synthetic-candidate",
        "candidate_version": "fixture-v1",
        "account_kind": "simulated",
        "physical_account_id": 17,
        "canonical_account_id": "account-v2:fixture-17",
        "owner_user_id": 29,
        "security_id": "SH.SYNTHETIC",
        "asset_code": "equity-cn",
        "exchange": "SH",
        "persona": "domestic_public_market_a_share",
        "instrument_kind": "listed_equity",
        "currency": "CNY",
        "record_date_entitlement_rule": "all_covered_positions",
        "applicability_ref": "synthetic-reviewed-applicability-v1",
        "record_date_from": "2025-01-01",
        "record_date_through": "2025-12-31",
        "valid_from": (_NOW - timedelta(days=1)).isoformat(),
        "valid_until": (_NOW + timedelta(days=1)).isoformat(),
        "statutory_bundle_id": "synthetic-source-bundle",
        "statutory_bundle_version": "fixture-capture-v1",
        "statutory_revision_set_sha256": _REVISION_SHA,
        "tax_policy": _tax_policy_json(),
    }
    row.update(changes)
    return row


def _runtime_value(*, rows: list[object] | None = None, enabled: bool = True) -> dict[str, object]:
    """Build one explicit current Config Center value."""

    return {
        "schema_version": "simulated-dividend-tax-policies.v1",
        "enabled": enabled,
        "policies": [_policy_row()] if rows is None else rows,
    }


def _evidence(
    value: object,
    *,
    environment: str = "development",
    definition_key: str = SIMULATED_DIVIDEND_TAX_POLICY_KEY,
    as_of: datetime = _NOW,
) -> ActiveRuntimeValueEvidence:
    """Bind synthetic current data to exact Config Center profile clocks."""

    created = _NOW - timedelta(days=3)
    activated = _NOW - timedelta(days=2)
    generated = _NOW - timedelta(hours=1)
    return ActiveRuntimeValueEvidence(
        environment=environment,
        definition_key=definition_key,
        value=value,
        profile_id="synthetic-profile-id",
        profile_key="synthetic-profile-key",
        profile_version=3,
        profile_content_hash="b" * 64,
        snapshot_id="synthetic-snapshot-id",
        snapshot_hash="c" * 64,
        created_at=created,
        known_at=created,
        activated_at=activated,
        snapshot_generated_at=generated,
        effective_at=activated,
        as_of=as_of,
    )


def _read(monkeypatch: pytest.MonkeyPatch, evidence: ActiveRuntimeValueEvidence | None):
    """Install exact evidence and read one requested synthetic owner instrument."""

    monkeypatch.setattr(
        "apps.simulated_trading.corporate_action_tax_policy_composition.read_active_runtime_value_evidence",
        lambda **_: evidence,
    )
    return read_current_simulated_dividend_tax_policy(
        environment="development",
        as_of=_NOW,
        account_kind="simulated",
        physical_account_id=17,
        canonical_account_id="account-v2:fixture-17",
        owner_user_id=29,
        security_id="SH.SYNTHETIC",
        asset_code="equity-cn",
        exchange=SimulatedDividendTaxExchange.SH,
        persona=SimulatedDividendTaxPersona.DOMESTIC_PUBLIC_MARKET_A_SHARE,
        instrument_kind=SimulatedDividendTaxInstrumentKind.LISTED_EQUITY,
        record_date=date(2025, 6, 1),
    )


def test_reads_one_current_candidate_with_complete_policy_and_runtime_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _runtime_value()
    evidence = _evidence(value)
    configured = _read(monkeypatch, evidence)

    assert configured.candidate.canonical_account_id == "account-v2:fixture-17"
    assert configured.candidate.tax_policy.policy_id == "synthetic-tax-policy"
    assert configured.candidate.statutory_bundle_id == "synthetic-source-bundle"
    assert configured.candidate.statutory_bundle_version == "fixture-capture-v1"
    assert configured.candidate.known_at == evidence.known_at
    assert configured.definition_key == SIMULATED_DIVIDEND_TAX_POLICY_KEY
    assert configured.profile_id == evidence.profile_id
    assert configured.snapshot_hash == evidence.snapshot_hash
    assert configured.as_of == _NOW
    assert not hasattr(configured, "is_qualified")
    assert not hasattr(configured, "has_tax_authority")


def test_missing_explicit_currency_cannot_authorize_an_untyped_cash_amount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _policy_row()
    row.pop("currency", None)
    with pytest.raises(SimulatedDividendTaxPolicyUnavailable):
        _read(monkeypatch, _evidence(_runtime_value(rows=[row])))


def test_missing_explicit_entitlement_rule_cannot_infer_aggregate_coverage(monkeypatch):
    row = _policy_row()
    row.pop("record_date_entitlement_rule", None)
    with pytest.raises(SimulatedDividendTaxPolicyUnavailable):
        _read(monkeypatch, _evidence(_runtime_value(rows=[row])))


def test_missing_current_runtime_evidence_fails_closed_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.simulated_trading.corporate_action_tax_policy_composition.read_active_runtime_value_evidence",
        lambda **_: None,
    )

    with pytest.raises(SimulatedDividendTaxPolicyUnavailable):
        read_current_simulated_dividend_tax_policy(
            environment="development",
            as_of=_NOW,
            account_kind="simulated",
            physical_account_id=17,
            canonical_account_id="account-v2:fixture-17",
            owner_user_id=29,
            security_id="SH.SYNTHETIC",
            asset_code="equity-cn",
            exchange=SimulatedDividendTaxExchange.SH,
            persona=SimulatedDividendTaxPersona.DOMESTIC_PUBLIC_MARKET_A_SHARE,
            instrument_kind=SimulatedDividendTaxInstrumentKind.LISTED_EQUITY,
            record_date=date(2025, 6, 1),
        )


@pytest.mark.parametrize(
    "value",
    [
        {"schema_version": "wrong", "enabled": True, "policies": [_policy_row()]},
        {
            "schema_version": "simulated-dividend-tax-policies.v1",
            "enabled": 1,
            "policies": [_policy_row()],
        },
        {
            "schema_version": "simulated-dividend-tax-policies.v1",
            "enabled": False,
            "policies": [_policy_row()],
        },
        {"schema_version": "simulated-dividend-tax-policies.v1", "enabled": True, "policies": []},
        {
            "schema_version": "simulated-dividend-tax-policies.v1",
            "enabled": True,
            "policies": [_policy_row(), "not-an-object"],
        },
    ],
)
def test_bad_or_disabled_top_level_config_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    value: object,
) -> None:
    with pytest.raises(SimulatedDividendTaxPolicyUnavailable):
        _read(monkeypatch, _evidence(value))


@pytest.mark.parametrize(
    "value",
    [
        {**_runtime_value(), "unexpected": "field"},
        _runtime_value(rows=[_policy_row(unexpected="field")]),
        _runtime_value(
            rows=[{key: value for key, value in _policy_row().items() if key != "owner_user_id"}]
        ),
        _runtime_value(
            rows=[_policy_row(tax_policy={**_tax_policy_json(), "unexpected": "field"})]
        ),
    ],
)
def test_unknown_or_missing_config_fields_are_rejected_at_each_boundary(
    monkeypatch: pytest.MonkeyPatch,
    value: object,
) -> None:
    with pytest.raises(SimulatedDividendTaxPolicyUnavailable):
        _read(monkeypatch, _evidence(value))


def test_duplicate_canonical_instrument_is_detected_before_owner_filtering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate = _policy_row(
        candidate_id="foreign-owner-duplicate",
        physical_account_id=99,
        owner_user_id=101,
    )
    evidence = _evidence(_runtime_value(rows=[_policy_row(), duplicate]))

    with pytest.raises(SimulatedDividendTaxPolicyUnavailable, match="duplicate"):
        _read(monkeypatch, evidence)


def test_duplicate_canonical_asset_mapping_is_detected_before_instrument_and_owner_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conflicting_mapping = _policy_row(
        candidate_id="foreign-instrument-owner-mapping",
        physical_account_id=99,
        owner_user_id=101,
        security_id="SZ.OTHER-SYNTHETIC",
        exchange="SZ",
    )
    evidence = _evidence(_runtime_value(rows=[_policy_row(), conflicting_mapping]))

    with pytest.raises(SimulatedDividendTaxPolicyUnavailable, match="duplicate"):
        _read(monkeypatch, evidence)


@pytest.mark.parametrize(
    "row_changes",
    [
        {"physical_account_id": 18},
        {"owner_user_id": 30},
        {"record_date_from": "2025-07-01"},
        {"valid_from": (_NOW + timedelta(seconds=1)).isoformat()},
        {"valid_until": _NOW.isoformat()},
        {"persona": "another-persona"},
        {"instrument_kind": "option"},
        {"exchange": "OTC"},
        {"account_kind": "real"},
    ],
)
def test_selected_candidate_must_match_owner_date_and_supported_scope(
    monkeypatch: pytest.MonkeyPatch,
    row_changes: dict[str, object],
) -> None:
    with pytest.raises(SimulatedDividendTaxPolicyUnavailable):
        _read(monkeypatch, _evidence(_runtime_value(rows=[_policy_row(**row_changes)])))


def test_tax_policy_source_identity_and_digest_must_match_declared_revision_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _policy_row(
        tax_policy=_tax_policy_json(
            source_identity="unrelated-source-set",
            source_sha256="d" * 64,
        )
    )

    with pytest.raises(SimulatedDividendTaxPolicyUnavailable):
        _read(monkeypatch, _evidence(_runtime_value(rows=[row])))


@pytest.mark.parametrize(
    "evidence_changes",
    [
        {"environment": "production"},
        {"definition_key": "other.key"},
        {"as_of": _NOW - timedelta(seconds=1)},
        {"known_at": _NOW + timedelta(seconds=1)},
        {"effective_at": _NOW - timedelta(days=3)},
        {"profile_version": True},
        {"snapshot_hash": "not-a-digest"},
    ],
)
def test_runtime_profile_and_snapshot_provenance_is_rechecked(
    monkeypatch: pytest.MonkeyPatch,
    evidence_changes: dict[str, object],
) -> None:
    altered = replace(_evidence(_runtime_value()), **evidence_changes)

    with pytest.raises(SimulatedDividendTaxPolicyUnavailable):
        _read(monkeypatch, cast(ActiveRuntimeValueEvidence, altered))


def test_request_for_real_or_unsupported_scope_is_rejected_before_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.simulated_trading.corporate_action_tax_policy_composition.read_active_runtime_value_evidence",
        lambda **_: None,
    )
    with pytest.raises(SimulatedDividendTaxPolicyUnavailable):
        read_current_simulated_dividend_tax_policy(
            environment="development",
            as_of=_NOW,
            account_kind="real",
            physical_account_id=17,
            canonical_account_id="account-v2:fixture-17",
            owner_user_id=29,
            security_id="SH.SYNTHETIC",
            asset_code="equity-cn",
            exchange=SimulatedDividendTaxExchange.SH,
            persona=SimulatedDividendTaxPersona.DOMESTIC_PUBLIC_MARKET_A_SHARE,
            instrument_kind=SimulatedDividendTaxInstrumentKind.LISTED_EQUITY,
            record_date=date(2025, 6, 1),
        )
