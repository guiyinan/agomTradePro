"""Contract coverage for policy-pinned retained portfolio risk input reads."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.data_center.application import raw_landing_public
from apps.data_center.domain.raw_landing import RawPayload
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetIdentity,
    PortfolioRiskAssetsReadRequest,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskSourceReference,
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.domain.portfolio_exposure_types import (
    ETFConstituentKind,
    PortfolioAssetKind,
)
from apps.risk_center.infrastructure.retained_portfolio_risk_assets_reader import (
    RetainedPortfolioRiskAssetsReader,
)

_AS_OF = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
_BUSINESS_DATE = date(2026, 11, 3)
_EXECUTION_SESSION = date(2026, 11, 3)
_EQUITY_CODE = "000001.SZ"
_EQUITY_ID = "equity:SZ:000001"
_ETF_CODE = "510300.SH"
_ETF_ID = "etf:SH:510300"


def _coverage(status: str = "complete") -> dict[str, object]:
    return {
        "status": status,
        "precision_basis": "portfolio_weight",
        "reported_weight_fraction": "1" if status == "complete" else "0.75",
        "expected_item_count": None,
        "observed_item_count": None,
    }


def _source(
    *,
    kind: str,
    asset_code: str,
    security_id: str,
    source_record_id: str,
    facts: dict[str, object],
    purpose: str | None = None,
    observed_at: datetime | None = None,
    observed_on: date | None = None,
    effective_on: date | None = None,
    restrictions: tuple[str, ...] = (),
    must_not_use: bool = False,
    coverage_status: str = "complete",
    declared_body_hash: str | None = None,
) -> RawPayload:
    """Build the exact retained manifest with separate manifest and body hashes."""

    body = f"raw-source:{source_record_id}".encode("utf-8")
    precision = "date" if observed_on is not None else "timestamp"
    selected_observed_at = observed_at or (_AS_OF - timedelta(minutes=2))
    source_purpose = purpose or (
        "ash07_capacity"
        if kind in ("capacity_window", "execution_session_state")
        else "ash07_portfolio_exposure"
    )
    evidence: dict[str, object] = {
        "source_id": f"source:{source_record_id}",
        "source_record_id": source_record_id,
        "original_payload_sha256": declared_body_hash or hashlib.sha256(body).hexdigest(),
        "observation_precision": precision,
        "observed_at": selected_observed_at.isoformat() if observed_on is None else None,
        "observed_on": observed_on.isoformat() if observed_on is not None else None,
        "available_at": (_AS_OF - timedelta(minutes=1)).isoformat(),
        "known_at": (_AS_OF - timedelta(minutes=1)).isoformat(),
        "valid_until": (_AS_OF + timedelta(hours=1)).isoformat(),
        "source_purpose": source_purpose,
        "allowed_purposes": [source_purpose],
        "restrictions": list(restrictions),
        "must_not_use_for_decision": must_not_use,
        "coverage": _coverage(coverage_status),
        "effective_on": effective_on.isoformat() if effective_on is not None else None,
        "effective_until": None,
    }
    manifest: dict[str, object] = {
        "schema_version": "ash07.retained_risk_input.v1",
        "kind": kind,
        "asset_code": asset_code,
        "security_id": security_id,
        "source_record_id": source_record_id,
        "original_body_base64": base64.b64encode(body).decode("ascii"),
        "original_url": "https://source.invalid/retained-record",
        "source_evidence": evidence,
        "facts": facts,
    }
    payload_hash = _manifest_hash(manifest)
    return RawPayload(
        payload_id=f"payload:{source_record_id}",
        dataset_key="risk_center.simulated_portfolio_risk_input",
        provider_name="retained-risk-manifest",
        payload_hash=payload_hash,
        schema_fingerprint="sha256:" + "a" * 64,
        payload=manifest,
        fetched_at=_AS_OF + timedelta(days=2),
        parser_version="ash07.retained_risk_input.v1",
        redacted=True,
    )


def _manifest_hash(manifest: dict[str, object]) -> str:
    encoded = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _reference(raw: RawPayload, kind: str, code: str, security_id: str) -> dict[str, object]:
    return {
        "kind": kind,
        "asset_code": code,
        "security_id": security_id,
        "raw_payload_hash": raw.payload_hash,
        "source_record_id": raw.payload["source_record_id"],
    }


def _valuation_facts(
    *,
    asset_kind: str = "equity",
    quantity_unit: str | None = "share",
    price_unit: str | None = "CNY",
) -> dict[str, object]:
    return {
        "price": "12.30",
        "asset_kind": asset_kind,
        "quantity_unit": quantity_unit,
        "price_unit": price_unit,
    }


def _configuration(
    references: tuple[dict[str, object], ...],
    *,
    capacity_measure: str = "volume",
    capacity_unit: str = "share",
) -> dict[str, object]:
    return {
        "schema_version": "ash07.simulated_portfolio_risk.v1",
        "scope": "simulation_only",
        "ledger_money_unit": "CNY",
        "account_ids": [12],
        "industry": {
            "taxonomy_id": "sw-2021",
            "taxonomy_kind": "industry",
            "provider_id": "provider-a",
            "provider_version": "v2026.10",
            "requested_purpose": "ash07_portfolio_exposure",
            "date_precision_purposes": ["ash07_portfolio_exposure"],
            "allowed_observation_precisions": ["timestamp", "date"],
            "allowed_source_restrictions": ["session_only"],
            "coverage_precision_basis": "portfolio_weight",
            "max_industry_weight": "0.35",
            "max_security_weight": "0.15",
            "minimum_industry_coverage": "0.90",
            "minimum_etf_lookthrough_coverage": "0.80",
            "coverage_weight_tolerance": "0.01",
        },
        "capacity": {
            "measure": capacity_measure,
            "unit": capacity_unit,
            "basis": "average_per_session",
            "usage_scope": "account_security_session",
            "date_basis": "execution_session",
            "max_participation": "0.08",
            "increment": "100",
            "window_kind": "rolling_sessions",
            "sessions": 5,
            "allowed_observation_precisions": ["timestamp", "date"],
            "date_precision_purposes": ["ash07_capacity"],
            "allowed_source_restrictions": ["session_only"],
        },
        "source_max_timestamp_age_seconds": 1800,
        "source_max_date_age_days": 5,
        "source_references": list(references),
    }


def _runtime_evidence(value: object) -> ActiveRuntimeValueEvidence:
    return ActiveRuntimeValueEvidence(
        environment="development",
        definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
        value=value,
        profile_id="runtime-profile-12",
        profile_key="risk-center-development",
        profile_version=12,
        profile_content_hash="e" * 64,
        snapshot_id="runtime-snapshot-12",
        snapshot_hash="f" * 64,
        created_at=_AS_OF - timedelta(minutes=5),
        known_at=_AS_OF - timedelta(minutes=5),
        activated_at=_AS_OF - timedelta(minutes=3),
        snapshot_generated_at=_AS_OF - timedelta(minutes=2),
        effective_at=_AS_OF - timedelta(minutes=3),
        as_of=_AS_OF,
    )


def _read(
    monkeypatch: pytest.MonkeyPatch,
    sources: tuple[RawPayload, ...],
    references: tuple[dict[str, object], ...],
    requested_assets: tuple[PortfolioRiskAssetIdentity, ...],
    *,
    capacity_measure: str = "volume",
    capacity_unit: str = "share",
) -> tuple[PortfolioRiskAssetsReadResult, tuple[str, ...]]:
    retained_by_hash = {item.payload_hash: item for item in sources}
    requested_hashes: list[str] = []

    def get_retained(*, payload_hash: str) -> RawPayload | None:
        requested_hashes.append(payload_hash)
        return retained_by_hash.get(payload_hash)

    monkeypatch.setattr(raw_landing_public, "get_retained_raw_payload", get_retained)
    bundle = parse_portfolio_risk_policy_bundle(
        _runtime_evidence(
            _configuration(
                references,
                capacity_measure=capacity_measure,
                capacity_unit=capacity_unit,
            )
        ),
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )
    request = PortfolioRiskAssetsReadRequest(
        policy=bundle,
        requested_assets=requested_assets,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        execution_session=_EXECUTION_SESSION,
        capacity_requested_purpose="ash07_capacity",
    )
    result = RetainedPortfolioRiskAssetsReader().read_assets(request)
    assert result.policy_snapshot_id == bundle.snapshot_id
    assert result.policy_snapshot_hash == bundle.snapshot_hash
    assert all(item in bundle.source_references for item in result.source_reference_bindings)
    return result, tuple(requested_hashes)


def test_unbound_source_result_is_only_valid_for_blocked_input() -> None:
    with pytest.raises(ValueError, match="unbound policy result must be blocked"):
        PortfolioRiskAssetsReadResult(
            status="partial",
            assets=(),
            all_source_evidence=(),
            reason_codes=("RISK_INPUT_UNKNOWN",),
        )

    invalid_request = cast(PortfolioRiskAssetsReadRequest, object())
    blocked = RetainedPortfolioRiskAssetsReader().read_assets(request=invalid_request)

    assert blocked.status == "blocked"
    assert blocked.policy_snapshot_id is None
    assert blocked.policy_snapshot_hash is None

    with pytest.raises(ValueError, match="must be provided together"):
        PortfolioRiskAssetsReadResult(
            status="blocked",
            assets=(),
            all_source_evidence=(),
            reason_codes=("RISK_INPUT_BLOCKED",),
            policy_snapshot_id="snapshot-only",
        )

    unproven_binding = PortfolioRiskSourceReference(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        raw_payload_hash="sha256:" + "1" * 64,
        source_record_id="unproven-source",
    )
    with pytest.raises(ValueError, match="cannot claim policy source bindings"):
        PortfolioRiskAssetsReadResult(
            status="blocked",
            assets=(),
            all_source_evidence=(),
            reason_codes=("RISK_INPUT_BLOCKED",),
            source_reference_bindings=(unproven_binding,),
        )


def test_reader_binds_policy_identity_even_when_request_cutoff_is_blocked() -> None:
    reference: dict[str, object] = {
        "kind": "valuation",
        "asset_code": _EQUITY_CODE,
        "security_id": _EQUITY_ID,
        "raw_payload_hash": "sha256:" + "1" * 64,
        "source_record_id": "valuation-cutoff-test",
    }
    bundle = parse_portfolio_risk_policy_bundle(
        _runtime_evidence(_configuration((reference,))),
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )
    request = PortfolioRiskAssetsReadRequest(
        policy=bundle,
        requested_assets=(PortfolioRiskAssetIdentity(_EQUITY_CODE, _EQUITY_ID),),
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE + timedelta(days=1),
        execution_session=_EXECUTION_SESSION,
        capacity_requested_purpose="ash07_capacity",
    )

    result = RetainedPortfolioRiskAssetsReader().read_assets(request)

    assert result.status == "blocked"
    assert result.reason_codes == ("RISK_INPUT_POLICY_CUTOFF_MISMATCH",)
    assert result.policy_snapshot_id == bundle.snapshot_id
    assert result.policy_snapshot_hash == bundle.snapshot_hash


def _membership_facts() -> dict[str, object]:
    return {
        "taxonomy_id": "sw-2021",
        "taxonomy_kind": "industry",
        "provider_id": "provider-a",
        "provider_version": "v2026.10",
        "industry_code": "banking",
        "effective_from": "2026-01-01",
        "effective_end_state": "open",
        "effective_until": None,
    }


def test_reader_selects_only_requested_pair_and_maps_missing_id_through_unique_valuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrelated stale policy pin cannot block this request or supply identity."""

    valuation = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="valuation-1",
        facts=_valuation_facts(),
    )
    unrelated = _source(
        kind="valuation",
        asset_code="600000.SH",
        security_id="equity:SH:600000",
        source_record_id="unrelated-valuation",
        facts=_valuation_facts(),
        observed_at=_AS_OF - timedelta(days=30),
    )
    references = (
        _reference(valuation, "valuation", _EQUITY_CODE, _EQUITY_ID),
        _reference(unrelated, "valuation", "600000.SH", "equity:SH:600000"),
    )

    result, requested_hashes = _read(
        monkeypatch,
        (valuation, unrelated),
        references,
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=None),),
    )

    assert result.status == "partial"
    assert result.assets[0].security_id == _EQUITY_ID
    assert result.assets[0].price_unit == "CNY"
    assert requested_hashes == (valuation.payload_hash,)
    assert tuple(item.raw_payload_hash for item in result.source_reference_bindings) == (
        valuation.payload_hash,
    )
    assert unrelated.payload_hash not in tuple(
        item.raw_payload_hash for item in result.source_reference_bindings
    )
    assert "RISK_INPUT_SOURCE_TIMESTAMP_AGE_EXCEEDED" not in result.reason_codes


