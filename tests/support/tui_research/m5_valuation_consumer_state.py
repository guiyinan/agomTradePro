"""Strict local M5 fixture for an exact published equity-valuation read."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from tests.support.tui_research.m5_playwright_fixture_guard import (
    require_m5_valuation_fixture_database,
)

if TYPE_CHECKING:
    from django.db.models import Model

    from tests.support.tui_research.financial_consumer_state import FinancialConsumerState
    from tests.support.tui_research.market_consumer_state import MarketConsumerState

_DATASET_KEYS: tuple[str, ...] = (
    "equity.price.bar",
    "equity.quote.snapshot",
    "equity.valuation.fact",
    "equity.financial.fact",
)
_VALUATION_METRICS: tuple[tuple[str, str, str], ...] = (
    ("revenue", "1000000.0000", "元"),
    ("net_profit", "200000.0000", "元"),
    ("total_assets", "3000000.0000", "元"),
    ("total_liabilities", "500000.0000", "元"),
    ("equity", "2500000.0000", "元"),
    ("roe", "18.5000", "%"),
    ("debt_ratio", "16.7000", "%"),
)


class M5PublishedValuationFixtureError(RuntimeError):
    """Raised when the isolated M5 valuation fixture cannot be safely prepared."""


@dataclass(frozen=True, slots=True)
class _PointerSnapshot:
    """Exact pre-fixture current pointer values for one dataset."""

    dataset_key: str
    existed: bool
    pointer_id: object | None
    publication_id: object | None
    publication_hash: str
    activation_id: str
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class _CatalogRowSnapshot:
    """One exact catalog row before fixture-specific active versions are installed."""

    table: Literal["contract", "policy"]
    primary_key: object
    fields: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class M5PublishedValuationFixture:
    """Exact publication IDs and pre-fixture state needed for safe cleanup."""

    base_url: str
    requested_asset_code: str
    source_name: str
    market_state: MarketConsumerState
    financial_state: FinancialConsumerState
    pointers_before: tuple[_PointerSnapshot, ...]
    pointers_after: tuple[_PointerSnapshot, ...]
    contracts_before: tuple[_CatalogRowSnapshot, ...]
    contracts_after: tuple[_CatalogRowSnapshot, ...]
    policies_before: tuple[_CatalogRowSnapshot, ...]
    policies_after: tuple[_CatalogRowSnapshot, ...]
    asset_master_created: bool
    asset_master_primary_key: object | None
    asset_master_fields: tuple[tuple[str, object], ...]


def _snapshot_pointers(dataset_keys: tuple[str, ...]) -> tuple[_PointerSnapshot, ...]:
    """Read current pointer rows without changing them."""

    from apps.data_center.infrastructure.publication_models import (
        CanonicalPublicationPointerModel,
    )

    snapshots: list[_PointerSnapshot] = []
    for dataset_key in dataset_keys:
        rows = tuple(
            CanonicalPublicationPointerModel._default_manager.filter(
                dataset_key=dataset_key,
                publication_key="current",
            )
        )
        if len(rows) > 1:
            raise M5PublishedValuationFixtureError(
                f"current pointer scope is not unique for {dataset_key}"
            )
        if not rows:
            snapshots.append(
                _PointerSnapshot(
                    dataset_key=dataset_key,
                    existed=False,
                    pointer_id=None,
                    publication_id=None,
                    publication_hash="",
                    activation_id="",
                    updated_at=None,
                )
            )
            continue
        pointer = rows[0]
        snapshots.append(
            _PointerSnapshot(
                dataset_key=dataset_key,
                existed=True,
                pointer_id=pointer.pointer_id,
                publication_id=pointer.publication_id,
                publication_hash=pointer.publication_hash,
                activation_id=pointer.activation_id,
                updated_at=pointer.updated_at,
            )
        )
    return tuple(snapshots)


def _snapshot_catalog_rows(
    *,
    table: Literal["contract", "policy"],
    model: type[Model],
    dataset_keys: tuple[str, ...],
) -> tuple[_CatalogRowSnapshot, ...]:
    """Capture all matching catalog rows, including rows whose active flag changes."""

    rows: list[_CatalogRowSnapshot] = []
    for row in model._default_manager.filter(dataset_key__in=dataset_keys).order_by("pk"):
        fields = tuple(
            (
                field.attname,
                deepcopy(getattr(row, field.attname)),
            )
            for field in model._meta.concrete_fields
            if not field.primary_key
        )
        rows.append(
            _CatalogRowSnapshot(
                table=table,
                primary_key=row.pk,
                fields=fields,
            )
        )
    return tuple(rows)


def _snapshot_asset_fields(
    asset_model: type[Model], asset: Model
) -> tuple[tuple[str, object], ...]:
    """Capture every stored field of the one fixture-created AssetMaster row."""

    return tuple(
        (
            field.attname,
            deepcopy(getattr(asset, field.attname)),
        )
        for field in asset_model._meta.concrete_fields
        if not field.primary_key
    )


def _period_end_before(report_date: date) -> date:
    """Return the preceding quarter end for the consumer-only financial statement."""

    quarter_start_month = ((report_date.month - 1) // 3) * 3 + 1
    return date(report_date.year, quarter_start_month, 1) - timedelta(days=1)


def prepare_m5_published_valuation_fixture(
    *,
    artifact_root: Path,
    governance_root: Path,
    base_url: str,
    requested_asset_code: str,
) -> M5PublishedValuationFixture:
    """Publish controlled local facts for the exact asset requested by the M5 task."""

    require_m5_valuation_fixture_database(base_url=base_url)
    if not artifact_root.is_dir():
        raise M5PublishedValuationFixtureError("artifact_root must already be a directory")
    normalized_asset_code = requested_asset_code.strip().upper()
    if normalized_asset_code != requested_asset_code or not normalized_asset_code:
        raise M5PublishedValuationFixtureError(
            "requested_asset_code must be the exact canonical user task input"
        )

    from django.db import transaction

    from apps.data_center.domain.enums import AssetType, MarketExchange
    from apps.data_center.domain.market_time import cn_market_session_close_utc
    from apps.data_center.infrastructure.catalog_models import (
        DatasetContractModel,
        DatasetPublicationPolicyModel,
    )
    from apps.data_center.infrastructure.catalog_repositories import AssetRepository
    from apps.data_center.infrastructure.models import AssetMasterModel
    from tests.support.tui_research.financial_consumer_state import (
        FinancialMetricSeed,
        prepare_m5_financial_consumer_state,
    )
    from tests.support.tui_research.market_consumer_state import (
        DECISION_ASSET_CODES,
        MarketConsumerClocks,
        PriceSeed,
        QuoteSeed,
        ValuationSeed,
        prepare_m5_market_consumer_state,
    )

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
    period_end = _period_end_before(report_date)
    source_name = f"m5-val-{uuid4().hex}"
    metric_seeds = tuple(
        FinancialMetricSeed(metric_code, Decimal(value), unit)
        for metric_code, value, unit in _VALUATION_METRICS
    )

    market_state: MarketConsumerState | None = None
    financial_state: FinancialConsumerState | None = None
    pointers_before: tuple[_PointerSnapshot, ...] = ()
    pointers_after: tuple[_PointerSnapshot, ...] = ()
    contracts_before: tuple[_CatalogRowSnapshot, ...] = ()
    contracts_after: tuple[_CatalogRowSnapshot, ...] = ()
    policies_before: tuple[_CatalogRowSnapshot, ...] = ()
    policies_after: tuple[_CatalogRowSnapshot, ...] = ()
    asset_master_created = False
    asset_master_primary_key: object | None = None
    asset_master_fields: tuple[tuple[str, object], ...] = ()

    with transaction.atomic():
        asset = AssetRepository().get_by_code(normalized_asset_code)
        if asset is None:
            asset_row, asset_master_created = AssetMasterModel._default_manager.get_or_create(
                code=normalized_asset_code,
                defaults={
                    "name": "平安银行",
                    "short_name": "平安银行",
                    "asset_type": AssetType.STOCK.value,
                    "exchange": MarketExchange.SZSE.value,
                    "sector": "银行",
                    "industry": "银行",
                    "currency": "CNY",
                    "is_active": True,
                    "extra": {"fixture_source": "m5-valuation-consumer"},
                },
            )
            asset_master_primary_key = asset_row.pk if asset_master_created else None
            if asset_master_created:
                asset_master_fields = _snapshot_asset_fields(AssetMasterModel, asset_row)
            asset = AssetRepository().get_by_code(normalized_asset_code)
        if asset is None or asset.code != normalized_asset_code:
            raise M5PublishedValuationFixtureError(
                "the requested AssetMaster could not be read through AssetRepository"
            )

        pointers_before = _snapshot_pointers(_DATASET_KEYS)
        contracts_before = _snapshot_catalog_rows(
            table="contract",
            model=DatasetContractModel,
            dataset_keys=_DATASET_KEYS,
        )
        policies_before = _snapshot_catalog_rows(
            table="policy",
            model=DatasetPublicationPolicyModel,
            dataset_keys=_DATASET_KEYS,
        )
        market_state = prepare_m5_market_consumer_state(
            tmp_path=artifact_root,
            governance_root=governance_root,
            clocks=MarketConsumerClocks(
                closed_session=trade_date,
                price_observed_at=cn_market_session_close_utc(trade_date),
                valuation_observed_at=cn_market_session_close_utc(trade_date),
                quote_snapshot_at=source_observed_at,
                available_at=available_at,
                fetched_at=fetched_at,
            ),
            price=PriceSeed(
                normalized_asset_code,
                trade_date,
                open=12.1,
                high=12.5,
                low=12.0,
                close=12.34,
                volume=1000.0,
                amount=12340.0,
            ),
            quotes=(
                QuoteSeed(DECISION_ASSET_CODES[0], 4.0),
                QuoteSeed(DECISION_ASSET_CODES[1], 4000.0),
                QuoteSeed(normalized_asset_code, 12.34),
            ),
            valuation=ValuationSeed(
                normalized_asset_code,
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
            base_url=base_url,
            snapshot_asset_code=normalized_asset_code,
            source_name=source_name,
        )
        financial_state = prepare_m5_financial_consumer_state(
            artifact_root,
            base_url=base_url,
            asset_code=normalized_asset_code,
            source_name=source_name,
            period_type="quarterly",
            period_end=period_end,
            report_date=report_date,
            announced_at=announced_at,
            available_at=available_at,
            metrics=metric_seeds,
        )
        pointers_after = _snapshot_pointers(_DATASET_KEYS)
        contracts_after = _snapshot_catalog_rows(
            table="contract",
            model=DatasetContractModel,
            dataset_keys=_DATASET_KEYS,
        )
        policies_after = _snapshot_catalog_rows(
            table="policy",
            model=DatasetPublicationPolicyModel,
            dataset_keys=_DATASET_KEYS,
        )

    if (
        market_state is None
        or financial_state is None
        or len(pointers_before) != len(_DATASET_KEYS)
        or len(pointers_after) != len(_DATASET_KEYS)
    ):
        raise M5PublishedValuationFixtureError("fixture transaction returned incomplete state")
    return M5PublishedValuationFixture(
        base_url=base_url,
        requested_asset_code=normalized_asset_code,
        source_name=source_name,
        market_state=market_state,
        financial_state=financial_state,
        pointers_before=pointers_before,
        pointers_after=pointers_after,
        contracts_before=contracts_before,
        contracts_after=contracts_after,
        policies_before=policies_before,
        policies_after=policies_after,
        asset_master_created=asset_master_created,
        asset_master_primary_key=asset_master_primary_key,
        asset_master_fields=asset_master_fields,
    )


def _publication_ids(state: M5PublishedValuationFixture) -> dict[str, str]:
    """Return the exact publication created for each current dataset pointer."""

    return {
        "equity.price.bar": state.market_state.price_publication_id,
        "equity.quote.snapshot": state.market_state.quote_publication_id,
        "equity.valuation.fact": state.market_state.valuation_publication_id,
        "equity.financial.fact": str(state.financial_state.publication.publication_id),
    }


def _restore_pointers(
    *,
    state: M5PublishedValuationFixture,
) -> None:
    """Restore only pointers still owned by this fixture; fail on concurrent changes."""

    from apps.data_center.infrastructure.publication_models import (
        CanonicalPublicationPointerModel,
    )

    after_by_dataset = {item.dataset_key: item for item in state.pointers_after}
    if set(after_by_dataset) != set(_DATASET_KEYS):
        raise M5PublishedValuationFixtureError("post-fixture pointer snapshot is incomplete")
    for snapshot in state.pointers_before:
        expected_after = after_by_dataset[snapshot.dataset_key]
        current = CanonicalPublicationPointerModel._default_manager.filter(
            dataset_key=snapshot.dataset_key,
            publication_key="current",
        ).first()
        if current is None or (
            current.pointer_id != expected_after.pointer_id
            or current.publication_id != expected_after.publication_id
            or current.publication_hash != expected_after.publication_hash
            or current.activation_id != expected_after.activation_id
            or current.updated_at != expected_after.updated_at
        ):
            raise M5PublishedValuationFixtureError(
                f"current pointer changed outside this fixture: {snapshot.dataset_key}"
            )
        if not snapshot.existed:
            deleted, _details = CanonicalPublicationPointerModel._default_manager.filter(
                pointer_id=expected_after.pointer_id,
                dataset_key=snapshot.dataset_key,
                publication_key="current",
                publication_id=expected_after.publication_id,
                publication_hash=expected_after.publication_hash,
                activation_id=expected_after.activation_id,
                updated_at=expected_after.updated_at,
            ).delete()
            if deleted != 1:
                raise M5PublishedValuationFixtureError(
                    f"fixture current pointer could not be removed: {snapshot.dataset_key}"
                )
            continue
        updated = CanonicalPublicationPointerModel._default_manager.filter(
            pointer_id=expected_after.pointer_id,
            dataset_key=snapshot.dataset_key,
            publication_key="current",
            publication_id=expected_after.publication_id,
            publication_hash=expected_after.publication_hash,
            activation_id=expected_after.activation_id,
            updated_at=expected_after.updated_at,
        ).update(
            publication_id=snapshot.publication_id,
            publication_hash=snapshot.publication_hash,
            activation_id=snapshot.activation_id,
            updated_at=snapshot.updated_at,
        )
        if updated != 1:
            raise M5PublishedValuationFixtureError(
                f"pre-fixture current pointer could not be restored: {snapshot.dataset_key}"
            )


def _restore_catalog_rows(
    *,
    model: type[Model],
    table: Literal["contract", "policy"],
    dataset_keys: tuple[str, ...],
    snapshots: tuple[_CatalogRowSnapshot, ...],
    expected_after: tuple[_CatalogRowSnapshot, ...],
) -> None:
    """Restore exact catalog rows only while their post-fixture snapshot is unchanged."""

    manager = model._default_manager
    table_snapshots = tuple(item for item in snapshots if item.table == table)
    table_after = tuple(item for item in expected_after if item.table == table)
    current_after = _snapshot_catalog_rows(
        table=table,
        model=model,
        dataset_keys=dataset_keys,
    )
    if current_after != table_after:
        raise M5PublishedValuationFixtureError(
            f"{table} catalog changed outside this fixture; refusing cleanup"
        )
    prior_pks = {item.primary_key for item in table_snapshots}
    created_pks = tuple(
        item.primary_key for item in table_after if item.primary_key not in prior_pks
    )
    if created_pks:
        created_rows = manager.filter(
            pk__in=created_pks,
            dataset_key__in=dataset_keys,
        )
        if created_rows.count() != len(created_pks):
            raise M5PublishedValuationFixtureError(
                f"fixture-created {table} catalog row disappeared before cleanup"
            )
        for relation in model._meta.related_objects:
            related_model = relation.related_model
            foreign_key_attname = relation.field.attname
            if related_model._default_manager.filter(
                **{f"{foreign_key_attname}__in": created_pks}
            ).exists():
                raise M5PublishedValuationFixtureError(
                    f"fixture-created {table} catalog row gained a related row"
                )
        created_rows.delete()
        if manager.filter(pk__in=created_pks).exists():
            raise M5PublishedValuationFixtureError(
                f"fixture-created {table} catalog row could not be removed"
            )
    for snapshot in table_snapshots:
        restored = manager.filter(pk=snapshot.primary_key).update(**dict(snapshot.fields))
        if restored != 1:
            raise M5PublishedValuationFixtureError(
                f"pre-fixture {table} catalog row could not be restored"
            )


def _delete_created_asset_master(state: M5PublishedValuationFixture) -> None:
    """Remove only the exact AssetMaster created by this fixture, with no cascades."""

    if not state.asset_master_created:
        return
    from apps.data_center.infrastructure.models import AssetMasterModel

    row = AssetMasterModel._default_manager.filter(
        pk=state.asset_master_primary_key,
        code=state.requested_asset_code,
    ).first()
    if row is None:
        raise M5PublishedValuationFixtureError("fixture-created AssetMaster disappeared")
    current_fields = tuple(
        (field.attname, deepcopy(getattr(row, field.attname)))
        for field in AssetMasterModel._meta.concrete_fields
        if not field.primary_key
    )
    if current_fields != state.asset_master_fields:
        raise M5PublishedValuationFixtureError(
            "fixture-created AssetMaster changed outside this fixture; refusing deletion"
        )
    for relation in AssetMasterModel._meta.related_objects:
        related_model = relation.related_model
        foreign_key_attname = relation.field.attname
        if related_model._default_manager.filter(**{foreign_key_attname: row.pk}).exists():
            raise M5PublishedValuationFixtureError(
                "fixture-created AssetMaster gained a related row; refusing cascade cleanup"
            )
    row.delete()


def cleanup_m5_published_valuation_fixture(
    *,
    base_url: str,
    state: M5PublishedValuationFixture,
) -> None:
    """Restore old pointers/catalog and delete only this fixture's exact rows."""

    require_m5_valuation_fixture_database(base_url=base_url)
    if base_url != state.base_url:
        raise M5PublishedValuationFixtureError("cleanup base URL differs from fixture admission")

    from django.db import transaction

    from apps.data_center.infrastructure.catalog_models import (
        DatasetContractModel,
        DatasetPublicationPolicyModel,
    )
    from apps.data_center.infrastructure.models import (
        FinancialFactModel,
        PriceBarModel,
        QuoteSnapshotModel,
        ValuationFactModel,
    )
    from apps.data_center.infrastructure.publication_models import (
        CanonicalPublicationModel,
        CoverageSnapshotModel,
        PublicationMemberModel,
    )

    publication_ids = _publication_ids(state)
    publication_id_values = tuple(publication_ids.values())
    fact_models: dict[str, type[Model]] = {
        "equity.price.bar": PriceBarModel,
        "equity.quote.snapshot": QuoteSnapshotModel,
        "equity.valuation.fact": ValuationFactModel,
        "equity.financial.fact": FinancialFactModel,
    }

    with transaction.atomic():
        _restore_pointers(state=state)

        publications = tuple(
            CanonicalPublicationModel._default_manager.filter(
                publication_id__in=publication_id_values
            )
        )
        if {str(item.publication_id) for item in publications} != set(publication_id_values):
            raise M5PublishedValuationFixtureError(
                "one or more fixture publications disappeared before cleanup"
            )
        members = tuple(
            PublicationMemberModel._default_manager.filter(publication_id__in=publication_id_values)
        )
        if any(
            member.dataset_key not in fact_models
            or member.source != state.source_name
            or member.fact_table != fact_models[member.dataset_key]._meta.db_table
            for member in members
        ):
            raise M5PublishedValuationFixtureError(
                "fixture publication contains an unexpected member or fact table"
            )
        for publication in publications:
            matching_members = tuple(
                member
                for member in members
                if str(member.publication_id) == str(publication.publication_id)
            )
            if publication.member_count != len(matching_members) or not matching_members:
                raise M5PublishedValuationFixtureError(
                    "fixture publication member count changed before cleanup"
                )
        for dataset_key, model in fact_models.items():
            selected_members = tuple(
                member for member in members if member.dataset_key == dataset_key
            )
            fact_pks = tuple(member.fact_pk for member in selected_members)
            if not fact_pks:
                continue
            matching_rows = tuple(
                model._default_manager.filter(
                    pk__in=fact_pks,
                    source=state.source_name,
                ).values_list("pk", flat=True)
            )
            if {str(pk) for pk in matching_rows} != set(fact_pks):
                raise M5PublishedValuationFixtureError(
                    f"fixture fact rows changed before cleanup: {dataset_key}"
                )

        PublicationMemberModel._default_manager.filter(
            publication_id__in=publication_id_values
        ).delete()
        CoverageSnapshotModel._default_manager.filter(
            publication_id__in=publication_id_values
        ).delete()
        CanonicalPublicationModel._default_manager.filter(
            publication_id__in=publication_id_values
        ).delete()
        for dataset_key, model in fact_models.items():
            selected_members = tuple(
                member for member in members if member.dataset_key == dataset_key
            )
            fact_pks = tuple(member.fact_pk for member in selected_members)
            if fact_pks:
                model._default_manager.filter(
                    pk__in=fact_pks,
                    source=state.source_name,
                ).delete()

        _restore_catalog_rows(
            model=DatasetContractModel,
            table="contract",
            dataset_keys=_DATASET_KEYS,
            snapshots=state.contracts_before,
            expected_after=state.contracts_after,
        )
        _restore_catalog_rows(
            model=DatasetPublicationPolicyModel,
            table="policy",
            dataset_keys=_DATASET_KEYS,
            snapshots=state.policies_before,
            expected_after=state.policies_after,
        )
        _delete_created_asset_master(state)


__all__ = [
    "M5PublishedValuationFixture",
    "M5PublishedValuationFixtureError",
    "cleanup_m5_published_valuation_fixture",
    "prepare_m5_published_valuation_fixture",
]
