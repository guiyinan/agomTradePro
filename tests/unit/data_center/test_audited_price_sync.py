"""RED contract tests for the audited historical-price sync path."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from apps.audit.application.data_fetch_audit import DataFetchAuditObservation
from apps.audit.application.data_publication_audit import DataPublicationAuditObservation
from apps.audit.domain.system_audit_event import AuditOutcome
from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStageRawAuditBinding,
)
from apps.data_center.application.dtos import SyncPriceRequest
from apps.data_center.application.model_history_preparation import ModelHistoryReferenceSnapshot
from apps.data_center.application.sync_identity import (
    SyncExecutionIdentity,
    build_sync_execution_identity,
)
from apps.data_center.application.sync_use_cases import SyncPriceUseCase
from apps.data_center.domain.entities import (
    PriceBar,
    ProviderConfig,
    RawAudit,
    raw_audit_content_hash,
)
from apps.data_center.domain.enums import DataCapability, PriceAdjustment
from apps.data_center.domain.model_market_data import ModelDailyBar
from apps.data_center.infrastructure import candidate_raw_audit_metadata_resolver
from core.exceptions import DataFetchError

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _identity() -> SyncExecutionIdentity:
    return build_sync_execution_identity(
        run_id="11111111-1111-4111-8111-111111111111",
        ingested_run_id="22222222-2222-4222-8222-222222222222",
        batch_id="33333333-3333-4333-8333-333333333333",
        dataset_key="equity.price.bar",
        provider_name="provider-main",
    )


def _bar() -> PriceBar:
    return PriceBar(
        asset_code="000001.SZ",
        bar_date=date(2026, 8, 26),
        open=10.0,
        high=11.0,
        low=9.5,
        close=10.5,
        freq="1d",
        adjustment=PriceAdjustment.NONE,
        source="provider-main",
        fetched_at=NOW,
    )


def _model_bar(asset_code: str, trade_date: date) -> ModelDailyBar:
    return ModelDailyBar(
        asset_code=asset_code,
        trade_date=trade_date,
        open=10.0,
        high=11.0,
        low=9.5,
        close=10.5,
        volume=1200.0,
        change_percent=0.0,
        adjustment_factor=2.0,
        source="tushare",
        amount=12345.0,
    )


def _empty_reference_snapshot(
    asset_codes: tuple[str, ...], start: date, end: date
) -> ModelHistoryReferenceSnapshot:
    """Build the pre-fetch repository snapshot for an empty test fact store."""

    return ModelHistoryReferenceSnapshot.from_bars(
        asset_codes, start, end, dict.fromkeys(asset_codes, ())
    )


def _config() -> ProviderConfig:
    return ProviderConfig(
        id=1,
        name="provider-main",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )


class _Provider:
    def __init__(self, bars: list[PriceBar] | None = None, error: Exception | None = None) -> None:
        self.bars = bars or []
        self.error = error

    def provider_name(self) -> str:
        return "provider-main"

    def fetch_price_history(self, _asset_code: str, _start: date, _end: date) -> list[PriceBar]:
        if self.error is not None:
            raise self.error
        return list(self.bars)


class _ProviderRepository:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.config = _config()

    def get_by_id(self, _provider_id: int) -> ProviderConfig:
        return self.config

    def save(self, config: ProviderConfig) -> ProviderConfig:
        self.events.append("health")
        self.config = config
        return config


class _Registry:
    def __init__(self, provider: _Provider) -> None:
        self.provider = provider

    def get_by_id(self, _provider_id: int) -> _Provider:
        return self.provider

    def record_success(
        self, _provider_name: str, _capability: DataCapability, _latency_ms: float
    ) -> None:
        return None

    def record_failure(self, _provider_name: str, _capability: DataCapability) -> None:
        return None


class _Facts:
    def __init__(self, events: list[str], active: Callable[[], bool]) -> None:
        self.events = events
        self.active = active
        self.saved: list[PriceBar] = []

    def bulk_upsert(self, bars: list[PriceBar]) -> int:
        assert self.active()
        self.events.append("facts")
        self.saved.extend(bars)
        return len(bars)

    def get_bars_for_assets(
        self,
        asset_codes: Sequence[str],
        start: date | None = None,
        end: date | None = None,
        limit: int = 5000,
    ) -> dict[str, tuple[PriceBar, ...]]:
        assert self.active()
        self.events.append("reference_snapshot")
        return dict.fromkeys(asset_codes, ())

    def list_publication_candidates(self, _bars: list[PriceBar]) -> list[object]:
        assert self.active()
        return []


class _RawAudit:
    def __init__(self, events: list[str], active: Callable[[], bool]) -> None:
        self.events = events
        self.active = active
        self.rows: list[RawAudit] = []

    def log(self, audit: RawAudit) -> RawAudit:
        assert self.active()
        self.events.append("raw_audit")
        persisted = RawAudit(
            provider_name=audit.provider_name,
            capability=audit.capability,
            request_params=audit.request_params,
            status=audit.status,
            row_count=audit.row_count,
            latency_ms=audit.latency_ms,
            error_message=audit.error_message,
            fetched_at=audit.fetched_at,
            extra=dict(audit.extra),
            request_params_hash=audit.request_params_hash,
            redacted=True,
            payload_size_bytes=0,
            raw_audit_id="1",
            run_id=audit.run_id,
            ingested_run_id=audit.ingested_run_id,
        )
        persisted = dataclasses.replace(
            persisted,
            content_hash=raw_audit_content_hash(persisted),
        )
        self.rows.append(persisted)
        return persisted


class _Uow:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.active = False

    def atomic(self) -> AbstractContextManager[None]:
        owner = self

        class _Atomic(AbstractContextManager[None]):
            def __enter__(self) -> None:
                owner.active = True
                owner.events.append("begin")
                return None

            def __exit__(self, exc_type: object, _exc: object, _tb: object) -> bool:
                owner.events.append("rollback" if exc_type else "commit")
                owner.active = False
                return False

        return _Atomic()


class _Issuer:
    def issue(self, *, dataset_key: str, provider_name: str) -> SyncExecutionIdentity:
        identity = _identity()
        assert dataset_key == identity.dataset_key
        assert provider_name == identity.provider_name
        return identity


class _AuditWriter:
    def __init__(self, events: list[str], active: Callable[[], bool]) -> None:
        self.events = events
        self.active = active
        self.fetch: list[DataFetchAuditObservation] = []
        self.publication: list[DataPublicationAuditObservation] = []
        self.fail = False

    def write(
        self, observation: DataFetchAuditObservation | DataPublicationAuditObservation
    ) -> None:
        assert self.active()
        if self.fail:
            raise RuntimeError("audit writer failure")
        if isinstance(observation, DataFetchAuditObservation):
            self.events.append("fetch_event")
            self.fetch.append(observation)
        else:
            self.events.append("publication_event")
            self.publication.append(observation)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Publisher:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def execute(
        self,
        _bars: list[PriceBar],
        *,
        provider_name: str,
        publication_key: str,
        run_id: str,
        published_at: datetime,
    ) -> object:
        assert provider_name == "provider-main"
        assert publication_key == "current"
        assert run_id == "11111111-1111-4111-8111-111111111111"
        assert published_at == NOW
        self.calls += 1
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            dataset_key="equity.price.bar",
            publication_key="current",
            publication_id="publication-1",
            policy_version="1.0:1.0",
            publication_hash="b" * 64,
            member_count=1,
            coverage=SimpleNamespace(requested_count=1, eligible_count=1, selected_count=1),
            published_at=published_at,
        )


class _PublicationQualityRecorder:
    """Typed fake for the post-publication persisted quality snapshot."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def execute(
        self,
        *,
        publication_id: str,
        run_id: str,
        ingested_run_id: str,
        provider_key: str,
    ) -> object:
        self.calls.append((publication_id, run_id, ingested_run_id, provider_key))
        return SimpleNamespace(publication_id=publication_id)