def test_missing_ledger_security_id_with_multiple_pinned_securities_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ticker with two possible valuation securities is never guessed."""

    first = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="valuation-a",
        facts=_valuation_facts(),
    )
    second = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id="equity:OTHER:000001",
        source_record_id="valuation-b",
        facts=_valuation_facts(),
    )
    references = (
        _reference(first, "valuation", _EQUITY_CODE, _EQUITY_ID),
        _reference(second, "valuation", _EQUITY_CODE, "equity:OTHER:000001"),
    )

    result, requested_hashes = _read(
        monkeypatch,
        (first, second),
        references,
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=None),),
    )

    assert result.status == "blocked"
    assert result.assets[0].security_id is None
    assert "RISK_INPUT_LEDGER_SECURITY_ID_AMBIGUOUS" in result.reason_codes
    assert requested_hashes == ()


def test_known_ledger_security_conflicting_with_any_pinned_ref_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit ledger ID cannot be overridden by a mismatching policy pin."""

    valuation = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id="equity:OTHER:000001",
        source_record_id="valuation-other-security",
        facts=_valuation_facts(),
    )
    references = (_reference(valuation, "valuation", _EQUITY_CODE, "equity:OTHER:000001"),)

    result, requested_hashes = _read(
        monkeypatch,
        (valuation,),
        references,
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )

    assert result.status == "blocked"
    assert "RISK_INPUT_ASSET_SECURITY_REFERENCE_CONFLICT" in result.reason_codes
    assert requested_hashes == ()


