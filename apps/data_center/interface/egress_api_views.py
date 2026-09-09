"""Staff-only configuration and bounded diagnostics for market-data exits."""

from collections.abc import Callable, Mapping
from typing import Protocol, cast

from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.data_center.application import egress_service
from apps.data_center.domain.egress_routing import (
    EgressRequestContext,
    EgressRouteDecision,
    EgressRouteRule,
    EgressRoutingError,
)
from apps.data_center.interface.egress_serializers import (
    EgressContextSerializer,
    EgressEndpointSerializer,
    EgressRuleSerializer,
)
from core.exceptions import ResourceNotFoundError


class _PublicRecord(Protocol):
    """Public service projections must explicitly supply their safe JSON form."""

    def to_dict(self) -> dict[str, object]:
        """Return metadata that contains no resolved credentials."""
        ...


def _public_payload(result: object) -> dict[str, object]:
    """Format pure routing objects and explicitly redacted service projections."""
    labels = {"direct": "直连", "fixed": "固定出口", "direct_fallback": "直连失败后使用备用出口"}
    if isinstance(result, EgressRouteRule):
        return {
            "id": result.rule_id,
            "provider_id": result.provider_id,
            "dataset_key": result.dataset_key,
            "domain_pattern": result.domain_pattern,
            "deployment_region": result.deployment_region,
            "strategy": result.strategy.value,
            "strategy_label": labels[result.strategy.value],
            "fixed_egress_id": result.fixed_egress_id,
            "priority": result.priority,
            "enabled": result.enabled,
        }
    if isinstance(result, EgressRouteDecision):
        return {
            "rule_id": result.rule_id,
            "strategy": result.strategy.value,
            "strategy_label": labels[result.strategy.value],
            "egress_id": result.egress_id,
            "allowed_egress_ids": list(result.candidates),
            "reason": result.reason,
            "matched_domain": result.matched_domain,
        }
    return cast(_PublicRecord, result).to_dict()


def _respond(operation: Callable[[], object], *, status: int = 200) -> Response:
    """Convert input errors without reflecting raw upstream or credential text."""
    try:
        result = operation()
    except ValueError as exc:
        code = getattr(exc, "code", "EGRESS_INVALID_CONFIGURATION")
        if not isinstance(code, str) or not code.startswith("EGRESS_"):
            code = "EGRESS_INVALID_CONFIGURATION"
        return Response(
            {"success": False, "error_code": code, "message": "出口配置或请求参数无效。"},
            status=400,
        )
    if result is None:
        raise ResourceNotFoundError("出口或规则不存在")
    if isinstance(result, tuple):
        return Response({"results": [_public_payload(item) for item in result]})
    payload = _public_payload(result)
    succeeded = payload.get("outcome", "success") == "success"
    return Response({"success": succeeded, "data": payload}, status=status)


def _context(request: Request) -> EgressRequestContext:
    """Validate HTTP input before constructing the domain request context."""
    serializer = EgressContextSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
        return EgressRequestContext(
            provider_id=cast(int, data["provider_id"]),
            dataset_key=cast(str, data["dataset_key"]),
            target_url=cast(str, data["url"]),
            deployment_region=cast(str, data["deployment_region"]),
        )
    except EgressRoutingError as exc:
        raise ValidationError(
            {"error_code": exc.code, "message": "请填写具体的数据集、执行区域和目标地址。"}
        ) from exc


@api_view(["GET", "POST"])
@permission_classes([IsAdminUser])
def egress_endpoint_list(request: Request) -> Response:
    """List registered exits or store one endpoint through Config Center."""
    if request.method == "GET":
        return _respond(egress_service.list_endpoints)
    serializer = EgressEndpointSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return _respond(
        lambda: egress_service.create_endpoint(
            cast(Mapping[str, object], serializer.validated_data)
        ),
        status=201,
    )


@api_view(["GET", "PATCH"])
@permission_classes([IsAdminUser])
def egress_endpoint_detail(request: Request, endpoint_id: int) -> Response:
    """Read safe endpoint metadata or update a subset of its settings."""
    if request.method == "GET":
        return _respond(
            lambda: next(
                (item for item in egress_service.list_endpoints() if item.id == endpoint_id), None
            )
        )
    serializer = EgressEndpointSerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    return _respond(
        lambda: egress_service.update_endpoint(
            endpoint_id, cast(Mapping[str, object], serializer.validated_data)
        )
    )


@api_view(["POST"])
@permission_classes([IsAdminUser])
def egress_endpoint_test(request: Request, endpoint_id: int) -> Response:
    """Test an endpoint against its configured, permitted provider target."""
    context = _context(request) if request.data else None
    return _respond(lambda: egress_service.test_endpoint(endpoint_id, context=context))


@api_view(["GET", "POST"])
@permission_classes([IsAdminUser])
def egress_rule_list(request: Request) -> Response:
    """List rules or create a validated rule with one optional exit."""
    if request.method == "GET":
        return _respond(egress_service.list_rules)
    serializer = EgressRuleSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return _respond(
        lambda: egress_service.create_rule(cast(Mapping[str, object], serializer.validated_data)),
        status=201,
    )


@api_view(["GET", "PATCH"])
@permission_classes([IsAdminUser])
def egress_rule_detail(request: Request, rule_id: int) -> Response:
    """Read or modify a rule, including disabling it without deleting history."""
    if request.method == "GET":
        return _respond(
            lambda: next(
                (item for item in egress_service.list_rules() if item.rule_id == rule_id), None
            )
        )
    serializer = EgressRuleSerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    return _respond(
        lambda: egress_service.update_rule(
            rule_id, cast(Mapping[str, object], serializer.validated_data)
        )
    )


@api_view(["POST"])
@permission_classes([IsAdminUser])
def egress_rule_preview(request: Request) -> Response:
    """Explain the selected route without issuing a provider request."""
    return _respond(lambda: egress_service.preview_route(_context(request)))


@api_view(["POST"])
@permission_classes([IsAdminUser])
def egress_diagnostics(request: Request) -> Response:
    """Run a bounded diagnostic only for a stored, permitted provider target."""
    return _respond(lambda: egress_service.diagnose_route(_context(request)))
