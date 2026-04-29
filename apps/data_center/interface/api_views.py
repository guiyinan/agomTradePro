"""
Data Center — Interface Layer API Views

Phase 1:
  GET/POST  /api/data-center/providers/
  GET/PATCH /api/data-center/providers/{id}/
  DELETE    /api/data-center/providers/{id}/
  POST      /api/data-center/providers/{id}/test/
  GET       /api/data-center/providers/status/
  GET/PUT   /api/data-center/settings/

Phase 2:
  GET  /api/data-center/assets/resolve/?code=&source_type=
  GET  /api/data-center/macro/series/?indicator_code=&start=&end=&limit=&source=
  GET  /api/data-center/prices/history/?asset_code=&start=&end=&freq=&adjustment=&limit=
  GET  /api/data-center/prices/quotes/?asset_code=

No business logic here — only HTTP plumbing + delegation to use cases.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.data_center.application.dtos import (
    CreateIndicatorCatalogRequest,
    CreateIndicatorUnitRuleRequest,
    CreateProviderRequest,
    DecisionReliabilityRepairRequest,
    LatestQuoteRequest,
    MacroSeriesRequest,
    PriceHistoryRequest,
    ResolveAssetRequest,
    SyncCapitalFlowRequest,
    SyncFinancialRequest,
    SyncFundNavRequest,
    SyncMacroRequest,
    SyncNewsRequest,
    SyncPriceRequest,
    SyncQuoteRequest,
    SyncSectorMembershipRequest,
    SyncValuationRequest,
    UpdateIndicatorCatalogRequest,
    UpdateIndicatorUnitRuleRequest,
    UpdateProviderRequest,
)
from apps.data_center.application.interface_services import (
    fetch_latest_realtime_prices,
    load_provider_settings_payload,
    make_manage_indicator_catalog_use_case,
    make_manage_indicator_unit_rule_use_case,
    make_decision_repair_use_case,
    make_manage_provider_config_use_case,
    make_query_capital_flows_use_case,
    make_query_financials_use_case,
    make_query_fund_nav_use_case,
    make_query_latest_quote_use_case,
    make_query_macro_series_use_case,
    make_query_news_use_case,
    make_query_price_history_use_case,
    make_query_sector_constituents_use_case,
    make_query_valuations_use_case,
    make_resolve_asset_use_case,
    make_run_provider_connection_test_use_case,
    make_sync_capital_flow_use_case,
    make_sync_financial_use_case,
    make_sync_fund_nav_use_case,
    make_sync_macro_use_case,
    make_sync_news_use_case,
    make_sync_price_use_case,
    make_sync_quote_use_case,
    make_sync_sector_membership_use_case,
    make_sync_valuation_use_case,
    save_provider_settings_payload,
)
from apps.data_center.application.registry_factory import get_registry, refresh_registry
from apps.data_center.application.use_cases import (
    QueryLatestQuoteUseCase,
    RepairDecisionDataReliabilityUseCase,
)
from apps.data_center.interface.serializers import (
    ConnectionTestResultSerializer,
    DataProviderSettingsSerializer,
    DecisionReliabilityRepairRequestSerializer,
    IndicatorCatalogSerializer,
    IndicatorUnitRuleSerializer,
    ProviderConfigListSerializer,
    ProviderConfigSerializer,
    ProviderHealthSnapshotSerializer,
    SyncCapitalFlowRequestSerializer,
    SyncFinancialRequestSerializer,
    SyncFundNavRequestSerializer,
    SyncMacroRequestSerializer,
    SyncNewsRequestSerializer,
    SyncPriceRequestSerializer,
    SyncQuoteRequestSerializer,
    SyncSectorMembershipRequestSerializer,
    SyncValuationRequestSerializer,
)

logger = logging.getLogger(__name__)

def _parse_bool_param(raw_value: str | None, *, default: bool = False) -> bool:
    if raw_value in (None, ""):
        return default

    normalized = str(raw_value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("strict_freshness 必须是布尔值")


def _parse_positive_float_param(
    raw_value: str | None,
    *,
    field_name: str,
    default: float,
) -> float:
    if raw_value in (None, ""):
        return default

    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是数字") from exc

    if value <= 0:
        raise ValueError(f"{field_name} 必须大于 0")
    return value


def _get_provider_health_metric(extra_config: dict, capability: str) -> dict:
    if capability and capability != "N/A":
        health_metrics = extra_config.get("health_metrics") or {}
        metric = health_metrics.get(capability)
        if isinstance(metric, dict):
            return metric
    return {}


def _enrich_provider_status_snapshot(snapshot: dict, extra_config: dict) -> dict:
    capability = str(snapshot.get("capability") or "")
    metric = _get_provider_health_metric(extra_config, capability)
    enriched = dict(snapshot)

    if enriched.get("last_success_at") in (None, ""):
        enriched["last_success_at"] = metric.get("last_success_at") or extra_config.get(
            "provider_last_success_at"
        )
    if enriched.get("avg_latency_ms") in (None, ""):
        enriched["avg_latency_ms"] = metric.get("avg_latency_ms") or extra_config.get(
            "provider_avg_latency_ms"
        )
    if not enriched.get("consecutive_failures"):
        enriched["consecutive_failures"] = int(metric.get("consecutive_failures", 0))

    return enriched

def _make_decision_repair_use_case(user) -> RepairDecisionDataReliabilityUseCase:
    return make_decision_repair_use_case(user)


# ---------------------------------------------------------------------------
# Provider list / create
# ---------------------------------------------------------------------------


@api_view(["GET", "POST"])
@permission_classes([IsAdminUser])
def provider_list_create(request: Request) -> Response:
    """
    GET  — list all provider configs (credentials masked).
    POST — create a new provider config.
    """
    use_case = make_manage_provider_config_use_case()

    if request.method == "GET":
        providers = use_case.list_all()
        serializer = ProviderConfigListSerializer([p.to_dict() for p in providers], many=True)
        return Response({"results": serializer.data})

    # POST — create
    serializer = ProviderConfigSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data
    req = CreateProviderRequest(
        name=d["name"],
        source_type=d["source_type"],
        is_active=d.get("is_active", True),
        priority=d.get("priority", 100),
        api_key=d.get("api_key", ""),
        api_secret=d.get("api_secret", ""),
        http_url=d.get("http_url", ""),
        api_endpoint=d.get("api_endpoint", ""),
        extra_config=d.get("extra_config", {}),
        description=d.get("description", ""),
    )
    created = use_case.create(req)
    refresh_registry()
    return Response(created.to_dict(), status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Provider detail / update / delete
# ---------------------------------------------------------------------------


@api_view(["GET", "PATCH", "PUT", "DELETE"])
@permission_classes([IsAdminUser])
def provider_detail(request: Request, provider_id: int) -> Response:
    """
    GET    — retrieve one provider config.
    PATCH  — partial update.
    PUT    — full update.
    DELETE — remove provider config.
    """
    use_case = make_manage_provider_config_use_case()

    if request.method == "GET":
        provider = use_case.get(provider_id)
        if provider is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(provider.to_dict())

    if request.method == "DELETE":
        deleted = use_case.delete(provider_id)
        if not deleted:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        refresh_registry()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # PATCH / PUT
    partial = request.method == "PATCH"
    serializer = ProviderConfigSerializer(data=request.data, partial=partial)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data
    req = UpdateProviderRequest(
        provider_id=provider_id,
        name=d.get("name"),
        source_type=d.get("source_type"),
        is_active=d.get("is_active"),
        priority=d.get("priority"),
        api_key=d.get("api_key"),
        api_secret=d.get("api_secret"),
        http_url=d.get("http_url"),
        api_endpoint=d.get("api_endpoint"),
        extra_config=d.get("extra_config"),
        description=d.get("description"),
    )
    updated = use_case.update(req)
    if updated is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    refresh_registry()
    return Response(updated.to_dict())


# ---------------------------------------------------------------------------
# Indicator catalog / unit-rule management
# ---------------------------------------------------------------------------


@api_view(["GET", "POST"])
@permission_classes([IsAdminUser])
def indicator_list_create(request: Request) -> Response:
    """GET/POST /api/data-center/indicators/."""
    use_case = make_manage_indicator_catalog_use_case()

    if request.method == "GET":
        active_only = _parse_bool_param(request.query_params.get("active_only"), default=False)
        results = use_case.list_all(active_only=active_only)
        serializer = IndicatorCatalogSerializer([item.to_dict() for item in results], many=True)
        return Response({"results": serializer.data})

    serializer = IndicatorCatalogSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data
    created = use_case.create(
        CreateIndicatorCatalogRequest(
            code=d["code"],
            name_cn=d["name_cn"],
            name_en=d.get("name_en", ""),
            description=d.get("description", ""),
            category=d.get("category", ""),
            default_period_type=d.get("default_period_type", "M"),
            is_active=d.get("is_active", True),
            extra=d.get("extra", {}),
        )
    )
    return Response(created.to_dict(), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAdminUser])
def indicator_detail(request: Request, indicator_code: str) -> Response:
    """GET/PATCH/DELETE /api/data-center/indicators/{code}/."""
    use_case = make_manage_indicator_catalog_use_case()

    if request.method == "GET":
        result = use_case.get(indicator_code)
        if result is None:
            return Response({"detail": "Indicator not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(result.to_dict())

    if request.method == "PATCH":
        serializer = IndicatorCatalogSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        updated = use_case.update(
            UpdateIndicatorCatalogRequest(
                code=indicator_code,
                name_cn=d.get("name_cn"),
                name_en=d.get("name_en"),
                description=d.get("description"),
                category=d.get("category"),
                default_period_type=d.get("default_period_type"),
                is_active=d.get("is_active"),
                extra=d.get("extra"),
            )
        )
        if updated is None:
            return Response({"detail": "Indicator not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(updated.to_dict())

    if not use_case.delete(indicator_code):
        return Response({"detail": "Indicator not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET", "POST"])
@permission_classes([IsAdminUser])
def indicator_unit_rule_list_create(request: Request, indicator_code: str) -> Response:
    """GET/POST /api/data-center/indicators/{code}/unit-rules/."""
    use_case = make_manage_indicator_unit_rule_use_case()

    if request.method == "GET":
        results = use_case.list_by_indicator(indicator_code)
        serializer = IndicatorUnitRuleSerializer([item.to_dict() for item in results], many=True)
        return Response({"results": serializer.data})

    serializer = IndicatorUnitRuleSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data
    try:
        created = use_case.create(
            CreateIndicatorUnitRuleRequest(
                indicator_code=indicator_code,
                source_type=d.get("source_type", ""),
                dimension_key=d["dimension_key"],
                original_unit=d.get("original_unit", ""),
                storage_unit=d["storage_unit"],
                display_unit=d["display_unit"],
                multiplier_to_storage=d["multiplier_to_storage"],
                is_active=d.get("is_active", True),
                priority=d.get("priority", 0),
                description=d.get("description", ""),
            )
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(created.to_dict(), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAdminUser])
def indicator_unit_rule_detail(request: Request, indicator_code: str, rule_id: int) -> Response:
    """GET/PATCH/DELETE /api/data-center/indicators/{code}/unit-rules/{rule_id}/."""
    use_case = make_manage_indicator_unit_rule_use_case()
    existing = use_case.get(rule_id)
    if existing is None or existing.indicator_code != indicator_code:
        return Response({"detail": "Indicator unit rule not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return Response(existing.to_dict())

    if request.method == "PATCH":
        serializer = IndicatorUnitRuleSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        try:
            updated = use_case.update(
                UpdateIndicatorUnitRuleRequest(
                    rule_id=rule_id,
                    indicator_code=indicator_code,
                    source_type=d.get("source_type"),
                    dimension_key=d.get("dimension_key"),
                    original_unit=d.get("original_unit"),
                    storage_unit=d.get("storage_unit"),
                    display_unit=d.get("display_unit"),
                    multiplier_to_storage=d.get("multiplier_to_storage"),
                    is_active=d.get("is_active"),
                    priority=d.get("priority"),
                    description=d.get("description"),
                )
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if updated is None:
            return Response(
                {"detail": "Indicator unit rule not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(updated.to_dict())

    use_case.delete(rule_id)
    return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------


@api_view(["POST"])
@permission_classes([IsAdminUser])
def provider_test_connection(request: Request, provider_id: int) -> Response:
    """POST /api/data-center/providers/{id}/test/ — run connectivity probe."""
    use_case = make_run_provider_connection_test_use_case()
    result = use_case.execute(provider_id)
    if result is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    serializer = ConnectionTestResultSerializer(result.to_dict())
    return Response(serializer.data)


# ---------------------------------------------------------------------------
# Provider status (DB-backed, enriched with live registry health)
# ---------------------------------------------------------------------------


@api_view(["GET"])
@permission_classes([IsAdminUser])
def provider_status(request: Request) -> Response:
    """GET /api/data-center/providers/status/ — per-provider health snapshot.

    Returns one entry per active provider configured in the DB.
    The ``status`` field reflects live circuit-breaker state when the provider
    has been exercised through the registry; otherwise it reads ``unknown``.
    """
    # Build a lookup: provider_name → [snapshot] from live registry
    live: dict[str, list[dict]] = {}
    for snap in get_registry().get_all_statuses():
        live.setdefault(snap.provider_name, []).append(snap.to_dict())

    providers = sorted(
        (provider for provider in make_manage_provider_config_use_case().list_all() if provider.is_active),
        key=lambda provider: (provider.priority, provider.name),
    )
    results = []
    for provider in providers:
        extra_config = provider.extra_config or {}
        if provider.name in live:
            results.extend(
                _enrich_provider_status_snapshot(snapshot, extra_config)
                for snapshot in live[provider.name]
            )
        else:
            # Provider configured but not yet exercised through registry
            results.append(
                {
                    "provider_name": provider.name,
                    "capability": "N/A",
                    "status": "unknown",
                    "consecutive_failures": 0,
                    "last_success_at": extra_config.get("provider_last_success_at"),
                    "avg_latency_ms": extra_config.get("provider_avg_latency_ms"),
                }
            )

    serializer = ProviderHealthSnapshotSerializer(results, many=True)
    return Response({"results": serializer.data})


# ---------------------------------------------------------------------------
# Global provider settings
# ---------------------------------------------------------------------------


@api_view(["GET", "PUT", "PATCH"])
@permission_classes([IsAdminUser])
def provider_settings(request: Request) -> Response:
    """
    GET         — retrieve global provider settings.
    PUT / PATCH — update global settings.
    """
    if request.method == "GET":
        return Response(load_provider_settings_payload())

    partial = request.method == "PATCH"
    serializer = DataProviderSettingsSerializer(data=request.data, partial=partial)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data

    current = load_provider_settings_payload()
    return Response(
        save_provider_settings_payload(
            default_source=d.get("default_source", current["default_source"]),
            enable_failover=d.get("enable_failover", current["enable_failover"]),
            failover_tolerance=d.get(
                "failover_tolerance",
                current["failover_tolerance"],
            ),
        )
    )


# ---------------------------------------------------------------------------
# Phase 2 — Data query endpoints
# ---------------------------------------------------------------------------


@api_view(["GET"])
def asset_resolve(request: Request) -> Response:
    """GET /api/data-center/assets/resolve/?code=&source_type=

    Resolve a (possibly provider-specific) ticker to a canonical AssetMaster record.

    Query params:
      code        — required; ticker code (e.g. 000001.XSHE, sh600519, 600519.SH)
      source_type — optional hint for normalisation (e.g. akshare)
    """
    code = request.query_params.get("code", "").strip()
    if not code:
        return Response(
            {"detail": "Query parameter 'code' is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    source_type = request.query_params.get("source_type", "")

    uc = make_resolve_asset_use_case()
    result = uc.execute(ResolveAssetRequest(code=code, source_type=source_type))
    if result is None:
        return Response({"detail": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(result.to_dict())


@api_view(["GET"])
def macro_series(request: Request) -> Response:
    """GET /api/data-center/macro/series/?indicator_code=&start=&end=&limit=&source=

    Fetch a macro economic time-series.

    Query params:
      indicator_code — required (e.g. CN_GDP, CN_PMI)
      start          — optional ISO date (YYYY-MM-DD)
      end            — optional ISO date
      limit          — optional int, default 500
      source         — optional provider filter (e.g. tushare, akshare)
    """
    from datetime import date as date_cls

    indicator_code = request.query_params.get("indicator_code", "").strip()
    if not indicator_code:
        return Response(
            {"detail": "Query parameter 'indicator_code' is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def _parse_date(s: str) -> date_cls | None:
        try:
            return date_cls.fromisoformat(s)
        except (ValueError, AttributeError):
            return None

    try:
        req = MacroSeriesRequest(
            indicator_code=indicator_code,
            start=_parse_date(request.query_params.get("start", "")),
            end=_parse_date(request.query_params.get("end", "")),
            limit=int(request.query_params.get("limit", 500)),
            source=request.query_params.get("source") or None,
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    uc = make_query_macro_series_use_case()
    result = uc.execute(req)
    return Response(result.to_dict())


@api_view(["GET"])
def price_history(request: Request) -> Response:
    """GET /api/data-center/prices/history/?asset_code=&start=&end=&freq=&adjustment=&limit=

    Fetch OHLCV price bars for a security.

    Query params:
      asset_code — required canonical ticker (e.g. 600519.SH)
      start      — optional ISO date
      end        — optional ISO date
      freq       — optional bar frequency, default "1d"
      adjustment — optional adjustment method (none/forward/backward), default "none"
      limit      — optional int, default 500
    """
    from datetime import date as date_cls

    asset_code = request.query_params.get("asset_code", "").strip()
    if not asset_code:
        return Response(
            {"detail": "Query parameter 'asset_code' is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def _parse_date(s: str) -> date_cls | None:
        try:
            return date_cls.fromisoformat(s)
        except (ValueError, AttributeError):
            return None

    req = PriceHistoryRequest(
        asset_code=asset_code,
        start=_parse_date(request.query_params.get("start", "")),
        end=_parse_date(request.query_params.get("end", "")),
        freq=request.query_params.get("freq", "1d"),
        adjustment=request.query_params.get("adjustment", "none"),
        limit=int(request.query_params.get("limit", 500)),
    )

    uc = make_query_price_history_use_case()
    bars = uc.execute(req)
    return Response(
        {"asset_code": asset_code, "total": len(bars), "data": [b.to_dict() for b in bars]}
    )


@api_view(["GET"])
def price_latest_quote(request: Request) -> Response:
    """GET /api/data-center/prices/quotes/?asset_code=

    Fetch the most recent intraday quote snapshot for a security.

    Query params:
      asset_code — required canonical ticker
      strict_freshness — optional bool, when true stale quotes return 409
      max_age_hours — optional float freshness threshold, default 4h
    """
    asset_code = request.query_params.get("asset_code", "").strip()
    if not asset_code:
        return Response(
            {"detail": "Query parameter 'asset_code' is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        strict_freshness = _parse_bool_param(
            request.query_params.get("strict_freshness"),
            default=False,
        )
        max_age_hours = _parse_positive_float_param(
            request.query_params.get("max_age_hours"),
            field_name="max_age_hours",
            default=QueryLatestQuoteUseCase.DEFAULT_MAX_AGE_HOURS,
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    uc = make_query_latest_quote_use_case()
    result = uc.execute(
        LatestQuoteRequest(
            asset_code=asset_code,
            max_age_hours=max_age_hours,
        )
    )

    if result is None or (strict_freshness and result.must_not_use_for_decision):
        fallback_prices = fetch_latest_realtime_prices([asset_code])
        if fallback_prices:
            fallback = fallback_prices[0]
            result = QueryLatestQuoteUseCase.build_response(
                asset_code=asset_code,
                snapshot_at=datetime.fromisoformat(fallback["timestamp"]),
                current_price=float(fallback["price"]),
                open=None,
                high=None,
                low=None,
                prev_close=None,
                volume=fallback.get("volume"),
                source=fallback["source"],
                max_age_hours=max_age_hours,
            )

    if result is None:
        return Response({"detail": "No quote found."}, status=status.HTTP_404_NOT_FOUND)

    if strict_freshness and result.must_not_use_for_decision:
        payload = result.to_dict()
        payload["detail"] = (
            "最新行情快照已超过 freshness 阈值；strict_freshness 模式下已阻断决策态读取。"
        )
        return Response(payload, status=status.HTTP_409_CONFLICT)

    return Response(result.to_dict())


@api_view(["GET"])
def fund_nav_series(request: Request) -> Response:
    from datetime import date as date_cls

    fund_code = request.query_params.get("fund_code", "").strip()
    if not fund_code:
        return Response({"detail": "Query parameter 'fund_code' is required."}, status=400)

    def _parse_date(s: str) -> date_cls | None:
        try:
            return date_cls.fromisoformat(s)
        except (ValueError, AttributeError):
            return None

    data = make_query_fund_nav_use_case().execute(
        fund_code=fund_code,
        start=_parse_date(request.query_params.get("start", "")),
        end=_parse_date(request.query_params.get("end", "")),
    )
    return Response({"fund_code": fund_code, "total": len(data), "data": data})


@api_view(["GET"])
def financials(request: Request) -> Response:
    from apps.data_center.domain.enums import FinancialPeriodType

    asset_code = request.query_params.get("asset_code", "").strip()
    if not asset_code:
        return Response({"detail": "Query parameter 'asset_code' is required."}, status=400)

    period_type_raw = request.query_params.get("period_type", "").strip()
    period_type = FinancialPeriodType(period_type_raw) if period_type_raw else None
    limit = int(request.query_params.get("limit", 20))
    data = make_query_financials_use_case().execute(
        asset_code=asset_code,
        period_type=period_type,
        limit=limit,
    )
    return Response({"asset_code": asset_code, "total": len(data), "data": data})


@api_view(["GET"])
def valuations(request: Request) -> Response:
    from datetime import date as date_cls

    asset_code = request.query_params.get("asset_code", "").strip()
    if not asset_code:
        return Response({"detail": "Query parameter 'asset_code' is required."}, status=400)

    def _parse_date(s: str) -> date_cls | None:
        try:
            return date_cls.fromisoformat(s)
        except (ValueError, AttributeError):
            return None

    data = make_query_valuations_use_case().execute(
        asset_code=asset_code,
        start=_parse_date(request.query_params.get("start", "")),
        end=_parse_date(request.query_params.get("end", "")),
    )
    return Response({"asset_code": asset_code, "total": len(data), "data": data})


@api_view(["GET"])
def sector_constituents(request: Request) -> Response:
    from datetime import date as date_cls

    sector_code = request.query_params.get("sector_code", "").strip()
    if not sector_code:
        return Response({"detail": "Query parameter 'sector_code' is required."}, status=400)

    as_of_raw = request.query_params.get("as_of", "").strip()
    as_of = None
    if as_of_raw:
        try:
            as_of = date_cls.fromisoformat(as_of_raw)
        except ValueError:
            return Response({"detail": "Invalid 'as_of' date."}, status=400)

    data = make_query_sector_constituents_use_case().execute(
        sector_code=sector_code,
        as_of=as_of,
    )
    return Response({"sector_code": sector_code, "total": len(data), "data": data})


@api_view(["GET"])
def news(request: Request) -> Response:
    asset_code = request.query_params.get("asset_code", "").strip() or None
    limit = int(request.query_params.get("limit", 50))
    data = make_query_news_use_case().execute(asset_code=asset_code, limit=limit)
    return Response({"asset_code": asset_code, "total": len(data), "data": data})


@api_view(["GET"])
def capital_flows(request: Request) -> Response:
    from datetime import date as date_cls

    asset_code = request.query_params.get("asset_code", "").strip()
    if not asset_code:
        return Response({"detail": "Query parameter 'asset_code' is required."}, status=400)

    def _parse_date(s: str) -> date_cls | None:
        try:
            return date_cls.fromisoformat(s)
        except (ValueError, AttributeError):
            return None

    data = make_query_capital_flows_use_case().execute(
        asset_code=asset_code,
        start=_parse_date(request.query_params.get("start", "")),
        end=_parse_date(request.query_params.get("end", "")),
    )
    return Response({"asset_code": asset_code, "total": len(data), "data": data})


@api_view(["POST"])
@permission_classes([IsAdminUser])
def repair_decision_reliability(request: Request) -> Response:
    """Repair macro/quote/Pulse/Alpha inputs and return readiness status."""
    serializer = DecisionReliabilityRepairRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = DecisionReliabilityRepairRequest(**serializer.validated_data)
    report = _make_decision_repair_use_case(request.user).execute(req)
    payload = report.to_dict()
    status_code = (
        status.HTTP_409_CONFLICT
        if req.strict and payload["must_not_use_for_decision"]
        else status.HTTP_200_OK
    )
    return Response(payload, status=status_code)


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_macro(request: Request) -> Response:
    serializer = SyncMacroRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncMacroRequest(**serializer.validated_data)
    result = make_sync_macro_use_case().execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_prices(request: Request) -> Response:
    serializer = SyncPriceRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncPriceRequest(**serializer.validated_data)
    result = make_sync_price_use_case().execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_quotes(request: Request) -> Response:
    serializer = SyncQuoteRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncQuoteRequest(**serializer.validated_data)
    result = make_sync_quote_use_case().execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_fund_nav(request: Request) -> Response:
    serializer = SyncFundNavRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncFundNavRequest(**serializer.validated_data)
    result = make_sync_fund_nav_use_case().execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_financials(request: Request) -> Response:
    serializer = SyncFinancialRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncFinancialRequest(**serializer.validated_data)
    result = make_sync_financial_use_case().execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_valuations(request: Request) -> Response:
    serializer = SyncValuationRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncValuationRequest(**serializer.validated_data)
    result = make_sync_valuation_use_case().execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_sector_constituents(request: Request) -> Response:
    serializer = SyncSectorMembershipRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncSectorMembershipRequest(**serializer.validated_data)
    result = make_sync_sector_membership_use_case().execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_news(request: Request) -> Response:
    serializer = SyncNewsRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncNewsRequest(**serializer.validated_data)
    result = make_sync_news_use_case().execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_capital_flows(request: Request) -> Response:
    serializer = SyncCapitalFlowRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncCapitalFlowRequest(**serializer.validated_data)
    result = make_sync_capital_flow_use_case().execute(req)
    return Response(result.to_dict())
