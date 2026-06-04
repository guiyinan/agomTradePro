"""Market thermometer application use cases."""

from __future__ import annotations

import csv
import dataclasses
import io
from datetime import UTC, date, datetime, timedelta
from typing import Any

from apps.data_center.domain.entities import (
    MacroFact,
    MarketThermometerComponentScore,
    MarketThermometerConfig,
    MarketThermometerSnapshot,
    MarketThermometerThresholds,
    MarketThermometerUserOverride,
    RawAudit,
)
from apps.data_center.domain.enums import DataQualityStatus
from apps.data_center.domain.protocols import (
    MacroFactRepositoryProtocol,
    MarketThermometerConfigRepositoryProtocol,
    MarketThermometerSnapshotRepositoryProtocol,
    MarketThermometerUserOverrideRepositoryProtocol,
    NewsRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    RawAuditRepositoryProtocol,
)
from apps.data_center.domain.rules import (
    clamp_score_0_100,
    compute_percentile_score,
    compute_rate_of_change,
    determine_market_thermometer_band,
    market_indicator_is_stale,
    normalize_signed_value,
)

MARKET_COMPONENT_SPECS: dict[str, dict[str, Any]] = {
    "new_investor_accounts": {
        "label": "新增开户",
        "indicator_code": "CN_A_NEW_INVESTOR_ACCOUNTS",
        "frequency": "M",
    },
    "turnover": {
        "label": "全市场成交额",
        "indicator_code": "CN_A_TOTAL_TURNOVER",
        "frequency": "D",
    },
    "margin_balance": {
        "label": "融资余额",
        "indicator_code": "CN_A_MARGIN_BALANCE",
        "frequency": "D",
    },
    "etf_net_flow": {
        "label": "ETF 资金净流入",
        "indicator_code": "CN_A_ETF_NET_FLOW",
        "frequency": "D",
    },
    "market_news_count": {
        "label": "市场新闻热度",
        "indicator_code": "CN_A_MARKET_NEWS_COUNT",
        "frequency": "D",
    },
    "market_news_sentiment": {
        "label": "市场新闻情绪",
        "indicator_code": "CN_A_MARKET_NEWS_SENTIMENT",
        "frequency": "D",
    },
}
MARKET_NEWS_POSITIVE_RATIO_CODE = "CN_A_MARKET_NEWS_POSITIVE_RATIO"
DEFAULT_MARKET_DATA_SOURCE_TYPES = ("akshare", "eastmoney", "tushare")
DEFAULT_NEWS_SOURCE_TYPES = ("akshare", "eastmoney")
RECOVERABLE_THERMOMETER_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


def _build_market_audit(
    *,
    provider_name: str,
    capability: str,
    request_params: dict[str, Any],
    status: str,
    row_count: int,
    error_message: str = "",
) -> RawAudit:
    """Build a raw-audit entry for market thermometer jobs."""

    return RawAudit(
        provider_name=provider_name,
        capability=capability,
        request_params=request_params,
        status=status,
        row_count=row_count,
        error_message=error_message,
        fetched_at=datetime.now(UTC),
    )


def _series_to_pairs(series: list[MacroFact]) -> list[tuple[date, float]]:
    """Normalize newest-first MacroFact rows into chronological numeric pairs."""

    ordered = sorted(series, key=lambda item: item.reporting_period)
    return [(item.reporting_period, float(item.value)) for item in ordered]


def _value_days_ago(series: list[tuple[date, float]], days: int, as_of_date: date) -> float | None:
    """Return the most recent series value on or before the target date."""

    target = as_of_date - timedelta(days=days)
    candidates = [value for observed_at, value in series if observed_at <= target]
    return candidates[-1] if candidates else None


def _component_reason(
    label: str,
    *,
    growth_score: float | None = None,
    percentile_score: float | None = None,
    sentiment_score: float | None = None,
) -> str:
    """Build a concise textual explanation for one component score."""

    parts: list[str] = []
    if growth_score is not None:
        parts.append(f"增速分 {growth_score:.1f}")
    if percentile_score is not None:
        parts.append(f"分位分 {percentile_score:.1f}")
    if sentiment_score is not None:
        parts.append(f"情绪分 {sentiment_score:.1f}")
    joined = " / ".join(parts) if parts else "数据可用"
    return f"{label}: {joined}"


