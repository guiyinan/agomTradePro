"""Portfolio plan preview, approval and execution handoff APIs."""

from decimal import Decimal

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.portfolio.composition import (
    get_transition_plan,
    make_build_transition_plan_use_case,
    make_submit_approved_plan_use_case,
    make_validate_transition_plan_use_case,
)
from apps.portfolio.domain.entities import (
    PortfolioSnapshot,
    TargetPortfolio,
    TargetPosition,
    TransitionPlan,
)
from apps.simulated_trading.application.interface_services import get_account_access


class BuildTransitionPlanSerializer(serializers.Serializer[dict[str, object]]):
    idempotency_key = serializers.CharField(max_length=128)
    account_id = serializers.CharField(max_length=64)
    portfolio_snapshot_id = serializers.CharField(max_length=64)
    as_of_time = serializers.DateTimeField()
    cash = serializers.DecimalField(max_digits=24, decimal_places=4)
    current_positions = serializers.DictField(child=serializers.DictField(), default=dict)
    target_portfolio_id = serializers.CharField(max_length=64)
    decision_snapshot_id = serializers.CharField(max_length=64)
    target_positions = serializers.ListField(child=serializers.DictField(), allow_empty=True)
    target_cash_weight = serializers.DecimalField(max_digits=10, decimal_places=8)
    strategy_version = serializers.CharField(max_length=64)
    explanation = serializers.CharField(required=False, allow_blank=True)
    prices = serializers.DictField(child=serializers.DecimalField(max_digits=24, decimal_places=8))
    market_facts = serializers.DictField(child=serializers.DictField(), default=dict)
    expires_at = serializers.DateTimeField()


def _serialize(plan: TransitionPlan) -> dict[str, object]:
    return {
        "plan_id": plan.plan_id,
        "idempotency_key": plan.idempotency_key,
        "account_id": plan.account_id,
        "decision_snapshot_id": plan.decision_snapshot_id,
        "portfolio_snapshot_id": plan.portfolio_snapshot_id,
        "target_portfolio_id": plan.target_portfolio_id,
        "as_of_time": plan.as_of_time.isoformat(),
        "expires_at": plan.expires_at.isoformat(),
        "orders": [
            {
                "asset_code": item.asset_code,
                "side": item.side,
                "quantity": item.quantity,
                "reference_price": str(item.reference_price),
                "estimated_fee": str(item.estimated_fee),
                "status": item.status,
                "remaining_quantity": item.remaining_quantity,
            }
            for item in plan.orders
        ],
        "constraints": [item.__dict__ for item in plan.constraints],
        "cash_before": str(plan.cash_before),
        "cash_after": str(plan.cash_after),
        "status": plan.status,
        "version": plan.version,
        "planning_policy_version": plan.metadata.get("planning_policy_version", ""),
    }


def _require_account_access(request: object, account_id: str, *, action: str) -> Response | None:
    """Require one numeric account owned by the authenticated caller."""

    if not account_id.isdigit():
        return Response({"detail": "account_id must identify an owned account."}, status=400)
    access = get_account_access(getattr(request, "user", None), int(account_id), action=action)
    if access.error:
        return Response({"detail": access.error}, status=access.status_code)
    return None


class TransitionPlanListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):  # type: ignore[no-untyped-def]
        serializer = BuildTransitionPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        access_error = _require_account_access(request, str(data["account_id"]), action="创建计划")
        if access_error is not None:
            return access_error
        target = TargetPortfolio(
            target_id=data["target_portfolio_id"],
            decision_snapshot_id=data["decision_snapshot_id"],
            positions=tuple(
                TargetPosition(
                    asset_code=str(item["asset_code"]),
                    target_weight=Decimal(str(item["target_weight"])),
                )
                for item in data["target_positions"]
            ),
            target_cash_weight=data["target_cash_weight"],
            strategy_version=data["strategy_version"],
            explanation=data.get("explanation", ""),
        )
        current = PortfolioSnapshot(
            snapshot_id=data["portfolio_snapshot_id"],
            account_id=data["account_id"],
            as_of_time=data["as_of_time"],
            cash=data["cash"],
            positions=data["current_positions"],
        )
        try:
            plan = make_build_transition_plan_use_case().execute(
                idempotency_key=data["idempotency_key"],
                target=target,
                current=current,
                prices={key: Decimal(str(value)) for key, value in data["prices"].items()},
                market_facts=data["market_facts"],
                expires_at=data["expires_at"],
            )
        except ValueError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return Response(_serialize(plan), status=status.HTTP_201_CREATED)


class TransitionPlanDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, plan_id: str):  # type: ignore[no-untyped-def]
        plan = get_transition_plan(plan_id)
        if plan is None:
            return Response({"detail": "Plan not found."}, status=status.HTTP_404_NOT_FOUND)
        access_error = _require_account_access(request, plan.account_id, action="查看计划")
        if access_error is not None:
            return access_error
        return Response(_serialize(plan))


class TransitionPlanApproveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, plan_id: str):  # type: ignore[no-untyped-def]
        existing = get_transition_plan(plan_id)
        if existing is None:
            return Response({"detail": "Plan not found."}, status=status.HTTP_404_NOT_FOUND)
        access_error = _require_account_access(request, existing.account_id, action="审批计划")
        if access_error is not None:
            return access_error
        decision_snapshot_id = str(request.data.get("decision_snapshot_id") or "")
        if not decision_snapshot_id:
            return Response({"detail": "decision_snapshot_id is required."}, status=400)
        try:
            plan = make_validate_transition_plan_use_case().execute(plan_id, decision_snapshot_id)
        except ValueError as exc:
            raise serializers.ValidationError({"decision_snapshot_id": [str(exc)]}) from exc
        return Response(_serialize(plan))


class TransitionPlanSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, plan_id: str):  # type: ignore[no-untyped-def]
        existing = get_transition_plan(plan_id)
        if existing is None:
            return Response({"detail": "Plan not found."}, status=status.HTTP_404_NOT_FOUND)
        access_error = _require_account_access(request, existing.account_id, action="提交计划")
        if access_error is not None:
            return access_error
        try:
            plan = make_submit_approved_plan_use_case().execute(plan_id)
        except ValueError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return Response({"execution_handoff": _serialize(plan)})
