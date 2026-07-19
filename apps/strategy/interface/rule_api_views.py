"""Rule-related API viewsets (position-management rules, rule conditions).

Interface层:
- 提供REST API接口，使用DRF ViewSet组织API
- 只做输入验证和输出格式化，禁止业务逻辑
"""

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.strategy.application.interface_services import (
    get_position_management_rule_queryset_for_access,
    get_rule_condition_queryset,
    set_rule_enabled,
)
from apps.strategy.application.position_management_service import (
    PositionManagementService,
    PositionRuleError,
)
from apps.strategy.interface.serializers import (
    PositionManagementEvaluateInputSerializer,
    PositionManagementEvaluateResultSerializer,
    PositionManagementRuleSerializer,
    RuleConditionListSerializer,
    RuleConditionSerializer,
)

# ========================================================================
# Position Management Rule ViewSet
# ========================================================================

class PositionManagementRuleViewSet(viewsets.ModelViewSet):
    """仓位管理规则 CRUD + 评估 API"""

    serializer_class = PositionManagementRuleSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['strategy', 'is_active']
    search_fields = ['name', 'strategy__name']
    ordering_fields = ['updated_at', 'created_at']
    ordering = ['-updated_at']

    def get_queryset(self):
        return get_position_management_rule_queryset_for_access(owner_profile_id=getattr(getattr(self.request.user, "account_profile", None), "id", None), include_all=bool(self.request.user.is_staff or self.request.user.is_superuser))

    @extend_schema(
        summary="评估仓位管理规则",
        description="按规则ID计算买卖价、止盈止损与仓位建议",
        request=PositionManagementEvaluateInputSerializer,
        responses={200: PositionManagementEvaluateResultSerializer}
    )
    @action(detail=True, methods=['post'])
    def evaluate(self, request, pk=None):
        rule = self.get_object()
        if not rule.is_active:
            return Response(
                {'detail': '仓位管理规则未启用'},
                status=status.HTTP_400_BAD_REQUEST
            )

        input_serializer = PositionManagementEvaluateInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        context = input_serializer.validated_data['context']

        try:
            result = PositionManagementService.evaluate(rule=rule, context=context)
        except PositionRuleError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = PositionManagementEvaluateResultSerializer(data=result.to_dict())
        output_serializer.is_valid(raise_exception=True)
        return Response(output_serializer.data)


# ========================================================================
# Rule Condition ViewSet
# ========================================================================

class RuleConditionViewSet(viewsets.ModelViewSet):
    """规则条件 CRUD API"""

    serializer_class = RuleConditionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['strategy', 'rule_type', 'is_enabled']
    search_fields = ['rule_name']
    ordering_fields = ['priority', 'created_at']
    ordering = ['-priority', '-created_at']

    def get_queryset(self):
        return get_rule_condition_queryset()

    def get_serializer_class(self):
        """根据操作选择序列化器"""
        if self.action == 'list':
            return RuleConditionListSerializer
        return RuleConditionSerializer

    @extend_schema(
        summary="启用规则",
        description="启用指定的规则条件",
        responses={200: RuleConditionSerializer}
    )
    @action(detail=True, methods=['post'])
    def enable(self, request, pk=None):
        """启用规则"""
        rule = self.get_object()
        rule = set_rule_enabled(rule.id, True) or rule
        serializer = self.get_serializer(rule)
        return Response(serializer.data)

    @extend_schema(
        summary="停用规则",
        description="停用指定的规则条件",
        responses={200: RuleConditionSerializer}
    )
    @action(detail=True, methods=['post'])
    def disable(self, request, pk=None):
        """停用规则"""
        rule = self.get_object()
        rule = set_rule_enabled(rule.id, False) or rule
        serializer = self.get_serializer(rule)
        return Response(serializer.data)


__all__ = [
    "PositionManagementRuleViewSet",
    "RuleConditionViewSet",
]