def test_selected_source_age_uses_source_observation_not_manifest_fetch_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A freshly retained manifest cannot make its older source observation fresh."""

    stale_source = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="stale-observed-valuation",
        facts=_valuation_facts(),
        observed_at=_AS_OF - timedelta(days=1),
    )
    result, _ = _read(
        monkeypatch,
        (stale_source,),
        (_reference(stale_source, "valuation", _EQUITY_CODE, _EQUITY_ID),),
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )

    assert result.status == "blocked"
    assert "RISK_INPUT_SOURCE_TIMESTAMP_AGE_EXCEEDED" in result.reason_codes


def test_missing_retained_manifest_does_not_create_a_source_reference_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="missing-retained-valuation",
        facts=_valuation_facts(),
    )
    reference = _reference(source, "valuation", _EQUITY_CODE, _EQUITY_ID)

    result, requested_hashes = _read(
        monkeypatch,
        (),
        (reference,),
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )

    assert result.status == "partial"
    assert "RISK_INPUT_RETAINED_PAYLOAD_MISSING" in result.reason_codes
    assert result.source_reference_bindings == ()
    assert requested_hashes == (source.payload_hash,)


def test_etf_partial_report_loads_only_its_unique_constituent_membership_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ETF look-through closes over exact named membership pins, preserving partial coverage."""

    etf_value = _source(
        kind="valuation",
        asset_code=_ETF_CODE,
        security_id=_ETF_ID,
        source_record_id="etf-valuation",
        facts=_valuation_facts(asset_kind="etf", quantity_unit="unit"),
    )
    member_value = _source(
        kind="industry_membership",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="member-industry",
        facts=_membership_facts(),
        observed_on=date(2026, 11, 2),
    )
    etf_report = _source(
        kind="etf_report",
        asset_code=_ETF_CODE,
        security_id=_ETF_ID,
        source_record_id="etf-report",
        facts={
            "report_date": "2026-10-31",
            "constituents": [
                {"asset_code": _EQUITY_CODE, "weight_fraction": "0.6", "kind": "equity"},
                {"asset_code": "cash:cn", "weight_fraction": "0.2", "kind": "cash"},
            ],
        },
        coverage_status="partial",
    )
    unrelated = _source(
        kind="industry_membership",
        asset_code="600000.SH",
        security_id="equity:SH:600000",
        source_record_id="unrelated-member",
        facts=_membership_facts(),
        observed_at=_AS_OF - timedelta(days=30),
    )
    references = (
        _reference(etf_value, "valuation", _ETF_CODE, _ETF_ID),
        _reference(etf_report, "etf_report", _ETF_CODE, _ETF_ID),
        _reference(member_value, "industry_membership", _EQUITY_CODE, _EQUITY_ID),
        _reference(unrelated, "industry_membership", "600000.SH", "equity:SH:600000"),
    )

    result, requested_hashes = _read(
        monkeypatch,
        (etf_value, etf_report, member_value, unrelated),
        references,
        (PortfolioRiskAssetIdentity(asset_code=_ETF_CODE, security_id=_ETF_ID),),
    )

    assert result.status == "partial"
    report = result.assets[0].etf_report
    assert report is not None
    assert report.source_evidence.coverage.status.value == "partial"
    equity_constituent = next(
        item for item in report.constituents if item.kind is ETFConstituentKind.EQUITY
    )
    assert equity_constituent.industry_membership is not None
    assert equity_constituent.industry_membership.industry_code == "banking"
    assert set(requested_hashes) == {
        etf_value.payload_hash,
        etf_report.payload_hash,
        member_value.payload_hash,
    }
    assert {item.raw_payload_hash for item in result.source_reference_bindings} == {
        etf_value.payload_hash,
        etf_report.payload_hash,
        member_value.payload_hash,
    }
    assert unrelated.payload_hash not in requested_hashes


