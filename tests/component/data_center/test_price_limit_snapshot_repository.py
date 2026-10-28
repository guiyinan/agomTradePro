"""Repository tests for immutable, original-body-bound price-limit facts."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models.deletion import ProtectedError

from apps.data_center.application.price_limit_capture import ReadRetainedPriceLimitUseCase
from apps.data_center.application.price_limit_response_capture import ExactPriceLimitRequestScope
from apps.data_center.application.price_limit_snapshot import price_limit_candidate_from_capture
from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.price_limit_snapshot import PriceLimitSnapshotCandidate
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
from apps.data_center.infrastructure.fact_and_operational_models import RawPayloadModel
from apps.data_center.infrastructure.price_limit_snapshot_models import PriceLimitSnapshotFactModel
from apps.data_center.infrastructure.price_limit_snapshot_repository import (
    DjangoPriceLimitSnapshotRepository,
)
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from core.exceptions import DataFetchError

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])

_ASSET_CODE = "600000.SH"
_EFFECTIVE_DATE = date(2026, 10, 28)
_PROVIDER_ID = 7
_PROVIDER_NAME = "tushare"


def _candidate(
    lower_price: str = "9.123400",
    upper_price: str = "11.456700",
    *,
    asset_code: str = _ASSET_CODE,
    effective_trade_date: date = _EFFECTIVE_DATE,
    provider_id: int = _PROVIDER_ID,
    provider_name: str = _PROVIDER_NAME,
    response_completed_at: datetime | None = None,
) -> tuple[PriceLimitSnapshotCandidate, RawLandingRepository]:
    """Capture and retain one exact numeric Tushare response without network I/O."""

    completed_at = response_completed_at or (datetime.now(UTC) - timedelta(minutes=1))
    scope = ExactPriceLimitRequestScope(
        provider_id=provider_id,
        provider_name=provider_name,
        dataset_key="equity.price.limit",
        api_name="stk_limit",
        asset_code=asset_code,
        trade_date=effective_trade_date,
    )
    body = (
        '{"code":0,"msg":null,"data":{"fields":'
        '["ts_code","trade_date","down_limit","up_limit"],"items":[["'
        f'{asset_code}","{effective_trade_date:%Y%m%d}",{lower_price},{upper_price}]]}}}}'
    ).encode()
    capture = ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=hashlib.sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=completed_at,
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.DIRECT,
    )
    raw_repository = RawLandingRepository()
    reference = RetainProviderResponsePayloadUseCase(raw_repository).execute(
        capture,
        provider_name=provider_name,
        dataset_key="equity.price.limit",
        api_name="stk_limit",
        request_params=scope.request_params(),
    )
    retained = ReadRetainedPriceLimitUseCase(raw_repository).execute(reference, scope=scope)
    return price_limit_candidate_from_capture(retained), raw_repository


def test_first_write_and_exact_replay_preserve_source_values_and_recorded_time(
    record_testsuite_property: Callable[[str, object], None],
) -> None:
    candidate, raw_repository = _candidate()
    repository = DjangoPriceLimitSnapshotRepository()

    first = repository.save(candidate)
    replay = repository.save(candidate)

    assert first.snapshot_id == replay.snapshot_id
    assert first.recorded_at == replay.recorded_at
    assert first.content_hash == candidate.content_hash
    assert first.record_digest == replay.record_digest
    assert first.candidate.lower_limit_price == Decimal("9.123400")
    assert first.candidate.upper_limit_price == Decimal("11.456700")
    assert PriceLimitSnapshotFactModel._default_manager.count() == 1
    raw = raw_repository.get_by_hash(candidate.raw_reference.payload_hash)
    assert raw is not None
    assert raw.payload_id == first.candidate.raw_reference.payload_id
    record_testsuite_property("price_limit_fact_database", connection.settings_dict["NAME"])
    record_testsuite_property("price_limit_fact_database_vendor", connection.vendor)


def test_exact_and_discovery_reads_enforce_both_known_at_boundaries() -> None:
    candidate, _raw_repository = _candidate()
    repository = DjangoPriceLimitSnapshotRepository()
    snapshot = repository.save(candidate)

    before_response = snapshot.candidate.response_completed_at - timedelta(microseconds=1)
    between_response_and_record = snapshot.candidate.response_completed_at
    exact = snapshot.recorded_at

    assert repository.get_exact(snapshot.reference(), known_at=before_response) is None
    assert repository.get_exact(snapshot.reference(), known_at=between_response_and_record) is None
    assert repository.get_exact(snapshot.reference(), known_at=exact) == snapshot
    assert (
        repository.discover(
            asset_code=_ASSET_CODE,
            effective_trade_date=_EFFECTIVE_DATE,
            provider_id=_PROVIDER_ID,
            provider_name=_PROVIDER_NAME,
            known_at=between_response_and_record,
        )
        == ()
    )
    assert repository.discover(
        asset_code=_ASSET_CODE,
        effective_trade_date=_EFFECTIVE_DATE,
        provider_id=_PROVIDER_ID,
        provider_name=_PROVIDER_NAME,
        known_at=exact,
    ) == (snapshot,)
    assert (
        repository.discover(
            asset_code="000001.SZ",
            effective_trade_date=_EFFECTIVE_DATE,
            provider_id=_PROVIDER_ID,
            provider_name=_PROVIDER_NAME,
            known_at=exact,
        )
        == ()
    )


def test_equal_values_from_distinct_responses_and_providers_remain_ambiguous() -> None:
    first_candidate, _ = _candidate("9.123400", "11.456700")
    second_candidate, _ = _candidate(
        "9.123400",
        "11.456700",
        response_completed_at=first_candidate.response_completed_at + timedelta(seconds=1),
    )
    other_provider_candidate, _ = _candidate(
        "9.123400",
        "11.456700",
        provider_id=_PROVIDER_ID + 1,
        provider_name="tushare-secondary",
    )
    repository = DjangoPriceLimitSnapshotRepository()

    first = repository.save(first_candidate)
    second = repository.save(second_candidate)
    other_provider = repository.save(other_provider_candidate)
    matches = repository.discover(
        asset_code=_ASSET_CODE,
        effective_trade_date=_EFFECTIVE_DATE,
        provider_id=_PROVIDER_ID,
        provider_name=_PROVIDER_NAME,
        known_at=datetime.now(UTC),
    )
    other_provider_matches = repository.discover(
        asset_code=_ASSET_CODE,
        effective_trade_date=_EFFECTIVE_DATE,
        provider_id=_PROVIDER_ID + 1,
        provider_name="tushare-secondary",
        known_at=datetime.now(UTC),
    )

    assert len(matches) == 2
    assert {item.snapshot_id for item in matches} == {first.snapshot_id, second.snapshot_id}
    assert len(other_provider_matches) == 1
    assert other_provider_matches[0] == other_provider
    assert first.candidate.lower_limit_price == second.candidate.lower_limit_price


def test_exact_decimal_scale_and_corrupt_source_rows_are_rejected() -> None:
    candidate, _raw_repository = _candidate()
    repository = DjangoPriceLimitSnapshotRepository()
    stored = repository.save(candidate)
    conflicting = replace(candidate, lower_limit_price=Decimal("9.1234"))
    assert conflicting.lower_limit_price == candidate.lower_limit_price
    assert str(conflicting.lower_limit_price) != str(candidate.lower_limit_price)

    with pytest.raises(DataFetchError) as caught:
        repository.save(conflicting)
    assert getattr(caught.value, "code", None) == "PRICE_LIMIT_SNAPSHOT_SOURCE_CONTENT_MISMATCH"

    raw_model = RawPayloadModel._default_manager.get(pk=candidate.raw_reference.payload_id)
    raw_model.payload = {"changed": True}
    raw_model.save()
    with pytest.raises(DataFetchError):
        repository.get_exact(stored.reference(), known_at=stored.recorded_at)
    raw_model.provider_name = ""
    raw_model.save()
    with pytest.raises(DataFetchError) as caught:
        repository.save(candidate)
    assert getattr(caught.value, "code", None) == "PRICE_LIMIT_SNAPSHOT_SOURCE_INVALID"

    sql_candidate, _ = _candidate(asset_code="000001.SZ")
    sql_snapshot = repository.save(sql_candidate)
    altered_recorded_at = sql_snapshot.recorded_at + timedelta(seconds=1)
    table = connection.ops.quote_name(PriceLimitSnapshotFactModel._meta.db_table)
    snapshot_id_column = connection.ops.quote_name(PriceLimitSnapshotFactModel._meta.pk.column)
    stored_snapshot_id = PriceLimitSnapshotFactModel._meta.pk.get_db_prep_value(
        sql_snapshot.snapshot_id, connection
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET recorded_at = %s WHERE {snapshot_id_column} = %s",
            [altered_recorded_at, stored_snapshot_id],
        )
        assert cursor.rowcount == 1
    with pytest.raises(DataFetchError):
        repository.discover(
            asset_code="000001.SZ",
            effective_trade_date=_EFFECTIVE_DATE,
            provider_id=_PROVIDER_ID,
            provider_name=_PROVIDER_NAME,
            known_at=altered_recorded_at + timedelta(microseconds=1),
        )
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET recorded_at = %s WHERE {snapshot_id_column} = %s",
            [sql_snapshot.recorded_at, stored_snapshot_id],
        )
        assert cursor.rowcount == 1
        cursor.execute(
            f"UPDATE {table} SET content_hash = %s WHERE {snapshot_id_column} = %s",
            ["sha256:" + "f" * 64, stored_snapshot_id],
        )
        assert cursor.rowcount == 1
    with pytest.raises(DataFetchError):
        repository.discover(
            asset_code="000001.SZ",
            effective_trade_date=_EFFECTIVE_DATE,
            provider_id=_PROVIDER_ID,
            provider_name=_PROVIDER_NAME,
            known_at=datetime.now(UTC),
        )
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET content_hash = %s WHERE {snapshot_id_column} = %s",
            [sql_snapshot.content_hash, stored_snapshot_id],
        )
        assert cursor.rowcount == 1
        cursor.execute(
            f"UPDATE {table} SET lower_limit_price = %s WHERE {snapshot_id_column} = %s",
            ["9.1234", stored_snapshot_id],
        )
        assert cursor.rowcount == 1
    with pytest.raises(DataFetchError):
        repository.discover(
            asset_code="000001.SZ",
            effective_trade_date=_EFFECTIVE_DATE,
            provider_id=_PROVIDER_ID,
            provider_name=_PROVIDER_NAME,
            known_at=datetime.now(UTC),
        )


def test_fact_is_append_only_and_protects_its_raw_payload() -> None:
    candidate, _raw_repository = _candidate()
    repository = DjangoPriceLimitSnapshotRepository()
    snapshot = repository.save(candidate)
    model = PriceLimitSnapshotFactModel._default_manager.get(pk=snapshot.snapshot_id)
    model.provider_name = "changed"

    with pytest.raises(ValidationError):
        model.save()
    model._state.adding = True
    with pytest.raises(ValidationError):
        model.save()
    with pytest.raises(ValidationError):
        model.delete()
    with pytest.raises(ValidationError):
        PriceLimitSnapshotFactModel._default_manager.filter(pk=snapshot.snapshot_id).update(
            provider_name="changed"
        )
    with pytest.raises(ValidationError):
        PriceLimitSnapshotFactModel._default_manager.filter(pk=snapshot.snapshot_id).delete()
    with pytest.raises(ValidationError):
        PriceLimitSnapshotFactModel._base_manager.filter(pk=snapshot.snapshot_id)._raw_delete(
            "default"
        )
    with pytest.raises(ValidationError):
        PriceLimitSnapshotFactModel._default_manager.bulk_update([model], ["provider_name"])
    with pytest.raises(ValidationError):
        PriceLimitSnapshotFactModel._default_manager.bulk_create([model])

    raw_model = RawPayloadModel._default_manager.get(pk=candidate.raw_reference.payload_id)
    with pytest.raises(ProtectedError):
        raw_model.delete()
