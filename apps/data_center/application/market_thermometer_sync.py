"""Market thermometer input synchronization use case."""

from __future__ import annotations

import dataclasses
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any, Generic, TypeVar

from apps.data_center.domain.entities import MacroFact, ProviderConfig, RawAudit
from apps.data_center.domain.enums import DataQualityStatus
from apps.data_center.domain.protocols import (
    MacroFactRepositoryProtocol,
    NewsRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    RawAuditRepositoryProtocol,
    UnifiedDataProviderProtocol,
)

from ._market_thermometer_runtime import (
    provider_timeout_overrides,
    provider_timeout_seconds,
    resolve_as_of_date,
)
from .macro_fact_governance import MacroFactGovernanceNormalizer
from .market_thermometer_specs import (
    DEFAULT_MARKET_DATA_SOURCE_TYPES,
    DEFAULT_NEWS_SOURCE_TYPES,
    ETF_MAIN_FLOW_CODE,
    ETF_SIZE_FLOW_CODE,
    MARKET_COMPONENT_SPECS,
    MARKET_NEWS_POSITIVE_RATIO_CODE,
    MARKET_THERMOMETER_CONSENSUS_SOURCE,
    MARKET_THERMOMETER_SOURCE_TOLERANCE,
    RECOVERABLE_THERMOMETER_EXCEPTION_NAMES,
    RECOVERABLE_THERMOMETER_EXCEPTIONS,
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


def _is_recoverable_thermometer_exception(exc: Exception) -> bool:
    """Return whether one provider failure should degrade instead of aborting the chain."""

    return isinstance(exc, RECOVERABLE_THERMOMETER_EXCEPTIONS) or (
        exc.__class__.__name__ in RECOVERABLE_THERMOMETER_EXCEPTION_NAMES
    )


_ProviderResult = TypeVar("_ProviderResult")


@dataclass(frozen=True)
class _ProviderCallSuccess(Generic[_ProviderResult]):
    value: _ProviderResult


@dataclass(frozen=True)
class _ProviderCallFailure:
    error: Exception


def _provider_failure_code(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "market_thermometer_provider_timeout"
    return "market_thermometer_provider_failed"


def _run_market_thermometer_provider_call(
    fetcher: Callable[[], _ProviderResult],
    *,
    capability: str,
    timeout_seconds: float | None = None,
) -> _ProviderResult:
    """Run one provider call with a bounded wait so sync jobs degrade quickly."""

    timeout = timeout_seconds if timeout_seconds is not None else provider_timeout_seconds()
    result_queue: queue.Queue[_ProviderCallSuccess[_ProviderResult] | _ProviderCallFailure] = (
        queue.Queue(maxsize=1)
    )

    def _worker() -> None:
        try:
            result_queue.put(_ProviderCallSuccess(fetcher()))
        except Exception as exc:
            result_queue.put(_ProviderCallFailure(exc))

    thread = threading.Thread(
        target=_worker,
        name=f"market-thermometer-{capability}",
        daemon=True,
    )
    thread.start()

    try:
        outcome = result_queue.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError("market_thermometer_provider_timeout") from exc

    if isinstance(outcome, _ProviderCallFailure):
        raise outcome.error
    return outcome.value


class SyncMarketThermometerInputsUseCase:
    """Fetch and persist market thermometer input series."""

    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        macro_repo: MacroFactRepositoryProtocol,
        news_repo: NewsRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        macro_normalizer: MacroFactGovernanceNormalizer,
    ) -> None:
        self._provider_repo = provider_repo
        self._provider_registry = provider_registry
        self._macro_repo = macro_repo
        self._news_repo = news_repo
        self._raw_audit_repo = raw_audit_repo
        self._macro_normalizer = macro_normalizer

    def execute(self, *, as_of_date: date | None = None) -> dict[str, Any]:
        """Sync daily market-heat inputs for the requested date."""

        target_date = as_of_date or resolve_as_of_date()
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
            if component_key == "etf_net_flow":
                results.extend(
                    self._sync_etf_net_flow_component(
                        component_key=component_key,
                        spec=spec,
                        start_date=start_date,
                        end_date=end_date,
                        providers=market_providers,
                    )
                )
                continue
            for config, provider in market_providers:
                provider_name = provider.provider_name()
                timeout_seconds = provider_timeout_overrides().get(component_key)
                try:
                    fetch_macro_series = partial(
                        provider.fetch_macro_series, spec["indicator_code"], start_date, end_date
                    )
                    facts = _run_market_thermometer_provider_call(
                        fetch_macro_series,
                        capability=f"{component_key}_macro_sync",
                        timeout_seconds=timeout_seconds,
                    )
                    normalized = self._macro_normalizer.normalize_many(
                        facts,
                        source_type=config.source_type,
                        provider_name=provider_name,
                    )
                    if not normalized:
                        self._raw_audit_repo.log(
                            _build_market_audit(
                                provider_name=provider_name,
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
                                "provider": provider_name,
                                "stored_count": 0,
                                "status": "no_data",
                            }
                        )
                        continue
                    stored_count = self._macro_repo.bulk_upsert(normalized)
                    self._raw_audit_repo.log(
                        _build_market_audit(
                            provider_name=provider_name,
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
                            "provider": provider_name,
                            "stored_count": stored_count,
                            "status": "success",
                        }
                    )
                    break
                except Exception as exc:
                    if not _is_recoverable_thermometer_exception(exc):
                        raise
                    self._raw_audit_repo.log(
                        _build_market_audit(
                            provider_name=provider_name,
                            capability="market_thermometer_sync",
                            request_params={
                                "indicator_code": spec["indicator_code"],
                                "start": start_date.isoformat(),
                                "end": end_date.isoformat(),
                            },
                            status="error",
                            row_count=0,
                            error_message=_provider_failure_code(exc),
                        )
                    )
                    results.append(
                        {
                            "component": component_key,
                            "provider": provider_name,
                            "stored_count": 0,
                            "status": "error",
                            "error": _provider_failure_code(exc),
                        }
                    )

        news_provider = self._resolve_provider(DEFAULT_NEWS_SOURCE_TYPES)
        if news_provider is not None:
            config, provider = news_provider
            provider_name = provider.provider_name()
            try:
                news_items = _run_market_thermometer_provider_call(
                    lambda: provider.fetch_news("", limit=200),
                    capability="market_news_sync",
                )
                normalized_news = [
                    dataclasses.replace(
                        item,
                        asset_code="",
                        source=config.source_type,
                        extra={
                            **dict(getattr(item, "extra", {}) or {}),
                            "source_type": config.source_type,
                            "provider_name": provider_name,
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
                                "provider_name": provider_name,
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
                                    "provider_name": provider_name,
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
                                    "provider_name": provider_name,
                                },
                            )
                        )
                normalized_metrics = self._macro_normalizer.normalize_many(
                    macro_facts,
                    source_type=config.source_type,
                    provider_name=provider_name,
                )
                stored_metrics = self._macro_repo.bulk_upsert(normalized_metrics)
                total_stored = stored_news + stored_metrics
                result_status = "success" if total_stored > 0 else "no_data"
                self._raw_audit_repo.log(
                    _build_market_audit(
                        provider_name=provider_name,
                        capability="market_thermometer_news_sync",
                        request_params={"date": target_date.isoformat(), "asset_code": ""},
                        status="ok" if total_stored > 0 else "no_data",
                        row_count=total_stored,
                    )
                )
                results.append(
                    {
                        "component": "market_news",
                        "provider": provider_name,
                        "stored_count": total_stored,
                        "status": result_status,
                    }
                )
            except Exception as exc:
                if not _is_recoverable_thermometer_exception(exc):
                    raise
                self._raw_audit_repo.log(
                    _build_market_audit(
                        provider_name=provider_name,
                        capability="market_thermometer_news_sync",
                        request_params={"date": target_date.isoformat(), "asset_code": ""},
                        status="error",
                        row_count=0,
                        error_message=_provider_failure_code(exc),
                    )
                )
                results.append(
                    {
                        "component": "market_news",
                        "provider": provider_name,
                        "stored_count": 0,
                        "status": "error",
                        "error": _provider_failure_code(exc),
                    }
                )

        return {"as_of_date": target_date.isoformat(), "results": results}

    def _sync_etf_net_flow_component(
        self,
        *,
        component_key: str,
        spec: dict[str, Any],
        start_date: date,
        end_date: date,
        providers: list[tuple[ProviderConfig, UnifiedDataProviderProtocol]],
    ) -> list[dict[str, Any]]:
        """Sync canonical ETF flow from main-flow sources, then size-flow proxy fallback."""

        results = self._sync_verified_component(
            component_key=component_key,
            spec=spec,
            start_date=start_date,
            end_date=end_date,
            providers=providers,
            indicator_code=ETF_MAIN_FLOW_CODE,
            output_indicator_code=spec["indicator_code"],
            consensus_extra={
                "primary_indicator": ETF_MAIN_FLOW_CODE,
                "flow_family": "etf_main_flow",
            },
        )
        if any(
            item.get("component") == component_key
            and item.get("provider") == MARKET_THERMOMETER_CONSENSUS_SOURCE
            and item.get("status") == "success"
            for item in results
        ):
            return results

        results.extend(
            self._sync_verified_component(
                component_key=component_key,
                spec=spec,
                start_date=start_date,
                end_date=end_date,
                providers=providers,
                indicator_code=ETF_SIZE_FLOW_CODE,
                output_indicator_code=spec["indicator_code"],
                consensus_extra={
                    "primary_indicator": ETF_MAIN_FLOW_CODE,
                    "proxy_indicator": ETF_SIZE_FLOW_CODE,
                    "flow_family": "etf_size_flow_proxy",
                },
                verification_status_override="fallback_proxy",
            )
        )
        return results

    def _sync_verified_component(
        self,
        *,
        component_key: str,
        spec: dict[str, Any],
        start_date: date,
        end_date: date,
        providers: list[tuple[ProviderConfig, UnifiedDataProviderProtocol]],
        indicator_code: str | None = None,
        output_indicator_code: str | None = None,
        consensus_extra: dict[str, Any] | None = None,
        verification_status_override: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch one component from all providers and persist a verified consensus row."""

        results: list[dict[str, Any]] = []
        candidates: list[MacroFact] = []
        candidate_meta: list[dict[str, Any]] = []
        requested_indicator_code = indicator_code or str(spec["indicator_code"])
        timeout_seconds = provider_timeout_overrides().get(component_key)

        for config, provider in providers:
            provider_name = provider.provider_name()
            try:
                fetch_macro_series = partial(
                    provider.fetch_macro_series, requested_indicator_code, start_date, end_date
                )
                facts = _run_market_thermometer_provider_call(
                    fetch_macro_series,
                    capability=f"{component_key}_verified_sync",
                    timeout_seconds=timeout_seconds,
                )
                normalized = self._macro_normalizer.normalize_many(
                    facts,
                    source_type=config.source_type,
                    provider_name=provider_name,
                )
                if not normalized:
                    self._raw_audit_repo.log(
                        _build_market_audit(
                            provider_name=provider_name,
                            capability="market_thermometer_sync",
                            request_params={
                                "indicator_code": requested_indicator_code,
                                "start": start_date.isoformat(),
                                "end": end_date.isoformat(),
                                "verification": "multi_source",
                            },
                            status="no_data",
                            row_count=0,
                        )
                    )
                    results.append(
                        {
                            "component": component_key,
                            "provider": provider_name,
                            "stored_count": 0,
                            "status": "no_data",
                        }
                    )
                    continue

                latest = max(normalized, key=lambda item: item.reporting_period)
                atomic_stored_count = self._macro_repo.bulk_upsert(normalized)
                candidates.append(latest)
                candidate_meta.append(
                    {
                        "provider": provider_name,
                        "source_type": config.source_type,
                        "reporting_period": latest.reporting_period.isoformat(),
                        "value": float(latest.value),
                        "unit": latest.unit,
                    }
                )
                self._raw_audit_repo.log(
                    _build_market_audit(
                        provider_name=provider_name,
                        capability="market_thermometer_sync",
                        request_params={
                            "indicator_code": requested_indicator_code,
                            "start": start_date.isoformat(),
                            "end": end_date.isoformat(),
                            "verification": "multi_source",
                        },
                        status="candidate",
                        row_count=atomic_stored_count,
                    )
                )
                results.append(
                    {
                        "component": component_key,
                        "provider": provider_name,
                        "stored_count": atomic_stored_count,
                        "status": "candidate",
                    }
                )
            except Exception as exc:
                if not _is_recoverable_thermometer_exception(exc):
                    raise
                self._raw_audit_repo.log(
                    _build_market_audit(
                        provider_name=provider_name,
                        capability="market_thermometer_sync",
                        request_params={
                            "indicator_code": requested_indicator_code,
                            "start": start_date.isoformat(),
                            "end": end_date.isoformat(),
                            "verification": "multi_source",
                        },
                        status="error",
                        row_count=0,
                        error_message=_provider_failure_code(exc),
                    )
                )
                results.append(
                    {
                        "component": component_key,
                        "provider": provider_name,
                        "stored_count": 0,
                        "status": "error",
                        "error": _provider_failure_code(exc),
                    }
                )

        if not candidates:
            return results

        consensus = self._build_consensus_fact(
            candidates=candidates,
            candidate_meta=candidate_meta,
            indicator_code=output_indicator_code,
            extra=consensus_extra,
            verification_status_override=verification_status_override,
        )
        if consensus is None:
            self._raw_audit_repo.log(
                _build_market_audit(
                    provider_name=MARKET_THERMOMETER_CONSENSUS_SOURCE,
                    capability="market_thermometer_sync",
                    request_params={
                        "indicator_code": requested_indicator_code,
                        "start": start_date.isoformat(),
                        "end": end_date.isoformat(),
                        "verification": "multi_source",
                        "candidates": candidate_meta,
                    },
                    status="mismatch",
                    row_count=0,
                    error_message="ETF net flow source deviation exceeded tolerance",
                )
            )
            results.append(
                {
                    "component": component_key,
                    "provider": MARKET_THERMOMETER_CONSENSUS_SOURCE,
                    "stored_count": 0,
                    "status": "mismatch",
                    "tolerance": MARKET_THERMOMETER_SOURCE_TOLERANCE,
                }
            )
            return results

        normalized_consensus = self._macro_normalizer.normalize(
            consensus,
            source_type=MARKET_THERMOMETER_CONSENSUS_SOURCE,
            provider_name=MARKET_THERMOMETER_CONSENSUS_SOURCE,
        )
        stored_count = self._macro_repo.bulk_upsert([normalized_consensus])
        self._raw_audit_repo.log(
            _build_market_audit(
                provider_name=MARKET_THERMOMETER_CONSENSUS_SOURCE,
                capability="market_thermometer_sync",
                request_params={
                    "indicator_code": consensus.indicator_code,
                    "input_indicator_code": requested_indicator_code,
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                    "verification": consensus.extra.get("verification_status"),
                    "candidates": candidate_meta,
                },
                status="ok",
                row_count=stored_count,
            )
        )
        results.append(
            {
                "component": component_key,
                "provider": MARKET_THERMOMETER_CONSENSUS_SOURCE,
                "stored_count": stored_count,
                "status": "success",
                "verification_status": consensus.extra.get("verification_status"),
            }
        )
        return results

    def _build_consensus_fact(
        self,
        *,
        candidates: list[MacroFact],
        candidate_meta: list[dict[str, Any]],
        indicator_code: str | None = None,
        extra: dict[str, Any] | None = None,
        verification_status_override: str | None = None,
    ) -> MacroFact | None:
        """Build a canonical fact when providers agree within tolerance."""

        latest_period = max(item.reporting_period for item in candidates)
        comparable = [item for item in candidates if item.reporting_period == latest_period]
        values = [float(item.value) for item in comparable]
        if len(values) >= 2:
            max_abs = max(abs(value) for value in values)
            denominator = max(max_abs, 1.0)
            relative_spread = (max(values) - min(values)) / denominator
            if relative_spread > MARKET_THERMOMETER_SOURCE_TOLERANCE:
                return None
            verification_status = "verified"
        else:
            relative_spread = None
            verification_status = "single_source"
        if verification_status_override is not None:
            verification_status = verification_status_override

        primary = comparable[0]
        return dataclasses.replace(
            primary,
            indicator_code=indicator_code or primary.indicator_code,
            source=MARKET_THERMOMETER_CONSENSUS_SOURCE,
            extra={
                **dict(getattr(primary, "extra", {}) or {}),
                **dict(extra or {}),
                "source_type": MARKET_THERMOMETER_CONSENSUS_SOURCE,
                "provider_name": MARKET_THERMOMETER_CONSENSUS_SOURCE,
                # Inputs are normalized before consensus. The derived row's
                # original unit is therefore its canonical storage unit; raw
                # provider units remain auditable on the atomic facts.
                "original_unit": primary.unit,
                "verification_status": verification_status,
                "source_tolerance": MARKET_THERMOMETER_SOURCE_TOLERANCE,
                "relative_spread": relative_spread,
                "candidates": candidate_meta,
            },
        )

    def _component_sync_window(
        self,
        component_key: str,
        target_date: date,
    ) -> tuple[date, date]:
        spec = MARKET_COMPONENT_SPECS[component_key]
        if spec.get("frequency") == "M":
            return target_date - timedelta(days=365 * 3), target_date
        if component_key in {"turnover", "margin_balance", "etf_net_flow"}:
            return target_date - timedelta(days=7), target_date
        return target_date, target_date

    def _resolve_provider(
        self,
        source_types: tuple[str, ...],
    ) -> tuple[ProviderConfig, UnifiedDataProviderProtocol] | None:
        resolved = self._resolve_providers(source_types)
        if not resolved:
            return None
        return resolved[0]

    def _resolve_providers(
        self,
        source_types: tuple[str, ...],
    ) -> list[tuple[ProviderConfig, UnifiedDataProviderProtocol]]:
        providers = [
            provider
            for provider in self._provider_repo.list_all()
            if provider.is_active and provider.source_type in source_types
        ]
        providers.sort(key=lambda item: (source_types.index(item.source_type), item.priority))
        resolved: list[tuple[ProviderConfig, UnifiedDataProviderProtocol]] = []
        for config in providers:
            provider = self._provider_registry.get_by_id(int(config.id or 0))
            if provider is not None:
                resolved.append((config, provider))
        return resolved
