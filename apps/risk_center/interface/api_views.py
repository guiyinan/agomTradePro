"""Risk center API views."""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.risk_center.application.trade_guard import (
    EvaluatePostInvestmentRiskUseCase,
    EvaluatePreTradeRiskUseCase,
    GenerateRiskCenterDailyReportUseCase,
)
from apps.risk_center.application.use_cases import (
    ApplyRiskTemplateToPolicyUseCase,
    CreateRiskExceptionUseCase,
    CreateRiskTemplateUseCase,
    GetAccountRiskPolicyUseCase,
    GetEffectiveRiskPolicyUseCase,
    GetRiskCenterDailyReportUseCase,
    GetRiskFloorUseCase,
    ListAccountRiskPoliciesUseCase,
    ListRiskCenterDailyReportsUseCase,
    ListRiskExceptionsUseCase,
    ListRiskTemplatesUseCase,
    RiskCenterAccessDeniedError,
    RiskCenterNotFoundError,
    RiskCenterValidationError,
    UpdateRiskFloorUseCase,
    UpdateRiskTemplateUseCase,
    UpsertAccountRiskPolicyUseCase,
)
from apps.risk_center.interface.serializers import (
    AccountRiskPolicySerializer,
    AccountRiskPolicyUpdateSerializer,
    ApplyTemplateSerializer,
    PostInvestmentRiskCheckSerializer,
    PreTradeRiskCheckSerializer,
    RiskCenterDailyReportQuerySerializer,
    RiskCenterDailyReportSerializer,
    RiskExceptionSerializer,
    RiskFloorSerializer,
    RiskTemplateSerializer,
    RiskTemplateUpdateSerializer,
)


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _serialize_model(model: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in model._meta.fields:
        value = getattr(model, field.name)
        if hasattr(value, "pk"):
            value = value.pk
        payload[field.name] = _iso(value)
    if hasattr(model, "template") and getattr(model, "template", None):
        payload["template_key"] = model.template.key
        payload["template_name"] = model.template.name
    if hasattr(model, "created_by") and getattr(model, "created_by", None):
        payload["created_by_username"] = model.created_by.username
    if hasattr(model, "is_current"):
        payload["is_current"] = model.is_current
    return payload


def _serialize_daily_report(model: Any) -> dict[str, Any]:
    return {
        "id": model.id,
        "account_id": model.account_id,
        "report_date": _iso(model.report_date),
        "status": model.status,
        "risk_daily_report": model.risk_daily_report or {},
        "position_daily_report": model.position_daily_report or {},
        "post_investment_check": model.post_investment_check or {},
        "input_snapshot": model.input_snapshot or {},
        "generated_by": getattr(model.generated_by, "username", None),
        "created_at": _iso(model.created_at),
        "updated_at": _iso(model.updated_at),
    }


def _error_response(exc: Exception) -> Response:
    if isinstance(exc, RiskCenterAccessDeniedError):
        return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    if isinstance(exc, RiskCenterNotFoundError):
        return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, RiskCenterValidationError):
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class RiskCenterApiHomeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        return Response(
            {
                "module": "risk-center",
                "endpoints": {
                    "floor": "/api/risk-center/floor/",
                    "templates": "/api/risk-center/templates/",
                    "account_policies": "/api/risk-center/account-policies/",
                    "exceptions": "/api/risk-center/exceptions/",
                    "effective_policy": "/api/risk-center/effective-policy/?account_id=1",
                    "pre_trade_check": "/api/risk-center/pre-trade-check/",
                    "post_investment_check": "/api/risk-center/post-investment-check/",
                    "daily_report": "/api/risk-center/daily-report/",
                    "daily_report_history": "/api/risk-center/daily-report/?account_id=1",
                },
            }
        )


class RiskFloorView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        try:
            floor = GetRiskFloorUseCase().execute(actor=request.user)
        except RiskCenterAccessDeniedError as exc:
            return _error_response(exc)
        return Response({"success": True, "data": _serialize_model(floor)})

    def put(self, request) -> Response:
        serializer = RiskFloorSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            floor = UpdateRiskFloorUseCase().execute(
                actor=request.user,
                payload=serializer.validated_data,
            )
        except (RiskCenterAccessDeniedError, RiskCenterValidationError) as exc:
            return _error_response(exc)
        return Response({"success": True, "data": _serialize_model(floor)})


class RiskTemplateListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        try:
            templates = ListRiskTemplatesUseCase().execute(actor=request.user)
        except RiskCenterAccessDeniedError as exc:
            return _error_response(exc)
        return Response({"success": True, "data": [_serialize_model(item) for item in templates]})

    def post(self, request) -> Response:
        serializer = RiskTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            template = CreateRiskTemplateUseCase().execute(
                actor=request.user,
                payload=serializer.validated_data,
            )
        except (RiskCenterAccessDeniedError, RiskCenterValidationError) as exc:
            return _error_response(exc)
        return Response(
            {"success": True, "data": _serialize_model(template)},
            status=status.HTTP_201_CREATED,
        )


class RiskTemplateDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, template_id: int) -> Response:
        return self._update(request, template_id, partial=False)

    def patch(self, request, template_id: int) -> Response:
        return self._update(request, template_id, partial=True)

    def get(self, request, template_id: int) -> Response:
        try:
            templates = ListRiskTemplatesUseCase().execute(actor=request.user)
        except RiskCenterAccessDeniedError as exc:
            return _error_response(exc)
        for template in templates:
            if template.id == template_id:
                return Response({"success": True, "data": _serialize_model(template)})
        return Response({"detail": "Risk template not found."}, status=status.HTTP_404_NOT_FOUND)

    def _update(self, request, template_id: int, *, partial: bool) -> Response:
        serializer = RiskTemplateUpdateSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            template = UpdateRiskTemplateUseCase().execute(
                actor=request.user,
                template_id=template_id,
                payload=serializer.validated_data,
            )
        except (RiskCenterAccessDeniedError, RiskCenterNotFoundError) as exc:
            return _error_response(exc)
        return Response({"success": True, "data": _serialize_model(template)})


class AccountRiskPolicyListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        try:
            policies = ListAccountRiskPoliciesUseCase().execute(actor=request.user)
        except RiskCenterAccessDeniedError as exc:
            return _error_response(exc)
        return Response({"success": True, "data": [_serialize_model(item) for item in policies]})

    def post(self, request) -> Response:
        serializer = AccountRiskPolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            policy = UpsertAccountRiskPolicyUseCase().execute(
                actor=request.user,
                payload=serializer.validated_data,
            )
        except (RiskCenterAccessDeniedError, RiskCenterValidationError) as exc:
            return _error_response(exc)
        return Response(
            {"success": True, "data": _serialize_model(policy)},
            status=status.HTTP_201_CREATED,
        )


class AccountRiskPolicyByAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id: int) -> Response:
        try:
            policy = GetAccountRiskPolicyUseCase().execute(
                actor=request.user,
                account_id=account_id,
            )
        except RiskCenterAccessDeniedError as exc:
            return _error_response(exc)
        if policy is None:
            return Response(
                {"detail": "Account risk policy not found."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response({"success": True, "data": _serialize_model(policy)})


class AccountRiskPolicyDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, policy_id: int) -> Response:
        return self._update(request, policy_id, partial=False)

    def patch(self, request, policy_id: int) -> Response:
        return self._update(request, policy_id, partial=True)

    def _update(self, request, policy_id: int, *, partial: bool) -> Response:
        serializer = AccountRiskPolicyUpdateSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        if "account_id" not in payload:
            policy = ListAccountRiskPoliciesUseCase().execute(actor=request.user)
            matched = next((item for item in policy if item.id == policy_id), None)
            if matched is None:
                return Response(
                    {"detail": "Account risk policy not found."}, status=status.HTTP_404_NOT_FOUND
                )
            payload["account_id"] = matched.account_id
        try:
            updated = UpsertAccountRiskPolicyUseCase().execute(
                actor=request.user,
                payload=payload,
            )
        except RiskCenterAccessDeniedError as exc:
            return _error_response(exc)
        return Response({"success": True, "data": _serialize_model(updated)})


class ApplyTemplateToPolicyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, policy_id: int) -> Response:
        serializer = ApplyTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            policy = ApplyRiskTemplateToPolicyUseCase().execute(
                actor=request.user,
                policy_id=policy_id,
                template_id=serializer.validated_data["template_id"],
            )
        except (RiskCenterAccessDeniedError, RiskCenterNotFoundError) as exc:
            return _error_response(exc)
        return Response({"success": True, "data": _serialize_model(policy)})


class RiskExceptionListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        account_id = request.query_params.get("account_id")
        try:
            exceptions = ListRiskExceptionsUseCase().execute(
                actor=request.user,
                account_id=int(account_id) if account_id else None,
            )
        except RiskCenterAccessDeniedError as exc:
            return _error_response(exc)
        return Response({"success": True, "data": [_serialize_model(item) for item in exceptions]})

    def post(self, request) -> Response:
        serializer = RiskExceptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            exception = CreateRiskExceptionUseCase().execute(
                actor=request.user,
                payload=serializer.validated_data,
            )
        except (RiskCenterAccessDeniedError, RiskCenterValidationError) as exc:
            return _error_response(exc)
        return Response(
            {"success": True, "data": _serialize_model(exception)},
            status=status.HTTP_201_CREATED,
        )


class EffectiveRiskPolicyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        account_id = request.query_params.get("account_id")
        if not account_id:
            return Response(
                {"detail": "account_id is required."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            payload = GetEffectiveRiskPolicyUseCase().execute(
                actor=request.user,
                account_id=int(account_id),
            )
        except (RiskCenterAccessDeniedError, RiskCenterNotFoundError) as exc:
            return _error_response(exc)
        return Response({"success": True, "data": payload})


class PreTradeRiskCheckView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request) -> Response:
        serializer = PreTradeRiskCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        account_id = int(payload["account_id"])
        try:
            GetEffectiveRiskPolicyUseCase().execute(
                actor=request.user,
                account_id=account_id,
            )
            result = EvaluatePreTradeRiskUseCase().execute(
                account_id=account_id,
                symbol=str(payload["symbol"]),
                side=str(payload["side"]),
                quantity=float(payload["quantity"]),
                price=float(payload["price"]),
                account_equity=float(payload["account_equity"]),
                total_position_value=float(payload["total_position_value"]),
                cash_balance=(
                    float(payload["cash_balance"])
                    if payload.get("cash_balance") is not None
                    else None
                ),
                current_symbol_position_value=float(
                    payload.get("current_symbol_position_value") or 0.0
                ),
            )
        except (RiskCenterAccessDeniedError, RiskCenterNotFoundError) as exc:
            return _error_response(exc)
        return Response(
            {
                "success": True,
                "data": {
                    "passed": result.passed,
                    "violations": result.violations,
                    "warnings": result.warnings,
                    "metrics": result.metrics,
                    "effective_policy": result.effective_policy,
                },
            }
        )


class PostInvestmentRiskCheckView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request) -> Response:
        serializer = PostInvestmentRiskCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        account_id = int(payload["account_id"])
        try:
            GetEffectiveRiskPolicyUseCase().execute(
                actor=request.user,
                account_id=account_id,
            )
            result = EvaluatePostInvestmentRiskUseCase().execute(
                account_id=account_id,
                account_equity=float(payload["account_equity"]),
                cash_balance=(
                    float(payload["cash_balance"])
                    if payload.get("cash_balance") is not None
                    else None
                ),
                total_position_value=(
                    float(payload["total_position_value"])
                    if payload.get("total_position_value") is not None
                    else None
                ),
                daily_pnl_pct=(
                    float(payload["daily_pnl_pct"])
                    if payload.get("daily_pnl_pct") is not None
                    else None
                ),
                drawdown_pct=(
                    float(payload["drawdown_pct"])
                    if payload.get("drawdown_pct") is not None
                    else None
                ),
                positions=list(payload.get("positions") or []),
            )
        except (RiskCenterAccessDeniedError, RiskCenterNotFoundError) as exc:
            return _error_response(exc)
        return Response(
            {
                "success": True,
                "data": {
                    "status": result.status,
                    "passed": result.passed,
                    "violations": result.violations,
                    "warnings": result.warnings,
                    "position_alerts": result.position_alerts,
                    "metrics": result.metrics,
                    "effective_policy": result.effective_policy,
                },
            }
        )


class RiskCenterDailyReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        serializer = RiskCenterDailyReportQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        account_id = int(payload["account_id"]) if payload.get("account_id") is not None else None
        try:
            if account_id is not None and payload.get("report_date") is not None:
                report = GetRiskCenterDailyReportUseCase().execute(
                    actor=request.user,
                    account_id=account_id,
                    report_date=payload["report_date"],
                )
                return Response({"success": True, "data": _serialize_daily_report(report)})
            reports = ListRiskCenterDailyReportsUseCase().execute(
                actor=request.user,
                account_id=account_id,
                start_date=payload.get("report_date") or payload.get("start_date"),
                end_date=payload.get("report_date") or payload.get("end_date"),
                limit=int(payload.get("limit") or 90),
            )
        except (RiskCenterAccessDeniedError, RiskCenterNotFoundError) as exc:
            return _error_response(exc)
        return Response({"success": True, "data": [_serialize_daily_report(item) for item in reports]})

    def post(self, request) -> Response:
        serializer = RiskCenterDailyReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        account_id = int(payload["account_id"])
        try:
            GetEffectiveRiskPolicyUseCase().execute(
                actor=request.user,
                account_id=account_id,
            )
            result = GenerateRiskCenterDailyReportUseCase().execute(
                account_id=account_id,
                report_date=(
                    payload["report_date"].isoformat()
                    if payload.get("report_date") is not None
                    else timezone.localdate().isoformat()
                ),
                account_equity=float(payload["account_equity"]),
                cash_balance=(
                    float(payload["cash_balance"])
                    if payload.get("cash_balance") is not None
                    else None
                ),
                total_position_value=(
                    float(payload["total_position_value"])
                    if payload.get("total_position_value") is not None
                    else None
                ),
                daily_pnl_pct=(
                    float(payload["daily_pnl_pct"])
                    if payload.get("daily_pnl_pct") is not None
                    else None
                ),
                drawdown_pct=(
                    float(payload["drawdown_pct"])
                    if payload.get("drawdown_pct") is not None
                    else None
                ),
                positions=list(payload.get("positions") or []),
                actor=request.user,
            )
        except (RiskCenterAccessDeniedError, RiskCenterNotFoundError) as exc:
            return _error_response(exc)
        return Response(
            {
                "success": True,
                "data": {
                    "report_id": result.report_id,
                    "account_id": result.account_id,
                    "report_date": result.report_date,
                    "risk_daily_report": result.risk_daily_report,
                    "position_daily_report": result.position_daily_report,
                    "post_investment_check": result.post_investment_check,
                },
            }
        )
