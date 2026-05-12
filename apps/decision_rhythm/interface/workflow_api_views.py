"""Decision rhythm execution workflow API views."""

import logging

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application.use_cases import (
    CancelDecisionRequest,
    ExecuteDecisionRequest,
    PrecheckRequest,
    UpdateQuotaConfigRequest,
)
from ..domain.entities import ExecutionTarget, QuotaPeriod
from .api_response_utils import bad_request_response, internal_error_response
from .dependencies import (
    build_cancel_decision_request_use_case,
    build_execute_decision_dependencies,
    build_precheck_decision_use_case,
    build_update_quota_config_use_case,
)
from .serializers import (
    CancelDecisionRequestSerializer,
    ExecuteDecisionRequestSerializer,
    PrecheckDecisionRequestSerializer,
    UpdateQuotaConfigRequestSerializer,
)

logger = logging.getLogger(__name__)


class PrecheckDecisionView(APIView):
    """
    决策预检查视图

    POST /api/decision-workflow/precheck/
    """

    @extend_schema(
        request=PrecheckDecisionRequestSerializer,
        responses={200: dict},
    )
    def post(self, request) -> Response:
        """
        执行决策预检查

        POST /api/decision-workflow/precheck/
        {
            "candidate_id": "cand_xxx"
        }
        """
        try:
            serializer = PrecheckDecisionRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            candidate_id = serializer.validated_data["candidate_id"]

            use_case = build_precheck_decision_use_case()
            response = use_case.execute(PrecheckRequest(candidate_id=candidate_id))

            if not response.success:
                return Response(
                    {"success": False, "error": response.error or "Precheck failed"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            if response.result is None:
                return Response(
                    {"success": False, "error": "Precheck result is empty"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            return Response(
                {
                    "success": True,
                    "result": {
                        "candidate_id": response.result.candidate_id,
                        "beta_gate_passed": response.result.beta_gate_passed,
                        "quota_ok": response.result.quota_ok,
                        "cooldown_ok": response.result.cooldown_ok,
                        "candidate_valid": response.result.candidate_valid,
                        "warnings": response.result.warnings,
                        "errors": response.result.errors,
                        "details": response.result.details,
                    },
                }
            )

        except DRFValidationError as e:
            return bad_request_response(e.detail)
        except Exception as e:
            logger.error(f"Precheck failed: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ExecuteDecisionRequestView(APIView):
    """
    执行决策请求视图

    POST /api/decision-rhythm/requests/{request_id}/execute/
    """

    @extend_schema(
        request=ExecuteDecisionRequestSerializer,
        responses={200: dict},
    )
    def post(self, request, request_id) -> Response:
        """
        执行决策请求

        POST /api/decision-rhythm/requests/{request_id}/execute/
        {
            "target": "SIMULATED",
            "sim_account_id": 1,
            "asset_code": "000001.SH",
            "action": "buy",
            "quantity": 1000,
            "price": 12.35,
            "reason": "按决策请求执行"
        }
        """
        try:
            dependencies = build_execute_decision_dependencies()

            # 获取决策请求
            decision_request = dependencies.request_repo.get_by_id(request_id)
            if decision_request is None:
                return Response(
                    {"success": False, "error": f"Request not found: {request_id}"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = ExecuteDecisionRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            target = ExecutionTarget(data["target"])

            exec_request = ExecuteDecisionRequest(
                request_id=request_id,
                target=target,
                sim_account_id=data.get("sim_account_id"),
                portfolio_id=data.get("portfolio_id"),
                asset_code=data.get("asset_code") or decision_request.asset_code,
                action=data.get("action", "buy"),
                quantity=data.get("quantity"),
                price=data.get("price"),
                signal_id=data.get("signal_id"),
                shares=data.get("shares"),
                avg_cost=data.get("avg_cost"),
                current_price=data.get("current_price"),
                reason=data.get("reason", "按决策请求执行"),
            )

            response = dependencies.use_case.execute(exec_request)

            if response.success:
                return Response(
                    {
                        "success": True,
                        "result": {
                            "request_id": request_id,
                            "execution_status": (
                                response.result.execution_status if response.result else "EXECUTED"
                            ),
                            "executed_at": (
                                response.result.executed_at.isoformat()
                                if response.result and response.result.executed_at
                                else None
                            ),
                            "execution_ref": (
                                response.result.execution_ref if response.result else None
                            ),
                            "candidate_status": (
                                response.result.candidate_status if response.result else None
                            ),
                        },
                    }
                )
            else:
                return Response(
                    {"success": False, "error": response.error},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except DRFValidationError as e:
            return bad_request_response(e.detail)
        except Exception as e:
            logger.error(f"Execute decision failed: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CancelDecisionRequestView(APIView):
    """
    取消决策请求视图

    POST /api/decision-rhythm/requests/{request_id}/cancel/
    """

    @extend_schema(
        request=CancelDecisionRequestSerializer,
        responses={200: dict},
    )
    def post(self, request, request_id) -> Response:
        """
        取消决策请求

        POST /api/decision-rhythm/requests/{request_id}/cancel/
        {
            "reason": "取消原因"
        }
        """
        try:
            serializer = CancelDecisionRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            reason = serializer.validated_data.get("reason", "")
            use_case = build_cancel_decision_request_use_case()
            response = use_case.execute(CancelDecisionRequest(request_id=request_id, reason=reason))

            if response.success:
                return Response(
                    {
                        "success": True,
                        "result": {
                            "request_id": response.request_id,
                            "status": response.status,
                            "reason": response.reason,
                        },
                    }
                )

            if response.error and response.error.startswith("Request not found:"):
                return Response(
                    {"success": False, "error": response.error},
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(
                {"success": False, "error": response.error or "Cancel failed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        except DRFValidationError as e:
            return bad_request_response(e.detail)
        except Exception as e:
            logger.error(f"Cancel decision failed: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class UpdateQuotaConfigView(APIView):
    """
    更新配额配置 API

    POST /api/decision-rhythm/quota/update/
    """

    @extend_schema(
        request=UpdateQuotaConfigRequestSerializer,
        responses={200: dict},
    )
    def post(self, request) -> Response:
        """
        更新配额配置

        POST /api/decision-rhythm/quota/update/
        {
            "account_id": "1",
            "period": "WEEKLY",
            "max_decisions": 10,
            "max_executions": 5
        }
        """
        try:
            serializer = UpdateQuotaConfigRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data

            use_case = build_update_quota_config_use_case()
            response = use_case.execute(
                UpdateQuotaConfigRequest(
                    account_id=str(data.get("account_id") or "default"),
                    period=QuotaPeriod(data["period"]),
                    max_decisions=int(data.get("max_decisions", 10)),
                    max_executions=int(data.get("max_executions", 5)),
                )
            )

            if not response.success or response.quota is None:
                return Response(
                    {"success": False, "error": response.error or "Update quota failed"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            quota = response.quota

            return Response(
                {
                    "success": True,
                    "quota_id": quota.quota_id,
                    "account_id": quota.account_id,
                    "period": quota.period,
                    "max_decisions": quota.max_decisions,
                    "max_executions": quota.max_execution_count,
                }
            )

        except DRFValidationError as e:
            return bad_request_response(e.detail)
        except (TypeError, ValueError, KeyError) as e:
            return bad_request_response(e)
        except Exception as e:
            return internal_error_response("Failed to update quota config", e)