def _build(
    bars: list[PriceBar],
    *,
    publisher: _Publisher | None = None,
) -> tuple[SyncPriceUseCase, _Uow, _AuditWriter, _Facts, _RawAudit, _PublicationQualityRecorder]:
    events: list[str] = []
    uow = _Uow(events)
    writer = _AuditWriter(events, lambda: uow.active)
    facts = _Facts(events, lambda: uow.active)
    raw = _RawAudit(events, lambda: uow.active)
    quality_recorder = _PublicationQualityRecorder()
    use_case = SyncPriceUseCase(
        provider_repo=_ProviderRepository(events),
        provider_registry=_Registry(_Provider(bars)),
        fact_repo=facts,
        raw_audit_repo=raw,
        publication_publisher=publisher,
        sync_identity_issuer=_Issuer(),
        sync_unit_of_work=uow,
        data_fetch_audit_writer=writer,
        data_publication_audit_writer=writer,
        publication_quality_recorder=quality_recorder if publisher is not None else None,
        clock=_Clock(),
    )
    return use_case, uow, writer, facts, raw, quality_recorder


def _request() -> SyncPriceRequest:
    return SyncPriceRequest(
        provider_id=1,
        asset_code="000001.SZ",
        start=date(2026, 8, 1),
        end=date(2026, 8, 27),
    )