def test_etf_constituent_without_membership_pin_remains_unclassified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unpinned constituent membership stays unknown instead of using an index proxy."""

    etf_value = _source(
        kind="valuation",
        asset_code=_ETF_CODE,
        security_id=_ETF_ID,
        source_record_id="unmapped-etf-valuation",
        facts=_valuation_facts(asset_kind="etf", quantity_unit="unit"),
    )
    etf_report = _source(
        kind="etf_report",
        asset_code=_ETF_CODE,
        security_id=_ETF_ID,
        source_record_id="unmapped-etf-report",
        facts={
            "report_date": "2026-10-31",
            "constituents": [
                {"asset_code": _EQUITY_CODE, "weight_fraction": "0.7", "kind": "equity"}
            ],
        },
    )

    result, _ = _read(
        monkeypatch,
        sources=(etf_value, etf_report),
        references=(
            _reference(etf_value, "valuation", _ETF_CODE, _ETF_ID),
            _reference(etf_report, "etf_report", _ETF_CODE, _ETF_ID),
        ),
        requested_assets=(PortfolioRiskAssetIdentity(asset_code=_ETF_CODE, security_id=_ETF_ID),),
    )

    assert result.status == "partial"
    assert result.assets[0].etf_report is not None
    assert result.assets[0].etf_report.constituents[0].industry_membership is None
    assert "RISK_INPUT_ETF_CONSTITUENT_INDUSTRY_REFERENCE_MISSING" in result.reason_codes


def test_etf_constituent_membership_with_multiple_security_pins_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The look-through join requires one unique pinned membership security."""

    etf_value = _source(
        kind="valuation",
        asset_code=_ETF_CODE,
        security_id=_ETF_ID,
        source_record_id="ambiguous-etf-valuation",
        facts=_valuation_facts(asset_kind="etf", quantity_unit="unit"),
    )
    etf_report = _source(
        kind="etf_report",
        asset_code=_ETF_CODE,
        security_id=_ETF_ID,
        source_record_id="ambiguous-etf-report",
        facts={
            "report_date": "2026-10-31",
            "constituents": [
                {"asset_code": _EQUITY_CODE, "weight_fraction": "0.7", "kind": "equity"}
            ],
        },
    )
    member_a = _source(
        kind="industry_membership",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="ambiguous-member-a",
        facts=_membership_facts(),
    )
    member_b = _source(
        kind="industry_membership",
        asset_code=_EQUITY_CODE,
        security_id="equity:OTHER:000001",
        source_record_id="ambiguous-member-b",
        facts=_membership_facts(),
    )
    sources = (etf_value, etf_report, member_a, member_b)
    references = (
        _reference(etf_value, "valuation", _ETF_CODE, _ETF_ID),
        _reference(etf_report, "etf_report", _ETF_CODE, _ETF_ID),
        _reference(member_a, "industry_membership", _EQUITY_CODE, _EQUITY_ID),
        _reference(member_b, "industry_membership", _EQUITY_CODE, "equity:OTHER:000001"),
    )

    result, requested_hashes = _read(
        monkeypatch,
        sources,
        references,
        (PortfolioRiskAssetIdentity(asset_code=_ETF_CODE, security_id=_ETF_ID),),
    )

    assert result.status == "blocked"
    assert "RISK_INPUT_ETF_CONSTITUENT_INDUSTRY_REFERENCE_AMBIGUOUS" in result.reason_codes
    assert member_a.payload_hash not in requested_hashes
    assert member_b.payload_hash not in requested_hashes


