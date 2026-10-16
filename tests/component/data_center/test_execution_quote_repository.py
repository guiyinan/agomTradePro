"""SQLite integration tests for exact publication-bound execution quotes."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from apps.data_center.application.execution_quotes import (
    ExecutionQuoteBlockReason,
    ExecutionQuoteUnavailable,
)
from apps.data_center.application.public import get_execution_quote
from apps.data_center.application.publication_sync_market import PublishQuoteSnapshotBatchUseCase
from apps.data_center.domain.contracts import MAX_CATALOG_TTL_SECONDS, DatasetKey, PublicationPolicy
from apps.data_center.domain.entities import QuoteSnapshot
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.models import QuoteSnapshotModel
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from apps.data_center.infrastructure.quote_snapshot_repository import QuoteSnapshotRepository
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])

NOW = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
ASSET = "600000.SH"
SCHEMA_MODELS = (
    QuoteSnapshotModel,
    DatasetContractModel,
    DatasetPublicationPolicyModel,
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    """Isolate only the quote, contract, and publication tables used here."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(SCHEMA_MODELS):
            yield


@pytest.fixture(autouse=True)
def _calendar_provider_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail if a test reaches the market-calendar owner without an explicit stub."""

    from apps.data_center.application import query_services

    def _unexpected_calendar_call(_now: datetime) -> None:
        raise AssertionError("component tests must not call a real calendar/provider")

    monkeypatch.setattr(
        query_services,
        "latest_completed_cn_market_session",
        _unexpected_calendar_call,
    )


def _seed_quote(
    *,
    asset_code: str = ASSET,
    source: str = "tushare",
    quality_status: str = "accepted",
    snapshot_at: datetime | None = None,
    fetched_at: datetime | None = None,
    freshness_seconds: int = 60,
    execution_freshness_seconds: int | None = None,
    published_at: datetime | None = None,
    bind_pointer_fixture: bool = True,
    publication_key: str = "execution",
) -> tuple[QuoteSnapshotModel, str]:
    """Publish one quote and optionally seed its exact pointer fixture state."""

    observed = snapshot_at or NOW - timedelta(seconds=10)
    fetched = fetched_at or observed + timedelta(seconds=1)
    publication_time = published_at or NOW - timedelta(seconds=1)
    dataset = DatasetKey("equity.quote.snapshot", "2.0", "1.0")
    policy = PublicationPolicy(
        dataset=dataset,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=(
            "source",
            "observed_at",
            "fetched_at",
            "source_record_id",
            "raw_payload_hash",
            "raw_payload_scope",
            "fact_content_hash",
        ),
        retention_days=3650,
        policy_version="2",
    )
    PublicationPolicyRepository().save(policy)
    DatasetContractModel._default_manager.create(
        dataset_key=dataset.value,
        contract_version=dataset.contract_version,
        schema_version=dataset.schema_version,
        owner="data-platform",
        frequency="intraday",
        decision_critical=True,
        fields=[{"name": "snapshot_at", "value_type": "datetime"}],
        freshness_seconds=freshness_seconds,
        execution_freshness_seconds=execution_freshness_seconds,
        active=True,
    )
    row = QuoteSnapshotModel._default_manager.create(
        asset_code=asset_code,
        snapshot_at=observed,
        fetched_at=fetched,
        current_price=Decimal("10.1234"),
        bid=None,
        ask=Decimal("10.1300"),
        prev_close=Decimal("9.9000"),
        source=source,
        source_record_id=f"source-record:{uuid4().hex}",
        raw_payload_hash="c" * 64,
        quality_status=quality_status,
        contract_version=dataset.contract_version,
        schema_version=dataset.schema_version,
        extra={"raw_payload_scope": "batch_response_body", "must_not_use_for_decision": False},
    )
    quote = QuoteSnapshot(
        asset_code=asset_code,
        snapshot_at=observed,
        fetched_at=fetched,
        current_price=10.1234,
        bid=None,
        ask=10.13,
        prev_close=9.9,
        source=source,
    )
    publication = PublishQuoteSnapshotBatchUseCase(
        fact_repository=QuoteSnapshotRepository(),
        publication_repository=CanonicalPublicationRepository(),
        policy_repository=PublicationPolicyRepository(),
    ).execute(
        [quote],
        provider_name="test-provider",
        publication_key=publication_key,
        published_at=publication_time,
    )
    assert publication is not None
    assert publication.publication_hash
    persisted_publication = CanonicalPublicationRepository().get_by_id(publication.publication_id)
    assert persisted_publication is not None
    assert persisted_publication.publication_hash == publication.publication_hash
    members = CanonicalPublicationRepository().list_members(publication.publication_id)
    assert len(members) == 1
    assert members[0].fact_content_hash
    if bind_pointer_fixture:
        # This represents an already activated exact execution pointer fixture.
        # It does not exercise authority, audit receipts, or activation workflow.
        CanonicalPublicationPointerModel._default_manager.update_or_create(
            dataset_key="equity.quote.snapshot",
            publication_key=publication_key,
            defaults={
                "publication_id": publication.publication_id,
                "publication_hash": publication.publication_hash,
            },
        )
    return row, publication.publication_id


def test_catalog_database_rejects_zero_execution_ttl() -> None:
    """A nullable execution TTL, when present, must be strictly positive in storage."""

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DatasetContractModel._default_manager.create(
                dataset_key="test.execution.ttl",
                contract_version="1.0",
                schema_version="1.0",
                owner="data-platform",
                frequency="intraday",
                decision_critical=True,
                fields=[{"name": "snapshot_at", "value_type": "datetime"}],
                execution_freshness_seconds=0,
            )


def test_execution_quote_blocks_datetime_deadline_overflow() -> None:
    """A signed-64-bit TTL that cannot form a datetime deadline fails closed."""

    _seed_quote(execution_freshness_seconds=MAX_CATALOG_TTL_SECONDS)

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote(ASSET, as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT


def test_execution_quote_reads_only_the_execution_pointer() -> None:
    row, publication_id = _seed_quote(execution_freshness_seconds=60)

    result = get_execution_quote(ASSET, as_of=NOW)

    assert result.fact_pk == str(row.pk)
    assert result.publication_id == publication_id


def test_execution_quote_blocks_catalog_policy_version_mismatch() -> None:
    """An execution contract cannot be mixed with a differently versioned policy."""

    _seed_quote(execution_freshness_seconds=60)
    DatasetContractModel._default_manager.filter(
        dataset_key="equity.quote.snapshot",
        contract_version="2.0",
        schema_version="1.0",
    ).update(contract_version="3.0")

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote(ASSET, as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.PUBLICATION_BLOCKED
    assert error.value.publication_blocked_reason == "execution_contract_policy_version_mismatch"


def test_execution_quote_blocks_fact_contract_version_mismatch() -> None:
    """A hash-bound fact row must carry the same contract and schema versions."""

    row, _publication_id = _seed_quote(execution_freshness_seconds=60)
    QuoteSnapshotModel._default_manager.filter(pk=row.pk).update(contract_version="1.0")

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote(ASSET, as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.PUBLICATION_BLOCKED
    assert error.value.publication_blocked_reason == "publication_member_fact_changed"


def test_execution_quote_does_not_fall_back_to_current_pointer() -> None:
    _seed_quote(publication_key="current", execution_freshness_seconds=60)

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote(ASSET, as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.PUBLICATION_MISSING


def test_execution_quote_reads_exact_decimal_fact_from_execution_publication() -> None:
    row, publication_id = _seed_quote(execution_freshness_seconds=60)

    result = get_execution_quote(ASSET, as_of=NOW)
    persisted_price = QuoteSnapshotModel._default_manager.get(pk=row.pk).current_price

    assert result.last == persisted_price
    assert isinstance(result.last, Decimal)
    assert result.last == Decimal("10.1234")
    assert result.bid is None
    assert result.ask == Decimal("10.1300")
    assert result.publication_id == publication_id
    assert result.publication_hash
    assert result.fact_content_hash
    assert result.dataset_key == "equity.quote.snapshot"
    assert result.contract_version == "2.0"
    assert result.schema_version == "1.0"
    assert result.contract_resolution == "current_active_not_point_in_time"
    assert result.execution_freshness_seconds == 60
    assert result.freshness_deadline == result.snapshot_at + timedelta(seconds=60)


def test_execution_quote_requires_execution_pointer_after_publication_is_persisted() -> None:
    _seed_quote(bind_pointer_fixture=False, execution_freshness_seconds=60)

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote(ASSET, as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.PUBLICATION_MISSING


def test_execution_quote_blocks_fact_mutation_after_publication() -> None:
    row, _publication_id = _seed_quote(execution_freshness_seconds=60)
    QuoteSnapshotModel._default_manager.filter(pk=row.pk).update(current_price=Decimal("11.0000"))

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote(ASSET, as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.PUBLICATION_BLOCKED


def test_execution_quote_does_not_leak_an_unpublished_asset_fact() -> None:
    _seed_quote(execution_freshness_seconds=60)
    unpublished = QuoteSnapshotModel._default_manager.create(
        asset_code="000001.SZ",
        snapshot_at=NOW - timedelta(seconds=2),
        fetched_at=NOW - timedelta(seconds=1),
        current_price=Decimal("11.0000"),
        source="tushare",
        source_record_id=f"source-record:{uuid4().hex}",
        raw_payload_hash="d" * 64,
        quality_status="accepted",
        extra={"raw_payload_scope": "batch_response_body"},
    )

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote("000001.SZ", as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.PUBLICATION_BLOCKED
    assert QuoteSnapshotModel._default_manager.filter(pk=unpublished.pk).exists()


def test_execution_quote_blocks_mismatched_member_table_and_member_metadata() -> None:
    _row, publication_id = _seed_quote(execution_freshness_seconds=60)
    PublicationMemberModel._default_manager.filter(publication_id=publication_id).update(
        fact_table="data_center_price_bar"
    )

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote(ASSET, as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.PUBLICATION_BLOCKED


def test_execution_quote_blocks_qmt_bridge_even_if_extra_claims_decision_ready() -> None:
    _seed_quote(source="qmt-bridge:binding-1", execution_freshness_seconds=60)

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote(ASSET, as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.SOURCE_UNVERIFIED


def test_execution_quote_blocks_when_active_freshness_policy_is_missing() -> None:
    _seed_quote(execution_freshness_seconds=60)
    DatasetContractModel._default_manager.filter(dataset_key="equity.quote.snapshot").update(
        active=False
    )

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote(ASSET, as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.POLICY_MISSING
    assert error.value.publication_blocked_reason == "publication_freshness_policy_missing"


def test_execution_quote_blocks_multiple_active_contracts_with_exact_reason() -> None:
    """Execution TTL resolution fails closed when the active catalog is ambiguous."""

    _seed_quote(execution_freshness_seconds=60)
    DatasetContractModel._default_manager.create(
        dataset_key="equity.quote.snapshot",
        contract_version="3.0",
        schema_version="1.0",
        owner="data-platform",
        frequency="intraday",
        decision_critical=True,
        fields=[{"name": "snapshot_at", "value_type": "datetime"}],
        execution_freshness_seconds=60,
        active=True,
    )

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote(ASSET, as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.PUBLICATION_BLOCKED
    assert error.value.publication_blocked_reason == "execution_catalog_contract_ambiguous"


def test_execution_quote_does_not_fall_back_to_research_freshness_without_execution_ttl() -> None:
    _seed_quote(freshness_seconds=14_400, execution_freshness_seconds=None)

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote(ASSET, as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.POLICY_MISSING
    assert error.value.publication_blocked_reason == "publication_freshness_policy_missing"


def test_execution_quote_applies_execution_ttl_without_research_ttl_fallback() -> None:
    old_observation = NOW - timedelta(seconds=61)
    _seed_quote(
        snapshot_at=old_observation,
        fetched_at=old_observation + timedelta(seconds=1),
        published_at=old_observation + timedelta(seconds=2),
        freshness_seconds=14_400,
        execution_freshness_seconds=60,
    )

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote(ASSET, as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.STALE


def test_execution_quote_preserves_missing_active_publication_policy_reason() -> None:
    _seed_quote(execution_freshness_seconds=60)
    DatasetPublicationPolicyModel._default_manager.filter(
        dataset_key="equity.quote.snapshot"
    ).update(active=False)

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote(ASSET, as_of=NOW)

    assert error.value.reason is ExecutionQuoteBlockReason.POLICY_MISSING
    assert error.value.publication_blocked_reason == "publication_policy_missing"


def test_execution_quote_blocks_completed_session_waiver_after_intraday_ttl(monkeypatch) -> None:
    old_observation = datetime(2026, 10, 16, 7, 0, tzinfo=UTC)
    closed_market_time = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
    _seed_quote(
        snapshot_at=old_observation,
        fetched_at=old_observation + timedelta(seconds=1),
        published_at=old_observation + timedelta(seconds=2),
        freshness_seconds=60,
        execution_freshness_seconds=60,
    )
    from apps.data_center.application import query_services

    monkeypatch.setattr(
        query_services,
        "latest_completed_cn_market_session",
        lambda _now: old_observation.astimezone(UTC).date(),
    )

    with pytest.raises(ExecutionQuoteUnavailable) as error:
        get_execution_quote(ASSET, as_of=closed_market_time)

    assert error.value.reason is ExecutionQuoteBlockReason.STALE