def test_success_correlates_price_raw_audit_publication_and_both_events_in_one_uow() -> None:
    use_case, uow, writer, facts, raw, quality_recorder = _build([_bar()], publisher=_Publisher())

    result = use_case.execute(_request())

    assert result.status == "success"
    publication = writer.publication[0]
    identity = _identity()
    assert result.run_id == identity.run_id
    assert result.ingested_run_id == identity.ingested_run_id
    assert result.publication_id == publication.publication_id
    assert result.publication_version == publication.publication_version
    assert result.publication_hash == publication.publication_hash
    result_payload = result.to_dict()
    assert result_payload["run_id"] == identity.run_id
    assert result_payload["ingested_run_id"] == identity.ingested_run_id
    assert result_payload["publication_id"] == publication.publication_id
    assert result_payload["publication_version"] == publication.publication_version
    assert result_payload["publication_hash"] == publication.publication_hash
    assert uow.active is False
    assert facts.saved[0].ingested_run_id == "22222222-2222-4222-8222-222222222222"
    assert raw.rows[0].run_id == "11111111-1111-4111-8111-111111111111"
    assert raw.rows[0].ingested_run_id == "22222222-2222-4222-8222-222222222222"
    assert writer.fetch[0].outcome is AuditOutcome.SUCCESS
    assert writer.publication[0].run_id == raw.rows[0].run_id
    assert quality_recorder.calls == [
        ("publication-1", identity.run_id, identity.ingested_run_id, "provider-main")
    ]
    events = [*uow.events]
    assert events[0] == "begin"
    assert events[-1] == "commit"


def test_noop_writes_fetch_noop_and_no_publication() -> None:
    use_case, _uow, writer, _facts, _raw, quality_recorder = _build([])

    result = use_case.execute(_request())

    assert result.status == "noop"
    identity = writer.fetch[0]
    assert result.run_id == identity.run_id
    assert result.ingested_run_id == identity.ingested_run_id
    assert result.publication_id is None
    assert result.publication_version is None
    assert result.publication_hash is None
    result_payload = result.to_dict()
    assert result_payload["run_id"] == identity.run_id
    assert result_payload["ingested_run_id"] == identity.ingested_run_id
    assert result_payload["publication_id"] is None
    assert result_payload["publication_version"] is None
    assert result_payload["publication_hash"] is None
    assert writer.fetch[0].outcome is AuditOutcome.NOOP
    assert writer.publication == []
    assert quality_recorder.calls == []


def test_provider_failure_commits_sanitized_failed_fetch_then_reraises() -> None:
    events: list[str] = []
    uow = _Uow(events)
    writer = _AuditWriter(events, lambda: uow.active)
    raw = _RawAudit(events, lambda: uow.active)
    use_case = SyncPriceUseCase(
        provider_repo=_ProviderRepository(events),
        provider_registry=_Registry(_Provider(error=TimeoutError("secret-token"))),
        fact_repo=_Facts(events, lambda: uow.active),
        raw_audit_repo=raw,
        sync_identity_issuer=_Issuer(),
        sync_unit_of_work=uow,
        data_fetch_audit_writer=writer,
        data_publication_audit_writer=writer,
        clock=_Clock(),
    )

    with pytest.raises(TimeoutError, match="secret-token"):
        use_case.execute(_request())

    assert writer.fetch[0].outcome is AuditOutcome.FAILED
    assert "secret-token" not in str(writer.fetch[0])
    assert events[-1] == "commit"