def test_manifest_integrity_and_original_source_hash_are_separate_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The admission manifest hash and embedded original-body hash each fail closed."""

    valid = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="valuation-integrity",
        facts=_valuation_facts(),
    )
    valid_result, _ = _read(
        monkeypatch,
        (valid,),
        (_reference(valid, "valuation", _EQUITY_CODE, _EQUITY_ID),),
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )
    original_body_hash = hashlib.sha256(b"raw-source:valuation-integrity").hexdigest()
    assert valid_result.source_reference_bindings[0].raw_payload_hash == valid.payload_hash
    assert valid_result.all_source_evidence[0].original_payload_sha256 == original_body_hash
    assert valid_result.source_reference_bindings[0].raw_payload_hash != (
        "sha256:" + original_body_hash
    )

    tampered_payload = dict(valid.payload)
    tampered_payload["asset_code"] = "600000.SH"
    tampered_manifest = replace(valid, payload=tampered_payload)
    result, _ = _read(
        monkeypatch,
        (tampered_manifest,),
        (_reference(valid, "valuation", _EQUITY_CODE, _EQUITY_ID),),
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )
    assert result.status == "blocked"
    assert "RISK_INPUT_MANIFEST_HASH_MISMATCH" in result.reason_codes
    assert result.source_reference_bindings == ()

    bad_body_hash = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="valuation-body-hash",
        facts=_valuation_facts(),
        declared_body_hash="0" * 64,
    )
    result, _ = _read(
        monkeypatch,
        (bad_body_hash,),
        (_reference(bad_body_hash, "valuation", _EQUITY_CODE, _EQUITY_ID),),
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )
    assert result.status == "blocked"
    assert "RISK_INPUT_ORIGINAL_BODY_HASH_MISMATCH" in result.reason_codes
    assert result.source_reference_bindings == ()


def test_source_restrictions_and_prohibition_survive_read_and_block_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reader never strips a source restriction to make pinned facts eligible."""

    source = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="prohibited-valuation",
        facts=_valuation_facts(),
        restrictions=("research_only",),
        must_not_use=True,
    )
    result, _ = _read(
        monkeypatch,
        (source,),
        (_reference(source, "valuation", _EQUITY_CODE, _EQUITY_ID),),
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )

    assert result.status == "blocked"
    assert result.all_source_evidence[0].restrictions == ("research_only",)
    assert result.all_source_evidence[0].must_not_use_for_decision is True
    assert result.assets[0].valuation_evidence is not None
    assert result.assets[0].valuation_evidence.restrictions == ("research_only",)


