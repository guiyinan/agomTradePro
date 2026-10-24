"""Exercise one quote metric through its real persisted publication boundary.

The provider and exchange-calendar responses below are deterministic synthetic
transport fixtures.  The provider adapters, catalog repositories, quote
repository, p2 publication, public query gate, and realtime cache repository
remain the real implementations.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pandas as pd
import pytest
from django.core.cache import cache
from django.db import transaction
from django.test import override_settings

from apps.audit.application.system_audit_query import SystemAuditReaderContext
from apps.data_center import provider_runtime
from apps.data_center.application.current_market_publication_activation import (
    stage_and_activate_current_market_group,
)
from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStageRawAuditBinding,
)
from apps.data_center.application.interface_services import save_provider_settings_payload
from apps.data_center.application.market_calendar import (
    latest_completed_cn_market_session,
    load_cn_market_calendar_evidence,
)
from apps.data_center.application.query_services import (
    query_published_price_bar_series,
    query_published_quote_payloads,
    query_published_valuation_facts,
)
from apps.data_center.application.quote_metric_normalization import (
    normalize_quote_snapshot_change_pct,
)
from apps.data_center.domain.contracts import (
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    PublicationPolicy,
    QuoteMetricSourceContract,
)
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationMember
from apps.data_center.domain.entities import (
    ProviderConfig,
    QuoteChangePctEvidence,
    QuoteSnapshot,
    RawAudit,
    ValuationFact,
)
from apps.data_center.domain.market_time import (
    CN_MARKET_TIMEZONE,
    cn_market_session_close_utc,
)
from apps.data_center.infrastructure._provider_adapter_tushare import (
    TushareUnifiedProviderAdapter,
)
from apps.data_center.infrastructure.candidate_raw_audit_manifest_repository import (
    DjangoCandidateRawAuditManifestRepository,
)
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    DatasetContractRepository,
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.gateways.tushare_gateway import TushareGateway
from apps.data_center.infrastructure.models import (
    PriceBarModel,
    ProviderConfigModel,
    QuoteSnapshotModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.publication_models import CanonicalPublicationPointerModel
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
)
from apps.data_center.infrastructure.quote_snapshot_repository import QuoteSnapshotRepository
from apps.data_center.infrastructure.tushare_client import (
    TushareResponseEvidence,
    _provider_frame,
)
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository
from apps.data_center.publication_candidate_activation_composition import (
    build_production_current_market_publication_bundle,
)
from apps.realtime.domain.entities import AssetType
from apps.realtime.infrastructure.publication_price_cache import (
    published_data_center_price,
)
from apps.realtime.infrastructure.repositories import RedisRealtimePriceRepository
from tests.component.data_center.test_publication_activation import (
    _AuthorityFence,
    _FenceResult,
    _GroupAuditWriter,
)
from tests.support.runtime_config import configure_critical_runtime

_ASSET_CODE = "000001.SZ"
_DATASET_KEY = "equity.quote.snapshot"
_PRICE_DATASET_KEY = "equity.price.bar"
_VALUATION_DATASET_KEY = "equity.valuation.fact"
_CONTRACT_VERSION = "2.0"
_SCHEMA_VERSION = "2.0"
_CALENDAR_PROVIDER_NAME = "quote-metric-calendar-fixture"
_QUOTE_PROVIDER_NAME = "quote-metric-tushare-fixture"
_QUOTE_SOURCE = "tushare"
_PRICE_SOURCE = "tushare"
_VALUATION_SOURCE = "tencent"


def _source_contract(*, action_basis: str) -> QuoteMetricSourceContract:
    """Return a test-only interpretation; it makes no claim about Tushare semantics."""

    return QuoteMetricSourceContract(
        provider_source=_QUOTE_SOURCE,
        source_field="pct_chg",
        origin="vendor_reported",
        source_unit="fixture_hundredth_percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=100,
        reference_session="source_quote_observation",
        action_basis=action_basis,
    )


def _dataset_contract(
    *,
    contract_version: str,
    schema_version: str,
    action_basis: str,
) -> DatasetContract:
    """Build a persisted fixture contract matching the existing quote schema."""

    return DatasetContract(
        key=DatasetKey(_DATASET_KEY, contract_version, schema_version),
        owner="pytest.quote-metric-fixture",
        frequency="intraday",
        decision_critical=True,
        # The fixture calendar excludes the current day, so a weekend run's
        # latest synthetic session is Friday and must still pass the real gate.
        freshness_seconds=7 * 24 * 60 * 60,
        fields=(
            DatasetFieldContract(
                name="snapshot_at",
                value_type="datetime",
                unit=None,
                nullable=False,
                zero_allowed=False,
            ),
            DatasetFieldContract(
                name="current_price",
                value_type="decimal",
                unit="CNY",
                nullable=False,
                zero_allowed=False,
            ),
            DatasetFieldContract(
                name="fetched_at",
                value_type="datetime",
                unit=None,
                nullable=False,
                zero_allowed=False,
            ),
            DatasetFieldContract(
                name="change_pct",
                value_type="decimal",
                unit="percent",
                nullable=True,
                zero_allowed=True,
                source_contracts=(_source_contract(action_basis=action_basis),),
            ),
        ),
    )


def _publication_policy(dataset: DatasetKey) -> PublicationPolicy:
    """Return the fixture's exact p2 evidence requirements for one dataset."""

    if dataset.value == _DATASET_KEY:
        required_evidence = (
            "source",
            "observed_at",
            "fetched_at",
            "source_record_id",
            "raw_payload_hash",
            "raw_payload_scope",
            "fact_content_hash",
        )
    elif dataset.value == _PRICE_DATASET_KEY:
        # PriceBarModel has no raw_payload_scope field, so require its stored
        # payload digest through the compatible payload_hash evidence key.
        required_evidence = (
            "source",
            "observed_at",
            "fetched_at",
            "source_record_id",
            "payload_hash",
            "fact_content_hash",
        )
    elif dataset.value == _VALUATION_DATASET_KEY:
        required_evidence = (
            "source",
            "observed_at",
            "available_at",
            "fetched_at",
            "source_record_id",
            "raw_payload_hash",
            "raw_payload_scope",
            "fact_content_hash",
        )
    else:
        raise ValueError(f"No quote metric fixture policy for {dataset.value}")

    return PublicationPolicy(
        dataset=dataset,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=required_evidence,
        retention_days=3650,
        policy_version="2",
    )


