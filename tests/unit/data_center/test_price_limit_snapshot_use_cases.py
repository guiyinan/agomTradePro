"""Application boundaries for unpublished exact daily price-limit facts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from apps.data_center.application.price_limit_capture import CaptureExactPriceLimitUseCase
from apps.data_center.application.price_limit_snapshot import (
    CapturePriceLimitSnapshotUseCase,
    ReadPriceLimitSnapshotUseCase,
    RecordPriceLimitSnapshotUseCase,
    price_limit_candidate_from_capture,
)
from apps.data_center.domain.price_limit_snapshot import make_price_limit_snapshot
from apps.data_center.infrastructure.provider_adapters import TushareUnifiedProviderAdapter
from core.exceptions import DataFetchError
from tests.unit.data_center.test_price_limit_capture import (
    TRADE_DATE,
    ConfigReader,
    RawStore,
    install_transport,
)


@pytest.fixture
def retained(monkeypatch):
    """Keep original HTTP/raw capture semantics; no real network or database."""
    install_transport(monkeypatch)
    return CaptureExactPriceLimitUseCase(
        ConfigReader(), TushareUnifiedProviderAdapter, RawStore()
    ).execute(provider_id=19, asset_code="600000.SH", target_trade_date=TRADE_DATE)


class Repository:
    """Return controlled typed results to exercise application boundary checks."""

    def __init__(self, snapshots=()):
        self.snapshots = snapshots
        self.calls = []

    def save(self, candidate):
        self.calls.append(("save", candidate))
        return make_price_limit_snapshot(
            candidate,
            snapshot_id=str(uuid4()),
            recorded_at=candidate.response_completed_at + timedelta(seconds=1),
        )

    def discover(self, **query):
        self.calls.append(("discover", query))
        return self.snapshots

    def get_exact(self, reference, *, known_at):
        self.calls.append(("exact", reference, known_at))
        return self.snapshots[0] if self.snapshots else None


def snapshot(retained):
    """Seal the real capture as one immutable repository response fixture."""
    candidate = price_limit_candidate_from_capture(retained)
    return make_price_limit_snapshot(
        candidate,
        snapshot_id=str(uuid4()),
        recorded_at=candidate.response_completed_at + timedelta(seconds=1),
    )


def test_record_preserves_exact_body_scope_and_unpublished_limits(retained):
    repository = Repository()
    result = RecordPriceLimitSnapshotUseCase(repository).execute(retained)
    candidate = result.candidate
    payload = candidate.raw_reference.to_payload()
    payload.pop("request_scope_sha256")
    assert payload == retained.reference.to_payload()
    assert str(candidate.lower_limit_price) == str(retained.values.lower_limit_price)
    assert str(candidate.upper_limit_price) == str(retained.values.upper_limit_price)
    assert candidate.effective_trade_date == retained.request_scope.trade_date
    assert candidate.response_completed_at == retained.reference.response_completed_at
    assert candidate.observed_at is candidate.source_available_at is None
    assert candidate.currency is candidate.source_published_at is None
    assert candidate.price_unit == "provider_native_price"
    assert result.publication_status == "unpublished"
    assert result.must_not_use_for_decision and result.must_not_execute
    assert repository.calls == [("save", candidate)]


def test_capture_then_record_uses_same_provider_asset_and_date(retained):
    class Capturer:
        def execute(self, **request):
            assert request == {
                "provider_id": 19,
                "asset_code": "600000.SH",
                "target_trade_date": TRADE_DATE,
            }
            return retained

    repository = Repository()
    result = CapturePriceLimitSnapshotUseCase(
        Capturer(), RecordPriceLimitSnapshotUseCase(repository)
    ).execute(provider_id=19, asset_code="600000.SH", target_trade_date=TRADE_DATE)
    assert result.candidate == repository.calls[0][1]


def test_wrong_capture_scope_cannot_be_recorded_under_requested_identity(retained):
    class Capturer:
        def execute(self, **_request):
            return retained

    repository = Repository()
    with pytest.raises(DataFetchError, match="PRICE_LIMIT_SNAPSHOT_CAPTURE_SCOPE_MISMATCH"):
        CapturePriceLimitSnapshotUseCase(
            Capturer(), RecordPriceLimitSnapshotUseCase(repository)
        ).execute(provider_id=20, asset_code="600000.SH", target_trade_date=TRADE_DATE)
    assert repository.calls == []


@pytest.mark.parametrize("count,code", [(0, "MISSING"), (2, "AMBIGUOUS")])
def test_discovery_never_chooses_a_latest_candidate(retained, count, code):
    item = snapshot(retained)
    repository = Repository(tuple(item for _ in range(count)))
    with pytest.raises(DataFetchError, match=f"PRICE_LIMIT_SNAPSHOT_{code}"):
        ReadPriceLimitSnapshotUseCase(repository).discover(
            scope=retained.request_scope, known_at=item.recorded_at
        )


def test_unique_discovery_and_exact_lookup_keep_both_time_cutoffs(retained):
    item = snapshot(retained)
    repository = Repository((item,))
    reader = ReadPriceLimitSnapshotUseCase(repository)
    assert reader.discover(scope=retained.request_scope, known_at=item.recorded_at) == item
    assert reader.get_exact(item.reference(), known_at=item.recorded_at) == item
    assert repository.calls[0][1] == {
        "asset_code": "600000.SH",
        "effective_trade_date": TRADE_DATE,
        "provider_id": 19,
        "provider_name": "limit-fixture",
        "known_at": item.recorded_at,
    }


@pytest.mark.parametrize("offset", [-1, 0])
def test_future_fact_is_refused_even_if_repository_returns_it(retained, offset):
    item = snapshot(retained)
    reader = ReadPriceLimitSnapshotUseCase(Repository((item,)))
    cutoff = item.candidate.response_completed_at + timedelta(microseconds=offset)
    for operation in (
        lambda: reader.discover(scope=retained.request_scope, known_at=cutoff),
        lambda: reader.get_exact(item.reference(), known_at=cutoff),
    ):
        with pytest.raises(DataFetchError, match="PRICE_LIMIT_SNAPSHOT_NOT_KNOWN"):
            operation()


def test_wrong_provider_scope_returned_by_repository_is_rejected(retained):
    item = snapshot(retained)
    with pytest.raises(DataFetchError, match="PRICE_LIMIT_SNAPSHOT_SCOPE_MISMATCH"):
        ReadPriceLimitSnapshotUseCase(Repository((item,))).discover(
            scope=replace(retained.request_scope, provider_id=20), known_at=item.recorded_at
        )


def test_exact_reference_is_not_replaced_by_another_snapshot(retained):
    original = snapshot(retained)
    other = snapshot(retained)
    with pytest.raises(DataFetchError, match="PRICE_LIMIT_SNAPSHOT_REFERENCE_MISMATCH"):
        ReadPriceLimitSnapshotUseCase(Repository((other,))).get_exact(
            original.reference(), known_at=original.recorded_at
        )


def test_missing_exact_reference_is_not_discovered_or_recreated(retained):
    item = snapshot(retained)
    repository = Repository()
    with pytest.raises(DataFetchError, match="PRICE_LIMIT_SNAPSHOT_MISSING"):
        ReadPriceLimitSnapshotUseCase(repository).get_exact(
            item.reference(), known_at=item.recorded_at
        )
    assert [call[0] for call in repository.calls] == ["exact"]


@pytest.mark.parametrize("cutoff", [None, date(2026, 10, 28), datetime(2026, 10, 28)])
def test_invalid_cutoff_rejected_before_repository_access(retained, cutoff):
    repository = Repository()
    with pytest.raises(DataFetchError, match="PRICE_LIMIT_SNAPSHOT_KNOWLEDGE_TIME_INVALID"):
        ReadPriceLimitSnapshotUseCase(repository).discover(
            scope=retained.request_scope, known_at=cutoff
        )
    assert repository.calls == []


@pytest.mark.parametrize("value", [None, {}, object()])
def test_untyped_capture_never_reaches_repository(value):
    repository = Repository()
    with pytest.raises(DataFetchError, match="PRICE_LIMIT_SNAPSHOT_CAPTURE_INVALID"):
        RecordPriceLimitSnapshotUseCase(repository).execute(value)
    assert repository.calls == []


def test_mapper_preserves_domain_validation_failure_code(retained):
    wrong = replace(retained, request_scope=replace(retained.request_scope, provider_name="other"))
    with pytest.raises(DataFetchError):
        price_limit_candidate_from_capture(wrong)


def test_reader_requires_typed_scope_and_reference_before_storage():
    repository = Repository()
    reader = ReadPriceLimitSnapshotUseCase(repository)
    now = datetime.now(UTC)
    with pytest.raises(DataFetchError, match="PRICE_LIMIT_SNAPSHOT_SCOPE_INVALID"):
        reader.discover(scope={}, known_at=now)
    with pytest.raises(DataFetchError, match="PRICE_LIMIT_SNAPSHOT_REFERENCE_INVALID"):
        reader.get_exact({}, known_at=now)
    assert repository.calls == []
