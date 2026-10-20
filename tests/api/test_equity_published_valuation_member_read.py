"""Real published-member reads for the equity valuation API."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from apps.data_center.application.valuation_publication import PublishValuationBatchUseCase
from apps.data_center.domain.entities import AssetMaster, ValuationFact
from apps.data_center.domain.enums import AssetType, MarketExchange
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.infrastructure.catalog_repositories import AssetRepository
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationPointerModel,
    PublicationMemberModel,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository
from tests.support.tui_research.disposable import require_test_database
from tests.support.tui_research.financial_consumer_state import (
    FinancialMetricSeed,
    prepare_financial_consumer_state,
)
from tests.support.tui_research.market_consumer_state import (
    MarketConsumerClocks,
    PriceSeed,
    QuoteSeed,
    ValuationSeed,
    prepare_market_consumer_state,
)

_ASSET_CODE = "600000.SH"
_VALUATION_DATASET = "equity.valuation.fact"
_PUBLICATION_KEY = "current"
_SOURCE = "synthetic-consumer-market"


@dataclass(frozen=True)
class _PublishedValuationApiFixture:
    """Exact current member plus a newer decoy revision in another publication."""

    valuation_publication_id: str
    valuation_member_id: str
    valuation_fact_pk: str
    valuation_fact: ValuationFact
    decoy_publication_id: str
    decoy_member_fact_pk: str
    financial_publication_id: str
    financial_publication_member_count: int
    financial_member_metric_codes: tuple[str, ...]
    financial_member_fact_pks: tuple[str, ...]
    financial_period_end: date
    price_publication_id: str


@contextmanager
def _fixture_artifact_root() -> Iterator[Path]:
    """Keep source-artifact bytes under the ignored repository tmp directory."""

    repository_tmp = (Path(settings.BASE_DIR).resolve() / ".tmp").resolve()
    root = (repository_tmp / "equity-valuation-api-fixtures" / uuid4().hex).resolve()
    if root == repository_tmp or not root.is_relative_to(repository_tmp):
        raise AssertionError("valuation fixture artifacts must stay below repository .tmp")
    root.mkdir(parents=True, exist_ok=False)
    try:
        yield root
    finally:
        resolved_root = root.resolve()
        if (
            resolved_root != repository_tmp
            and resolved_root.is_relative_to(repository_tmp)
            and resolved_root.is_dir()
        ):
            shutil.rmtree(resolved_root)


def _quarter_end_before(report_date: date) -> date:
    """Return the latest quarter end preceding a synthetic report date."""

    quarter_start_month = ((report_date.month - 1) // 3) * 3 + 1
    return date(report_date.year, quarter_start_month, 1) - timedelta(days=1)


def _write_unselected_valuation_revision(
    artifact_root: Path,
    selected: ValuationFact,
    *,
    pe_ttm: float,
    observed_at: datetime,
    available_at: datetime,
    fetched_at: datetime,
) -> ValuationFact:
    """Create a distinct source-evidence-bearing revision without changing its member."""

    source_record_id = (
        f"{_SOURCE}:valuation-revision-decoy:{selected.asset_code}:"
        f"{selected.val_date.isoformat()}"
    )
    payload = {
        "asset_code": selected.asset_code,
        "dataset_key": _VALUATION_DATASET,
        "fixture_source": "synthetic-unselected-revision-decoy",
        "fetched_at": fetched_at.isoformat(),
        "observed_at": observed_at.isoformat(),
        "available_at": available_at.isoformat(),
        "pe_ttm": pe_ttm,
        "raw_payload_scope": "record_response_body",
        "source": selected.source,
        "source_record_id": source_record_id,
        "val_date": selected.val_date.isoformat(),
    }
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    (artifact_root / "valuation-revision-decoy.json").write_bytes(body)
    return replace(
        selected,
        pe_ttm=pe_ttm,
        observed_at=observed_at,
        available_at=available_at,
        fetched_at=fetched_at,
        extra={
            **selected.extra,
            "fixture_source": "synthetic-unselected-revision-decoy",
            "raw_payload_scope": "record_response_body",
        },
        source_record_id=source_record_id,
        raw_payload_hash=hashlib.sha256(body).hexdigest(),
        ingested_run_id=str(uuid4()),
    )


def _prepare_published_valuation_api_fixture(
    artifact_root: Path,
) -> _PublishedValuationApiFixture:
    """Publish controlled synthetic facts through real readers and publishers."""

    database_path = require_test_database(allow_native_postgres_test=True)
    if database_path is not None and not database_path.name.startswith("test_"):
        raise AssertionError("API publication fixtures require a disposable test_ database")

    now = datetime.now(UTC)
    shanghai_today = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    trade_date = shanghai_today - timedelta(days=1)
    source_observed_at = now - timedelta(minutes=2)
    available_at = now - timedelta(minutes=1)
    fetched_at = now - timedelta(seconds=30)
    report_date = shanghai_today - timedelta(days=7)
    announced_at = datetime.combine(
        report_date,
        time(9),
        tzinfo=ZoneInfo("Asia/Shanghai"),
    ).astimezone(UTC)
    period_end = _quarter_end_before(report_date)

    AssetRepository().upsert(
        AssetMaster(
            code=_ASSET_CODE,
            name="浦发银行",
            short_name="浦发银行",
            asset_type=AssetType.STOCK,
            exchange=MarketExchange.SSE,
            sector="银行",
            industry="银行",
            currency="CNY",
        )
    )

    financial_state = prepare_financial_consumer_state(
        artifact_root,
        asset_code=_ASSET_CODE,
        period_type="quarterly",
        period_end=period_end,
        report_date=report_date,
        announced_at=announced_at,
        available_at=available_at,
        metrics=(
            FinancialMetricSeed("revenue", Decimal("1000000.0000"), "元"),
            FinancialMetricSeed("net_profit", Decimal("200000.0000"), "元"),
            FinancialMetricSeed("total_assets", Decimal("3000000.0000"), "元"),
            FinancialMetricSeed("total_liabilities", Decimal("500000.0000"), "元"),
            FinancialMetricSeed("equity", Decimal("2500000.0000"), "元"),
            FinancialMetricSeed("roe", Decimal("18.5000"), "%"),
            FinancialMetricSeed("debt_ratio", Decimal("16.7000"), "%"),
        ),
        allow_native_postgres_test=True,
    )
    market_state = prepare_market_consumer_state(
        tmp_path=artifact_root,
        governance_root=Path(settings.BASE_DIR) / "governance",
        clocks=MarketConsumerClocks(
            closed_session=trade_date,
            price_observed_at=cn_market_session_close_utc(trade_date),
            valuation_observed_at=cn_market_session_close_utc(trade_date),
            quote_snapshot_at=source_observed_at,
            available_at=available_at,
            fetched_at=fetched_at,
        ),
        price=PriceSeed(
            _ASSET_CODE,
            trade_date,
            open=12.1,
            high=12.5,
            low=12.0,
            close=12.34,
            volume=1000.0,
            amount=12340.0,
        ),
        quotes=(
            QuoteSeed("510300.SH", 4.0),
            QuoteSeed("000300.SH", 4000.0),
            QuoteSeed(_ASSET_CODE, 12.34),
        ),
        valuation=ValuationSeed(
            _ASSET_CODE,
            trade_date,
            pe_ttm=8.0,
            pe_static=9.0,
            pb=0.8,
            ps_ttm=1.2,
            market_cap=200_000_000_000.0,
            float_market_cap=120_000_000_000.0,
            dv_ratio=2.0,
        ),
        run_id=str(uuid4()),
        publication_clock=lambda: datetime.now(UTC),
        allow_native_postgres_test=True,
    )

    publication_repository = CanonicalPublicationRepository()
    valuation_repository = ValuationFactRepository()
    current_publication = publication_repository.get_current(
        _VALUATION_DATASET,
        _PUBLICATION_KEY,
    )
    if (
        current_publication is None
        or current_publication.publication_id != market_state.valuation_publication_id
    ):
        raise AssertionError("valuation current pointer must select the real publisher result")
    current_members = publication_repository.list_members(current_publication.publication_id)
    if len(current_members) != 1:
        raise AssertionError("controlled valuation publication must have one selected member")
    current_member = current_members[0]
    selected_rows = valuation_repository.get_series(
        _ASSET_CODE,
        start=trade_date,
        end=trade_date,
        fact_pks=[current_member.fact_pk],
    )
    if len(selected_rows) != 1:
        raise AssertionError("current publication member must resolve to one exact fact")
    selected_fact = selected_rows[0]

    decoy_observed_at = datetime.now(UTC) - timedelta(seconds=20)
    decoy_available_at = decoy_observed_at + timedelta(seconds=5)
    decoy_fetched_at = decoy_observed_at + timedelta(seconds=10)
    decoy_fact = _write_unselected_valuation_revision(
        artifact_root,
        selected_fact,
        pe_ttm=99.0,
        observed_at=decoy_observed_at,
        available_at=decoy_available_at,
        fetched_at=decoy_fetched_at,
    )
    if valuation_repository.bulk_upsert([decoy_fact]) != 1:
        raise AssertionError("valuation repository must store one unselected revision")
    raw_latest_rows = valuation_repository.get_series(
        _ASSET_CODE,
        start=trade_date,
        end=trade_date,
    )
    if len(raw_latest_rows) != 1 or raw_latest_rows[0].pe_ttm != 99.0:
        raise AssertionError("raw latest valuation must expose the decoy revision")

    decoy_publication = PublishValuationBatchUseCase(
        fact_repository=valuation_repository,
        publication_repository=publication_repository,
        policy_repository=PublicationPolicyRepository(),
    ).execute(
        [decoy_fact],
        provider_name=_SOURCE,
        publication_key="unselected-decoy",
        run_id=str(uuid4()),
        published_at=datetime.now(UTC),
    )
    if decoy_publication is None:
        raise AssertionError("decoy revision must be bound by a real non-current publication")
    decoy_members = publication_repository.list_members(decoy_publication.publication_id)
    if len(decoy_members) != 1 or decoy_members[0].fact_pk == current_member.fact_pk:
        raise AssertionError("decoy publication must contain a distinct unselected fact member")
    if CanonicalPublicationPointerModel._default_manager.filter(
        dataset_key=_VALUATION_DATASET,
        publication_key="unselected-decoy",
    ).exists():
        raise AssertionError("the decoy publication must not acquire a current pointer")

    current_pointer = CanonicalPublicationPointerModel._default_manager.get(
        dataset_key=_VALUATION_DATASET,
        publication_key=_PUBLICATION_KEY,
    )
    if str(current_pointer.publication_id) != market_state.valuation_publication_id:
        raise AssertionError("publishing the decoy must not replace the selected current pointer")

    return _PublishedValuationApiFixture(
        valuation_publication_id=market_state.valuation_publication_id,
        valuation_member_id=current_member.member_id,
        valuation_fact_pk=current_member.fact_pk,
        valuation_fact=selected_fact,
        decoy_publication_id=decoy_publication.publication_id,
        decoy_member_fact_pk=decoy_members[0].fact_pk,
        financial_publication_id=str(financial_state.publication.publication_id),
        financial_publication_member_count=financial_state.publication.member_count,
        financial_member_metric_codes=tuple(
            state.seed.metric_code for state in financial_state.metric_states
        ),
        financial_member_fact_pks=tuple(
            state.member.fact_pk for state in financial_state.metric_states
        ),
        financial_period_end=financial_state.fact.period_end,
        price_publication_id=market_state.price_publication_id,
    )


@pytest.mark.django_db
def test_published_valuation_api_reads_exact_current_members_and_source_clocks(
    authenticated_client: APIClient,
) -> None:
    """Serve selected current facts, not a newer revision or another publication."""

    require_test_database(allow_native_postgres_test=True)
    with _fixture_artifact_root() as artifact_root:
        fixture = _prepare_published_valuation_api_fixture(artifact_root)
        response = authenticated_client.get(
            f"/api/equity/valuation/{_ASSET_CODE}/",
            {"mode": "published", "publication_key": _PUBLICATION_KEY},
        )

    assert response.status_code == 200
    assert response["Content-Type"].split(";")[0] == "application/json"
    payload = response.json()
    assert payload["success"] is True
    assert payload["status"] == "success"
    assert payload["must_not_use_for_decision"] is False
    assert payload["publication_id"] == fixture.valuation_publication_id
    assert payload["publication_gates"]["equity.valuation.fact"]["publication_id"] == (
        fixture.valuation_publication_id
    )
    assert payload["publication_gates"]["equity.financial.fact"]["publication_id"] == (
        fixture.financial_publication_id
    )
    assert payload["publication_gates"]["equity.price.bar"]["publication_id"] == (
        fixture.price_publication_id
    )
    assert payload["publication_gates"][_VALUATION_DATASET]["freshness_status"] == "fresh"
    assert payload["publication_gates"]["equity.financial.fact"]["freshness_status"] == "fresh"
    assert payload["publication_gates"]["equity.price.bar"]["must_not_use_for_decision"] is False
    assert fixture.financial_publication_member_count == 7
    assert set(fixture.financial_member_metric_codes) == {
        "revenue",
        "net_profit",
        "total_assets",
        "total_liabilities",
        "equity",
        "roe",
        "debt_ratio",
    }
    assert len(fixture.financial_member_fact_pks) == 7
    assert len(set(fixture.financial_member_fact_pks)) == 7
    assert fixture.valuation_fact_pk != fixture.decoy_member_fact_pk
    assert fixture.valuation_publication_id != fixture.decoy_publication_id
    assert payload["current_pe"] == pytest.approx(8.0)
    assert payload["current_pb"] == pytest.approx(0.8)
    assert payload["latest_valuation"]["pe"] == pytest.approx(8.0)
    assert payload["latest_valuation"]["pb"] == pytest.approx(0.8)
    assert payload["latest_valuation"]["price"] == pytest.approx(12.34)
    financial_data = payload["financial_data"]
    assert isinstance(financial_data, dict)
    assert financial_data["revenue"] == pytest.approx(1_000_000.0)
    assert financial_data["net_profit"] == pytest.approx(200_000.0)
    assert financial_data["roe"] == pytest.approx(18.5)
    assert financial_data["debt_ratio"] == pytest.approx(16.7)
    assert financial_data["period_end"] == fixture.financial_period_end.isoformat()
    assert payload["latest_valuation"]["source_updated_at"] == (
        fixture.valuation_fact.observed_at.isoformat()
    )
    assert payload["latest_valuation"]["updated_at"] == (
        fixture.valuation_fact.fetched_at.isoformat()
    )
    assert (
        payload["latest_valuation"]["source_updated_at"]
        != payload["latest_valuation"]["updated_at"]
    )


@pytest.mark.django_db
def test_published_valuation_api_blocks_when_current_member_is_missing(
    authenticated_client: APIClient,
) -> None:
    """A corrupted real member manifest stays blocked in the HTTP contract."""

    require_test_database(allow_native_postgres_test=True)
    with _fixture_artifact_root() as artifact_root:
        fixture = _prepare_published_valuation_api_fixture(artifact_root)
        deleted, _details = PublicationMemberModel._default_manager.filter(
            member_id=fixture.valuation_member_id
        ).delete()
        if deleted != 1:
            raise AssertionError("negative case must remove exactly the selected current member")
        response = authenticated_client.get(
            f"/api/equity/valuation/{_ASSET_CODE}/",
            {"mode": "published", "publication_key": _PUBLICATION_KEY},
        )

    assert response.status_code == 200
    assert response["Content-Type"].split(";")[0] == "application/json"
    payload = response.json()
    assert payload["success"] is False
    assert payload["status"] == "blocked"
    assert payload["error"] == "publication_member_snapshot_invalid"
    assert payload["must_not_use_for_decision"] is True
    assert payload["latest_valuation"] is None
    assert payload["financial_data"] is None
    valuation_gate = payload["publication_gates"][_VALUATION_DATASET]
    assert valuation_gate["must_not_use_for_decision"] is True
    assert valuation_gate["blocked_reason"] == "publication_member_snapshot_invalid"
    assert valuation_gate["publication_id"] == fixture.valuation_publication_id