def _other_dataset_contract(
    *,
    dataset_key: str,
    contract_version: str,
    schema_version: str,
) -> DatasetContract:
    """Build one small daily contract for the synthetic price/valuation rows."""

    if dataset_key == _PRICE_DATASET_KEY:
        fields = (
            DatasetFieldContract(
                name="bar_date",
                value_type="date",
                unit=None,
                nullable=False,
                zero_allowed=False,
            ),
            DatasetFieldContract(
                name="close",
                value_type="decimal",
                unit="CNY",
                nullable=False,
                zero_allowed=False,
            ),
        )
    elif dataset_key == _VALUATION_DATASET_KEY:
        fields = (
            DatasetFieldContract(
                name="val_date",
                value_type="date",
                unit=None,
                nullable=False,
                zero_allowed=False,
            ),
            DatasetFieldContract(
                name="pe_ttm",
                value_type="decimal",
                unit=None,
                nullable=True,
                zero_allowed=False,
            ),
        )
    else:
        raise ValueError(f"Unsupported fixture dataset {dataset_key}")

    return DatasetContract(
        key=DatasetKey(dataset_key, contract_version, schema_version),
        owner="pytest.quote-metric-current-fixture",
        frequency="daily",
        decision_critical=True,
        freshness_seconds=7 * 24 * 60 * 60,
        fields=fields,
    )


def _fixture_payload_identity(payload: dict[str, object]) -> tuple[str, int]:
    """Hash deterministic synthetic transport bytes without claiming a vendor body."""

    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest(), len(body)


def _log_fixture_audit(
    *,
    provider_name: str,
    capability: str,
    asset_code: str,
    source_type: str,
    response_hash: str,
    payload_size_bytes: int,
    fetched_at: datetime,
    ingested_run_id: str,
    extra: dict[str, object],
) -> RawAudit:
    """Persist one synthetic source audit through the real RawAudit repository."""

    audit_extra = {"source_type": source_type, **extra}
    return RawAuditRepository().log(
        RawAudit(
            provider_name=provider_name,
            capability=capability,
            request_params={"asset_code": asset_code},
            status="ok",
            row_count=1,
            fetched_at=fetched_at,
            extra=audit_extra,
            response_payload_hash=response_hash,
            schema_fingerprint=hashlib.sha256(
                f"synthetic-schema:{capability}:v1".encode()
            ).hexdigest(),
            parser_version="quote-metric-current-fixture-v1",
            payload_size_bytes=payload_size_bytes,
            run_id=str(uuid4()),
            ingested_run_id=ingested_run_id,
        )
    )


def _reader_context() -> SystemAuditReaderContext:
    """Build the capability-shaped context required by the test authority seam."""

    now = datetime.now(UTC)
    return SystemAuditReaderContext._from_authority(
        authority_source_id="fixture:authority",
        authority_source_version="1",
        actor_id="fixture:operator",
        user_id=7,
        tenant_id="fixture-tenant",
        owner_id="fixture-owner",
        authority_content_hash="a" * 64,
        is_authenticated=True,
        is_staff=True,
        role="admin",
        authority_state="active",
        authority_recorded_at=now - timedelta(minutes=1),
        authority_valid_until=now + timedelta(hours=1),
    )


class _RecordingAuthorityFence(_AuthorityFence):
    """Retain the existing test fence result so its lease is asserted explicitly."""

    def __init__(self) -> None:
        self.last_lease: _FenceResult | None = None

    @contextmanager
    def fence_complete(self, proof: object) -> Iterator[_FenceResult]:
        with super().fence_complete(proof) as lease:
            self.last_lease = lease
            yield lease


@dataclass(frozen=True)
class _TestAuthorityCapture:
    """Test-only authority seam passed to the real activation use case."""

    database_alias: str
    authority_fence: _RecordingAuthorityFence
    authority_proof: object


@dataclass(frozen=True)
class _CycleFacts:
    """Persisted source rows and exact audit references for one group revision."""

    quote: QuoteSnapshot
    quote_fact: QuoteSnapshotModel
    price_fact: PriceBarModel
    valuation_fact: ValuationFactModel
    raw_audits: tuple[RawAudit, RawAudit, RawAudit]
    quote_payload_hash: str
    quote_response_completed_at: datetime


