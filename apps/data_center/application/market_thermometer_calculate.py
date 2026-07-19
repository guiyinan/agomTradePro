"""Market thermometer snapshot calculation use case."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, timedelta
from typing import Any

from apps.data_center.domain.entities import (
    MacroFact,
    MarketThermometerComponentScore,
    MarketThermometerConfig,
    MarketThermometerSnapshot,
)
from apps.data_center.domain.protocols import (
    MacroFactRepositoryProtocol,
    MarketThermometerConfigRepositoryProtocol,
    MarketThermometerSnapshotRepositoryProtocol,
    MarketThermometerUserOverrideRepositoryProtocol,
)
from apps.data_center.domain.rules import (
    clamp_score_0_100,
    compute_percentile_score,
    compute_rate_of_change,
    determine_market_thermometer_band,
    market_indicator_is_stale,
    normalize_signed_value,
)

from ._market_thermometer_runtime import resolve_as_of_date
from .market_thermometer_provenance import append_component_provenance
from .market_thermometer_specs import (
    MARKET_COMPONENT_SPECS,
    MARKET_NEWS_POSITIVE_RATIO_CODE,
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

    def execute(
        self,
        *,
        as_of_date: date | None = None,
        persist: bool = True,
        persist_blocked: bool = True,
    ) -> MarketThermometerSnapshot:
        """Calculate a fresh snapshot and persist it."""

        target_date = as_of_date or resolve_as_of_date()
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
        if persist and (persist_blocked or not snapshot.must_not_use_for_decision):
            return self._snapshot_repo.save(snapshot)
        return snapshot

    def build_current_payload(
        self,
        *,
        user_id: int | None = None,
        use_personal_thresholds: bool = True,
        as_of_date: date | None = None,
        auto_calculate: bool = True,
    ) -> dict[str, Any]:
        """Return the current payload enriched with threshold source metadata."""

        config = self._config_repo.load()
        if as_of_date is None:
            target_date = resolve_as_of_date()
            snapshot = self._snapshot_repo.get_by_date(target_date)
            if self._should_refresh_snapshot(
                snapshot=snapshot,
                target_date=target_date,
                auto_calculate=auto_calculate,
            ):
                snapshot = self.execute(as_of_date=target_date)
            if snapshot is None:
                snapshot = self._find_latest_snapshot_on_or_before(
                    target_date=target_date,
                    history_days=max(config.long_window, 180),
                )
        else:
            target_date = as_of_date
            snapshot = self._snapshot_repo.get_by_date(target_date)
            if self._should_refresh_snapshot(
                snapshot=snapshot,
                target_date=target_date,
                auto_calculate=auto_calculate,
            ):
                snapshot = self.execute(as_of_date=target_date)
        if snapshot is None:
            snapshot = self._find_latest_snapshot_on_or_before(
                target_date=target_date,
                history_days=max(config.long_window, 180),
            )
        if snapshot is None:
            return {
                "observed_at": None,
                "score": 0.0,
                "band": "cold",
                "effective_band": "cold",
                "overheating_risk": False,
                "avoid_chasing": False,
                "threshold_source": "system",
                "thresholds": self._config_repo.load().thresholds.to_dict(),
                "components": [],
                "trigger_reasons": [],
                "stale_components": [],
                "missing_components": [],
                "must_not_use_for_decision": True,
                "blocked_reason": "暂无市场温度计快照。",
            }

        latest_snapshot = snapshot
        snapshot = self._resolve_display_snapshot(
            snapshot=snapshot,
            history_days=max(config.long_window, 180),
        )
        threshold_source = "system"
        thresholds = config.thresholds
        if use_personal_thresholds and user_id is not None:
            override = self._override_repo.get_by_user_id(user_id)
            if override is not None:
                thresholds = override.thresholds
                threshold_source = "user_override"
        payload = snapshot.to_dict()
        payload["threshold_source"], payload["thresholds"] = threshold_source, thresholds.to_dict()
        payload["score_available"], payload["fallback_used"] = (
            self._snapshot_score_available(snapshot),
            latest_snapshot.observed_at != snapshot.observed_at,
        )
        payload["latest_snapshot_observed_at"] = latest_snapshot.observed_at.isoformat()
        payload["effective_band"] = determine_market_thermometer_band(
            payload["score"],
            warm_threshold=thresholds.warm_threshold,
            hot_threshold=thresholds.hot_threshold,
            overheat_threshold=thresholds.overheat_threshold,
            extreme_threshold=thresholds.extreme_threshold,
        )
        payload["overheating_risk"] = payload["effective_band"] in {
            "overheat",
            "extreme",
        }
        payload["avoid_chasing"] = payload["effective_band"] in {
            "hot",
            "overheat",
            "extreme",
        }
        append_component_provenance(
            payload, macro_repo=self._macro_repo, observed_at=snapshot.observed_at
        )
        return payload

    @staticmethod
    def _should_refresh_snapshot(
        *,
        snapshot: MarketThermometerSnapshot | None,
        target_date: date,
        auto_calculate: bool,
    ) -> bool:
        """Return whether the current request should calculate a fresh snapshot."""

        if not auto_calculate:
            return False
        if snapshot is None:
            return True
        return snapshot.observed_at < target_date

    def _resolve_display_snapshot(
        self,
        *,
        snapshot: MarketThermometerSnapshot,
        history_days: int,
    ) -> MarketThermometerSnapshot:
        """Prefer a richer historical snapshot when today's chain is materially degraded."""

        fallback = self._find_latest_score_snapshot(
            exclude_observed_at=snapshot.observed_at,
            history_days=history_days,
            max_observed_at=snapshot.observed_at,
        )
        if fallback is None:
            return snapshot

        should_fallback = not self._snapshot_score_available(snapshot) or (
            snapshot.must_not_use_for_decision
            and fallback.valid_component_count > snapshot.valid_component_count
        )
        if not should_fallback:
            return snapshot

        return dataclasses.replace(
            fallback,
            must_not_use_for_decision=True,
            blocked_reason=self._build_fallback_blocked_reason(
                latest_snapshot=snapshot,
                fallback_snapshot=fallback,
            ),
        )

    def _find_latest_score_snapshot(
        self,
        *,
        exclude_observed_at: date,
        history_days: int,
        max_observed_at: date | None = None,
    ) -> MarketThermometerSnapshot | None:
        """Return the newest snapshot that still carries a displayable score."""

        for item in self._snapshot_repo.list_history(days=history_days):
            if item.observed_at == exclude_observed_at:
                continue
            if max_observed_at is not None and item.observed_at > max_observed_at:
                continue
            if self._snapshot_score_available(item):
                return item
        return None

    def _find_latest_snapshot_on_or_before(
        self,
        *,
        target_date: date,
        history_days: int,
    ) -> MarketThermometerSnapshot | None:
        """Return the newest snapshot that is not later than the decision-safe date."""

        for item in self._snapshot_repo.list_history(days=history_days):
            if item.observed_at <= target_date:
                return item
        return None

    @staticmethod
    def _snapshot_score_available(snapshot: MarketThermometerSnapshot) -> bool:
        """Return whether one snapshot should show its numeric score in UI."""

        return not (snapshot.must_not_use_for_decision and snapshot.valid_component_count <= 0)

    @staticmethod
    def _build_fallback_blocked_reason(
        *,
        latest_snapshot: MarketThermometerSnapshot,
        fallback_snapshot: MarketThermometerSnapshot,
    ) -> str:
        """Explain why UI is showing an older score-bearing snapshot."""

        parts: list[str] = []
        if latest_snapshot.blocked_reason:
            parts.append(latest_snapshot.blocked_reason.strip())
        parts.append(
            "已回退展示最近有效快照 "
            f"{fallback_snapshot.observed_at.isoformat()}，避免将断链结果显示为 0.0。"
        )
        return " ".join(parts)

    def list_history(self, *, days: int = 90) -> list[dict[str, Any]]:
        """Return history payload ordered by observed date ascending."""

        target_date = resolve_as_of_date()
        return [
            {
                "observed_at": item.observed_at.isoformat(),
                "score": item.score,
                "band": item.band,
            }
            for item in reversed(self._snapshot_repo.list_history(days=days))
            if item.observed_at <= target_date
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
