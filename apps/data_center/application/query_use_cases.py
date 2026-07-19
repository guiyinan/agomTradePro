"""Read-only query use cases for Data Center."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any

from apps.data_center.application.dtos import (
    AssetResponse,
    LatestQuoteRequest,
    MacroDataPoint,
    MacroSeriesRequest,
    MacroSeriesResponse,
    PriceBarResponse,
    PriceHistoryRequest,
    QuoteResponse,
    ResolveAssetRequest,
)
from apps.data_center.domain.protocols import (
    AssetRepositoryProtocol,
    IndicatorCatalogRepositoryProtocol,
    IndicatorUnitRuleRepositoryProtocol,
    MacroFactRepositoryProtocol,
    PriceBarRepositoryProtocol,
    ProviderRegistryProtocol,
    PublisherCatalogRepositoryProtocol,
    QuoteSnapshotRepositoryProtocol,
)
from apps.data_center.domain.rules import (
    convert_currency_value,
    deduplicate_macro_facts,
    get_macro_age_days,
    is_macro_observation_stale,
    normalize_asset_code,
)

if TYPE_CHECKING:
    from apps.data_center.domain.entities import ProviderHealthSnapshot

CN_MARKET_TZ = timezone(timedelta(hours=8))
CN_MARKET_OPEN = time(9, 30)
CN_MARKET_CLOSE = time(15, 0)
DEFAULT_LATEST_QUOTE_MAX_AGE_HOURS = 4.0


def _previous_weekday(target_date: date) -> date:
    """Return the latest weekday before ``target_date``."""

    previous_day = target_date - timedelta(days=1)
    while previous_day.weekday() >= 5:
        previous_day -= timedelta(days=1)
    return previous_day


def _latest_completed_cn_quote_session(now: datetime) -> date | None:
    """Return the latest completed A-share quote session for non-live periods."""

    local_now = now.astimezone(CN_MARKET_TZ)
    current_date = local_now.date()
    if current_date.weekday() >= 5:
        return _previous_weekday(current_date)
    current_time = local_now.time()
    if current_time < CN_MARKET_OPEN:
        return _previous_weekday(current_date)
    if current_time >= CN_MARKET_CLOSE:
        return current_date
    return None


def _is_cn_listed_asset(asset_code: str) -> bool:
    """Return True for common A-share and mainland ETF quote codes."""

    normalized = asset_code.strip().upper()
    return normalized.endswith((".SH", ".SZ", ".BJ"))


def _storage_value_to_display_value(
    value: float,
    *,
    storage_unit: str,
    display_unit: str,
    multiplier_to_storage: float,
) -> float:
    converted_value, converted_unit = convert_currency_value(
        value,
        storage_unit,
        display_unit,
    )
    if converted_unit == display_unit:
        return converted_value
    if multiplier_to_storage == 0:
        return value
    return value / multiplier_to_storage


def _dedupe_string_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized:
            continue
        key = normalized.upper()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


class GetProviderStatusUseCase:
    """Query live health snapshots from the runtime registry.

    Args:
        registry: Injected ProviderRegistryProtocol implementation.
    """

    def __init__(self, registry: ProviderRegistryProtocol) -> None:
        self._registry = registry

    def execute(self) -> list[ProviderHealthSnapshot]:
        return self._registry.get_all_statuses()


# Phase 2 — Query use cases
# ---------------------------------------------------------------------------


class ResolveAssetUseCase:
    """Resolve a potentially provider-specific ticker to canonical AssetMaster.

    Normalises the input code via domain rules before hitting the repository,
    so callers can pass AKShare / Wind / Baostock codes directly.
    """

    def __init__(self, repo: AssetRepositoryProtocol) -> None:
        self._repo = repo

    def execute(self, request: ResolveAssetRequest) -> AssetResponse | None:
        canonical = normalize_asset_code(request.code, request.source_type)
        asset = self._repo.get_by_code(canonical)
        if asset is None and canonical != request.code:
            # Try the raw code as fallback
            asset = self._repo.get_by_code(request.code)
        if asset is None:
            return None
        return AssetResponse(
            code=asset.code,
            name=asset.name,
            short_name=asset.short_name,
            asset_type=asset.asset_type.value,
            exchange=asset.exchange.value,
            is_active=asset.is_active,
            list_date=asset.list_date,
            sector=asset.sector,
            industry=asset.industry,
            currency=asset.currency,
        )


class QueryMacroSeriesUseCase:
    """Fetch a macro economic time-series by indicator code.

    Enriches the response with indicator metadata from IndicatorCatalog.
    """

    def __init__(
        self,
        fact_repo: MacroFactRepositoryProtocol,
        catalog_repo: IndicatorCatalogRepositoryProtocol,
        unit_rule_repo: IndicatorUnitRuleRepositoryProtocol,
        publisher_repo: PublisherCatalogRepositoryProtocol | None = None,
    ) -> None:
        self._facts = fact_repo
        self._catalog = catalog_repo
        self._unit_rules = unit_rule_repo
        self._publishers = publisher_repo

    def execute(self, request: MacroSeriesRequest) -> MacroSeriesResponse:
        facts = self._facts.get_series(
            indicator_code=request.indicator_code,
            start=request.start,
            end=request.end,
            limit=max(request.limit * 4, request.limit),
        )
        if request.source:
            facts = [f for f in facts if f.source == request.source]
        facts = self._dedupe_facts_by_source_period(facts)[: request.limit]

        catalog = self._catalog.get_by_code(request.indicator_code)
        name_cn = catalog.name_cn if catalog else request.indicator_code
        period_type = catalog.default_period_type if catalog else "M"
        description = catalog.description if catalog else ""
        catalog_extra = dict(catalog.extra or {}) if catalog else {}
        series_semantics = str(catalog_extra.get("series_semantics") or "")
        paired_indicator_code = str(catalog_extra.get("paired_indicator_code") or "")
        chart_policy = str(catalog_extra.get("chart_policy") or "")
        chart_reset_frequency = str(catalog_extra.get("chart_reset_frequency") or "")
        chart_segment_basis = str(catalog_extra.get("chart_segment_basis") or "")
        provenance_class = str(catalog_extra.get("provenance_class") or "").strip()
        provenance_label = _provenance_label_for_class(provenance_class)
        publisher_code, publisher_codes = self._extract_publisher_codes(catalog_extra)
        publisher = self._resolve_publisher_display_name(
            publisher_code=publisher_code,
            publisher_codes=publisher_codes,
            explicit_publisher=str(catalog_extra.get("publisher") or "").strip(),
        )
        access_channel = str(catalog_extra.get("access_channel") or "").strip()
        derivation_method = str(catalog_extra.get("derivation_method") or "").strip()
        upstream_indicator_codes = [
            str(code).strip()
            for code in (catalog_extra.get("upstream_indicator_codes") or [])
            if str(code).strip()
        ]
        is_derived = provenance_class == "derived"
        decision_grade_enabled = self._is_decision_grade_enabled(
            provenance_class=provenance_class,
            catalog_extra=catalog_extra,
        )

        data_points: list[MacroDataPoint]
        data_source = "none"
        freshness_status = "missing"
        decision_grade = "blocked"
        must_not_use_for_decision = True
        blocked_reason = "当前无可用宏观数据。"
        if facts:
            data_source = "data_center_fact"
            as_of_date = request.end
            data_points = [
                self._build_macro_data_point(
                    indicator_code=f.indicator_code,
                    reporting_period=f.reporting_period,
                    value=f.value,
                    unit=f.unit,
                    extra=f.extra or {},
                    source=f.source,
                    quality=f.quality.value,
                    published_at=f.published_at,
                    period_type=period_type,
                    as_of_date=as_of_date,
                    catalog_extra=catalog_extra,
                )
                for f in facts
            ]
        else:
            data_points = []

        if data_points:
            latest = data_points[0]
            if latest.is_stale:
                freshness_status = "stale"
                decision_grade = "degraded"
                blocked_reason = (
                    "最新宏观数据已超过 freshness 阈值，当前结果仅可用于研究，不可直接用于决策。"
                )
            elif not decision_grade_enabled:
                freshness_status = "fresh"
                decision_grade = "research_only"
                blocked_reason = self._build_provenance_blocked_reason(
                    provenance_class=provenance_class,
                    derivation_method=derivation_method,
                )
            else:
                freshness_status = "fresh"
                decision_grade = "decision_safe"
                must_not_use_for_decision = False
                blocked_reason = ""

        latest_reporting_period = data_points[0].reporting_period if data_points else None
        latest_published_at = data_points[0].published_at if data_points else None
        latest_quality = data_points[0].quality if data_points else ""

        return MacroSeriesResponse(
            indicator_code=request.indicator_code,
            name_cn=name_cn,
            period_type=period_type,
            description=description,
            series_semantics=series_semantics,
            paired_indicator_code=paired_indicator_code,
            chart_policy=chart_policy,
            chart_reset_frequency=chart_reset_frequency,
            chart_segment_basis=chart_segment_basis,
            data=data_points,
            total=len(data_points),
            data_source=data_source,
            freshness_status=freshness_status,
            decision_grade=decision_grade,
            must_not_use_for_decision=must_not_use_for_decision,
            blocked_reason=blocked_reason,
            latest_reporting_period=latest_reporting_period,
            latest_published_at=latest_published_at,
            latest_quality=latest_quality,
            provenance_class=provenance_class,
            provenance_label=provenance_label,
            publisher=publisher,
            publisher_code=publisher_code,
            publisher_codes=publisher_codes,
            access_channel=access_channel or (data_points[0].access_channel if data_points else ""),
            derivation_method=derivation_method,
            upstream_indicator_codes=upstream_indicator_codes,
            is_derived=is_derived,
        )

    @staticmethod
    def _dedupe_facts_by_source_period(facts: list[Any]) -> list[Any]:
        """Keep one governed fact per source and reporting period.

        The pre-cutover macro writer used revision 1 for first observations,
        while canonical Data Center ingestion starts at revision 0. Prefer the
        canonical row marked with provider governance metadata so a stale
        legacy projection cannot duplicate or mask a refreshed fact. Different
        sources remain visible when the caller does not request one source.
        """
        return deduplicate_macro_facts(facts, by_source=True)

    def _build_macro_data_point(
        self,
        *,
        indicator_code: str,
        reporting_period: date,
        value: float,
        unit: str,
        extra: dict[str, Any],
        source: str,
        quality: str,
        published_at: date | None,
        period_type: str,
        as_of_date: date | None = None,
        catalog_extra: dict[str, Any] | None = None,
    ) -> MacroDataPoint:
        catalog_meta = dict(catalog_extra or {})
        age_days = get_macro_age_days(reporting_period, published_at, as_of_date=as_of_date)
        point_is_stale = is_macro_observation_stale(
            reporting_period,
            published_at,
            period_type=period_type,
            as_of_date=as_of_date,
        )
        provenance_class = str(catalog_meta.get("provenance_class") or "").strip()
        derivation_method = str(catalog_meta.get("derivation_method") or "").strip()
        publisher_code, publisher_codes = self._extract_publisher_codes(catalog_meta)
        publisher = self._resolve_publisher_display_name(
            publisher_code=publisher_code,
            publisher_codes=publisher_codes,
            explicit_publisher=str(catalog_meta.get("publisher") or "").strip(),
        )
        is_derived = provenance_class == "derived"
        decision_grade_enabled = self._is_decision_grade_enabled(
            provenance_class=provenance_class,
            catalog_extra=catalog_meta,
        )
        if point_is_stale:
            decision_grade = "degraded"
        elif not decision_grade_enabled:
            decision_grade = "research_only"
        else:
            decision_grade = "decision_safe"

        original_unit = str(extra.get("original_unit") or "")
        display_unit = str(extra.get("display_unit") or original_unit or unit)
        try:
            multiplier_to_storage = float(extra.get("multiplier_to_storage") or 1.0)
        except (TypeError, ValueError):
            multiplier_to_storage = 1.0

        if not display_unit or not original_unit:
            matched_rule = self._unit_rules.resolve_active_rule(
                indicator_code,
                source_type=str(extra.get("source_type") or ""),
                original_unit=original_unit or None,
            )
            if matched_rule is not None:
                original_unit = original_unit or matched_rule.original_unit
                display_unit = display_unit or matched_rule.display_unit or original_unit or unit
                multiplier_to_storage = matched_rule.multiplier_to_storage

        display_value = _storage_value_to_display_value(
            value,
            storage_unit=unit,
            display_unit=display_unit or unit,
            multiplier_to_storage=multiplier_to_storage,
        )

        return MacroDataPoint(
            indicator_code=indicator_code,
            reporting_period=reporting_period,
            value=value,
            unit=unit,
            display_value=display_value,
            display_unit=display_unit or unit,
            original_unit=original_unit or display_unit or unit,
            source=source,
            quality=quality,
            published_at=published_at,
            age_days=age_days,
            is_stale=point_is_stale,
            freshness_status="stale" if point_is_stale else "fresh",
            decision_grade=decision_grade,
            provenance_class=provenance_class,
            provenance_label=_provenance_label_for_class(provenance_class),
            publisher=publisher,
            publisher_code=publisher_code,
            publisher_codes=publisher_codes,
            access_channel=str(
                catalog_meta.get("access_channel") or extra.get("source_type") or source
            ),
            derivation_method=derivation_method,
            is_derived=is_derived,
        )

    @staticmethod
    def _extract_publisher_codes(catalog_extra: dict[str, Any]) -> tuple[str, list[str]]:
        explicit_code = str(catalog_extra.get("publisher_code") or "").strip().upper()
        explicit_codes = _dedupe_string_list(
            [str(code).strip().upper() for code in (catalog_extra.get("publisher_codes") or [])]
        )
        publisher_codes = explicit_codes or ([explicit_code] if explicit_code else [])
        publisher_code = explicit_code or (publisher_codes[0] if publisher_codes else "")
        return publisher_code, publisher_codes

    def _resolve_publisher_display_name(
        self,
        *,
        publisher_code: str,
        publisher_codes: list[str],
        explicit_publisher: str,
    ) -> str:
        if self._publishers is None:
            return explicit_publisher

        resolved_names: list[str] = []
        seen: set[str] = set()
        for code in publisher_codes:
            publisher = self._publishers.get_by_code(code)
            if publisher is None:
                continue
            name = publisher.canonical_name.strip()
            if not name:
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            resolved_names.append(name)

        if resolved_names:
            return "/".join(resolved_names)

        if publisher_code:
            publisher = self._publishers.get_by_code(publisher_code)
            if publisher is not None and publisher.canonical_name.strip():
                return publisher.canonical_name.strip()

        return explicit_publisher

    @staticmethod
    def _is_decision_grade_enabled(
        *,
        provenance_class: str,
        catalog_extra: dict[str, Any],
    ) -> bool:
        explicit = catalog_extra.get("decision_grade_enabled")
        if explicit is None:
            return provenance_class != "derived"
        return bool(explicit)

    @staticmethod
    def _build_provenance_blocked_reason(
        *,
        provenance_class: str,
        derivation_method: str,
    ) -> str:
        if provenance_class == "derived":
            if derivation_method:
                return (
                    "当前序列属于系统衍生数据，默认仅供研究，不可直接用于决策。"
                    f"派生方法：{derivation_method}"
                )
            return "当前序列属于系统衍生数据，默认仅供研究，不可直接用于决策。"
        return "当前序列 provenance 未通过决策级校验，仅可用于研究。"


def _provenance_label_for_class(provenance_class: str) -> str:
    return {
        "official": "官方数据",
        "authoritative_third_party": "权威转引",
        "derived": "系统衍生",
    }.get(provenance_class, "")


class QueryPriceHistoryUseCase:
    """Fetch OHLCV price bars for a security."""

    def __init__(self, repo: PriceBarRepositoryProtocol) -> None:
        self._repo = repo

    def execute(self, request: PriceHistoryRequest) -> list[PriceBarResponse]:
        bars = self._repo.get_bars(
            asset_code=request.asset_code,
            start=request.start,
            end=request.end,
            limit=request.limit,
        )
        return [
            PriceBarResponse(
                asset_code=b.asset_code,
                bar_date=b.bar_date,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
                amount=b.amount,
                source=b.source,
            )
            for b in bars
        ]


class QueryLatestQuoteUseCase:
    """Fetch the most recent real-time quote snapshot for a security."""

    DEFAULT_MAX_AGE_HOURS = DEFAULT_LATEST_QUOTE_MAX_AGE_HOURS

    def __init__(self, repo: QuoteSnapshotRepositoryProtocol) -> None:
        self._repo = repo

    @classmethod
    def build_response(
        cls,
        *,
        asset_code: str,
        snapshot_at: datetime,
        current_price: float,
        open: float | None,
        high: float | None,
        low: float | None,
        prev_close: float | None,
        volume: float | None,
        source: str,
        max_age_hours: float | None = None,
        now: datetime | None = None,
    ) -> QuoteResponse:
        effective_max_age_hours = (
            cls.DEFAULT_MAX_AGE_HOURS if max_age_hours is None else max_age_hours
        )
        if effective_max_age_hours <= 0:
            raise ValueError("max_age_hours must be greater than 0")

        normalized_snapshot_at = snapshot_at
        if normalized_snapshot_at.tzinfo is None:
            normalized_snapshot_at = normalized_snapshot_at.replace(tzinfo=UTC)
        else:
            normalized_snapshot_at = normalized_snapshot_at.astimezone(UTC)

        current_now = now or datetime.now(UTC)
        if current_now.tzinfo is None:
            current_now = current_now.replace(tzinfo=UTC)
        else:
            current_now = current_now.astimezone(UTC)

        age_seconds = max(
            0.0,
            (current_now - normalized_snapshot_at).total_seconds(),
        )
        age_minutes = int(age_seconds // 60)
        quote_is_stale = (age_seconds / 3600) > effective_max_age_hours
        freshness_status = "stale" if quote_is_stale else "fresh"

        snapshot_local = normalized_snapshot_at.astimezone(CN_MARKET_TZ)
        if (
            quote_is_stale
            and (latest_completed_session := _latest_completed_cn_quote_session(current_now))
            is not None
            and _is_cn_listed_asset(asset_code)
            and snapshot_local.date() == latest_completed_session
            and snapshot_local.time() >= CN_MARKET_CLOSE
        ):
            quote_is_stale = False
            freshness_status = "latest_completed_session"

        blocked_reason = ""
        if quote_is_stale:
            blocked_reason = (
                "最新行情快照已超过 freshness 阈值，当前结果仅可用于诊断，不得直接用于决策。"
            )

        return QuoteResponse(
            asset_code=asset_code,
            snapshot_at=normalized_snapshot_at,
            current_price=current_price,
            open=open,
            high=high,
            low=low,
            prev_close=prev_close,
            volume=volume,
            source=source,
            age_minutes=age_minutes,
            is_stale=quote_is_stale,
            freshness_status=freshness_status,
            must_not_use_for_decision=quote_is_stale,
            blocked_reason=blocked_reason,
            max_age_hours=effective_max_age_hours,
        )

    def execute(self, request: LatestQuoteRequest) -> QuoteResponse | None:
        quote = self._repo.get_latest(request.asset_code)
        if quote is None:
            return None
        return self.build_response(
            asset_code=quote.asset_code,
            snapshot_at=quote.snapshot_at,
            current_price=quote.current_price,
            open=quote.open,
            high=quote.high,
            low=quote.low,
            prev_close=quote.prev_close,
            volume=quote.volume,
            source=quote.source,
            max_age_hours=request.max_age_hours,
        )


__all__ = [
    "DEFAULT_LATEST_QUOTE_MAX_AGE_HOURS",
    "GetProviderStatusUseCase",
    "QueryLatestQuoteUseCase",
    "QueryMacroSeriesUseCase",
    "QueryPriceHistoryUseCase",
    "ResolveAssetUseCase",
]