class ManageMarketThermometerConfigUseCase:
    """CRUD facade for system-level market thermometer config."""

    def __init__(self, repo: MarketThermometerConfigRepositoryProtocol) -> None:
        self._repo = repo

    def get(self) -> MarketThermometerConfig:
        """Return the active singleton config."""

        return self._repo.load()

    def update(
        self,
        *,
        short_window: int | None = None,
        medium_window: int | None = None,
        long_window: int | None = None,
        monthly_long_window: int | None = None,
        daily_stale_days: int | None = None,
        monthly_stale_days: int | None = None,
        min_valid_components: int | None = None,
        component_weights: dict[str, float] | None = None,
        thresholds: dict[str, float] | None = None,
    ) -> MarketThermometerConfig:
        """Update the singleton config with partial fields."""

        current = self._repo.load()
        next_thresholds = current.thresholds.to_dict()
        if thresholds:
            next_thresholds.update(thresholds)
        updated = MarketThermometerConfig(
            short_window=short_window or current.short_window,
            medium_window=medium_window or current.medium_window,
            long_window=long_window or current.long_window,
            monthly_long_window=monthly_long_window or current.monthly_long_window,
            daily_stale_days=daily_stale_days or current.daily_stale_days,
            monthly_stale_days=monthly_stale_days or current.monthly_stale_days,
            min_valid_components=min_valid_components or current.min_valid_components,
            component_weights=component_weights or dict(current.component_weights),
            thresholds=MarketThermometerThresholds(**next_thresholds),
        )
        return self._repo.save(updated)


class ManageMarketThermometerUserOverrideUseCase:
    """Manage per-user threshold overrides."""

    def __init__(self, repo: MarketThermometerUserOverrideRepositoryProtocol) -> None:
        self._repo = repo

    def get(self, user_id: int) -> MarketThermometerUserOverride | None:
        """Return the override for one user, if present."""

        return self._repo.get_by_user_id(user_id)

    def upsert(
        self,
        *,
        user_id: int,
        warm_threshold: float | None = None,
        hot_threshold: float | None = None,
        overheat_threshold: float | None = None,
        extreme_threshold: float | None = None,
    ) -> MarketThermometerUserOverride:
        """Create or update one user's threshold override."""

        existing = self._repo.get_by_user_id(user_id)
        base = (
            existing.thresholds.to_dict() if existing else MarketThermometerThresholds().to_dict()
        )
        payload = {
            "warm_threshold": (
                warm_threshold if warm_threshold is not None else base["warm_threshold"]
            ),
            "hot_threshold": hot_threshold if hot_threshold is not None else base["hot_threshold"],
            "overheat_threshold": (
                overheat_threshold if overheat_threshold is not None else base["overheat_threshold"]
            ),
            "extreme_threshold": (
                extreme_threshold if extreme_threshold is not None else base["extreme_threshold"]
            ),
        }
        return self._repo.save(
            MarketThermometerUserOverride(
                user_id=user_id,
                thresholds=MarketThermometerThresholds(**payload),
            )
        )

    def delete(self, user_id: int) -> None:
        """Delete one user's override."""

        self._repo.delete(user_id)


class ImportInvestorAccountsUseCase:
    """Import investor-account time series rows into canonical MacroFact storage."""

    def __init__(self, macro_repo: MacroFactRepositoryProtocol) -> None:
        self._macro_repo = macro_repo

    def execute(self, csv_text: str, *, source: str = "manual_import") -> dict[str, Any]:
        """Parse CSV text and upsert investor-account rows.

        Accepted columns:
        - reporting_period / date / month
        - value / accounts / new_accounts
        """

        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        facts: list[MacroFact] = []
        for row in reader:
            raw_period = str(
                row.get("reporting_period") or row.get("date") or row.get("month") or ""
            ).strip()
            raw_value = str(
                row.get("value") or row.get("accounts") or row.get("new_accounts") or ""
            ).strip()
            if not raw_period or not raw_value:
                continue
            normalized_period = raw_period[:10]
            reporting_period = date.fromisoformat(normalized_period)
            value = float(raw_value.replace(",", ""))
            facts.append(
                MacroFact(
                    indicator_code=MARKET_COMPONENT_SPECS["new_investor_accounts"][
                        "indicator_code"
                    ],
                    reporting_period=reporting_period,
                    value=value,
                    unit="户",
                    source=source,
                    quality=DataQualityStatus.VALID,
                    extra={"source_type": source, "provider_name": source},
                )
            )
        stored_count = self._macro_repo.bulk_upsert(facts)
        return {"stored_count": stored_count}


