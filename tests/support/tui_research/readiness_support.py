"""Test-only stored inputs for an isolated TUX-08 consumer fixture.

This helper neither admits a production runtime nor establishes real provider
health, publication authority or a complete readiness result. Financial and
market publications and controlled external calendar input are separate fixture
dependencies. Importing this module does not initialize Django or touch a DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.config_center.infrastructure.decision_runtime_models import (
        DecisionRuntimeStateModel,
    )
    from apps.data_center.domain.entities import MarketThermometerSnapshot
    from apps.data_center.infrastructure.market_thermometer_models import (
        MarketThermometerSnapshotModel,
    )
    from apps.data_center.infrastructure.models import AssetMasterModel, ProviderConfigModel


@dataclass(frozen=True)
class StoredReadinessSupport:
    """Exact rows created in the disposable, single-stock test universe."""

    asset: AssetMasterModel
    runtime: DecisionRuntimeStateModel
    provider: ProviderConfigModel
    thermometer: MarketThermometerSnapshotModel


def require_tux08_sqlite_database() -> None:
    """Require the exact disposable research test database before writing."""

    from tests.support.tui_research.disposable import require_test_database

    require_test_database()


def seed_readiness_support(
    *,
    source_observed_at: datetime,
    closed_session: date,
    snapshot: MarketThermometerSnapshot,
) -> StoredReadinessSupport:
    """Store synthetic support rows without replacing owner read/check functions.

    ``closed_session`` must come from the real calendar resolver under a clearly
    marked controlled external-input fixture. The caller supplies a complete
    thermometer snapshot; this function does not calculate or infer its score.
    The one-stock universe is local test scope, never full-market coverage.
    """

    from django.db import transaction
    from django.utils import timezone

    from apps.config_center.infrastructure.decision_runtime_models import (
        DecisionRuntimeStateModel,
    )
    from apps.data_center.domain.entities import MarketThermometerConfig
    from apps.data_center.domain.enums import DataCapability
    from apps.data_center.infrastructure.market_thermometer_models import (
        MarketThermometerConfigModel,
        MarketThermometerSnapshotModel,
    )
    from apps.data_center.infrastructure.models import (
        AssetMasterModel,
        ProductionCoverageUniverseConfigModel,
        ProviderConfigModel,
    )

    require_tux08_sqlite_database()
    if source_observed_at.utcoffset() is None:
        raise ValueError("synthetic source observation must be timezone-aware")
    if source_observed_at > timezone.now():
        raise ValueError("synthetic source observation cannot be in the future")
    if snapshot.observed_at != closed_session:
        raise ValueError("snapshot must match the resolver's explicit closed session")
    config = MarketThermometerConfig()
    if snapshot.valid_component_count != len(snapshot.components):
        raise ValueError("fixture component count must match its actual rows")

    with transaction.atomic():
        if AssetMasterModel.objects.filter(asset_type="stock").exists():
            raise RuntimeError("fixture expects an empty isolated stock universe")
        asset = AssetMasterModel.objects.create(
            code="600000.SH",
            name="隔离研究夹具",
            short_name="研究夹具",
            asset_type="stock",
            exchange="SSE",
            currency="CNY",
            is_active=True,
            extra={"fixture_scope": "tux08-synthetic-consumer-only"},
        )
        ProductionCoverageUniverseConfigModel.objects.update_or_create(
            pk=1,
            defaults={
                "universe_id": "tux08_local_test",
                "asset_type": "stock",
                "exchanges": ["SSE"],
                "include_inactive": False,
                "min_active_asset_count": 1,
                "min_star_market_count": 0,
                "min_chinext_count": 0,
                "min_bse_count": 0,
                "description": "Disposable one-stock consumer fixture, not production coverage",
            },
        )
        runtime, _ = DecisionRuntimeStateModel.objects.update_or_create(
            pk=1,
            defaults={
                "status": "active",
                "reason": "Disposable TUX08 synthetic consumer test state",
                "changed_at": source_observed_at,
                "changed_by": "standalone:tux08-local-fixture",
                "release_ref": "local-synthetic-test-only",
            },
        )
        provider = ProviderConfigModel.objects.create(
            name="tux08_synthetic_stored_health",
            source_type="akshare",
            is_active=True,
            description="Synthetic stored health; no provider request or real health proof",
            extra_config={
                "fixture_scope": "tux08-synthetic-consumer-only",
                "health_metrics_by_dataset": {
                    capability.dataset_key: {
                        "last_status": "healthy",
                        "consecutive_failures": 0,
                        "last_success_at": source_observed_at.isoformat(),
                    }
                    for capability in (
                        DataCapability.HISTORICAL_PRICE,
                        DataCapability.VALUATION,
                        DataCapability.FINANCIAL,
                    )
                },
            },
        )
        # Preseed exact Domain defaults so owner reads do not bootstrap a row.
        MarketThermometerConfigModel.objects.update_or_create(
            pk=1,
            defaults={
                "short_window": config.short_window,
                "medium_window": config.medium_window,
                "long_window": config.long_window,
                "monthly_long_window": config.monthly_long_window,
                "daily_stale_days": config.daily_stale_days,
                "monthly_stale_days": config.monthly_stale_days,
                "min_valid_components": config.min_valid_components,
                "component_weights": dict(config.component_weights),
                "warm_threshold": config.thresholds.warm_threshold,
                "hot_threshold": config.thresholds.hot_threshold,
                "overheat_threshold": config.thresholds.overheat_threshold,
                "extreme_threshold": config.thresholds.extreme_threshold,
            },
        )
        thermometer = MarketThermometerSnapshotModel.objects.create(
            observed_at=snapshot.observed_at,
            score=snapshot.score,
            band=snapshot.band,
            change_5d=snapshot.change_5d,
            change_20d=snapshot.change_20d,
            components=[item.to_dict() for item in snapshot.components],
            trigger_reasons=list(snapshot.trigger_reasons),
            stale_components=list(snapshot.stale_components),
            missing_components=list(snapshot.missing_components),
            valid_component_count=snapshot.valid_component_count,
            data_source="tux08-fixture",
            must_not_use_for_decision=snapshot.must_not_use_for_decision,
            blocked_reason=snapshot.blocked_reason,
        )
    return StoredReadinessSupport(asset, runtime, provider, thermometer)
