"""
Data Center — Interface Layer API Views

Phase 1: GET/POST  /api/data-center/providers/
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
from typing import Any

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.data_center.application.dtos import (
    CreateIndicatorCatalogRequest,
    CreateIndicatorUnitRuleRequest,
    CreatePublisherCatalogRequest,
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
    UpdatePublisherCatalogRequest,
)
from apps.data_center.application.interface_services import (
    fetch_latest_realtime_prices,
    load_market_thermometer_override_payload,
    load_production_coverage_universe_config_payload,
    make_import_investor_accounts_use_case,
    make_manage_indicator_catalog_use_case,
    make_manage_indicator_unit_rule_use_case,
    make_manage_market_thermometer_config_use_case,
    make_manage_market_thermometer_user_override_use_case,
    make_manage_publisher_catalog_use_case,
    make_query_capital_flows_use_case,
    make_query_financials_use_case,
    make_query_fund_nav_use_case,
    make_query_latest_quote_use_case,
    make_query_news_use_case,
    make_query_price_history_use_case,
    make_query_sector_constituents_use_case,
    make_query_valuations_use_case,
    make_resolve_asset_use_case,
    make_run_provider_connection_test_use_case,
    make_sync_capital_flow_use_case,
    make_sync_fund_nav_use_case,
    make_sync_market_thermometer_inputs_use_case,
    make_sync_news_use_case,
    make_sync_price_use_case,
    make_sync_quote_use_case,
    make_sync_sector_membership_use_case,
    save_production_coverage_universe_config_payload,
    save_provider_settings_payload,
)
from apps.data_center.application.pit_use_cases import BuildPITManifestRequest
from apps.data_center.application.public import (
    get_active_stock_fact_coverage_payload,
    get_current_publication,
    get_current_publication_freshness_gate,
    get_market_thermometer_payload,
    get_provider_settings_payload,
    get_publication_member_fact_pks,
    make_calculate_market_thermometer_use_case,
    make_decision_repair_use_case,
    make_query_macro_series_use_case,
    make_sync_financial_use_case,
    make_sync_macro_use_case,
    make_sync_valuation_use_case,
)
from apps.data_center.application.use_cases import (
    QueryLatestQuoteUseCase,
    RepairDecisionDataReliabilityUseCase,
)
from apps.data_center.composition import (
    make_build_pit_manifest_use_case,
    make_query_pit_manifest_use_case,
)
from apps.data_center.domain.pit import KnowledgeScope
from apps.data_center.interface import provider_api_views as _provider_api_views
from apps.data_center.interface.auth_helpers import _authenticated_user_id
from apps.data_center.interface.pit_serializers import (
    BuildPITManifestSerializer,
    serialize_pit_manifest,
)
from apps.data_center.interface.query_params import (
    _parse_bool_param,
    _parse_positive_float_param,
    _parse_positive_int_param,
)
from apps.data_center.interface.serializers import (
    CapitalFlowQuerySerializer,
    ConnectionTestResultSerializer,
    DataProviderSettingsSerializer,
    DecisionReliabilityRepairRequestSerializer,
    IndicatorCatalogSerializer,
    IndicatorUnitRuleSerializer,
    MarketThermometerConfigSerializer,
    MarketThermometerImportSerializer,
    MarketThermometerUserOverrideSerializer,
    ProductionCoverageUniverseConfigSerializer,
    PublisherCatalogSerializer,
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
from apps.data_center.provider_runtime import get_registry
from shared.request_payload import request_data_mapping

from .publication_guards import (
    apply_published_gate_with_members,
)
from .publication_guards import publication_member_pks as _publication_member_pks
from .publication_guards import published_as_of_date as _published_as_of_date
from .publication_guards import published_as_of_datetime as _published_as_of_datetime
from .publication_guards import published_bounded_end as _published_bounded_end
from .publication_guards import (
    published_empty_intersection_response as _published_empty_intersection_response,
)

logger = logging.getLogger(__name__)


def _published_gate(
    request: Request,
    *,
    dataset_key: str,
    default_publication_key: str,
    identity_field: str,
    identity_value: str,
) -> tuple[dict[str, object] | None, Response | None]:
    """Apply the shared gate seam; emits canonical_publication_missing and canonical_publication_stale."""

    return apply_published_gate_with_members(
        request,
        dataset_key=dataset_key,
        default_publication_key=default_publication_key,
        identity_field=identity_field,
        identity_value=identity_value,
        get_publication=get_current_publication,
        get_freshness_gate=get_current_publication_freshness_gate,
        get_member_fact_pks=get_publication_member_fact_pks,
    )


provider_detail = _provider_api_views.provider_detail
provider_list_create = _provider_api_views.provider_list_create
_provider_status = _provider_api_views.provider_status


def provider_status(request: Request) -> Response:
    """Compatibility entry point retaining the historic patch surface."""

    import apps.data_center.interface.provider_api_views as provider_views

    provider_views.get_registry = get_registry
    return _provider_status(request)


def _make_decision_repair_use_case(user: Any) -> RepairDecisionDataReliabilityUseCase:
    return make_decision_repair_use_case(user)


# ---------------------------------------------------------------------------
# Publisher catalog management
# ---------------------------------------------------------------------------


@api_view(["GET", "POST"])
@permission_classes([IsAdminUser])
def publisher_list_create(request: Request) -> Response:
    """GET/POST /api/data-center/publishers/."""
    use_case = make_manage_publisher_catalog_use_case()

    if request.method == "GET":
        try:
            active_only = _parse_bool_param(
                request.query_params.get("active_only"),
                field_name="active_only",
                default=False,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        results = use_case.list_all(active_only=active_only)
        serializer = PublisherCatalogSerializer([item.to_dict() for item in results], many=True)
        return Response({"results": serializer.data})

    serializer = PublisherCatalogSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data
    created = use_case.create(
        CreatePublisherCatalogRequest(
            code=d["code"],
            canonical_name=d["canonical_name"],
            canonical_name_en=d.get("canonical_name_en", ""),
            publisher_class=d["publisher_class"],
            aliases=d.get("aliases", []),
            country_code=d.get("country_code", "CN"),
            website=d.get("website", ""),
            is_active=d.get("is_active", True),
            description=d.get("description", ""),
        )
    )
    return Response(created.to_dict(), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAdminUser])
def publisher_detail(request: Request, publisher_code: str) -> Response:
    """GET/PATCH/DELETE /api/data-center/publishers/{code}/."""
    use_case = make_manage_publisher_catalog_use_case()

    if request.method == "GET":
        result = use_case.get(publisher_code)
        if result is None:
            return Response({"detail": "Publisher not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(result.to_dict())

    if request.method == "PATCH":
        serializer = PublisherCatalogSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        updated = use_case.update(
            UpdatePublisherCatalogRequest(
                code=publisher_code,
                canonical_name=d.get("canonical_name"),
                canonical_name_en=d.get("canonical_name_en"),
                publisher_class=d.get("publisher_class"),
                aliases=d.get("aliases"),
                country_code=d.get("country_code"),
                website=d.get("website"),
                is_active=d.get("is_active"),
                description=d.get("description"),
            )
        )
        if updated is None:
            return Response({"detail": "Publisher not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(updated.to_dict())

    if not use_case.delete(publisher_code):
        return Response({"detail": "Publisher not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Indicator catalog / unit-rule management
# ---------------------------------------------------------------------------


@api_view(["GET", "POST"])
@permission_classes([IsAdminUser])
def indicator_list_create(request: Request) -> Response:
    """GET/POST /api/data-center/indicators/."""
    use_case = make_manage_indicator_catalog_use_case()

    if request.method == "GET":
        try:
            active_only = _parse_bool_param(
                request.query_params.get("active_only"),
                field_name="active_only",
                default=False,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
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
        return Response(
            {"detail": "Indicator unit rule not found."}, status=status.HTTP_404_NOT_FOUND
        )

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
        return Response(get_provider_settings_payload())

    partial = request.method == "PATCH"
    serializer = DataProviderSettingsSerializer(data=request.data, partial=partial)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data

    current = get_provider_settings_payload()
    return Response(
        save_provider_settings_payload(
            default_source=d.get("default_source", current["default_source"]),
            enable_failover=d.get("enable_failover", current["enable_failover"]),
            failover_tolerance=d.get(
                "failover_tolerance",
                current["failover_tolerance"],
            ),
            actor=str(getattr(request.user, "username", "") or "data-center-admin"),
        )
    )


@api_view(["GET", "PUT", "PATCH"])
@permission_classes([IsAdminUser])
def production_coverage_universe_config(request: Request) -> Response:
    """Return or update the production coverage diagnostics universe."""

    if request.method == "GET":
        return Response(load_production_coverage_universe_config_payload())

    serializer = ProductionCoverageUniverseConfigSerializer(
        data=request.data,
        partial=request.method == "PATCH",
    )
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    current = load_production_coverage_universe_config_payload()
    return Response(
        save_production_coverage_universe_config_payload(
            universe_id=data.get("universe_id", current["universe_id"]),
            asset_type=data.get("asset_type", current["asset_type"]),
            exchanges=data.get("exchanges", current["exchanges"]),
            include_inactive=data.get("include_inactive", current["include_inactive"]),
            min_active_asset_count=data.get(
                "min_active_asset_count",
                current["min_active_asset_count"],
            ),
            min_star_market_count=data.get(
                "min_star_market_count",
                current["min_star_market_count"],
            ),
            min_chinext_count=data.get("min_chinext_count", current["min_chinext_count"]),
            min_bse_count=data.get("min_bse_count", current["min_bse_count"]),
            description=data.get("description", current["description"]),
        )
    )


@api_view(["GET"])
@permission_classes([IsAdminUser])
def production_coverage_summary(request: Request) -> Response:
    """Return current production coverage diagnostics summary."""

    return Response(get_active_stock_fact_coverage_payload())


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

    Fetch a macro economic time-series in reverse chronological order.

    Query params:
      indicator_code — required (e.g. CN_GDP, CN_PMI)
      start          — optional ISO date (YYYY-MM-DD)
      end            — optional ISO date
      limit          — optional int, default 500
      source         — optional provider filter (e.g. tushare, akshare)

    Notes:
      - API consumers get newest-first rows by default.
      - Chart/timeline UIs should reorder to past→now before rendering.
    """
    from datetime import date as date_cls

    indicator_code = request.query_params.get("indicator_code", "").strip()
    if not indicator_code:
        return Response(
            {"detail": "Query parameter 'indicator_code' is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    publication, blocked = _published_gate(
        request,
        dataset_key="macro.fact",
        default_publication_key=indicator_code,
        identity_field="indicator_code",
        identity_value=indicator_code,
    )
    if blocked is not None:
        return blocked

    def _parse_date(s: str) -> date_cls | None:
        try:
            return date_cls.fromisoformat(s)
        except (ValueError, AttributeError):
            return None

    try:
        requested_start = _parse_date(request.query_params.get("start", ""))
        requested_end = _parse_date(request.query_params.get("end", ""))
        bounded_end = _published_bounded_end(requested_end, publication)
        if (
            requested_start is not None
            and bounded_end is not None
            and requested_start > bounded_end
            and publication is not None
        ):
            return _published_empty_intersection_response(
                identity_field="indicator_code",
                identity_value=indicator_code,
                publication=publication,
            )
        req = MacroSeriesRequest(
            indicator_code=indicator_code,
            start=requested_start,
            end=bounded_end,
            limit=int(request.query_params.get("limit", 500)),
            source=request.query_params.get("source") or None,
            fact_pks=_publication_member_pks(publication),
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    uc = make_query_macro_series_use_case()
    result = uc.execute(req)
    payload = result.to_dict()
    if publication is not None:
        payload["publication_id"] = publication["publication_id"]
        payload["publication"] = publication
    return Response(payload)


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
    publication, blocked = _published_gate(
        request,
        dataset_key="equity.price.bar",
        default_publication_key="current",
        identity_field="asset_code",
        identity_value=asset_code,
    )
    if blocked is not None:
        return blocked

    def _parse_date(s: str) -> date_cls | None:
        try:
            return date_cls.fromisoformat(s)
        except (ValueError, AttributeError):
            return None

    requested_start = _parse_date(request.query_params.get("start", ""))
    requested_end = _parse_date(request.query_params.get("end", ""))
    bounded_end = _published_bounded_end(requested_end, publication)
    member_pks = _publication_member_pks(publication)
    if (
        requested_start is not None
        and bounded_end is not None
        and requested_start > bounded_end
        and publication is not None
    ):
        return _published_empty_intersection_response(
            identity_field="asset_code",
            identity_value=asset_code,
            publication=publication,
        )

    req = PriceHistoryRequest(
        asset_code=asset_code,
        start=requested_start,
        end=bounded_end,
        freq=request.query_params.get("freq", "1d"),
        adjustment=request.query_params.get("adjustment", "none"),
        limit=int(request.query_params.get("limit", 500)),
        fact_pks=member_pks,
    )

    uc = make_query_price_history_use_case()
    bars = uc.execute(req)
    payload: dict[str, object] = {
        "asset_code": asset_code,
        "total": len(bars),
        "data": [b.to_dict() for b in bars],
    }
    if publication is not None:
        payload["publication_id"] = publication["publication_id"]
        payload["publication"] = publication
    return Response(payload)


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
    publication, blocked = _published_gate(
        request,
        dataset_key="equity.quote.snapshot",
        default_publication_key="current",
        identity_field="asset_code",
        identity_value=asset_code,
    )
    if blocked is not None:
        return blocked

    try:
        strict_freshness = _parse_bool_param(
            request.query_params.get("strict_freshness"),
            field_name="strict_freshness",
            default=False,
        )
        max_age_hours = _parse_positive_float_param(
            request.query_params.get("max_age_hours"),
            field_name="max_age_hours",
            default=QueryLatestQuoteUseCase.DEFAULT_MAX_AGE_HOURS,
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    member_pks = _publication_member_pks(publication)
    uc = make_query_latest_quote_use_case()
    result = uc.execute(
        LatestQuoteRequest(
            asset_code=asset_code,
            max_age_hours=max_age_hours,
            fact_pks=member_pks,
        )
    )

    publication_as_of = _published_as_of_datetime(publication)
    if publication is not None and publication_as_of is not None and result is not None:
        if result.snapshot_at > publication_as_of:
            payload = result.to_dict()
            payload.update(
                {
                    "status": "blocked",
                    "must_not_use_for_decision": True,
                    "blocked_reason": "quote_observation_after_publication_as_of",
                    "publication_id": publication["publication_id"],
                    "publication": publication,
                }
            )
            return Response(payload, status=status.HTTP_200_OK)
    if publication_as_of is None and (
        result is None or (strict_freshness and result.must_not_use_for_decision)
    ):
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
                fetched_at=(
                    datetime.fromisoformat(str(fallback["fetched_at"]))
                    if fallback.get("fetched_at")
                    else None
                ),
            )

    if result is None:
        if publication_as_of is not None and publication is not None:
            return Response(
                {
                    "asset_code": asset_code,
                    "status": "blocked",
                    "must_not_use_for_decision": True,
                    "blocked_reason": "canonical_quote_missing_before_publication_as_of",
                    "publication_id": publication["publication_id"],
                    "publication": publication,
                },
                status=status.HTTP_200_OK,
            )
        return Response({"detail": "No quote found."}, status=status.HTTP_404_NOT_FOUND)

    if strict_freshness and result.must_not_use_for_decision:
        payload = result.to_dict()
        payload["detail"] = (
            "最新行情快照已超过 freshness 阈值；strict_freshness 模式下已阻断决策态读取。"
        )
        return Response(payload, status=status.HTTP_409_CONFLICT)

    payload = result.to_dict()
    if publication is not None:
        payload["publication_id"] = publication["publication_id"]
        payload["publication"] = publication
    return Response(payload)


@api_view(["GET"])
def fund_nav_series(request: Request) -> Response:
    from datetime import date as date_cls

    fund_code = request.query_params.get("fund_code", "").strip()
    if not fund_code:
        return Response({"detail": "Query parameter 'fund_code' is required."}, status=400)
    publication, blocked = _published_gate(
        request,
        dataset_key="fund.nav",
        default_publication_key="current",
        identity_field="fund_code",
        identity_value=fund_code,
    )
    if blocked is not None:
        return blocked

    def _parse_date(s: str) -> date_cls | None:
        try:
            return date_cls.fromisoformat(s)
        except (ValueError, AttributeError):
            return None

    requested_start = _parse_date(request.query_params.get("start", ""))
    requested_end = _parse_date(request.query_params.get("end", ""))
    bounded_end = _published_bounded_end(requested_end, publication)
    if (
        requested_start is not None
        and bounded_end is not None
        and requested_start > bounded_end
        and publication is not None
    ):
        return _published_empty_intersection_response(
            identity_field="fund_code",
            identity_value=fund_code,
            publication=publication,
        )

    data = make_query_fund_nav_use_case().execute(
        fund_code=fund_code,
        start=requested_start,
        end=bounded_end,
        **({"fact_pks": _publication_member_pks(publication)} if publication is not None else {}),
    )
    payload: dict[str, object] = {"fund_code": fund_code, "total": len(data), "data": data}
    if publication is not None:
        payload.update(
            publication_id=publication["publication_id"],
            publication=publication,
        )
    return Response(payload)


@api_view(["GET"])
def financials(request: Request) -> Response:
    from apps.data_center.domain.enums import FinancialPeriodType

    asset_code = request.query_params.get("asset_code", "").strip()
    if not asset_code:
        return Response({"detail": "Query parameter 'asset_code' is required."}, status=400)
    publication, blocked = _published_gate(
        request,
        dataset_key="equity.financial.fact",
        default_publication_key="current",
        identity_field="asset_code",
        identity_value=asset_code,
    )
    if blocked is not None:
        return blocked

    period_type_raw = request.query_params.get("period_type", "").strip()
    period_type = FinancialPeriodType(period_type_raw) if period_type_raw else None
    limit = int(request.query_params.get("limit", 20))
    member_pks = _publication_member_pks(publication)
    financial_use_case = make_query_financials_use_case()
    if publication is None:
        data = financial_use_case.execute(
            asset_code=asset_code,
            period_type=period_type,
            limit=limit,
        )
    else:
        data = financial_use_case.execute(
            asset_code=asset_code,
            period_type=period_type,
            limit=limit,
            end=_published_as_of_date(publication),
            fact_pks=member_pks,
        )
    payload = {"asset_code": asset_code, "total": len(data), "data": data}
    if publication is not None:
        payload["publication_id"] = publication["publication_id"]
        payload["publication"] = publication
    return Response(payload)


@api_view(["GET"])
def valuations(request: Request) -> Response:
    from datetime import date as date_cls

    asset_code = request.query_params.get("asset_code", "").strip()
    if not asset_code:
        return Response({"detail": "Query parameter 'asset_code' is required."}, status=400)
    publication, blocked = _published_gate(
        request,
        dataset_key="equity.valuation.fact",
        default_publication_key="current",
        identity_field="asset_code",
        identity_value=asset_code,
    )
    if blocked is not None:
        return blocked

    def _parse_date(s: str) -> date_cls | None:
        try:
            return date_cls.fromisoformat(s)
        except (ValueError, AttributeError):
            return None

    requested_start = _parse_date(request.query_params.get("start", ""))
    requested_end = _parse_date(request.query_params.get("end", ""))
    bounded_end = _published_bounded_end(requested_end, publication)
    member_pks = _publication_member_pks(publication)
    if (
        requested_start is not None
        and bounded_end is not None
        and requested_start > bounded_end
        and publication is not None
    ):
        return _published_empty_intersection_response(
            identity_field="asset_code",
            identity_value=asset_code,
            publication=publication,
        )

    data = make_query_valuations_use_case().execute(
        asset_code=asset_code,
        start=requested_start,
        end=bounded_end,
        fact_pks=member_pks,
    )
    payload = {"asset_code": asset_code, "total": len(data), "data": data}
    if publication is not None:
        payload["publication_id"] = publication["publication_id"]
        payload["publication"] = publication
    return Response(payload)


@api_view(["GET"])
def sector_constituents(request: Request) -> Response:
    from datetime import date as date_cls

    sector_code = request.query_params.get("sector_code", "").strip()
    if not sector_code:
        return Response({"detail": "Query parameter 'sector_code' is required."}, status=400)

    publication, blocked = _published_gate(
        request,
        dataset_key="sector.membership",
        default_publication_key=sector_code,
        identity_field="sector_code",
        identity_value=sector_code,
    )
    if blocked is not None:
        return blocked

    as_of_raw = request.query_params.get("as_of", "").strip()
    as_of = None
    if as_of_raw:
        try:
            as_of = date_cls.fromisoformat(as_of_raw)
        except ValueError:
            return Response({"detail": "Invalid 'as_of' date."}, status=400)
    publication_as_of = _published_as_of_date(publication)
    if publication_as_of is not None and (as_of is None or as_of > publication_as_of):
        as_of = publication_as_of
    member_pks = _publication_member_pks(publication)

    data = make_query_sector_constituents_use_case().execute(
        sector_code=sector_code,
        as_of=as_of,
        fact_pks=member_pks,
    )
    payload: dict[str, object] = {
        "sector_code": sector_code,
        "total": len(data),
        "data": data,
    }
    if publication is not None:
        payload["publication_id"] = publication["publication_id"]
        payload["publication"] = publication
    return Response(payload)


@api_view(["GET"])
def news(request: Request) -> Response:
    asset_code = request.query_params.get("asset_code", "").strip() or None
    publication, blocked = _published_gate(
        request,
        dataset_key="market.news",
        default_publication_key="current",
        identity_field="asset_code",
        identity_value=asset_code or "",
    )
    if blocked is not None:
        return blocked
    limit = int(request.query_params.get("limit", 50))
    member_pks = _publication_member_pks(publication)
    news_use_case = make_query_news_use_case()
    if publication is None:
        data = news_use_case.execute(asset_code=asset_code, limit=limit)
    else:
        data = news_use_case.execute(
            asset_code=asset_code,
            limit=limit,
            end=_published_as_of_date(publication),
            fact_pks=member_pks,
        )
    payload: dict[str, object] = {"asset_code": asset_code, "total": len(data), "data": data}
    if publication is not None:
        payload["publication_id"] = publication["publication_id"]
        payload["publication"] = publication
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def capital_flows(request: Request) -> Response:
    publication, blocked = _published_gate(
        request,
        dataset_key="market.capital_flow",
        default_publication_key="current",
        identity_field="asset_code",
        identity_value=request.query_params.get("asset_code", "").strip(),
    )
    if blocked is not None:
        return blocked
    query_params = request.query_params.copy()
    # ``mode``/``publication_key`` belong to the shared publication gate, not
    # the fact-range serializer's domain payload.
    query_params.pop("mode", None)
    query_params.pop("publication_key", None)
    serializer = CapitalFlowQuerySerializer(data=query_params)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data
    requested_start = query.get("start")
    requested_end = query.get("end")
    bounded_end = _published_bounded_end(requested_end, publication)
    member_pks = _publication_member_pks(publication)
    if (
        requested_start is not None
        and bounded_end is not None
        and requested_start > bounded_end
        and publication is not None
    ):
        return _published_empty_intersection_response(
            identity_field="asset_code",
            identity_value=query["asset_code"],
            publication=publication,
        )
    data = make_query_capital_flows_use_case().execute(
        asset_code=query["asset_code"],
        start=requested_start,
        end=bounded_end,
        limit=query["limit"],
        fact_pks=member_pks,
    )
    payload: dict[str, object] = {
        "asset_code": query["asset_code"],
        "query": {
            "start": query["start"].isoformat() if query.get("start") else None,
            "end": bounded_end.isoformat() if bounded_end else None,
            "limit": query["limit"],
        },
        "total": len(data),
        "data": data,
    }
    if publication is not None:
        payload["publication_id"] = publication["publication_id"]
        payload["publication"] = publication
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def market_thermometer_current(request: Request) -> Response:
    """Return the latest market-thermometer payload."""

    try:
        use_personal_thresholds = _parse_bool_param(
            request.query_params.get("use_personal_thresholds"),
            field_name="use_personal_thresholds",
            default=True,
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    payload = get_market_thermometer_payload(
        user_id=_authenticated_user_id(request),
        use_personal_thresholds=use_personal_thresholds,
    )
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def market_thermometer_history(request: Request) -> Response:
    """Return recent market-thermometer snapshots."""

    try:
        days = _parse_positive_int_param(
            request.query_params.get("days"),
            field_name="days",
            default=90,
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    data = make_calculate_market_thermometer_use_case().list_history(days=days)
    return Response({"results": data})


@api_view(["GET", "PUT", "PATCH"])
@permission_classes([IsAdminUser])
def market_thermometer_config(request: Request) -> Response:
    """Return or update global market-thermometer config."""

    use_case = make_manage_market_thermometer_config_use_case()
    if request.method == "GET":
        return Response(use_case.get().to_dict())

    serializer = MarketThermometerConfigSerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    updated = use_case.update(**serializer.validated_data)
    return Response(updated.to_dict())


@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def market_thermometer_me(request: Request) -> Response:
    """Return or update current user's threshold override."""

    user_id = _authenticated_user_id(request)
    use_case = make_manage_market_thermometer_user_override_use_case()
    if request.method == "GET":
        return Response(load_market_thermometer_override_payload(user_id=user_id))

    if request.method == "DELETE":
        use_case.delete(user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = MarketThermometerUserOverrideSerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    use_case.upsert(user_id=user_id, **serializer.validated_data)
    return Response(load_market_thermometer_override_payload(user_id=user_id))


@api_view(["POST"])
@permission_classes([IsAdminUser])
def market_thermometer_calculate(request: Request) -> Response:
    """Trigger a manual market-thermometer recalculation."""

    raw_date = str(request_data_mapping(request).get("as_of_date") or "").strip()
    as_of_date = date.fromisoformat(raw_date) if raw_date else None
    snapshot = make_calculate_market_thermometer_use_case().execute(as_of_date=as_of_date)
    return Response(snapshot.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def market_thermometer_sync_inputs(request: Request) -> Response:
    """Trigger input synchronization for the market thermometer."""

    raw_date = str(request_data_mapping(request).get("as_of_date") or "").strip()
    as_of_date = date.fromisoformat(raw_date) if raw_date else None
    payload = make_sync_market_thermometer_inputs_use_case().execute(as_of_date=as_of_date)
    return Response(payload)


@api_view(["POST"])
@permission_classes([IsAdminUser])
def market_thermometer_import_investor_accounts(request: Request) -> Response:
    """Import investor-account CSV text into canonical MacroFact storage."""

    serializer = MarketThermometerImportSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    csv_text = ""
    upload = request.FILES.get("file")
    if upload is not None:
        csv_text = upload.read().decode("utf-8-sig")
    else:
        csv_text = serializer.validated_data.get("csv_text", "")

    if not str(csv_text or "").strip():
        return Response(
            {"detail": "csv_text or file is required."}, status=status.HTTP_400_BAD_REQUEST
        )

    result = make_import_investor_accounts_use_case().execute(
        csv_text,
        dry_run=bool(serializer.validated_data.get("dry_run", False)),
        value_unit=str(serializer.validated_data.get("value_unit") or "户"),
    )
    if bool(serializer.validated_data.get("fail_on_warning", False)) and result.get("warnings"):
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    status_code = status.HTTP_200_OK if result.get("dry_run") else status.HTTP_201_CREATED
    return Response(result, status=status_code)


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


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def pit_manifest_list_create(request: Request) -> Response:
    """List PIT manifests or freeze a new evidence set."""

    if request.method == "GET":
        limit = int(request.query_params.get("limit", 100))
        manifests = make_query_pit_manifest_use_case().list_recent(limit)
        return Response({"results": [serialize_pit_manifest(item) for item in manifests]})
    serializer = BuildPITManifestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    manifest = make_build_pit_manifest_use_case().execute(
        BuildPITManifestRequest(
            as_of_time=data["as_of_time"],
            knowledge_scope=KnowledgeScope(data["knowledge_scope"]),
            calendar_version=data["calendar_version"],
            query_spec=data["query_spec"],
            required_keys=data["required_keys"],
        )
    )
    return Response(serialize_pit_manifest(manifest), status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pit_manifest_detail(request: Request, manifest_id: str) -> Response:
    """Return one immutable PIT manifest."""

    manifest = make_query_pit_manifest_use_case().get(manifest_id)
    if manifest is None:
        return Response({"detail": "Manifest not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(serialize_pit_manifest(manifest))