def test_capacity_window_and_execution_state_keep_independent_source_clocks_and_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prior market window cannot double as today's unsuspended state evidence."""

    valuation = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="capacity-valuation",
        facts=_valuation_facts(),
    )
    industry = _source(
        kind="industry_membership",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="capacity-industry",
        facts=_membership_facts(),
        observed_on=date(2026, 11, 2),
    )
    window = _source(
        kind="capacity_window",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="market-window",
        facts={
            "window_kind": "rolling_sessions",
            "start": "2026-10-26",
            "end": "2026-10-30",
            "sessions": 5,
            "volume": {"value": "100000", "unit": "share"},
            "amount": {"value": "1200000", "unit": "CNY"},
        },
        observed_at=_AS_OF - timedelta(minutes=4),
    )
    state = _source(
        kind="execution_session_state",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="execution-session-state",
        facts={"session_date": _EXECUTION_SESSION.isoformat(), "suspended": False},
        observed_at=_AS_OF - timedelta(minutes=1),
        effective_on=_EXECUTION_SESSION,
    )
    sources = (valuation, industry, window, state)
    references = (
        _reference(valuation, "valuation", _EQUITY_CODE, _EQUITY_ID),
        _reference(industry, "industry_membership", _EQUITY_CODE, _EQUITY_ID),
        _reference(window, "capacity_window", _EQUITY_CODE, _EQUITY_ID),
        _reference(state, "execution_session_state", _EQUITY_CODE, _EQUITY_ID),
    )

    result, requested_hashes = _read(
        monkeypatch,
        sources,
        references,
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )

    assert result.status == "complete"
    observation = result.assets[0].capacity_observation
    assert observation is not None
    assert observation.source_evidence.source_record_id == "market-window"
    assert observation.execution_session_state_evidence is not None
    assert observation.execution_session_state_evidence.source_record_id == (
        "execution-session-state"
    )
    assert observation.execution_session_suspended is False
    assert observation.volume.value == Decimal("100000")
    assert observation.volume.unit == result.assets[0].quantity_unit == "share"
    assert observation.amount.unit == "CNY"
    assert set(requested_hashes) == {item.payload_hash for item in sources}