def test_model_history_batch_shares_one_exact_identity_and_raw_audit_in_one_uow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_case, uow, writer, facts, raw, _quality = _build([])
    rows = (
        _model_bar("000001.SZ", date(2026, 8, 26)),
        _model_bar("000002.SZ", date(2026, 8, 26)),
    )

    result = use_case.record_model_history_fetch_success(
        provider_id=1,
        asset_codes=("000001.SZ", "000002.SZ"),
        start_date=date(2026, 8, 26),
        end_date=date(2026, 8, 26),
        rows=rows,
        request_details={"provider_fetch_kind": "tushare_daily_adj_factor_session_batch"},
        reference_snapshot=_empty_reference_snapshot(
            ("000001.SZ", "000002.SZ"), date(2026, 8, 26), date(2026, 8, 26)
        ),
    )

    assert result.stored_count == 2
    assert result.stored_asset_codes == ("000001.SZ", "000002.SZ")
    assert len({bar.ingested_run_id for bar in facts.saved}) == 1
    assert {bar.source for bar in facts.saved} == {"tushare"}
    assert facts.saved[0].ingested_run_id == _identity().ingested_run_id
    assert result.raw_audit_reference.raw_audit_id == raw.rows[0].raw_audit_id
    assert result.raw_audit_reference.run_id == raw.rows[0].run_id == _identity().run_id
    assert result.source_type == "tushare"
    assert raw.rows[0].extra == {"source_type": "tushare"}
    assert raw.rows[0].provider_name == "provider-main"
    assert facts.saved[0].source == "tushare"
    assert raw.rows[0].content_hash == result.raw_audit_reference.content_hash
    assert raw.rows[0].content_hash != raw_audit_content_hash(
        dataclasses.replace(raw.rows[0], extra={})
    )
    assert (
        result.raw_audit_reference.ingested_run_id
        == raw.rows[0].ingested_run_id
        == facts.saved[0].ingested_run_id
    )
    assert writer.fetch[0].raw_audit_id == result.raw_audit_reference.raw_audit_id
    assert writer.fetch[0].outcome is AuditOutcome.SUCCESS
    assert uow.events == [
        "begin",
        "reference_snapshot",
        "facts",
        "health",
        "raw_audit",
        "fetch_event",
        "commit",
    ]

    persisted_row = SimpleNamespace(
        pk=1,
        status=raw.rows[0].status,
        row_count=raw.rows[0].row_count,
        capability=raw.rows[0].capability,
        provider_name=raw.rows[0].provider_name,
        run_id=raw.rows[0].run_id,
        ingested_run_id=raw.rows[0].ingested_run_id,
        extra=raw.rows[0].extra,
    )

    class _AuditQuery:
        def order_by(self, *_fields: str) -> list[SimpleNamespace]:
            return [persisted_row]

    class _AuditManager:
        def filter(self, **criteria: object) -> _AuditQuery:
            assert criteria == {"pk__in": (1,)}
            return _AuditQuery()

    monkeypatch.setattr(
        candidate_raw_audit_metadata_resolver,
        "RawAuditModel",
        SimpleNamespace(_default_manager=_AuditManager()),
    )
    monkeypatch.setattr(
        candidate_raw_audit_metadata_resolver,
        "RawAuditRepository",
        SimpleNamespace(_from_model=lambda _row: raw.rows[0]),
    )
    resolved = (
        candidate_raw_audit_metadata_resolver.DjangoCandidateRawAuditMetadataResolver().resolve(
            (
                CurrentPublicationStageRawAuditBinding(
                    reference=result.raw_audit_reference,
                    expected_source_type="tushare",
                ),
            ),
            dataset_key="equity.price.bar",
        )
    )

    assert len(resolved) == 1
    assert resolved[0].raw_audit_id == result.raw_audit_reference.raw_audit_id
    assert resolved[0].content_hash == result.raw_audit_reference.content_hash
    assert resolved[0].provider_name == "provider-main"
    assert resolved[0].capability == "historical_price"
    assert resolved[0].run_id == result.raw_audit_reference.run_id
    assert resolved[0].ingested_run_id == result.raw_audit_reference.ingested_run_id


