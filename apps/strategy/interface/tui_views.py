"""TUI-only typed adapters for strategy configuration."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.strategy.application.interface_services import (
    get_rule_condition_queryset_for_access,
    get_strategy_queryset_for_access,
    strategy_is_accessible,
)
from apps.strategy.interface.serializers import (
    RuleConditionSerializer,
    StrategyDetailSerializer,
    StrategySerializer,
)
from apps.strategy.interface.tui_serializers import (
    StrategyTuiCreateSerializer,
    StrategyTuiRuleMutationSerializer,
    StrategyTuiUpdateSerializer,
)


def _access_context(request: Request) -> tuple[int | None, bool]:
    """Return owner profile id and staff override for one request."""

    profile_id = getattr(getattr(request.user, "account_profile", None), "id", None)
    if isinstance(profile_id, bool) or not isinstance(profile_id, int) or profile_id <= 0:
        profile_id = None
    include_all = bool(
        getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False)
    )
    return profile_id, include_all


def _require_strategy_access(request: Request, strategy_id: int) -> None:
    """Fail closed when the requested strategy is outside caller scope."""

    owner_profile_id, include_all = _access_context(request)
    if not strategy_is_accessible(
        strategy_id=strategy_id,
        owner_profile_id=owner_profile_id,
        include_all=include_all,
    ):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("无权为该策略配置规则")


class StrategyTuiCreateView(APIView):
    """Create one inactive owner strategy through a scalar contract."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """Create an inactive strategy ready for later configuration."""

        profile = getattr(request.user, "account_profile", None)
        profile_id = getattr(profile, "id", None)
        if isinstance(profile_id, bool) or not isinstance(profile_id, int) or profile_id <= 0:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("当前用户缺少账户档案")

        request_serializer = StrategyTuiCreateSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        owner_payload = {
            **request_serializer.validated_data,
            "version": 1,
            "is_active": False,
        }
        owner_serializer = StrategySerializer(data=owner_payload)
        owner_serializer.is_valid(raise_exception=True)
        instance = owner_serializer.save(created_by=profile)
        return Response(
            StrategyDetailSerializer(instance).data,
            status=status.HTTP_201_CREATED,
        )


class StrategyTuiUpdateView(APIView):
    """Update scalar strategy fields and advance its immutable version number."""

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, strategy_id: int) -> Response:
        """Apply an owner-scoped partial update and bump version once."""

        owner_profile_id, include_all = _access_context(request)
        queryset = get_strategy_queryset_for_access(
            owner_profile_id=owner_profile_id,
            include_all=include_all,
        )
        instance = get_object_or_404(queryset, id=strategy_id)
        request_serializer = StrategyTuiUpdateSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        owner_serializer = StrategySerializer(
            instance,
            data={
                **request_serializer.validated_data,
                "version": int(instance.version) + 1,
            },
            partial=True,
        )
        owner_serializer.is_valid(raise_exception=True)
        updated = owner_serializer.save()
        return Response(StrategyDetailSerializer(updated).data)


class StrategyTuiRuleCreateView(APIView):
    """Create one owner-scoped strategy rule from flat TUI fields."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """Validate, translate, and create one condition rule."""

        request_serializer = StrategyTuiRuleMutationSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload = request_serializer.to_rule_payload()
        _require_strategy_access(request, int(payload["strategy"]))

        owner_serializer = RuleConditionSerializer(data=payload)
        owner_serializer.is_valid(raise_exception=True)
        instance = owner_serializer.save()
        return Response(
            RuleConditionSerializer(instance).data,
            status=status.HTTP_201_CREATED,
        )


class StrategyTuiRuleUpdateView(APIView):
    """Replace one owner-scoped rule through the same flat contract."""

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, rule_id: int) -> Response:
        """Validate, translate, and replace one condition rule."""

        owner_profile_id, include_all = _access_context(request)
        queryset = get_rule_condition_queryset_for_access(
            owner_profile_id=owner_profile_id,
            include_all=include_all,
        )
        instance = get_object_or_404(queryset, id=rule_id)

        request_serializer = StrategyTuiRuleMutationSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload = request_serializer.to_rule_payload()
        _require_strategy_access(request, int(payload["strategy"]))
        if int(instance.strategy_id) != int(payload["strategy"]):
            return Response(
                {"strategy": ["更新规则时不得改变所属策略"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        owner_serializer = RuleConditionSerializer(instance, data=payload)
        owner_serializer.is_valid(raise_exception=True)
        updated = owner_serializer.save()
        return Response(RuleConditionSerializer(updated).data)


__all__ = [
    "StrategyTuiCreateView",
    "StrategyTuiRuleCreateView",
    "StrategyTuiRuleUpdateView",
    "StrategyTuiUpdateView",
]
