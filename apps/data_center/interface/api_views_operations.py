"""
Data Center operational API views

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
from datetime import date

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.data_center.application.dtos import (
    DecisionReliabilityRepairRequest,
    SyncCapitalFlowRequest,
    SyncFinancialRequest,
    SyncFundNavRequest,
    SyncMacroRequest,
    SyncNewsRequest,
    SyncPriceRequest,
    SyncQuoteRequest,
    SyncSectorMembershipRequest,
    SyncValuationRequest,
)
from apps.data_center.application.interface_services import (
    load_market_thermometer_override_payload,
    make_import_investor_accounts_use_case,
    make_manage_market_thermometer_config_use_case,
    make_manage_market_thermometer_user_override_use_case,
    make_sync_capital_flow_use_case,
    make_sync_fund_nav_use_case,
    make_sync_market_thermometer_inputs_use_case,
    make_sync_news_use_case,
    make_sync_price_use_case,
    make_sync_quote_use_case,
    make_sync_sector_membership_use_case,
)
from apps.data_center.application.pit_use_cases import BuildPITManifestRequest
from apps.data_center.application.public import (
    get_market_thermometer_payload,
    make_calculate_market_thermometer_use_case,
    make_sync_financial_use_case,
    make_sync_macro_use_case,
    make_sync_valuation_use_case,
)
from apps.data_center.composition import (
    make_build_pit_manifest_use_case,
    make_query_pit_manifest_use_case,
)
from apps.data_center.domain.pit import KnowledgeScope
from apps.data_center.interface.auth_helpers import _authenticated_user_id
from apps.data_center.interface.pit_serializers import (
    BuildPITManifestSerializer,
    serialize_pit_manifest,
)
from apps.data_center.interface.query_params import (
    _parse_bool_param,
    _parse_positive_int_param,
)
from apps.data_center.interface.serializers import (
    DecisionReliabilityRepairRequestSerializer,
    MarketThermometerConfigSerializer,
    MarketThermometerImportSerializer,
    MarketThermometerUserOverrideSerializer,
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
from shared.request_payload import request_data_mapping

logger = logging.getLogger(__name__)


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
    from apps.data_center.interface.api_views import _make_decision_repair_use_case

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