def test_model_history_fails_closed_when_persisted_raw_audit_return_loses_source_type() -> None:
    use_case, uow, writer, _facts, raw, _quality = _build([])
    original_log = raw.log

    def strip_success_source_type(audit: RawAudit) -> RawAudit:
        persisted = original_log(audit)
        if audit.status == "ok":
            return dataclasses.replace(persisted, extra={})
        return persisted

    raw.log = strip_success_source_type

    with pytest.raises(DataFetchError) as caught:
        use_case.record_model_history_fetch_success(
            provider_id=1,
            asset_codes=("000001.SZ",),
            start_date=date(2026, 8, 26),
            end_date=date(2026, 8, 26),
            rows=(_model_bar("000001.SZ", date(2026, 8, 26)),),
            request_details={"provider_fetch_kind": "tushare_daily_adj_factor_session_batch"},
            reference_snapshot=_empty_reference_snapshot(
                ("000001.SZ",), date(2026, 8, 26), date(2026, 8, 26)
            ),
        )

    assert caught.value.code == "MODEL_MARKET_AUDIT_SOURCE_TYPE_MISMATCH"
    assert "rollback" in uow.events
    assert writer.fetch[-1].outcome is AuditOutcome.FAILED


def test_model_history_store_count_mismatch_rolls_back_then_records_failure_audit() -> None:
    use_case, uow, writer, _facts, raw, _quality = _build([])

    class ShortFacts(_Facts):
        def bulk_upsert(self, bars: list[PriceBar]) -> int:
            assert self.active()
            self.events.append("facts")
            return len(bars) - 1

    events = uow.events
    short_facts = ShortFacts(events, lambda: uow.active)
    use_case._facts = short_facts

    with pytest.raises(DataFetchError) as caught:
        use_case.record_model_history_fetch_success(
            provider_id=1,
            asset_codes=("000001.SZ", "000002.SZ"),
            start_date=date(2026, 8, 26),
            end_date=date(2026, 8, 26),
            rows=(
                _model_bar("000001.SZ", date(2026, 8, 26)),
                _model_bar("000002.SZ", date(2026, 8, 26)),
            ),
            request_details={"provider_fetch_kind": "tushare_daily_adj_factor_session_batch"},
            reference_snapshot=_empty_reference_snapshot(
                ("000001.SZ", "000002.SZ"), date(2026, 8, 26), date(2026, 8, 26)
            ),
        )

    assert getattr(caught.value, "code", None) == "MODEL_MARKET_AUDIT_FACT_COUNT_MISMATCH"
    assert uow.events == [
        "begin",
        "reference_snapshot",
        "facts",
        "rollback",
        "begin",
        "health",
        "raw_audit",
        "fetch_event",
        "commit",
    ]
    assert len(raw.rows) == 1
    assert writer.fetch[0].outcome is AuditOutcome.FAILED


def test_model_history_validation_failure_audit_keeps_known_source_type() -> None:
    use_case, _uow, writer, facts, raw, _quality = _build([])

    with pytest.raises(DataFetchError) as caught:
        use_case.record_model_history_fetch_success(
            provider_id=1,
            asset_codes=("000001.SZ",),
            start_date=date(2026, 8, 26),
            end_date=date(2026, 8, 26),
            rows=(
                dataclasses.replace(_model_bar("000001.SZ", date(2026, 8, 26)), source="akshare"),
            ),
            request_details={"provider_fetch_kind": "tushare_daily_adj_factor_session_batch"},
            reference_snapshot=_empty_reference_snapshot(
                ("000001.SZ",), date(2026, 8, 26), date(2026, 8, 26)
            ),
        )

    assert caught.value.code == "MODEL_MARKET_INVALID"
    assert facts.saved == []
    assert len(raw.rows) == 1
    assert raw.rows[0].status == "error"
    assert raw.rows[0].extra == {"source_type": "tushare"}
    assert writer.fetch[0].outcome is AuditOutcome.FAILED