def test_known_valuation_currency_mismatch_blocks_without_converting_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source amount in another currency cannot be silently rescaled to ledger units."""

    valuation = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="foreign-unit-valuation",
        facts=_valuation_facts(price_unit="USD"),
    )
    result, _ = _read(
        monkeypatch,
        (valuation,),
        (_reference(valuation, "valuation", _EQUITY_CODE, _EQUITY_ID),),
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )

    assert result.status == "blocked"
    assert "RISK_INPUT_VALUATION_PRICE_UNIT_MISMATCH" in result.reason_codes


def test_capacity_volume_and_amount_units_must_match_security_and_ledger_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capacity values are never converted between share, lot, or currency units."""

    valuation = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="capacity-unit-valuation",
        facts=_valuation_facts(quantity_unit="lot"),
    )
    window = _source(
        kind="capacity_window",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="capacity-unit-window",
        facts={
            "window_kind": "rolling_sessions",
            "start": "2026-10-26",
            "end": "2026-10-30",
            "sessions": 5,
            "volume": {"value": "100000", "unit": "share"},
            "amount": {"value": "1200000", "unit": "USD"},
        },
    )
    state = _source(
        kind="execution_session_state",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="capacity-unit-state",
        facts={"session_date": _EXECUTION_SESSION.isoformat(), "suspended": False},
        effective_on=_EXECUTION_SESSION,
    )
    references = (
        _reference(valuation, "valuation", _EQUITY_CODE, _EQUITY_ID),
        _reference(window, "capacity_window", _EQUITY_CODE, _EQUITY_ID),
        _reference(state, "execution_session_state", _EQUITY_CODE, _EQUITY_ID),
    )

    volume_result, _ = _read(
        monkeypatch,
        (valuation, window, state),
        references,
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )
    assert volume_result.status == "blocked"
    assert "RISK_INPUT_CAPACITY_VOLUME_QUANTITY_UNIT_MISMATCH" in (volume_result.reason_codes)
    assert {item.kind for item in volume_result.source_reference_bindings} == {
        "valuation",
        "capacity_window",
        "execution_session_state",
    }

    amount_result, _ = _read(
        monkeypatch,
        (valuation, window, state),
        references,
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
        capacity_measure="amount",
        capacity_unit="CNY",
    )
    assert amount_result.status == "blocked"
    assert "RISK_INPUT_CAPACITY_AMOUNT_LEDGER_UNIT_MISMATCH" in (amount_result.reason_codes)