def _synthetic_tushare_frame(
    *,
    observed_session: date,
    raw_change_pct: str,
    response_completed_at: datetime,
) -> tuple[object, str, int]:
    """Create a witnessed frame and hash the exact serialized fixture bytes."""

    columns = [
        "ts_code",
        "trade_date",
        "close",
        "pre_close",
        "pct_chg",
        "vol",
        "amount",
    ]
    row = {
        "ts_code": _ASSET_CODE,
        "trade_date": observed_session.strftime("%Y%m%d"),
        "close": "12.3400",
        "pre_close": "12.0000",
        "pct_chg": raw_change_pct,
        "vol": "100",
        "amount": "123.45",
    }
    fixture_body = json.dumps(
        {"rows": [row]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    raw_payload_hash = hashlib.sha256(fixture_body).hexdigest()
    evidence = TushareResponseEvidence(
        body_sha256=raw_payload_hash,
        response_completed_at=response_completed_at,
    )
    return (
        _provider_frame(
            [[row[column] for column in columns]],
            columns,
            None,
            evidence,
        ),
        raw_payload_hash,
        len(fixture_body),
    )


def _weekday_calendar_fixture(
    start: date,
    end: date,
    *,
    excluded_sessions: frozenset[date] = frozenset(),
) -> pd.DataFrame:
    """Provide a bounded test calendar with a stable latest-completed session."""

    cursor = start - timedelta(days=7)
    final = end + timedelta(days=7)
    days: list[str] = []
    while cursor <= final:
        if cursor.weekday() < 5 and cursor not in excluded_sessions:
            days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return pd.DataFrame({"trade_date": days})


@pytest.mark.django_db(
    transaction=True,
    available_apps=["apps.data_center", "apps.audit"],
)
def test_quote_metric_roundtrips_through_atomic_current_group_and_realtime_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise three real current-market stagers and atomic group activation.

    The one asset is the complete synthetic fixture universe for this isolated
    component test. Calendar rows and non-quote source rows are explicit
    synthetic fixtures; no statutory holiday or production authority claim is
    made. Only provider transport, Audit writer, and authority capture are seams.
    """

    from apps.data_center.infrastructure import _provider_adapter_akshare

    configure_critical_runtime()
    save_provider_settings_payload(
        default_source="akshare",
        enable_failover=False,
        failover_tolerance=0.01,
        actor="pytest.quote-metric-current-fixture",
    )
    ProviderConfigModel._default_manager.create(
        name=_CALENDAR_PROVIDER_NAME,
        source_type="akshare",
        is_active=True,
        priority=1,
        extra_config={},
    )

    local_today = datetime.now(UTC).astimezone(CN_MARKET_TIMEZONE).date()
    calendar_start = local_today - timedelta(days=45)

    class _CalendarTransport:
        def tool_trade_date_hist_sina(self) -> pd.DataFrame:
            """Return explicit synthetic weekdays for the market-session lookup."""

            # Exclude the current cutoff so this weekday fixture is stable during
            # market hours; it does not represent statutory exchange holidays.
            return _weekday_calendar_fixture(
                calendar_start,
                local_today,
                excluded_sessions=frozenset({local_today, local_today + timedelta(days=1)}),
            )

    calendar_transport = _CalendarTransport()
    monkeypatch.setattr(
        _provider_adapter_akshare,
        "get_akshare_module",
        lambda: calendar_transport,
    )
    provider_runtime.reset_registry()
    load_cn_market_calendar_evidence.cache_clear()
    try:
        calendar_evidence = load_cn_market_calendar_evidence(calendar_start, local_today)
        target_session = latest_completed_cn_market_session(datetime.now(UTC))
        assert calendar_evidence.source == "akshare"
        assert calendar_evidence.coverage_start == calendar_start
        assert calendar_evidence.coverage_end == local_today
        assert target_session is not None
        assert target_session in calendar_evidence.open_sessions

        quote_config = ProviderConfig(
            id=91_704,
            name=_QUOTE_PROVIDER_NAME,
            source_type="tushare",
            is_active=True,
            priority=1,
            api_key="fixture-only",
            api_secret="",
            http_url="",
            api_endpoint="",
            extra_config={},
            description="synthetic transport fixture; not an active provider seed",
        )
        adapter = TushareUnifiedProviderAdapter(quote_config)
        frame_state: dict[str, object] = {}

        def create_provider_client(_gateway: TushareGateway) -> object:
            """Replace only the external Tushare transport."""

            frame = frame_state["frame"]
            return SimpleNamespace(daily=lambda **_kwargs: frame)

        monkeypatch.setattr(TushareGateway, "_create_client", create_provider_client)

        dataset_contract_repository = DatasetContractRepository()
        publication_policy_repository = PublicationPolicyRepository()
        for dataset_key in (_DATASET_KEY, _PRICE_DATASET_KEY, _VALUATION_DATASET_KEY):
            DatasetContractModel._default_manager.filter(dataset_key=dataset_key).delete()
            DatasetPublicationPolicyModel._default_manager.filter(dataset_key=dataset_key).delete()

        quote_contract_v2 = _dataset_contract(
            contract_version="2.0",
            schema_version="2.0",
            action_basis="test_fixture_action_basis_v1",
        )
        price_contract = _other_dataset_contract(
            dataset_key=_PRICE_DATASET_KEY,
            contract_version="1.0",
            schema_version="1.0",
        )
        valuation_contract = _other_dataset_contract(
            dataset_key=_VALUATION_DATASET_KEY,
            contract_version="1.0",
            schema_version="1.0",
        )
        quote_policy_v2 = _publication_policy(quote_contract_v2.key)
        price_policy = _publication_policy(price_contract.key)
        valuation_policy = _publication_policy(valuation_contract.key)
        for contract in (quote_contract_v2, price_contract, valuation_contract):
            dataset_contract_repository.save(contract)
        for policy in (quote_policy_v2, price_policy, valuation_policy):
            publication_policy_repository.save(policy)
        assert dataset_contract_repository.get_active(_DATASET_KEY) == quote_contract_v2

        quote_repository = QuoteSnapshotRepository()
        valuation_repository = ValuationFactRepository()
        publication_repository = CanonicalPublicationRepository()
        manifest_repository = DjangoCandidateRawAuditManifestRepository()
        group_writers: list[_GroupAuditWriter] = []
        authority_captures: list[_TestAuthorityCapture] = []

        def make_group_audit_writer() -> _GroupAuditWriter:
            """Use the existing test writer, which persists actual Audit/outbox rows."""

            writer = _GroupAuditWriter()
            group_writers.append(writer)
            return writer

        reader_context = _reader_context()

        def capture_test_authority(
            *,
            as_of: datetime,
            preflight_context: SystemAuditReaderContext,
        ) -> _TestAuthorityCapture:
            """Inject only the explicitly test-only authority capture seam."""

            assert as_of.tzinfo is not None and as_of.utcoffset() is not None
            assert preflight_context is reader_context
            capture = _TestAuthorityCapture(
                database_alias="default",
                authority_fence=_RecordingAuthorityFence(),
                authority_proof="proof",
            )
            authority_captures.append(capture)
            return capture

        production_bundle = build_production_current_market_publication_bundle()
        bundle = replace(
            production_bundle,
            audit_writer_factory=make_group_audit_writer,
            authority_capture=capture_test_authority,
        )

        def fetch_normalized_quote(
            raw_change_pct: str,
            *,
            ingested_run_id: str,
            contract: DatasetContract,
        ) -> tuple[QuoteSnapshot, str, int, datetime]:
            """Use the real Tushare adapter and catalog-backed metric normalizer."""

            response_completed_at = datetime.now(UTC)
            frame, fixture_hash, fixture_size = _synthetic_tushare_frame(
                observed_session=target_session,
                raw_change_pct=raw_change_pct,
                response_completed_at=response_completed_at,
            )
            frame_state["frame"] = frame
            provider_quotes = adapter.fetch_quote_snapshots_for_session(
                [_ASSET_CODE],
                target_session,
            )
            assert len(provider_quotes) == 1
            provider_quote = provider_quotes[0]
            assert provider_quote.snapshot_at == cn_market_session_close_utc(target_session)
            assert provider_quote.fetched_at == response_completed_at
            assert provider_quote.change_pct_candidate is not None
            assert provider_quote.change_pct_candidate.raw_value == raw_change_pct
            assert provider_quote.change_pct_candidate.source_field == "pct_chg"
            assert provider_quote.change_pct_candidate.provider_source == _QUOTE_SOURCE
            assert provider_quote.extra.get("actual_source") == _QUOTE_SOURCE
            assert provider_quote.source == adapter.provider_source()
            assert adapter.provider_name() == _QUOTE_PROVIDER_NAME
            assert provider_quote.extra.get("provider_name") == _QUOTE_PROVIDER_NAME
            assert isinstance(provider_quote.extra.get("source_record_id"), str)
            assert provider_quote.extra.get("source_record_id")
            assert provider_quote.extra.get("raw_payload_hash") == fixture_hash
            assert provider_quote.extra.get("raw_payload_scope") == "batch_response_body"

            normalized = normalize_quote_snapshot_change_pct(provider_quote, contract)
            assert normalized.change_pct is not None
            assert normalized.change_pct_candidate is None
            assert normalized.change_pct_evidence is not None
            assert normalized.change_pct_evidence.source_value == raw_change_pct
            assert normalized.change_pct_evidence.source_contract.source_field == "pct_chg"
            return (
                replace(normalized, ingested_run_id=ingested_run_id),
                fixture_hash,
                fixture_size,
                response_completed_at,
            )

        def persist_cycle_facts(
            cycle_number: int,
            raw_change_pct: str,
            contract: DatasetContract,
        ) -> _CycleFacts:
            """Write three exact synthetic facts and audits before any fact upsert."""

            quote_ingested_run_id = str(uuid4())
            price_ingested_run_id = str(uuid4())
            valuation_ingested_run_id = str(uuid4())
            quote, quote_hash, quote_payload_size, fetched_at = fetch_normalized_quote(
                raw_change_pct,
                ingested_run_id=quote_ingested_run_id,
                contract=contract,
            )
            quote_source_record_id = quote.extra.get("source_record_id")
            assert isinstance(quote_source_record_id, str) and quote_source_record_id
            assert quote.change_pct_candidate is None
            assert quote.change_pct_evidence is not None
            quote_change_pct_evidence = quote.change_pct_evidence
            assert quote_change_pct_evidence.source_value == raw_change_pct

            observed_at = cn_market_session_close_utc(target_session)
            # This is an explicit synthetic source-availability field from the
            # fixture; fetched_at remains the witnessed response completion time.
            valuation_available_at = observed_at + timedelta(minutes=30)
            price_record_id = (
                f"synthetic-price:{_ASSET_CODE}:{target_session.isoformat()}:{cycle_number}"
            )
            price_payload: dict[str, object] = {
                "asset_code": _ASSET_CODE,
                "bar_date": target_session.isoformat(),
                "source": _PRICE_SOURCE,
                "source_record_id": price_record_id,
                "open": "12.1000",
                "high": "12.5000",
                "low": "11.9000",
                "close": "12.3400",
                "volume": "100.00",
                "amount": "1234.50",
                "fixture_cycle": str(cycle_number),
            }
            price_hash, price_payload_size = _fixture_payload_identity(price_payload)

            valuation_record_id = (
                f"synthetic-valuation:{_ASSET_CODE}:{target_session.isoformat()}:{cycle_number}"
            )
            valuation_pe = 18.0 + cycle_number / 100
            valuation_payload: dict[str, object] = {
                "asset_code": _ASSET_CODE,
                "val_date": target_session.isoformat(),
                "source": _VALUATION_SOURCE,
                "source_record_id": valuation_record_id,
                "observed_at": observed_at.isoformat(),
                "available_at": valuation_available_at.isoformat(),
                "pe_ttm": f"{valuation_pe:.2f}",
                "fixture_cycle": str(cycle_number),
            }
            valuation_hash, valuation_payload_size = _fixture_payload_identity(valuation_payload)

            # Each exact RawAudit is durable before any of the three fact upserts.
            quote_audit = _log_fixture_audit(
                provider_name=adapter.provider_name(),
                capability="realtime_quote",
                asset_code=_ASSET_CODE,
                source_type=quote.source,
                response_hash=quote_hash,
                payload_size_bytes=quote_payload_size,
                fetched_at=fetched_at,
                ingested_run_id=quote_ingested_run_id,
                extra={
                    "actual_source": _QUOTE_SOURCE,
                    "provider_source": quote_change_pct_evidence.source_contract.provider_source,
                    "source_record_id": quote_source_record_id,
                    "raw_payload_scope": "batch_response_body",
                },
            )
            price_audit = _log_fixture_audit(
                provider_name=_PRICE_SOURCE,
                capability="historical_price",
                asset_code=_ASSET_CODE,
                source_type=_PRICE_SOURCE,
                response_hash=price_hash,
                payload_size_bytes=price_payload_size,
                fetched_at=fetched_at,
                ingested_run_id=price_ingested_run_id,
                extra={"source_record_id": price_record_id},
            )
            valuation_audit = _log_fixture_audit(
                provider_name=_VALUATION_SOURCE,
                capability="valuation",
                asset_code=_ASSET_CODE,
                source_type=_VALUATION_SOURCE,
                response_hash=valuation_hash,
                payload_size_bytes=valuation_payload_size,
                fetched_at=fetched_at,
                ingested_run_id=valuation_ingested_run_id,
                extra={"source_record_id": valuation_record_id},
            )
            raw_audits = (quote_audit, price_audit, valuation_audit)
            assert quote_audit.provider_name == _QUOTE_PROVIDER_NAME
            assert quote_audit.extra["source_type"] == quote.source
            assert quote_audit.extra["actual_source"] == _QUOTE_SOURCE
            assert quote_audit.extra["provider_source"] == (
                quote_change_pct_evidence.source_contract.provider_source
            )
            assert len({audit.raw_audit_id for audit in raw_audits}) == 3
            assert len({audit.run_id for audit in raw_audits}) == 3
            assert len({audit.ingested_run_id for audit in raw_audits}) == 3
            assert quote_audit.ingested_run_id == quote_ingested_run_id
            assert price_audit.ingested_run_id == price_ingested_run_id
            assert valuation_audit.ingested_run_id == valuation_ingested_run_id
            assert all(audit.status == "ok" and audit.row_count == 1 for audit in raw_audits)

            assert quote_repository.bulk_upsert([quote]) == 1
            quote_fact = (
                QuoteSnapshotModel._default_manager.filter(
                    asset_code=_ASSET_CODE,
                    snapshot_at=quote.snapshot_at,
                    source=quote.source,
                )
                .order_by("-revision_number", "-pk")
                .first()
            )
            assert quote_fact is not None
            assert quote_fact.revision_number == cycle_number
            assert quote_fact.ingested_run_id == UUID(quote_ingested_run_id)
            assert quote_fact.source_record_id == quote_source_record_id
            assert quote_fact.raw_payload_hash == quote_hash
            assert quote_fact.change_pct == quote.change_pct
            assert quote_fact.contract_version == contract.key.contract_version
            assert quote_fact.schema_version == contract.key.schema_version

            created_price = PriceBarModel._default_manager.create(
                asset_code=_ASSET_CODE,
                bar_date=target_session,
                freq="1d",
                adjustment="none",
                open=Decimal("12.1000"),
                high=Decimal("12.5000"),
                low=Decimal("11.9000"),
                close=Decimal("12.3400"),
                volume=Decimal("100.00"),
                amount=Decimal("1234.50"),
                source=_PRICE_SOURCE,
                contract_version=price_contract.key.contract_version,
                schema_version=price_contract.key.schema_version,
                source_record_id=price_record_id,
                raw_payload_hash=price_hash,
                quality_status="accepted",
                revision_number=cycle_number,
                ingested_run_id=UUID(price_ingested_run_id),
            )
            PriceBarModel._default_manager.filter(pk=created_price.pk).update(fetched_at=fetched_at)
            price_fact = PriceBarModel._default_manager.get(pk=created_price.pk)
            assert price_fact.fetched_at == fetched_at
            assert price_fact.source_record_id == price_record_id
            assert price_fact.raw_payload_hash == price_hash
            assert price_fact.quality_status == "accepted"
            assert price_fact.revision_number == cycle_number
            assert price_fact.ingested_run_id == UUID(price_ingested_run_id)

            valuation_fact_input = ValuationFact(
                asset_code=_ASSET_CODE,
                val_date=target_session,
                pe_ttm=valuation_pe,
                pb=1.35,
                source=_VALUATION_SOURCE,
                available_at=valuation_available_at,
                fetched_at=fetched_at,
                extra={"raw_payload_scope": "batch_response_body"},
                observed_at=observed_at,
                source_record_id=valuation_record_id,
                raw_payload_hash=valuation_hash,
                ingested_run_id=valuation_ingested_run_id,
            )
            assert valuation_repository.bulk_upsert([valuation_fact_input]) == 1
            valuation_fact = (
                ValuationFactModel._default_manager.filter(
                    asset_code=_ASSET_CODE,
                    val_date=target_session,
                    source=_VALUATION_SOURCE,
                )
                .order_by("-revision_number", "-pk")
                .first()
            )
            assert valuation_fact is not None
            assert valuation_fact.available_at == valuation_available_at
            assert valuation_fact.observed_at == observed_at
            assert valuation_fact.fetched_at == fetched_at
            assert valuation_fact.source_record_id == valuation_record_id
            assert valuation_fact.raw_payload_hash == valuation_hash
            assert valuation_fact.quality_status == "accepted"
            assert valuation_fact.revision_number == cycle_number
            assert valuation_fact.ingested_run_id == UUID(valuation_ingested_run_id)
            assert valuation_fact.extra["raw_payload_scope"] == "batch_response_body"

            return _CycleFacts(
                quote=quote,
                quote_fact=quote_fact,
                price_fact=price_fact,
                valuation_fact=valuation_fact,
                raw_audits=raw_audits,
                quote_payload_hash=quote_hash,
                quote_response_completed_at=fetched_at,
            )

        def current_public_quote() -> tuple[dict[str, object], dict[str, object]]:
            """Read one current quote through the real publication gate."""

            payload = query_published_quote_payloads(
                [_ASSET_CODE],
                publication_key="current",
            )
            assert payload.get("must_not_use_for_decision") is False
            rows = payload.get("rows")
            assert isinstance(rows, list) and len(rows) == 1
            row = rows[0]
            assert isinstance(row, dict)
            return payload, row

        def assert_authority_seam(capture: _TestAuthorityCapture) -> None:
            """Assert the fixture proof and the existing real-transaction test fence."""

            assert capture.database_alias == "default"
            assert capture.authority_proof == "proof"
            lease = capture.authority_fence.last_lease
            assert lease is not None
            assert lease.scope == "account_authority_complete_graph"
            assert lease.database_alias == "default"
            assert lease.tenant_id == "tenant-1"
            assert lease.owner_id == "owner-1"
            assert lease.generation > 0
            assert len(lease.fingerprint.complete_graph_hash) == 64
            assert lease.checked_at.tzinfo is not None
            assert lease.valid_until.tzinfo is not None
            assert lease.checked_at < lease.valid_until

        def evidence_hash(evidence: QuoteChangePctEvidence) -> str:
            encoded = json.dumps(
                evidence.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            return hashlib.sha256(encoded).hexdigest()

        current_published: dict[str, CanonicalPublication] = {}
        current_members: dict[str, tuple[PublicationMember, ...]] = {}
        current_published_before_activation: dict[str, CanonicalPublication] = {}
        current_members_before_activation: dict[str, tuple[PublicationMember, ...]] = {}
        previous_cycle: _CycleFacts | None = None
        previous_group_published_at: datetime | None = None
        realtime_repository = RedisRealtimePriceRepository()

        with override_settings(
            CACHES={
                "default": {
                    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                    "LOCATION": "ash04-quote-metric-current-group",
                }
            }
        ):
            cache.clear()
            scenarios = (
                (
                    "0",
                    Decimal("0"),
                    quote_contract_v2,
                    "test_fixture_action_basis_v1",
                ),
                (
                    "123.4567891234",
                    Decimal("1.234567891234"),
                    quote_contract_v2,
                    "test_fixture_action_basis_v1",
                ),
                (
                    "123.4567891234",
                    Decimal("1.234567891234"),
                    _dataset_contract(
                        contract_version="3.0",
                        schema_version="3.0",
                        action_basis="test_fixture_action_basis_v2",
                    ),
                    "test_fixture_action_basis_v2",
                ),
            )

            for cycle_number, (
                raw_change_pct,
                expected_metric,
                quote_contract,
                action_basis,
            ) in enumerate(scenarios, start=1):
                if cycle_number == 3:
                    same_version_mutation = _dataset_contract(
                        contract_version="2.0",
                        schema_version="2.0",
                        action_basis="test_fixture_action_basis_v2",
                    )
                    with pytest.raises(ValueError):
                        dataset_contract_repository.save(same_version_mutation)
                    assert dataset_contract_repository.get_active(_DATASET_KEY) == quote_contract_v2
                    assert publication_policy_repository.get_active(_DATASET_KEY) == quote_policy_v2

                cycle = persist_cycle_facts(
                    cycle_number,
                    raw_change_pct,
                    quote_contract,
                )
                assert cycle.quote.change_pct == expected_metric
                assert cycle.quote.change_pct_evidence is not None
                assert cycle.quote.change_pct_evidence.source_contract.action_basis == action_basis
                assert cycle.quote_fact.source == cycle.quote.source
                assert cycle.quote_fact.contract_version == (quote_contract.key.contract_version)
                assert cycle.quote_fact.schema_version == quote_contract.key.schema_version

                if previous_cycle is not None:
                    old_quote_payload, old_quote_row = current_public_quote()
                    old_quote_publication = current_published[_DATASET_KEY]
                    assert old_quote_payload.get("publication_id") == (
                        old_quote_publication.publication_id
                    )
                    assert Decimal(str(old_quote_row["change_pct"])) == (
                        previous_cycle.quote.change_pct
                    )
                    old_evidence = previous_cycle.quote.change_pct_evidence
                    assert old_evidence is not None
                    old_source_evidence = QuoteChangePctEvidence.from_payload(
                        old_quote_row["change_pct_source_contract"]
                    )
                    assert old_source_evidence == old_evidence
                    assert (
                        old_quote_row["fetched_at"]
                        == previous_cycle.quote_response_completed_at.isoformat()
                    )
                    assert old_quote_row["contract_version"] == (
                        previous_cycle.quote.contract_version
                    )
                    assert old_quote_row["schema_version"] == (previous_cycle.quote.schema_version)
                    assert old_quote_row["source"] == previous_cycle.quote_fact.source

                    old_price_payload = query_published_price_bar_series(
                        _ASSET_CODE,
                        publication_key="current",
                        start=target_session,
                        end=target_session,
                    )
                    old_valuation_payload = query_published_valuation_facts(
                        _ASSET_CODE,
                        publication_key="current",
                        as_of=target_session,
                    )
                    for dataset_key, payload in (
                        (_PRICE_DATASET_KEY, old_price_payload),
                        (_VALUATION_DATASET_KEY, old_valuation_payload),
                    ):
                        assert payload.get("must_not_use_for_decision") is False
                        assert payload.get("publication_id") == (
                            current_published[dataset_key].publication_id
                        )
                    for dataset_key, publication in current_published.items():
                        assert (
                            publication_repository.get_current(
                                dataset_key,
                                "current",
                            )
                            == publication
                        )
                        assert (
                            tuple(publication_repository.list_members(publication.publication_id))
                            == current_members[dataset_key]
                        )

                    old_cache = realtime_repository.get_latest_price(_ASSET_CODE)
                    assert old_cache is not None
                    assert old_cache.publication_id == old_quote_publication.publication_id
                    assert old_cache.change_pct == previous_cycle.quote.change_pct
                    assert old_cache.change_pct_evidence_hash == evidence_hash(old_evidence)

                raw_audit_by_dataset = dict(
                    zip(
                        (_DATASET_KEY, _PRICE_DATASET_KEY, _VALUATION_DATASET_KEY),
                        cycle.raw_audits,
                        strict=True,
                    )
                )
                expected_source_by_dataset = {
                    _DATASET_KEY: cycle.quote.source,
                    _PRICE_DATASET_KEY: _PRICE_SOURCE,
                    _VALUATION_DATASET_KEY: _VALUATION_SOURCE,
                }
                bindings_by_dataset = {
                    dataset_key: (
                        CurrentPublicationStageRawAuditBinding(
                            reference=raw_audit.exact_reference(),
                            expected_source_type=expected_source_by_dataset[dataset_key],
                        ),
                    )
                    for dataset_key, raw_audit in raw_audit_by_dataset.items()
                }
                assert set(bindings_by_dataset) == {
                    _DATASET_KEY,
                    _PRICE_DATASET_KEY,
                    _VALUATION_DATASET_KEY,
                }
                for dataset_key, raw_audit in raw_audit_by_dataset.items():
                    assert raw_audit.extra["source_type"] == (
                        expected_source_by_dataset[dataset_key]
                    )
                    assert raw_audit.run_id
                    assert raw_audit.ingested_run_id
                    assert raw_audit.run_id != raw_audit.ingested_run_id

                published_at = datetime.now(UTC)
                if (
                    previous_group_published_at is not None
                    and published_at <= previous_group_published_at
                ):
                    published_at = previous_group_published_at + timedelta(microseconds=1)
                group_run_id = str(uuid4())
                task_attempt_id = f"quote-metric-current-group-{cycle_number}"
                if cycle_number == 3:
                    # Keep the quote contract and its p2 policy update atomic.
                    # Group activation owns its own outermost fenced transaction
                    # and must start after this bounded catalog transaction ends.
                    with transaction.atomic():
                        quote_contract_v3 = quote_contract
                        assert quote_contract_v3.key.contract_version == "3.0"
                        assert quote_contract_v3.key.schema_version == "3.0"
                        dataset_contract_repository.save(quote_contract_v3)
                        quote_policy_v3 = _publication_policy(quote_contract_v3.key)
                        publication_policy_repository.save(quote_policy_v3)
                        assert (
                            dataset_contract_repository.get_active(_DATASET_KEY)
                            == quote_contract_v3
                        )
                        assert (
                            publication_policy_repository.get_active(_DATASET_KEY)
                            == quote_policy_v3
                        )

                activation_result = stage_and_activate_current_market_group(
                    bundle=bundle,
                    asset_codes=[_ASSET_CODE],
                    published_at=published_at,
                    run_id=group_run_id,
                    task_attempt_id=task_attempt_id,
                    required_observation_date=target_session,
                    scope_exclusions_by_dataset={},
                    raw_audit_bindings_by_dataset=bindings_by_dataset,
                    preflight_context=reader_context,
                )

                assert activation_result.covered_asset_count == 1
                activated_by_dataset = {
                    publication.dataset_key: publication
                    for publication in activation_result.publications
                }
                assert set(activated_by_dataset) == {
                    _DATASET_KEY,
                    _PRICE_DATASET_KEY,
                    _VALUATION_DATASET_KEY,
                }
                assert len(group_writers) == cycle_number
                writer = group_writers[-1]
                assert len(writer.manifest_calls) == 3
                assert len(set(writer.manifest_calls)) == 3
                assert len(authority_captures) == cycle_number
                assert_authority_seam(authority_captures[-1])

                activation_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"agomtradepro:current-market-activation:{group_run_id}",
                    )
                )
                active_quote_policy = publication_policy_repository.get_active(_DATASET_KEY)
                assert active_quote_policy is not None
                policies_by_dataset = {
                    _DATASET_KEY: active_quote_policy,
                    _PRICE_DATASET_KEY: price_policy,
                    _VALUATION_DATASET_KEY: valuation_policy,
                }
                for dataset_key, publication in activated_by_dataset.items():
                    assert publication.state.value == "published"
                    assert publication.published_at is not None
                    assert publication.run_id == group_run_id
                    assert publication.publication_key == "current"
                    assert publication.policy_version == (policies_by_dataset[dataset_key].identity)
                    assert publication.policy_version.startswith("p2:")
                    assert publication.member_count == 1

                    current = publication_repository.get_current(dataset_key, "current")
                    assert current == publication
                    pointer = CanonicalPublicationPointerModel._default_manager.get(
                        dataset_key=dataset_key,
                        publication_key="current",
                    )
                    assert str(pointer.publication_id) == publication.publication_id
                    assert pointer.publication_hash == publication.publication_hash
                    assert pointer.activation_id == activation_id

                    members = tuple(publication_repository.list_members(publication.publication_id))
                    assert len(members) == 1
                    current_members[dataset_key] = members
                    manifest = manifest_repository.get_by_publication_id(publication.publication_id)
                    assert manifest is not None
                    assert manifest.dataset_key == dataset_key
                    assert manifest.publication_key == "current"
                    assert manifest.run_id == group_run_id
                    assert manifest.task_attempt_id == task_attempt_id
                    assert manifest.raw_audit_count == 1
                    manifest_reference = manifest.raw_audits[0]
                    expected_audit = raw_audit_by_dataset[dataset_key]
                    assert manifest_reference.raw_audit_id == expected_audit.raw_audit_id
                    assert manifest_reference.version == "1"
                    assert manifest_reference.content_hash == expected_audit.content_hash
                    assert manifest_reference.run_id == expected_audit.run_id
                    assert manifest_reference.ingested_run_id == (expected_audit.ingested_run_id)

                current_published = activated_by_dataset
                quote_publication = current_published[_DATASET_KEY]
                price_publication = current_published[_PRICE_DATASET_KEY]
                valuation_publication = current_published[_VALUATION_DATASET_KEY]
                quote_payload, quote_row = current_public_quote()
                assert quote_payload.get("publication_id") == quote_publication.publication_id
                assert quote_payload.get("policy_identity") == quote_publication.policy_version
                assert Decimal(str(quote_row["change_pct"])) == expected_metric
                assert quote_row["contract_version"] == quote_contract.key.contract_version
                assert quote_row["schema_version"] == quote_contract.key.schema_version
                assert quote_row["fetched_at"] == (cycle.quote_response_completed_at.isoformat())
                assert quote_row["source"] == cycle.quote_fact.source
                quote_extra = quote_row.get("extra")
                assert isinstance(quote_extra, dict)
                assert quote_extra.get("actual_source") == _QUOTE_SOURCE
                quote_evidence = QuoteChangePctEvidence.from_payload(
                    quote_row["change_pct_source_contract"]
                )
                assert quote_evidence.source_value == raw_change_pct
                assert quote_evidence.metric_value == expected_metric
                assert quote_evidence.observed_at == cycle.quote.snapshot_at
                assert quote_evidence.source_contract.provider_source == _QUOTE_SOURCE
                assert quote_evidence.source_contract_hash == (
                    _source_contract(action_basis=action_basis).content_hash
                )
                assert quote_evidence.dataset_contract_version == (
                    quote_contract.key.contract_version
                )
                quote_member = current_members[_DATASET_KEY][0]
                assert quote_member.raw_payload_hash == cycle.quote_payload_hash
                assert quote_member.source_record_id == cycle.quote_fact.source_record_id
                assert quote_member.fact_content_hash

                price_payload = query_published_price_bar_series(
                    _ASSET_CODE,
                    publication_key="current",
                    start=target_session,
                    end=target_session,
                )
                assert price_payload.get("must_not_use_for_decision") is False
                assert price_payload.get("publication_id") == price_publication.publication_id
                assert price_payload.get("policy_identity") == price_publication.policy_version
                price_rows = price_payload.get("rows")
                assert isinstance(price_rows, list) and len(price_rows) == 1
                price_row = price_rows[0]
                assert isinstance(price_row, dict)
                assert Decimal(str(price_row["close"])) == Decimal("12.3400")
                price_member = current_members[_PRICE_DATASET_KEY][0]
                assert price_member.raw_payload_hash == cycle.price_fact.raw_payload_hash
                assert price_member.source_record_id == cycle.price_fact.source_record_id

                valuation_payload = query_published_valuation_facts(
                    _ASSET_CODE,
                    publication_key="current",
                    as_of=target_session,
                )
                assert valuation_payload.get("must_not_use_for_decision") is False
                assert valuation_payload.get("publication_id") == (
                    valuation_publication.publication_id
                )
                assert valuation_payload.get("policy_identity") == (
                    valuation_publication.policy_version
                )
                valuation_rows = valuation_payload.get("rows")
                assert isinstance(valuation_rows, list) and len(valuation_rows) == 1
                valuation_row = valuation_rows[0]
                assert isinstance(valuation_row, dict)
                assert Decimal(str(valuation_row["pe_ttm"])) == Decimal(
                    f"{18.0 + cycle_number / 100:.2f}"
                )
                valuation_member = current_members[_VALUATION_DATASET_KEY][0]
                assert valuation_member.raw_payload_hash == (cycle.valuation_fact.raw_payload_hash)
                assert valuation_member.source_record_id == (cycle.valuation_fact.source_record_id)
                assert valuation_member.available_at == cycle.valuation_fact.available_at

                realtime_price = published_data_center_price(
                    _ASSET_CODE,
                    AssetType.EQUITY,
                )
                assert realtime_price is not None
                assert realtime_price.price == Decimal("12.34")
                assert realtime_price.change_pct == expected_metric
                assert realtime_price.timestamp == cycle.quote.snapshot_at
                assert realtime_price.fetched_at == cycle.quote_response_completed_at
                assert realtime_price.source == cycle.quote_fact.source
                assert realtime_price.publication_id == quote_publication.publication_id
                assert realtime_price.publication_dataset_key == _DATASET_KEY
                assert realtime_price.publication_key == "current"
                expected_evidence_hash = evidence_hash(quote_evidence)
                assert realtime_price.change_pct_evidence_hash == expected_evidence_hash

                if previous_cycle is not None:
                    # The group switch supersedes old members and invalidates a
                    # cached price carrying the former publication identity.
                    assert realtime_repository.get_latest_price(_ASSET_CODE) is None
                    for dataset_key, old_publication in current_published_before_activation.items():
                        old_model = CanonicalPublicationModel._default_manager.get(
                            publication_id=old_publication.publication_id
                        )
                        assert old_model.state == "superseded"
                        assert old_model.publication_hash == old_publication.publication_hash
                        assert (
                            tuple(
                                publication_repository.list_members(old_publication.publication_id)
                            )
                            == current_members_before_activation[dataset_key]
                        )
                    previous_cycle.quote_fact.refresh_from_db()
                    assert previous_cycle.quote_fact.change_pct == (previous_cycle.quote.change_pct)
                    assert previous_cycle.quote_fact.raw_payload_hash == (
                        previous_cycle.quote_payload_hash
                    )
                    assert previous_cycle.quote_fact.contract_version == (
                        previous_cycle.quote.contract_version
                    )
                    assert previous_cycle.quote_fact.schema_version == (
                        previous_cycle.quote.schema_version
                    )

                realtime_repository.save_price(realtime_price)
                cached_price = realtime_repository.get_latest_price(_ASSET_CODE)
                assert cached_price is not None
                assert cached_price.price == realtime_price.price
                assert cached_price.change_pct == expected_metric
                assert cached_price.timestamp == realtime_price.timestamp
                assert cached_price.fetched_at == realtime_price.fetched_at
                assert cached_price.publication_id == quote_publication.publication_id
                assert cached_price.change_pct_evidence_hash == expected_evidence_hash
                if cycle_number == 3:
                    precise_previous_cycle = previous_cycle
                    assert precise_previous_cycle is not None
                    precise_previous_cycle.quote_fact.refresh_from_db()
                    assert precise_previous_cycle.quote_fact.contract_version == "2.0"
                    assert precise_previous_cycle.quote_fact.schema_version == "2.0"
                    assert precise_previous_cycle.quote_fact.change_pct == Decimal("1.234567891234")
                    assert (
                        precise_previous_cycle.quote_fact.extra["change_pct_source_contract"][
                            "action_basis"
                        ]
                        == "test_fixture_action_basis_v1"
                    )
                    precise_publication = current_published_before_activation[_DATASET_KEY]
                    precise_publication_row = CanonicalPublicationModel._default_manager.get(
                        publication_id=precise_publication.publication_id
                    )
                    assert precise_publication_row.policy_version == quote_policy_v2.identity
                    assert precise_publication_row.publication_hash == (
                        precise_publication.publication_hash
                    )
                    assert precise_publication_row.state == "superseded"
                    precise_evidence = precise_previous_cycle.quote.change_pct_evidence
                    assert precise_evidence is not None
                    assert quote_evidence.source_contract_hash != (
                        precise_evidence.source_contract_hash
                    )

                previous_cycle = cycle
                previous_group_published_at = published_at
                current_published_before_activation = dict(current_published)
                current_members_before_activation = dict(current_members)
    finally:
        load_cn_market_calendar_evidence.cache_clear()
        provider_runtime.reset_registry()