def test_model_history_reference_snapshot_drift_rolls_back_before_identity_or_fact_write() -> None:
    use_case, uow, writer, _facts, raw, _quality = _build([])

    class DriftingFacts(_Facts):
        def get_bars_for_assets(
            self,
            asset_codes: Sequence[str],
            start: date | None = None,
            end: date | None = None,
            limit: int = 5000,
        ) -> dict[str, tuple[PriceBar, ...]]:
            assert self.active()
            self.events.append("reference_snapshot")
            return {
                code: (
                    PriceBar(
                        asset_code=code,
                        bar_date=date(2026, 8, 26),
                        open=10.0,
                        high=11.0,
                        low=9.5,
                        close=10.5,
                        source="previous",
                    ),
                )
                for code in asset_codes
            }

    facts = DriftingFacts(uow.events, lambda: uow.active)
    use_case._facts = facts

    with pytest.raises(DataFetchError) as caught:
        use_case.record_model_history_fetch_success(
            provider_id=1,
            asset_codes=("000001.SZ",),
            start_date=date(2026, 8, 26),
            end_date=date(2026, 8, 26),
            rows=(_model_bar("000001.SZ", date(2026, 8, 26)),),
            request_details={"provider_fetch_kind": "tushare_daily_adj_factor_session_batch"},
            reference_snapshot=_empty_reference_snapshot(
                ("000001.SZ",), date(2026, 8, 26), date(2026, 8, 26)
            ),
        )

    assert caught.value.code == "MODEL_MARKET_REFERENCE_SNAPSHOT_CHANGED"
    assert facts.saved == []
    assert uow.events == [
        "begin",
        "reference_snapshot",
        "rollback",
        "begin",
        "health",
        "raw_audit",
        "fetch_event",
        "commit",
    ]
    assert len(raw.rows) == 1
    assert raw.rows[0].status == "error"
    assert raw.rows[0].extra == {"source_type": "tushare"}
    assert writer.fetch[0].outcome is AuditOutcome.FAILED


def test_model_history_audit_scope_hash_is_canonical_and_bounded_for_large_batches() -> None:
    codes = tuple(f"{value:06d}.SZ" for value in range(5000))
    details = {"provider_fetch_kind": "tushare_daily_adj_factor_session_batch"}
    build = SyncPriceUseCase._model_history_request_params

    forward = build(
        asset_codes=codes,
        start_date=date(2026, 8, 26),
        end_date=date(2026, 8, 26),
        request_details=details,
    )
    reverse = build(
        asset_codes=tuple(reversed(codes)),
        start_date=date(2026, 8, 26),
        end_date=date(2026, 8, 26),
        request_details=details,
    )
    changed_scope = build(
        asset_codes=(*codes[:-1], "999999.SZ"),
        start_date=date(2026, 8, 26),
        end_date=date(2026, 8, 26),
        request_details=details,
    )

    assert forward["asset_count"] == 5000
    assert forward["asset_codes_sha256"] == reverse["asset_codes_sha256"]
    assert forward["asset_codes_sha256"] != changed_scope["asset_codes_sha256"]
    assert "asset_codes" not in forward
    assert len(json.dumps(forward, separators=(",", ":"))) <= 512


def test_audit_writer_failure_rolls_back_and_is_not_hidden() -> None:
    use_case, uow, writer, _facts, _raw, quality_recorder = _build([_bar()])
    writer.fail = True

    with pytest.raises(RuntimeError, match="audit writer failure"):
        use_case.execute(_request())

    assert uow.active is False
    assert uow.events[-1] == "rollback"
    assert quality_recorder.calls == []


def test_publication_block_commits_blocked_publication_event_then_reraises() -> None:
    use_case, _uow, writer, _facts, _raw, quality_recorder = _build(
        [_bar()], publisher=_Publisher(error=ValueError("publication blocked"))
    )

    with pytest.raises(ValueError, match="publication blocked"):
        use_case.execute(_request())

    assert writer.publication[0].outcome is AuditOutcome.BLOCKED
    assert writer.publication[0].blocked_reason
    assert "publication blocked" not in str(writer.publication[0])
    assert quality_recorder.calls == []