def test_missing_or_mismatching_execution_state_fails_closed_independently_of_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capacity window facts do not supply a missing, future, or stale session state."""

    valuation = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="state-valuation",
        facts=_valuation_facts(),
    )
    window = _source(
        kind="capacity_window",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="prior-window",
        facts={
            "window_kind": "rolling_sessions",
            "start": "2026-10-26",
            "end": "2026-10-30",
            "sessions": 5,
            "volume": {"value": "100000", "unit": "share"},
            "amount": {"value": "1200000", "unit": "CNY"},
        },
    )
    references = (
        _reference(valuation, "valuation", _EQUITY_CODE, _EQUITY_ID),
        _reference(window, "capacity_window", _EQUITY_CODE, _EQUITY_ID),
    )
    result, _ = _read(
        monkeypatch,
        (valuation, window),
        references,
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )
    assert result.status == "partial"
    assert result.assets[0].capacity_observation is None
    assert "RISK_INPUT_EXECUTION_SESSION_STATE_REFERENCE_MISSING" in result.reason_codes

    future_state = _source(
        kind="execution_session_state",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="future-state",
        facts={"session_date": "2026-11-04", "suspended": False},
        effective_on=date(2026, 11, 4),
    )
    state_reference = _reference(
        future_state,
        "execution_session_state",
        _EQUITY_CODE,
        _EQUITY_ID,
    )
    result, _ = _read(
        monkeypatch,
        (valuation, window, future_state),
        (*references, state_reference),
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )
    assert result.status == "blocked"
    assert "RISK_INPUT_EXECUTION_SESSION_STATE_FUTURE" in result.reason_codes
    assert result.assets[0].capacity_observation is None


def test_date_precision_session_state_must_describe_the_execution_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A date-only prior observation cannot certify today's suspension state."""

    valuation = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="date-state-valuation",
        facts=_valuation_facts(),
    )
    window = _source(
        kind="capacity_window",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="date-state-window",
        facts={
            "window_kind": "rolling_sessions",
            "start": "2026-10-26",
            "end": "2026-10-30",
            "sessions": 5,
            "volume": {"value": "100000", "unit": "share"},
            "amount": {"value": "1200000", "unit": "CNY"},
        },
    )
    state = _source(
        kind="execution_session_state",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="prior-date-state",
        facts={"session_date": _EXECUTION_SESSION.isoformat(), "suspended": False},
        observed_on=date(2026, 11, 2),
        effective_on=_EXECUTION_SESSION,
    )
    references = (
        _reference(valuation, "valuation", _EQUITY_CODE, _EQUITY_ID),
        _reference(window, "capacity_window", _EQUITY_CODE, _EQUITY_ID),
        _reference(state, "execution_session_state", _EQUITY_CODE, _EQUITY_ID),
    )

    result, _ = _read(
        monkeypatch,
        (valuation, window, state),
        references,
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )

    assert result.status == "blocked"
    assert "RISK_INPUT_EXECUTION_SESSION_OBSERVATION_DATE_MISMATCH" in (result.reason_codes)
    assert result.assets[0].capacity_observation is None


def test_unbounded_membership_start_and_missing_units_remain_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source facts with absent temporal/unit bounds are never filled by local time."""

    valuation = _source(
        kind="valuation",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="unknown-units-valuation",
        facts=_valuation_facts(quantity_unit=None, price_unit=None),
    )
    membership_facts = _membership_facts()
    membership_facts["effective_from"] = None
    membership = _source(
        kind="industry_membership",
        asset_code=_EQUITY_CODE,
        security_id=_EQUITY_ID,
        source_record_id="unknown-start-membership",
        facts=membership_facts,
        observed_on=date(2026, 11, 2),
    )
    references = (
        _reference(valuation, "valuation", _EQUITY_CODE, _EQUITY_ID),
        _reference(membership, "industry_membership", _EQUITY_CODE, _EQUITY_ID),
    )

    result, _ = _read(
        monkeypatch,
        (valuation, membership),
        references,
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )

    assert result.status == "partial"
    assert result.assets[0].quantity_unit is None
    assert result.assets[0].price_unit is None
    assert result.assets[0].industry_membership is None
    assert "RISK_INPUT_VALUATION_UNIT_UNKNOWN" in result.reason_codes
    assert "RISK_INPUT_INDUSTRY_EFFECTIVE_FROM_UNKNOWN" in result.reason_codes


def test_policy_reference_must_match_raw_manifest_asset_and_security_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hash-pinned payload for another pair cannot be joined by ticker alone."""

    raw = _source(
        kind="valuation",
        asset_code="600000.SH",
        security_id="equity:SH:600000",
        source_record_id="cross-asset-source",
        facts=_valuation_facts(),
    )
    forged_reference = _reference(raw, "valuation", _EQUITY_CODE, _EQUITY_ID)

    result, _ = _read(
        monkeypatch,
        (raw,),
        (forged_reference,),
        (PortfolioRiskAssetIdentity(asset_code=_EQUITY_CODE, security_id=_EQUITY_ID),),
    )

    assert result.status == "blocked"
    assert "RISK_INPUT_MANIFEST_CONTRACT_INVALID" in result.reason_codes
    assert result.source_reference_bindings == ()