class SyncMarketThermometerInputsUseCase:
    """Fetch and persist market thermometer input series."""

    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_factory,
        macro_repo: MacroFactRepositoryProtocol,
        news_repo: NewsRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        self._provider_repo = provider_repo
        self._provider_factory = provider_factory
        self._macro_repo = macro_repo
        self._news_repo = news_repo
        self._raw_audit_repo = raw_audit_repo

    def execute(self, *, as_of_date: date | None = None) -> dict[str, Any]:
        """Sync daily market-heat inputs for the requested date."""

        target_date = as_of_date or date.today()
        results: list[dict[str, Any]] = []

        market_providers = self._resolve_providers(DEFAULT_MARKET_DATA_SOURCE_TYPES)
        for component_key in (
            "new_investor_accounts",
            "turnover",
            "margin_balance",
            "etf_net_flow",
        ):
            spec = MARKET_COMPONENT_SPECS[component_key]
            start_date, end_date = self._component_sync_window(
                component_key,
                target_date,
            )
            for config, provider in market_providers:
                try:
                    facts = provider.fetch_macro_series(
                        spec["indicator_code"],
                        start_date,
                        end_date,
                    )
                    normalized = [
                        dataclasses.replace(
                            fact,
                            source=config.source_type,
                            extra={
                                **dict(getattr(fact, "extra", {}) or {}),
                                "source_type": config.source_type,
                                "provider_name": provider.provider_name(),
                            },
                        )
                        for fact in facts
                    ]
                    if not normalized:
                        self._raw_audit_repo.log(
                            _build_market_audit(
                                provider_name=provider.provider_name(),
                                capability="market_thermometer_sync",
                                request_params={
                                    "indicator_code": spec["indicator_code"],
                                    "start": start_date.isoformat(),
                                    "end": end_date.isoformat(),
                                },
                                status="no_data",
                                row_count=0,
                            )
                        )
                        results.append(
                            {
                                "component": component_key,
                                "provider": provider.provider_name(),
                                "stored_count": 0,
                                "status": "no_data",
                            }
                        )
                        continue
                    stored_count = self._macro_repo.bulk_upsert(normalized)
                    self._raw_audit_repo.log(
                        _build_market_audit(
                            provider_name=provider.provider_name(),
                            capability="market_thermometer_sync",
                            request_params={
                                "indicator_code": spec["indicator_code"],
                                "start": start_date.isoformat(),
                                "end": end_date.isoformat(),
                            },
                            status="ok",
                            row_count=stored_count,
                        )
                    )
                    results.append(
                        {
                            "component": component_key,
                            "provider": provider.provider_name(),
                            "stored_count": stored_count,
                            "status": "success",
                        }
                    )
                    break
                except RECOVERABLE_THERMOMETER_EXCEPTIONS as exc:
                    self._raw_audit_repo.log(
                        _build_market_audit(
                            provider_name=provider.provider_name(),
                            capability="market_thermometer_sync",
                            request_params={
                                "indicator_code": spec["indicator_code"],
                                "start": start_date.isoformat(),
                                "end": end_date.isoformat(),
                            },
                            status="error",
                            row_count=0,
                            error_message=str(exc),
                        )
                    )
                    results.append(
                        {
                            "component": component_key,
                            "provider": provider.provider_name(),
                            "stored_count": 0,
                            "status": "error",
                            "error": str(exc),
                        }
                    )

        news_provider = self._resolve_provider(DEFAULT_NEWS_SOURCE_TYPES)
        if news_provider is not None:
            config, provider = news_provider
            try:
                news_items = provider.fetch_news("", limit=200)
                normalized_news = [
                    dataclasses.replace(
                        item,
                        asset_code="",
                        source=config.source_type,
                        extra={
                            **dict(getattr(item, "extra", {}) or {}),
                            "source_type": config.source_type,
                            "provider_name": provider.provider_name(),
                        },
                    )
                    for item in news_items
                ]
                stored_news = self._news_repo.bulk_insert(normalized_news)
                aggregated = self._news_repo.aggregate_market_daily(
                    start=target_date, end=target_date
                )
                macro_facts: list[MacroFact] = []
                for item in aggregated:
                    macro_facts.append(
                        MacroFact(
                            indicator_code=MARKET_COMPONENT_SPECS["market_news_count"][
                                "indicator_code"
                            ],
                            reporting_period=item.observed_date,
                            value=float(item.news_count),
                            unit="篇",
                            source=config.source_type,
                            quality=DataQualityStatus.VALID,
                            extra={
                                "source_type": config.source_type,
                                "provider_name": provider.provider_name(),
                            },
                        )
                    )
                    if item.avg_sentiment is not None:
                        macro_facts.append(
                            MacroFact(
                                indicator_code=MARKET_COMPONENT_SPECS["market_news_sentiment"][
                                    "indicator_code"
                                ],
                                reporting_period=item.observed_date,
                                value=float(item.avg_sentiment),
                                unit="score",
                                source=config.source_type,
                                quality=DataQualityStatus.VALID,
                                extra={
                                    "source_type": config.source_type,
                                    "provider_name": provider.provider_name(),
                                },
                            )
                        )
                    if item.positive_ratio is not None:
                        macro_facts.append(
                            MacroFact(
                                indicator_code=MARKET_NEWS_POSITIVE_RATIO_CODE,
                                reporting_period=item.observed_date,
                                value=float(item.positive_ratio),
                                unit="ratio",
                                source=config.source_type,
                                quality=DataQualityStatus.VALID,
                                extra={
                                    "source_type": config.source_type,
                                    "provider_name": provider.provider_name(),
                                },
                            )
                        )
                stored_metrics = self._macro_repo.bulk_upsert(macro_facts)
                self._raw_audit_repo.log(
                    _build_market_audit(
                        provider_name=provider.provider_name(),
                        capability="market_thermometer_news_sync",
                        request_params={"date": target_date.isoformat(), "asset_code": ""},
                        status="ok",
                        row_count=stored_news + stored_metrics,
                    )
                )
                results.append(
                    {
                        "component": "market_news",
                        "provider": provider.provider_name(),
                        "stored_count": stored_news + stored_metrics,
                        "status": "success",
                    }
                )
            except RECOVERABLE_THERMOMETER_EXCEPTIONS as exc:
                self._raw_audit_repo.log(
                    _build_market_audit(
                        provider_name=provider.provider_name(),
                        capability="market_thermometer_news_sync",
                        request_params={"date": target_date.isoformat(), "asset_code": ""},
                        status="error",
                        row_count=0,
                        error_message=str(exc),
                    )
                )
                results.append(
                    {
                        "component": "market_news",
                        "provider": provider.provider_name(),
                        "stored_count": 0,
                        "status": "error",
                        "error": str(exc),
                    }
                )

        return {"as_of_date": target_date.isoformat(), "results": results}

    def _component_sync_window(
        self,
        component_key: str,
        target_date: date,
    ) -> tuple[date, date]:
        spec = MARKET_COMPONENT_SPECS[component_key]
        if spec.get("frequency") == "M":
            return target_date - timedelta(days=365 * 3), target_date
        return target_date, target_date

    def _resolve_provider(self, source_types: tuple[str, ...]):
        resolved = self._resolve_providers(source_types)
        if not resolved:
            return None
        return resolved[0]

    def _resolve_providers(self, source_types: tuple[str, ...]):
        providers = [
            provider
            for provider in self._provider_repo.list_all()
            if provider.is_active and provider.source_type in source_types
        ]
        providers.sort(key=lambda item: (source_types.index(item.source_type), item.priority))
        resolved = []
        for config in providers:
            provider = self._provider_factory.get_by_id(int(config.id or 0))
            if provider is not None:
                resolved.append((config, provider))
        return resolved


