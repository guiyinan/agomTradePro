"""End-to-end source-reader contracts for the opted-in industry DATE mode."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any, cast
from zoneinfo import ZoneInfo

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
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.infrastructure.retained_portfolio_risk_assets_reader import (
    RetainedPortfolioRiskAssetsReader,
)

_AS_OF = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
_DATE = date(2026, 11, 3)
_ZONE = ZoneInfo("Asia/Shanghai")
_ASSET = "600036.SH"
_SECURITY = "equity:SH:600036"
_INDUSTRY_PURPOSE = "ash07_portfolio_exposure"


def _source(
    *,
    kind: str,
    record_id: str,
    facts: dict[str, object],
    observed_on: date | None = None,
    capture_completed_at: datetime | None = None,
    timestamp_snapshot: bool = False,
    observed_at: datetime | None = None,
) -> RawPayload:
    body = f"raw:{record_id}".encode()
    original_hash = hashlib.sha256(body).hexdigest()
    source_id = f"source:{record_id}"
    is_date = observed_on is not None
    source_time = observed_at or _AS_OF - timedelta(minutes=2)
    evidence: dict[str, object] = {
        "source_id": source_id,
        "source_record_id": record_id,
        "original_payload_sha256": original_hash,
        "observation_precision": "date" if is_date else "timestamp",
        "observed_at": None if is_date else source_time.isoformat(),
        "observed_on": observed_on.isoformat() if observed_on is not None else None,
        "available_at": (
            None if is_date or timestamp_snapshot else (_AS_OF - timedelta(minutes=1)).isoformat()
        ),
        "known_at": (_AS_OF - timedelta(seconds=30)).isoformat(),
        "valid_until": (
            None if is_date or timestamp_snapshot else (_AS_OF + timedelta(hours=1)).isoformat()
        ),
        "source_purpose": _INDUSTRY_PURPOSE,
        "allowed_purposes": [_INDUSTRY_PURPOSE],
        "restrictions": [],
        "must_not_use_for_decision": False,
        "coverage": {
            "status": "complete",
            "precision_basis": "portfolio_weight",
            "reported_weight_fraction": "1",
            "expected_item_count": None,
            "observed_item_count": None,
        },
        "effective_on": observed_on.isoformat() if is_date else None,
        "effective_until": observed_on.isoformat() if is_date else None,
    }
    capture_schema = capture_completed_at is not None
    manifest: dict[str, object] = {
        "schema_version": (
            "ash07.retained_risk_input.v2" if capture_schema else "ash07.retained_risk_input.v1"
        ),
        "kind": kind,
        "asset_code": _ASSET,
        "security_id": _SECURITY,
        "source_record_id": record_id,
        "original_body_base64": base64.b64encode(body).decode("ascii"),
        "original_url": None,
        "source_evidence": evidence,
        "facts": facts,
    }
    if capture_completed_at is not None:
        manifest["capture_receipt"] = {
            "capture_id": f"capture:{record_id}",
            "source_id": source_id,
            "source_record_id": record_id,
            "original_body_sha256": original_hash,
            "response_completed_at": capture_completed_at.isoformat(),
            "http_status": 200,
            "body_size_bytes": len(body),
            "body_complete": True,
        }
        manifest["sina_capture_metadata"] = None
    manifest_hash = _manifest_hash(manifest)
    return RawPayload(
        payload_id=f"payload:{record_id}",
        dataset_key="risk_center.simulated_portfolio_risk_input",
        provider_name=source_id,
        payload_hash=manifest_hash,
        schema_fingerprint="sha256:" + "a" * 64,
        payload=cast(dict[str, Any], manifest),
        fetched_at=capture_completed_at or (_AS_OF + timedelta(days=2)),
        parser_version=(
            "ash07.retained_risk_input.v2" if capture_schema else "ash07.retained_risk_input.v1"
        ),
        redacted=True,
        payload_size_bytes=len(body),
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


def _policy_references(
    valuation: RawPayload,
    membership: RawPayload,
    *,
    special_mode: bool,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "kind": "valuation",
            "asset_code": _ASSET,
            "security_id": _SECURITY,
            "raw_payload_hash": valuation.payload_hash,
            "source_record_id": "valuation-record",
        },
        {
            "kind": "industry_membership",
            "asset_code": _ASSET,
            "security_id": _SECURITY,
            "raw_payload_hash": membership.payload_hash,
            "source_record_id": "membership-record",
        },
    ]
    if special_mode:
        rows[1]["clock_evidence_mode"] = "policy_bounded_date_snapshot"
    return rows


def _configuration(references: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "ash07.simulated_portfolio_risk.v1",
        "scope": "simulation_only",
        "ledger_money_unit": "CNY",
        "account_ids": [12],
        "industry": {
            "taxonomy_id": "cnindex-reviewed-taxonomy",
            "taxonomy_kind": "industry",
            "provider_id": "cnindex",
            "provider_version": "reviewed-standard-plus-notice",
            "requested_purpose": _INDUSTRY_PURPOSE,
            "date_precision_purposes": [_INDUSTRY_PURPOSE],
            "allowed_observation_precisions": ["timestamp", "date"],
            "allowed_source_restrictions": [],
            "coverage_precision_basis": "portfolio_weight",
            "max_industry_weight": "0.35",
            "max_security_weight": "0.15",
            "minimum_industry_coverage": "0.90",
            "minimum_etf_lookthrough_coverage": "0.80",
            "coverage_weight_tolerance": "0.01",
        },
        "capacity": {
            "measure": "volume",
            "unit": "share",
            "basis": "average_per_session",
            "usage_scope": "account_security_session",
            "date_basis": "execution_session",
            "max_participation": "0.08",
            "increment": "100",
            "window_kind": "rolling_sessions",
            "sessions": 5,
            "allowed_observation_precisions": ["timestamp"],
            "date_precision_purposes": [],
            "allowed_source_restrictions": [],
        },
        "source_max_timestamp_age_seconds": 1800,
        "source_max_date_age_days": 0,
        "source_references": references,
    }


def _read(
    monkeypatch: pytest.MonkeyPatch,
    *,
    special_mode: bool,
    capture_completed_at: datetime | None,
    account_id: int | None = 12,
    business_timezone: tzinfo | None = _ZONE,
    business_timezone_name: str | None = "Asia/Shanghai",
) -> tuple[PortfolioRiskAssetsReadResult, RawPayload]:
    valuation = _source(
        kind="valuation",
        record_id="valuation-record",
        facts={
            "price": "100",
            "asset_kind": "equity",
            "quantity_unit": "share",
            "price_unit": "CNY",
        },
    )
    membership = _source(
        kind="industry_membership",
        record_id="membership-record",
        facts={
            "taxonomy_id": "cnindex-reviewed-taxonomy",
            "taxonomy_kind": "industry",
            "provider_id": "cnindex",
            "provider_version": "reviewed-standard-plus-notice",
            "industry_code": "C07010101",
            "effective_from": _DATE.isoformat(),
            "effective_end_state": "bounded",
            "effective_until": _DATE.isoformat(),
        },
        observed_on=_DATE,
        capture_completed_at=capture_completed_at,
    )
    retained = {valuation.payload_hash: valuation, membership.payload_hash: membership}
    monkeypatch.setattr(
        raw_landing_public,
        "get_retained_raw_payload",
        lambda *, payload_hash: retained.get(payload_hash),
    )
    runtime = ActiveRuntimeValueEvidence(
        environment="development",
        definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
        value=_configuration(_policy_references(valuation, membership, special_mode=special_mode)),
        profile_id="risk-profile-12",
        profile_key="risk-center-simulation",
        profile_version=12,
        profile_content_hash="e" * 64,
        snapshot_id="risk-snapshot-12",
        snapshot_hash="f" * 64,
        created_at=_AS_OF - timedelta(minutes=5),
        known_at=_AS_OF - timedelta(minutes=5),
        activated_at=_AS_OF - timedelta(minutes=3),
        snapshot_generated_at=_AS_OF - timedelta(minutes=2),
        effective_at=_AS_OF - timedelta(minutes=3),
        as_of=_AS_OF,
    )
    policy = parse_portfolio_risk_policy_bundle(runtime, business_date=_DATE, as_of=_AS_OF)
    request = PortfolioRiskAssetsReadRequest(
        policy=policy,
        requested_assets=(PortfolioRiskAssetIdentity(_ASSET, _SECURITY),),
        as_of=_AS_OF,
        business_date=_DATE,
        execution_session=_DATE,
        capacity_requested_purpose="ash07_capacity",
        account_id=account_id,
        business_timezone=business_timezone,
        business_timezone_name=business_timezone_name,
    )
    return RetainedPortfolioRiskAssetsReader().read_assets(request), membership


def _read_timestamp_valuation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    special_mode: bool,
    capture_completed_at: datetime | None,
    observed_at: datetime | None = None,
) -> tuple[PortfolioRiskAssetsReadResult, RawPayload]:
    """Read one valuation fixture with an optional per-reference timestamp mode."""

    valuation = _source(
        kind="valuation",
        record_id="valuation-timestamp-record",
        facts={
            "price": "100",
            "asset_kind": "equity",
            "quantity_unit": "share",
            "price_unit": "CNY",
        },
        capture_completed_at=capture_completed_at,
        timestamp_snapshot=True,
        observed_at=observed_at,
    )
    reference: dict[str, object] = {
        "kind": "valuation",
        "asset_code": _ASSET,
        "security_id": _SECURITY,
        "raw_payload_hash": valuation.payload_hash,
        "source_record_id": "valuation-timestamp-record",
    }
    if special_mode:
        reference["clock_evidence_mode"] = "policy_bounded_timestamp_snapshot"
    monkeypatch.setattr(
        raw_landing_public,
        "get_retained_raw_payload",
        lambda *, payload_hash: valuation if payload_hash == valuation.payload_hash else None,
    )
    runtime = ActiveRuntimeValueEvidence(
        environment="development",
        definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
        value=_configuration([reference]),
        profile_id="risk-profile-12",
        profile_key="risk-center-simulation",
        profile_version=12,
        profile_content_hash="e" * 64,
        snapshot_id="risk-snapshot-12",
        snapshot_hash="f" * 64,
        created_at=_AS_OF - timedelta(minutes=5),
        known_at=_AS_OF - timedelta(minutes=5),
        activated_at=_AS_OF - timedelta(minutes=3),
        snapshot_generated_at=_AS_OF - timedelta(minutes=2),
        effective_at=_AS_OF - timedelta(minutes=3),
        as_of=_AS_OF,
    )
    policy = parse_portfolio_risk_policy_bundle(runtime, business_date=_DATE, as_of=_AS_OF)
    request = PortfolioRiskAssetsReadRequest(
        policy=policy,
        requested_assets=(PortfolioRiskAssetIdentity(_ASSET, _SECURITY),),
        as_of=_AS_OF,
        business_date=_DATE,
        execution_session=_DATE,
        capacity_requested_purpose="ash07_capacity",
        account_id=12,
        business_timezone=_ZONE,
        business_timezone_name="Asia/Shanghai",
    )
    return RetainedPortfolioRiskAssetsReader().read_assets(request), valuation


def test_reader_attaches_policy_clock_proof_only_to_exact_same_day_industry_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, membership = _read(
        monkeypatch,
        special_mode=True,
        capture_completed_at=_AS_OF - timedelta(minutes=1),
    )

    evidence = next(
        item for item in result.all_source_evidence if item.source_record_id == "membership-record"
    )
    assert result.status in {"partial", "complete"}
    assert evidence.policy_clock_proof is not None
    assert evidence.available_at is None
    assert evidence.valid_until is None
    assert evidence.policy_clock_proof.proven_available_at == _AS_OF - timedelta(minutes=1)
    assert evidence.policy_clock_proof.source_reference_hash == membership.payload_hash
    assert "RISK_SOURCE_AVAILABLE_AT_UNKNOWN" not in result.reason_codes
    assert "RISK_SOURCE_VALID_UNTIL_UNKNOWN" not in result.reason_codes


def test_explicit_clock_mode_requires_receipt_bearing_manifest_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = _read(
        monkeypatch,
        special_mode=True,
        capture_completed_at=None,
    )

    assert "RISK_INPUT_CAPTURE_RECEIPT_REQUIRED" in result.reason_codes
    assert all(item.source_record_id != "membership-record" for item in result.all_source_evidence)


@pytest.mark.parametrize(
    "overrides, expected_reason",
    [
        ({"special_mode": False}, "RISK_SOURCE_AVAILABLE_AT_UNKNOWN"),
        ({"account_id": None}, "RISK_SOURCE_AVAILABLE_AT_UNKNOWN"),
        ({"business_timezone_name": None}, "RISK_SOURCE_AVAILABLE_AT_UNKNOWN"),
    ],
)
def test_reader_never_infers_date_clock_mode_from_date_precision_or_receipt(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
    expected_reason: str,
) -> None:
    result, _ = _read(
        monkeypatch,
        special_mode=cast(bool, overrides.get("special_mode", True)),
        capture_completed_at=cast(
            datetime | None, overrides.get("capture_completed_at", _AS_OF - timedelta(minutes=1))
        ),
        account_id=cast(int | None, overrides.get("account_id", 12)),
        business_timezone=cast(tzinfo | None, overrides.get("business_timezone", _ZONE)),
        business_timezone_name=cast(
            str | None, overrides.get("business_timezone_name", "Asia/Shanghai")
        ),
    )

    assert expected_reason in result.reason_codes
    evidence = next(
        item for item in result.all_source_evidence if item.source_record_id == "membership-record"
    )
    assert evidence.policy_clock_proof is None


def test_reader_attaches_timestamp_proof_without_rewriting_source_clocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, valuation = _read_timestamp_valuation(
        monkeypatch,
        special_mode=True,
        capture_completed_at=_AS_OF - timedelta(minutes=1),
    )

    evidence = next(
        item
        for item in result.all_source_evidence
        if item.source_record_id == "valuation-timestamp-record"
    )
    assert result.status == "partial"  # The fixture intentionally has no industry source.
    assert evidence.policy_clock_proof is not None
    assert evidence.policy_clock_proof.source_kind == "valuation"
    assert evidence.observation_precision.value == "timestamp"
    assert evidence.observed_at == _AS_OF - timedelta(minutes=2)
    assert evidence.available_at is None
    assert evidence.valid_until is None
    assert evidence.policy_clock_proof.source_reference_hash == valuation.payload_hash
    assert "RISK_SOURCE_AVAILABLE_AT_UNKNOWN" not in result.reason_codes
    assert "RISK_SOURCE_VALID_UNTIL_UNKNOWN" not in result.reason_codes


def test_timestamp_proof_does_not_infer_missing_receipt_or_relax_strict_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = _read_timestamp_valuation(
        monkeypatch,
        special_mode=True,
        capture_completed_at=None,
    )
    assert "RISK_INPUT_CAPTURE_RECEIPT_REQUIRED" in result.reason_codes

    strict_result, _ = _read_timestamp_valuation(
        monkeypatch,
        special_mode=False,
        capture_completed_at=_AS_OF - timedelta(minutes=1),
    )
    evidence = strict_result.all_source_evidence[0]
    assert evidence.policy_clock_proof is None
    assert "RISK_SOURCE_AVAILABLE_AT_UNKNOWN" in strict_result.reason_codes
    assert "RISK_SOURCE_VALID_UNTIL_UNKNOWN" in strict_result.reason_codes


def test_timestamp_snapshot_rejects_observation_from_another_business_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = _read_timestamp_valuation(
        monkeypatch,
        special_mode=True,
        capture_completed_at=_AS_OF - timedelta(minutes=1),
        observed_at=datetime(2026, 11, 2, 7, 0, tzinfo=UTC),
    )
    evidence = next(
        item
        for item in result.all_source_evidence
        if item.source_record_id == "valuation-timestamp-record"
    )
    assert evidence.policy_clock_proof is None
    assert "PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_OBSERVATION_DATE_MISMATCH" in result.reason_codes
