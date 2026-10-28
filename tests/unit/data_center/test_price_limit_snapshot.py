"""Exact provider-native price limits remain unpublished source facts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.domain.price_limit_snapshot import (
    PriceLimitRawReference,
    PriceLimitSnapshot,
    PriceLimitSnapshotCandidate,
    PriceLimitSnapshotError,
    make_price_limit_snapshot,
    price_limit_request_scope_hash,
    price_limit_snapshot_record_digest,
)
from apps.data_center.domain.provider_response import ProviderResponseTransport

ASSET_CODE = "600000.SH"
EFFECTIVE_DATE = date(2026, 10, 28)
PROVIDER_ID = 7
PROVIDER_NAME = "tushare"
RESPONSE_COMPLETED_AT = datetime(2026, 10, 29, 1, 2, 3, tzinfo=UTC)
RECORDED_AT = RESPONSE_COMPLETED_AT + timedelta(seconds=2)


def _scope_hash(
    *,
    provider_id: int = PROVIDER_ID,
    provider_name: str = PROVIDER_NAME,
    asset_code: str = ASSET_CODE,
    effective_trade_date: date = EFFECTIVE_DATE,
) -> str:
    return price_limit_request_scope_hash(
        provider_id=provider_id,
        provider_name=provider_name,
        asset_code=asset_code,
        effective_trade_date=effective_trade_date,
    )


def _raw_reference(
    *,
    asset_code: str = ASSET_CODE,
    effective_trade_date: date = EFFECTIVE_DATE,
    provider_id: int = PROVIDER_ID,
    provider_name: str = PROVIDER_NAME,
    payload_id: str | None = None,
    payload_hash: str = "sha256:" + "1" * 64,
    record_digest: str = "sha256:" + "2" * 64,
    body_sha256: str = "3" * 64,
    retained_content_sha256: str = "3" * 64,
    original_body_retained: bool = True,
    retained_content_encoding: str = "exact_original_utf8_json",
    body_size_bytes: int = 64,
    response_completed_at: datetime = RESPONSE_COMPLETED_AT,
    dataset_key: str = "equity.price.limit",
    transport: ProviderResponseTransport = ProviderResponseTransport.DIRECT,
    run_id: str = "",
    request_scope_sha256: str | None = None,
) -> PriceLimitRawReference:
    resolved_payload_id = payload_id or str(uuid5(NAMESPACE_URL, payload_hash))
    return PriceLimitRawReference(
        payload_id=resolved_payload_id,
        payload_hash=payload_hash,
        record_digest=record_digest,
        body_sha256=body_sha256,
        retained_content_sha256=retained_content_sha256,
        original_body_retained=original_body_retained,
        retained_content_encoding=retained_content_encoding,
        body_size_bytes=body_size_bytes,
        response_completed_at=response_completed_at,
        provider_name=provider_name,
        dataset_key=dataset_key,
        transport=transport,
        run_id=run_id,
        request_scope_sha256=request_scope_sha256
        or _scope_hash(
            provider_id=provider_id,
            provider_name=provider_name,
            asset_code=asset_code,
            effective_trade_date=effective_trade_date,
        ),
    )


def _candidate(
    *,
    asset_code: str = ASSET_CODE,
    effective_trade_date: date = EFFECTIVE_DATE,
    provider_id: int = PROVIDER_ID,
    provider_name: str = PROVIDER_NAME,
    lower_limit_price: Decimal = Decimal("9.123400"),
    upper_limit_price: Decimal = Decimal("11.456700"),
    raw_reference: PriceLimitRawReference | None = None,
) -> PriceLimitSnapshotCandidate:
    return PriceLimitSnapshotCandidate(
        asset_code=asset_code,
        effective_trade_date=effective_trade_date,
        provider_id=provider_id,
        provider_name=provider_name,
        lower_limit_price=lower_limit_price,
        upper_limit_price=upper_limit_price,
        raw_reference=raw_reference
        or _raw_reference(
            asset_code=asset_code,
            effective_trade_date=effective_trade_date,
            provider_id=provider_id,
            provider_name=provider_name,
        ),
    )


def _snapshot(
    candidate: PriceLimitSnapshotCandidate | None = None,
    *,
    snapshot_id: str | None = None,
    recorded_at: datetime = RECORDED_AT,
) -> PriceLimitSnapshot:
    return make_price_limit_snapshot(
        candidate or _candidate(),
        snapshot_id=snapshot_id or str(uuid4()),
        recorded_at=recorded_at,
    )


def test_scope_hash_binds_the_exact_tushare_request_dimensions() -> None:
    scope = {
        "provider_id": PROVIDER_ID,
        "provider_name": PROVIDER_NAME,
        "dataset_key": "equity.price.limit",
        "api_name": "stk_limit",
        "asset_code": ASSET_CODE,
        "trade_date": EFFECTIVE_DATE.isoformat(),
        "request_params": {
            "provider_id": PROVIDER_ID,
            "provider_name": PROVIDER_NAME,
            "api_name": "stk_limit",
            "fields": "ts_code,trade_date,down_limit,up_limit",
            "params": {"ts_code": ASSET_CODE, "trade_date": "20261028"},
        },
    }
    expected = hashlib.sha256(
        json.dumps(
            scope,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    ).hexdigest()

    assert _scope_hash() == expected
    assert _scope_hash(provider_id=8) != expected
    assert _scope_hash(provider_name="other") != expected
    assert _scope_hash(asset_code="000001.SZ") != expected
    assert _scope_hash(effective_trade_date=date(2026, 10, 29)) != expected


def test_scope_hash_rejects_noncanonical_scope_types_and_values() -> None:
    invalid_scopes = (
        {"provider_id": True},
        {"provider_id": 0},
        {"provider_name": " tushare"},
        {"provider_name": "tushare "},
        {"provider_name": "tushare\n"},
        {"asset_code": "600000"},
        {"asset_code": "600000.SH "},
        {"asset_code": "123456.AB"},
        {"effective_trade_date": datetime(2026, 10, 28, tzinfo=UTC)},
    )
    for overrides in invalid_scopes:
        values: dict[str, object] = {
            "provider_id": PROVIDER_ID,
            "provider_name": PROVIDER_NAME,
            "asset_code": ASSET_CODE,
            "effective_trade_date": EFFECTIVE_DATE,
        }
        values.update(overrides)
        with pytest.raises(PriceLimitSnapshotError):
            price_limit_request_scope_hash(**values)  # type: ignore[arg-type]


def test_raw_reference_payload_matches_the_existing_complete_reference_shape() -> None:
    app_reference = ProviderResponsePayloadReference(
        payload_hash="sha256:" + "a" * 64,
        payload_id=str(uuid5(NAMESPACE_URL, "sha256:" + "a" * 64)),
        record_digest="sha256:" + "b" * 64,
        body_sha256="c" * 64,
        retained_content_sha256="c" * 64,
        original_body_retained=True,
        retained_content_encoding="exact_original_utf8_json",
        body_size_bytes=64,
        response_completed_at=RESPONSE_COMPLETED_AT,
        provider_name=PROVIDER_NAME,
        dataset_key="equity.price.limit",
        transport=ProviderResponseTransport.EGRESS,
        run_id=str(uuid4()),
    )
    reference = PriceLimitRawReference(
        payload_id=app_reference.payload_id,
        payload_hash=app_reference.payload_hash,
        record_digest=app_reference.record_digest,
        body_sha256=app_reference.body_sha256,
        retained_content_sha256=app_reference.retained_content_sha256,
        original_body_retained=app_reference.original_body_retained,
        retained_content_encoding=app_reference.retained_content_encoding,
        body_size_bytes=app_reference.body_size_bytes,
        response_completed_at=app_reference.response_completed_at,
        provider_name=app_reference.provider_name,
        dataset_key=app_reference.dataset_key,
        transport=app_reference.transport,
        run_id=app_reference.run_id,
        request_scope_sha256=_scope_hash(),
    )

    assert reference.to_payload() == {
        **app_reference.to_payload(),
        "request_scope_sha256": _scope_hash(),
    }
    assert reference.to_payload()["transport"] == "egress"
    assert reference.to_payload()["time_semantics"] == "local_response_body_completion"


def test_raw_reference_payload_omits_only_empty_legacy_run_id() -> None:
    reference = _raw_reference()

    assert "run_id" not in reference.to_payload()
    assert reference.to_payload()["request_scope_sha256"] == _scope_hash()


def test_raw_reference_payload_id_must_be_derived_from_payload_hash() -> None:
    with pytest.raises(PriceLimitSnapshotError) as caught:
        _raw_reference(payload_id=str(uuid4()))

    assert caught.value.code == "PRICE_LIMIT_SNAPSHOT_RAW_REFERENCE_INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("payload_id", "not-a-uuid"),
        ("payload_id", object()),
        ("payload_hash", "1" * 64),
        ("record_digest", "sha256:bad"),
        ("body_sha256", "g" * 64),
        ("retained_content_sha256", "4" * 64),
        ("original_body_retained", False),
        ("original_body_retained", 1),
        ("retained_content_encoding", "redacted_canonical_json"),
        ("body_size_bytes", True),
        ("body_size_bytes", -1),
        ("response_completed_at", datetime(2026, 10, 29, 1, 2, 3)),
        ("provider_name", " tushare"),
        ("dataset_key", "equity.other"),
        ("transport", "direct"),
        ("transport", object()),
        ("run_id", "not-a-uuid"),
        ("run_id", object()),
        ("request_scope_sha256", "sha256:" + "a" * 64),
    ],
)
def test_raw_reference_rejects_malformed_identity_or_inexact_body(
    field: str, value: object
) -> None:
    with pytest.raises(PriceLimitSnapshotError):
        replace(_raw_reference(), **{field: value})


def test_candidate_exposes_only_acquisition_time_and_unpublished_native_values() -> None:
    candidate = _candidate()
    payload = candidate.to_content_payload()

    assert candidate.response_completed_at == RESPONSE_COMPLETED_AT
    assert candidate.request_scope_sha256 == _scope_hash()
    assert candidate.price_unit == "provider_native_price"
    assert candidate.currency is None
    assert candidate.observed_at is None
    assert candidate.source_published_at is None
    assert candidate.source_available_at is None
    assert payload["lower_limit_price"] == "9.123400"
    assert payload["upper_limit_price"] == "11.456700"
    assert payload["response_time_semantics"] == "local_response_body_completion"
    assert payload["source_published_at"] is None
    assert payload["source_available_at"] is None
    assert payload["currency"] is None


def test_candidate_hash_preserves_decimal_scale_and_exact_source_reference() -> None:
    scaled = _candidate(lower_limit_price=Decimal("1.2300"), upper_limit_price=Decimal("2"))
    unscaled = _candidate(lower_limit_price=Decimal("1.23"), upper_limit_price=Decimal("2"))
    different_raw = _candidate(
        raw_reference=replace(
            _raw_reference(), body_sha256="4" * 64, retained_content_sha256="4" * 64
        )
    )

    assert scaled.content_hash != unscaled.content_hash
    assert scaled.content_hash != different_raw.content_hash
    assert scaled.to_content_payload()["lower_limit_price"] == "1.2300"
    assert unscaled.to_content_payload()["lower_limit_price"] == "1.23"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("asset_code", "600000"),
        ("effective_trade_date", datetime(2026, 10, 28, tzinfo=UTC)),
        ("provider_id", True),
        ("provider_id", 0),
        ("provider_name", "tushare "),
        ("lower_limit_price", 1.0),
        ("lower_limit_price", True),
        ("lower_limit_price", Decimal("NaN")),
        ("upper_limit_price", Decimal("Infinity")),
        ("lower_limit_price", Decimal("0")),
        ("upper_limit_price", Decimal("-1")),
        ("lower_limit_price", Decimal("20")),
        ("upper_limit_price", Decimal("1")),
        ("lower_limit_price", Decimal("1e513")),
        ("upper_limit_price", Decimal("1e-513")),
        ("raw_reference", object()),
    ],
)
def test_candidate_rejects_invalid_scope_or_exact_price_values(field: str, value: object) -> None:
    with pytest.raises(PriceLimitSnapshotError):
        replace(_candidate(), **{field: value})


def test_candidate_rejects_request_scope_provider_and_dataset_mismatches() -> None:
    candidate = _candidate()
    for raw_reference in (
        _raw_reference(provider_name="other-provider"),
        replace(_raw_reference(), request_scope_sha256="0" * 64),
    ):
        with pytest.raises(PriceLimitSnapshotError):
            replace(candidate, raw_reference=raw_reference)


def test_candidate_rejects_non_utc_response_completion() -> None:
    with pytest.raises(PriceLimitSnapshotError):
        _raw_reference(
            response_completed_at=datetime(
                2026, 10, 29, 1, 2, 3, tzinfo=timezone(timedelta(hours=1))
            )
        )


def test_snapshot_binds_first_record_identity_and_safe_publication_markers() -> None:
    snapshot = _snapshot()
    reference = snapshot.reference()
    payload = snapshot.to_payload()

    assert snapshot.content_hash == snapshot.candidate.content_hash
    assert snapshot.record_digest == price_limit_snapshot_record_digest(snapshot)
    assert snapshot.candidate.response_completed_at == RESPONSE_COMPLETED_AT
    assert snapshot.recorded_at == RECORDED_AT
    assert snapshot.candidate.asset_code == ASSET_CODE
    assert snapshot.candidate.effective_trade_date == EFFECTIVE_DATE
    assert snapshot.candidate.provider_id == PROVIDER_ID
    assert snapshot.candidate.provider_name == PROVIDER_NAME
    assert snapshot.candidate.lower_limit_price == Decimal("9.123400")
    assert snapshot.candidate.upper_limit_price == Decimal("11.456700")
    assert snapshot.candidate.currency is None
    assert snapshot.candidate.observed_at is None
    assert snapshot.candidate.source_published_at is None
    assert snapshot.candidate.source_available_at is None
    assert snapshot.candidate.price_unit == "provider_native_price"
    assert payload["publication_status"] == "unpublished"
    assert payload["must_not_use_for_decision"] is True
    assert payload["must_not_execute"] is True
    assert payload["blocked_reason"] == "price_limit_snapshot_unpublished_reference"
    assert snapshot.publication_status == "unpublished"
    assert snapshot.must_not_use_for_decision is True
    assert snapshot.must_not_execute is True
    assert reference.snapshot_id == snapshot.snapshot_id
    assert reference.asset_code == ASSET_CODE
    assert reference.effective_trade_date == EFFECTIVE_DATE
    assert reference.provider_id == PROVIDER_ID
    assert reference.provider_name == PROVIDER_NAME
    assert reference.dataset_key == "equity.price.limit"
    assert reference.api_name == "stk_limit"
    assert reference.request_scope_sha256 == _scope_hash()
    assert reference.raw_payload_id == snapshot.candidate.raw_reference.payload_id
    assert reference.raw_payload_hash == snapshot.candidate.raw_reference.payload_hash
    assert reference.raw_record_digest == snapshot.candidate.raw_reference.record_digest
    assert reference.to_payload()["effective_trade_date"] == EFFECTIVE_DATE.isoformat()


def test_snapshot_record_digest_binds_uuid_and_recorded_time() -> None:
    candidate = _candidate()
    first = _snapshot(candidate, snapshot_id=str(uuid4()))
    second = _snapshot(candidate, snapshot_id=str(uuid4()))
    later = _snapshot(
        candidate=first.candidate,
        snapshot_id=first.snapshot_id,
        recorded_at=RECORDED_AT + timedelta(seconds=1),
    )

    assert first.content_hash == second.content_hash == later.content_hash
    assert first.record_digest != second.record_digest
    assert first.record_digest != later.record_digest


def test_snapshot_rejects_pre_response_recording_and_forged_hashes() -> None:
    with pytest.raises(PriceLimitSnapshotError):
        _snapshot(recorded_at=RESPONSE_COMPLETED_AT - timedelta(microseconds=1))

    snapshot = _snapshot()
    with pytest.raises(PriceLimitSnapshotError):
        replace(snapshot, recorded_at=RESPONSE_COMPLETED_AT - timedelta(microseconds=1))
    with pytest.raises(PriceLimitSnapshotError):
        replace(snapshot, content_hash="sha256:" + "a" * 64)
    with pytest.raises(PriceLimitSnapshotError):
        replace(snapshot, record_digest="sha256:" + "a" * 64)
    with pytest.raises(PriceLimitSnapshotError):
        replace(snapshot, recorded_at=datetime(2026, 10, 29, 1, 2, 3))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("snapshot_id", "not-a-uuid"),
        ("snapshot_id", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
        ("candidate", object()),
        ("record_digest", "invalid"),
    ],
)
def test_snapshot_rejects_malformed_identity_candidate_or_digest(field: str, value: object) -> None:
    with pytest.raises(PriceLimitSnapshotError):
        replace(_snapshot(), **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("snapshot_id", "not-a-uuid"),
        ("asset_code", "600000"),
        ("effective_trade_date", datetime(2026, 10, 28, tzinfo=UTC)),
        ("provider_id", True),
        ("provider_name", "tushare "),
        ("dataset_key", "equity.other"),
        ("api_name", "daily"),
        ("request_scope_sha256", "sha256:" + "1" * 64),
        ("content_hash", "invalid"),
        ("record_digest", "invalid"),
        ("raw_payload_id", "not-a-uuid"),
        ("raw_payload_hash", "1" * 64),
        ("raw_record_digest", "invalid"),
    ],
)
def test_snapshot_reference_rejects_noncanonical_identity(field: str, value: object) -> None:
    with pytest.raises(PriceLimitSnapshotError):
        replace(_snapshot().reference(), **{field: value})


def test_domain_error_exposes_stable_machine_code() -> None:
    with pytest.raises(PriceLimitSnapshotError) as caught:
        price_limit_request_scope_hash(
            provider_id=0,
            provider_name=PROVIDER_NAME,
            asset_code=ASSET_CODE,
            effective_trade_date=EFFECTIVE_DATE,
        )

    assert isinstance(caught.value, ValueError)
    assert caught.value.code == "PRICE_LIMIT_SNAPSHOT_SCOPE_INVALID"


def test_snapshot_public_functions_reject_untyped_values() -> None:
    with pytest.raises(PriceLimitSnapshotError):
        price_limit_snapshot_record_digest(object())  # type: ignore[arg-type]
    with pytest.raises(PriceLimitSnapshotError):
        make_price_limit_snapshot(
            object(),  # type: ignore[arg-type]
            snapshot_id=str(uuid4()),
            recorded_at=RECORDED_AT,
        )
