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

from datetime import datetime
import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.data_center.application.dtos import (
    CreateProviderRequest,
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
    UpdateProviderRequest,
)
from apps.data_center.application.use_cases import (
    ManageProviderConfigUseCase,
    QueryCapitalFlowsUseCase,
    QueryFinancialsUseCase,
    QueryFundNavUseCase,
    QueryLatestQuoteUseCase,
    QueryMacroSeriesUseCase,
    QueryNewsUseCase,
    QueryPriceHistoryUseCase,
    QuerySectorConstituentsUseCase,
    QueryValuationsUseCase,
    ResolveAssetUseCase,
    RunProviderConnectionTestUseCase,
    SyncCapitalFlowUseCase,
    SyncFinancialUseCase,
    SyncFundNavUseCase,
    SyncMacroUseCase,
    SyncNewsUseCase,
    SyncPriceUseCase,
    SyncQuoteUseCase,
    SyncSectorMembershipUseCase,
    SyncValuationUseCase,
)
from apps.data_center.application.registry_factory import get_registry
from apps.data_center.application.registry_factory import refresh_registry
from apps.data_center.infrastructure.connection_tester import run_connection_test
from apps.data_center.infrastructure.provider_factory import UnifiedProviderFactory
from apps.data_center.infrastructure.repositories import (
    CapitalFlowRepository,
    DataProviderSettingsRepository,
    FinancialFactRepository,
    FundNavRepository,
    MacroFactRepository,
    NewsRepository,
    PriceBarRepository,
    ProviderConfigRepository,
    QuoteSnapshotRepository,
    RawAuditRepository,
    SectorMembershipRepository,
    ValuationFactRepository,
)
from apps.data_center.interface.serializers import (
    ConnectionTestResultSerializer,
    DataProviderSettingsSerializer,
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

# ---------------------------------------------------------------------------
# Lazy dependency factories — keep views testable via simple argument injection
# ---------------------------------------------------------------------------

def _make_repo() -> ProviderConfigRepository:
    return ProviderConfigRepository()


def _make_provider_factory() -> UnifiedProviderFactory:
    return UnifiedProviderFactory(_make_repo())


def _make_raw_audit_repo() -> RawAuditRepository:
    return RawAuditRepository()


def _make_tester():
    """Return a ConnectionTesterProtocol-compatible callable wrapper."""

    class _Tester:
        def test(self, config):
            return run_connection_test(config)

    return _Tester()



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
    repo = _make_repo()
    use_case = ManageProviderConfigUseCase(repo)

    if request.method == "GET":
        providers = use_case.list_all()
        serializer = ProviderConfigListSerializer(
            [p.to_dict() for p in providers], many=True
        )
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
    repo = _make_repo()
    use_case = ManageProviderConfigUseCase(repo)

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
# Connection test
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([IsAdminUser])
def provider_test_connection(request: Request, provider_id: int) -> Response:
    """POST /api/data-center/providers/{id}/test/ — run connectivity probe."""
    repo = _make_repo()
    tester = _make_tester()
    use_case = RunProviderConnectionTestUseCase(repo, tester)
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
    from apps.data_center.infrastructure.models import ProviderConfigModel
    from apps.data_center.domain.enums import DataCapability, ProviderHealthStatus

    # Build a lookup: provider_name → [snapshot] from live registry
    live: dict[str, list[dict]] = {}
    for snap in get_registry().get_all_statuses():
        live.setdefault(snap.provider_name, []).append(snap.to_dict())

    results = []
    for model in ProviderConfigModel.objects.filter(is_active=True).order_by("priority"):
        if model.name in live:
            results.extend(live[model.name])
        else:
            # Provider configured but not yet exercised through registry
            results.append({
                "provider_name": model.name,
                "capability": "N/A",
                "status": ProviderHealthStatus.UNKNOWN.value,
                "consecutive_failures": 0,
                "last_success_at": None,
                "avg_latency_ms": None,
            })

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
    settings_repo = DataProviderSettingsRepository()

    if request.method == "GET":
        settings = settings_repo.load()
        data = {
            "default_source": settings.default_source,
            "enable_failover": settings.enable_failover,
            "failover_tolerance": settings.failover_tolerance,
        }
        return Response(data)

    partial = request.method == "PATCH"
    serializer = DataProviderSettingsSerializer(data=request.data, partial=partial)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data

    current = settings_repo.load()
    from apps.data_center.domain.entities import DataProviderSettings

    updated = DataProviderSettings(
        default_source=d.get("default_source", current.default_source),
        enable_failover=d.get("enable_failover", current.enable_failover),
        failover_tolerance=d.get("failover_tolerance", current.failover_tolerance),
    )
    saved = settings_repo.save(updated)
    return Response({
        "default_source": saved.default_source,
        "enable_failover": saved.enable_failover,
        "failover_tolerance": saved.failover_tolerance,
    })


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
    from apps.data_center.infrastructure.repositories import AssetRepository

    code = request.query_params.get("code", "").strip()
    if not code:
        return Response(
            {"detail": "Query parameter 'code' is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    source_type = request.query_params.get("source_type", "")

    uc = ResolveAssetUseCase(AssetRepository())
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

    from apps.data_center.infrastructure.repositories import (
        IndicatorCatalogRepository,
        MacroFactRepository,
    )

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

    req = MacroSeriesRequest(
        indicator_code=indicator_code,
        start=_parse_date(request.query_params.get("start", "")),
        end=_parse_date(request.query_params.get("end", "")),
        limit=int(request.query_params.get("limit", 500)),
        source=request.query_params.get("source") or None,
    )

    from apps.data_center.application.dtos import MacroDataPoint, MacroSeriesResponse
    from apps.regime.infrastructure.macro_data_provider import DataCenterMacroRepositoryAdapter

    uc = QueryMacroSeriesUseCase(MacroFactRepository(), IndicatorCatalogRepository())
    result = uc.execute(req)
    if result.total > 0:
        return Response(result.to_dict())

    fallback_series = DataCenterMacroRepositoryAdapter().get_series(
        code=indicator_code,
        start_date=req.start,
        end_date=req.end,
        source=req.source,
    )
    fallback_response = MacroSeriesResponse(
        indicator_code=indicator_code,
        name_cn=result.name_cn,
        data=[
            MacroDataPoint(
                indicator_code=indicator.code,
                reporting_period=indicator.reporting_period,
                value=float(indicator.value),
                unit=indicator.unit,
                source=indicator.source,
                quality="legacy",
                published_at=indicator.published_at,
            )
            for indicator in fallback_series[: req.limit]
        ],
        total=min(len(fallback_series), req.limit),
    )
    return Response(fallback_response.to_dict())


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

    from apps.data_center.infrastructure.repositories import PriceBarRepository

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

    uc = QueryPriceHistoryUseCase(PriceBarRepository())
    bars = uc.execute(req)
    return Response({"asset_code": asset_code, "total": len(bars), "data": [b.to_dict() for b in bars]})


@api_view(["GET"])
def price_latest_quote(request: Request) -> Response:
    """GET /api/data-center/prices/quotes/?asset_code=

    Fetch the most recent intraday quote snapshot for a security.

    Query params:
      asset_code — required canonical ticker
    """
    from apps.data_center.application.dtos import QuoteResponse
    from apps.data_center.infrastructure.repositories import QuoteSnapshotRepository
    from apps.realtime.application.price_polling_service import PricePollingUseCase

    asset_code = request.query_params.get("asset_code", "").strip()
    if not asset_code:
        return Response(
            {"detail": "Query parameter 'asset_code' is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    uc = QueryLatestQuoteUseCase(QuoteSnapshotRepository())
    result = uc.execute(LatestQuoteRequest(asset_code=asset_code))
    if result is None:
        fallback_prices = PricePollingUseCase().get_latest_prices([asset_code])
        if fallback_prices:
            fallback = fallback_prices[0]
            result = QuoteResponse(
                asset_code=asset_code,
                snapshot_at=datetime.fromisoformat(fallback["timestamp"]),
                current_price=float(fallback["price"]),
                open=None,
                high=None,
                low=None,
                prev_close=None,
                volume=fallback.get("volume"),
                source=fallback["source"],
            )
        else:
            return Response({"detail": "No quote found."}, status=status.HTTP_404_NOT_FOUND)
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

    data = QueryFundNavUseCase(FundNavRepository()).execute(
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
    data = QueryFinancialsUseCase(FinancialFactRepository()).execute(
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

    data = QueryValuationsUseCase(ValuationFactRepository()).execute(
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

    data = QuerySectorConstituentsUseCase(SectorMembershipRepository()).execute(
        sector_code=sector_code,
        as_of=as_of,
    )
    return Response({"sector_code": sector_code, "total": len(data), "data": data})


@api_view(["GET"])
def news(request: Request) -> Response:
    asset_code = request.query_params.get("asset_code", "").strip() or None
    limit = int(request.query_params.get("limit", 50))
    data = QueryNewsUseCase(NewsRepository()).execute(asset_code=asset_code, limit=limit)
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

    data = QueryCapitalFlowsUseCase(CapitalFlowRepository()).execute(
        asset_code=asset_code,
        start=_parse_date(request.query_params.get("start", "")),
        end=_parse_date(request.query_params.get("end", "")),
    )
    return Response({"asset_code": asset_code, "total": len(data), "data": data})


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_macro(request: Request) -> Response:
    serializer = SyncMacroRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncMacroRequest(**serializer.validated_data)
    result = SyncMacroUseCase(
        provider_repo=_make_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=MacroFactRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    ).execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_prices(request: Request) -> Response:
    serializer = SyncPriceRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncPriceRequest(**serializer.validated_data)
    result = SyncPriceUseCase(
        provider_repo=_make_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=PriceBarRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    ).execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_quotes(request: Request) -> Response:
    serializer = SyncQuoteRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncQuoteRequest(**serializer.validated_data)
    result = SyncQuoteUseCase(
        provider_repo=_make_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=QuoteSnapshotRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    ).execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_fund_nav(request: Request) -> Response:
    serializer = SyncFundNavRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncFundNavRequest(**serializer.validated_data)
    result = SyncFundNavUseCase(
        provider_repo=_make_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=FundNavRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    ).execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_financials(request: Request) -> Response:
    serializer = SyncFinancialRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncFinancialRequest(**serializer.validated_data)
    result = SyncFinancialUseCase(
        provider_repo=_make_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=FinancialFactRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    ).execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_valuations(request: Request) -> Response:
    serializer = SyncValuationRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncValuationRequest(**serializer.validated_data)
    result = SyncValuationUseCase(
        provider_repo=_make_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=ValuationFactRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    ).execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_sector_constituents(request: Request) -> Response:
    serializer = SyncSectorMembershipRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncSectorMembershipRequest(**serializer.validated_data)
    result = SyncSectorMembershipUseCase(
        provider_repo=_make_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=SectorMembershipRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    ).execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_news(request: Request) -> Response:
    serializer = SyncNewsRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncNewsRequest(**serializer.validated_data)
    result = SyncNewsUseCase(
        provider_repo=_make_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=NewsRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    ).execute(req)
    return Response(result.to_dict())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_capital_flows(request: Request) -> Response:
    serializer = SyncCapitalFlowRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    req = SyncCapitalFlowRequest(**serializer.validated_data)
    result = SyncCapitalFlowUseCase(
        provider_repo=_make_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=CapitalFlowRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    ).execute(req)
    return Response(result.to_dict())