class CalculateMarketThermometerUseCase:
    """Calculate and persist a market thermometer snapshot."""

    def __init__(
        self,
        config_repo: MarketThermometerConfigRepositoryProtocol,
        snapshot_repo: MarketThermometerSnapshotRepositoryProtocol,
        override_repo: MarketThermometerUserOverrideRepositoryProtocol,
        macro_repo: MacroFactRepositoryProtocol,
    ) -> None:
        self._config_repo = config_repo
        self._snapshot_repo = snapshot_repo
        self._override_repo = override_repo
        self._macro_repo = macro_repo

    def execute(self, *, as_of_date: date | None = None) -> MarketThermometerSnapshot:
        """Calculate a fresh snapshot and persist it."""

        target_date = as_of_date or date.today()
        config = self._config_repo.load()
        components = [
            self._score_investor_accounts(target_date, config),
            self._score_daily_acceleration_component(target_date, config, "turnover"),
            self._score_daily_acceleration_component(target_date, config, "margin_balance"),
            self._score_daily_acceleration_component(target_date, config, "etf_net_flow"),
            self._score_daily_acceleration_component(target_date, config, "market_news_count"),
            self._score_news_sentiment(target_date, config),
        ]

        valid_components = [
            component
            for component in components
            if not component.is_stale and not component.is_missing
        ]
        total_weight = sum(component.weight for component in valid_components)
        if total_weight > 0:
            score = (
                sum(component.score * component.weight for component in valid_components)
                / total_weight
            )
        else:
            score = 0.0
        score = round(clamp_score_0_100(score), 2)
        band = determine_market_thermometer_band(
            score,
            warm_threshold=config.thresholds.warm_threshold,
            hot_threshold=config.thresholds.hot_threshold,
            overheat_threshold=config.thresholds.overheat_threshold,
            extreme_threshold=config.thresholds.extreme_threshold,
        )
        history = self._snapshot_repo.list_history(days=max(config.long_window, 30))
        previous_by_date = {item.observed_at: item for item in history}
        change_5d = self._compute_change(previous_by_date, target_date, score, 5)
        change_20d = self._compute_change(previous_by_date, target_date, score, 20)
        ordered_reasons = [
            component.reason
            for component in sorted(
                valid_components, key=lambda item: item.score * item.weight, reverse=True
            )
            if component.reason
        ]
        stale_components = [
            component.component_key for component in components if component.is_stale
        ]
        missing_components = [
            component.component_key for component in components if component.is_missing
        ]
        must_not_use_for_decision = len(valid_components) < config.min_valid_components
        blocked_reason = (
            f"有效组件数不足，当前仅 {len(valid_components)} 个，低于要求 {config.min_valid_components} 个。"
            if must_not_use_for_decision
            else ""
        )
        snapshot = MarketThermometerSnapshot(
            observed_at=target_date,
            score=score,
            band=band,
            change_5d=change_5d,
            change_20d=change_20d,
            components=components,
            trigger_reasons=ordered_reasons[:5],
            stale_components=stale_components,
            missing_components=missing_components,
            valid_component_count=len(valid_components),
            data_source=(
                "calculated" if not stale_components and not missing_components else "degraded"
            ),
            must_not_use_for_decision=must_not_use_for_decision,
            blocked_reason=blocked_reason,
            calculated_at=datetime.now(UTC),
        )
        return self._snapshot_repo.save(snapshot)

    def build_current_payload(
        self,
        *,
        user_id: int | None = None,
        use_personal_thresholds: bool = True,
        as_of_date: date | None = None,
        auto_calculate: bool = True,
    ) -> dict[str, Any]:
        """Return the current payload enriched with threshold source metadata."""

        if as_of_date is None:
            snapshot = self._snapshot_repo.get_latest()
            target_date = snapshot.observed_at if snapshot is not None else date.today()
            if snapshot is None and auto_calculate:
                snapshot = self.execute(as_of_date=target_date)
        else:
            target_date = as_of_date
            snapshot = self._snapshot_repo.get_by_date(target_date)
            if snapshot is None and auto_calculate:
                snapshot = self.execute(as_of_date=target_date)
        if snapshot is None:
            latest = self._snapshot_repo.get_latest()
            snapshot = latest
        if snapshot is None:
            return {
                "observed_at": None,
                "score": 0.0,
                "band": "cold",
                "threshold_source": "system",
                "thresholds": self._config_repo.load().thresholds.to_dict(),
                "components": [],
                "trigger_reasons": [],
                "stale_components": [],
                "missing_components": [],
                "must_not_use_for_decision": True,
                "blocked_reason": "暂无市场温度计快照。",
            }

        config = self._config_repo.load()
        threshold_source = "system"
        thresholds = config.thresholds
        if use_personal_thresholds and user_id is not None:
            override = self._override_repo.get_by_user_id(user_id)
            if override is not None:
                thresholds = override.thresholds
                threshold_source = "user_override"
        payload = snapshot.to_dict()
        payload["threshold_source"] = threshold_source
        payload["thresholds"] = thresholds.to_dict()
        payload["score_available"] = not (
            bool(payload.get("must_not_use_for_decision", False))
            and int(payload.get("valid_component_count") or 0) <= 0
        )
        payload["effective_band"] = determine_market_thermometer_band(
            payload["score"],
            warm_threshold=thresholds.warm_threshold,
            hot_threshold=thresholds.hot_threshold,
            overheat_threshold=thresholds.overheat_threshold,
            extreme_threshold=thresholds.extreme_threshold,
        )
        return payload

    def list_history(self, *, days: int = 90) -> list[dict[str, Any]]:
        """Return history payload ordered by observed date ascending."""

        return [
            {
                "observed_at": item.observed_at.isoformat(),
                "score": item.score,
                "band": item.band,
            }
            for item in reversed(self._snapshot_repo.list_history(days=days))
        ]

    def _score_investor_accounts(
        self,
        target_date: date,
        config: MarketThermometerConfig,
    ) -> MarketThermometerComponentScore:
        spec = MARKET_COMPONENT_SPECS["new_investor_accounts"]
        series = _series_to_pairs(
            self._macro_repo.get_series(
                spec["indicator_code"],
                start=target_date - timedelta(days=365 * 3),
                end=target_date,
                limit=config.monthly_long_window + 12,
            )
        )
        return self._build_component_from_series(
            component_key="new_investor_accounts",
            label=spec["label"],
            indicator_code=spec["indicator_code"],
            frequency=spec["frequency"],
            series=series,
            target_date=target_date,
            weight=config.component_weights.get("new_investor_accounts", 0.15),
            daily_stale_days=config.daily_stale_days,
            monthly_stale_days=config.monthly_stale_days,
            monthly_long_window=config.monthly_long_window,
            long_window=config.long_window,
            short_window=config.short_window,
            medium_window=config.medium_window,
            monthly_mode=True,
        )

    def _score_daily_acceleration_component(
        self,
        target_date: date,
        config: MarketThermometerConfig,
        component_key: str,
    ) -> MarketThermometerComponentScore:
        spec = MARKET_COMPONENT_SPECS[component_key]
        series = _series_to_pairs(
            self._macro_repo.get_series(
                spec["indicator_code"],
                start=target_date - timedelta(days=config.long_window + 60),
                end=target_date,
                limit=config.long_window + 30,
            )
        )
        return self._build_component_from_series(
            component_key=component_key,
            label=spec["label"],
            indicator_code=spec["indicator_code"],
            frequency=spec["frequency"],
            series=series,
            target_date=target_date,
            weight=config.component_weights.get(component_key, 0.1),
            daily_stale_days=config.daily_stale_days,
            monthly_stale_days=config.monthly_stale_days,
            monthly_long_window=config.monthly_long_window,
            long_window=config.long_window,
            short_window=config.short_window,
            medium_window=config.medium_window,
            monthly_mode=False,
        )

    def _score_news_sentiment(
        self,
        target_date: date,
        config: MarketThermometerConfig,
    ) -> MarketThermometerComponentScore:
        sentiment_spec = MARKET_COMPONENT_SPECS["market_news_sentiment"]
        sentiment_series = _series_to_pairs(
            self._macro_repo.get_series(
                sentiment_spec["indicator_code"],
                start=target_date - timedelta(days=config.long_window + 60),
                end=target_date,
                limit=config.long_window + 30,
            )
        )
        ratio_series = _series_to_pairs(
            self._macro_repo.get_series(
                MARKET_NEWS_POSITIVE_RATIO_CODE,
                start=target_date - timedelta(days=config.long_window + 60),
                end=target_date,
                limit=config.long_window + 30,
            )
        )
        if not sentiment_series:
            return MarketThermometerComponentScore(
                component_key="market_news_sentiment",
                label=sentiment_spec["label"],
                indicator_code=sentiment_spec["indicator_code"],
                score=0.0,
                weight=config.component_weights.get("market_news_sentiment", 0.10),
                is_missing=True,
                reason="市场新闻情绪数据缺失",
            )

        latest_date, latest_value = sentiment_series[-1]
        is_stale, age_days = market_indicator_is_stale(
            latest_date,
            frequency=sentiment_spec["frequency"],
            as_of_date=target_date,
            daily_stale_days=config.daily_stale_days,
            monthly_stale_days=config.monthly_stale_days,
        )
        percentile_score = compute_percentile_score(
            [value for _, value in sentiment_series[-config.long_window :]],
            latest_value,
        )
        sentiment_score = normalize_signed_value(
            latest_value, negative_bound=-0.5, positive_bound=0.5
        )
        latest_ratio = ratio_series[-1][1] if ratio_series else None
        positive_ratio_score = clamp_score_0_100((latest_ratio or 0.5) * 100.0)
        score = round(
            sentiment_score * 0.4 + positive_ratio_score * 0.3 + percentile_score * 0.3,
            2,
        )
        return MarketThermometerComponentScore(
            component_key="market_news_sentiment",
            label=sentiment_spec["label"],
            indicator_code=sentiment_spec["indicator_code"],
            score=score,
            weight=config.component_weights.get("market_news_sentiment", 0.10),
            current_value=latest_value,
            unit="score",
            percentile_score=percentile_score,
            sentiment_score=sentiment_score,
            positive_ratio_score=positive_ratio_score,
            is_stale=is_stale,
            age_days=age_days,
            reason=_component_reason(
                sentiment_spec["label"],
                percentile_score=percentile_score,
                sentiment_score=sentiment_score,
            ),
        )

    def _build_component_from_series(
        self,
        *,
        component_key: str,
        label: str,
        indicator_code: str,
        frequency: str,
        series: list[tuple[date, float]],
        target_date: date,
        weight: float,
        daily_stale_days: int,
        monthly_stale_days: int,
        monthly_long_window: int,
        long_window: int,
        short_window: int,
        medium_window: int,
        monthly_mode: bool,
    ) -> MarketThermometerComponentScore:
        if not series:
            return MarketThermometerComponentScore(
                component_key=component_key,
                label=label,
                indicator_code=indicator_code,
                score=0.0,
                weight=weight,
                is_missing=True,
                reason=f"{label}数据缺失",
            )

        latest_date, latest_value = series[-1]
        is_stale, age_days = market_indicator_is_stale(
            latest_date,
            frequency=frequency,
            as_of_date=target_date,
            daily_stale_days=daily_stale_days,
            monthly_stale_days=monthly_stale_days,
        )
        values = [value for _, value in series]
        if monthly_mode:
            previous_value = values[-2] if len(values) >= 2 else None
            growth = compute_rate_of_change(latest_value, previous_value)
            growth_score = normalize_signed_value(growth, negative_bound=-0.3, positive_bound=1.0)
            percentile_score = compute_percentile_score(values[-monthly_long_window:], latest_value)
        else:
            value_5d = _value_days_ago(series, short_window, target_date)
            value_20d = _value_days_ago(series, medium_window, target_date)
            growth_5d = compute_rate_of_change(latest_value, value_5d)
            growth_20d = compute_rate_of_change(latest_value, value_20d)
            growth_score = (
                normalize_signed_value(growth_5d, negative_bound=-0.2, positive_bound=0.6)
                + normalize_signed_value(growth_20d, negative_bound=-0.3, positive_bound=1.0)
            ) / 2
            percentile_score = compute_percentile_score(values[-long_window:], latest_value)
        score = round(growth_score * 0.6 + percentile_score * 0.4, 2)
        return MarketThermometerComponentScore(
            component_key=component_key,
            label=label,
            indicator_code=indicator_code,
            score=score,
            weight=weight,
            current_value=latest_value,
            unit=(
                "户"
                if component_key == "new_investor_accounts"
                else ("篇" if component_key == "market_news_count" else "元")
            ),
            growth_score=growth_score,
            percentile_score=percentile_score,
            is_stale=is_stale,
            age_days=age_days,
            reason=_component_reason(
                label, growth_score=growth_score, percentile_score=percentile_score
            ),
        )

    @staticmethod
    def _compute_change(
        history_by_date: dict[date, MarketThermometerSnapshot],
        target_date: date,
        current_score: float,
        days: int,
    ) -> float | None:
        target_previous_date = target_date - timedelta(days=days)
        candidates = [
            snapshot
            for observed_at, snapshot in history_by_date.items()
            if observed_at <= target_previous_date
        ]
        if not candidates:
            return None
        previous = max(candidates, key=lambda item: item.observed_at)
        if previous is None:
            return None
        return round(current_score - previous.score, 2)


def build_market_thermometer_override_payload(
    *,
    config: MarketThermometerConfig,
    override: MarketThermometerUserOverride | None,
) -> dict[str, Any]:
    """Return combined system + override payload for API consumers."""

    effective = override.thresholds if override is not None else config.thresholds
    return {
        "override": override.thresholds.to_dict() if override is not None else None,
        "effective": effective.to_dict(),
        "source": "user_override" if override is not None else "system",
    }
