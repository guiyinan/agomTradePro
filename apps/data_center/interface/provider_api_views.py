"""Provider configuration endpoints kept separate from the general data APIs."""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.data_center.application.dtos import (
    CreateProviderRequest,
    ProviderResponse,
    UpdateProviderRequest,
)
from apps.data_center.application.interface_services import make_manage_provider_config_use_case
from apps.data_center.application.provider_health import build_capability_health_payload
from apps.data_center.interface.serializers import (
    ProviderConfigListSerializer,
    ProviderConfigSerializer,
    ProviderHealthSnapshotSerializer,
)
from apps.data_center.provider_runtime import get_registry as _runtime_get_registry
from apps.data_center.provider_runtime import refresh_registry
from shared.config.tushare import (
    TUSHARE_REQUEST_MODE_SDK_PATH,
    TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
    TUSHARE_REQUEST_MODE_VALUES,
)
from shared.numeric import safe_float


def get_registry() -> Any:
    """Expose the runtime registry through the provider view module."""

    return _runtime_get_registry()


def _get_provider_health_metric(extra_config: dict[str, Any], capability: str) -> dict[str, Any]:
    """Read dataset-keyed health evidence, retaining capability-keyed compatibility."""

    from apps.data_center.domain.enums import DataCapability

    try:
        dataset_key = DataCapability(capability).dataset_key
    except ValueError:
        dataset_key = capability
    dataset_metrics = extra_config.get("health_metrics_by_dataset") or {}
    if isinstance(dataset_metrics, dict):
        metric = dataset_metrics.get(dataset_key)
        if isinstance(metric, dict):
            return dict(metric)
    if capability and capability != "N/A":
        health_metrics = extra_config.get("health_metrics") or {}
        metric = health_metrics.get(capability)
        if isinstance(metric, dict):
            return dict(metric)
    return {}


def _enrich_provider_status_snapshot(
    snapshot: dict[str, Any], extra_config: dict[str, Any]
) -> dict[str, Any]:
    metric = _get_provider_health_metric(extra_config, str(snapshot.get("capability") or ""))
    enriched = build_capability_health_payload(snapshot, extra_config)
    if enriched.get("last_success_at") in (None, ""):
        enriched["last_success_at"] = metric.get("last_success_at") or extra_config.get(
            "provider_last_success_at"
        )
    if enriched.get("avg_latency_ms") in (None, ""):
        latency = safe_float(
            metric.get("avg_latency_ms", extra_config.get("provider_avg_latency_ms"))
        )
        enriched["avg_latency_ms"] = latency if latency is not None and latency >= 0 else None
    if not enriched.get("consecutive_failures"):
        failures = safe_float(metric.get("consecutive_failures"))
        if failures is not None and failures >= 0 and failures.is_integer():
            enriched["consecutive_failures"] = int(failures)
    return enriched


def _safe_provider_payload(provider: ProviderResponse) -> dict[str, Any]:
    return dict(ProviderConfigListSerializer(provider.to_dict()).data)


def _optional_masked_secret(value: object, *, supplied: bool) -> str | None:
    """Preserve PATCH omission while retaining an explicit blank clear."""

    if not supplied:
        return None
    if not isinstance(value, str):
        return None
    return value if value.strip() else ""


def _provider_extra_config_with_tushare_mode(
    *,
    existing: dict[str, Any],
    submitted: dict[str, Any] | None,
    submitted_mode: object,
    source_type: str,
    http_url: str,
) -> dict[str, Any]:
    extra_config = dict(submitted) if submitted is not None else dict(existing)
    explicit_mode = submitted_mode.strip() if isinstance(submitted_mode, str) else ""
    if source_type != "tushare":
        if explicit_mode:
            raise ValidationError({"tushare_request_mode": "连接方式仅适用于 Tushare 服务商。"})
        extra_config.pop("tushare_request_mode", None)
        return extra_config
    if explicit_mode:
        extra_config["tushare_request_mode"] = explicit_mode
    raw_mode = extra_config.get("tushare_request_mode", TUSHARE_REQUEST_MODE_SDK_PATH)
    mode = raw_mode.strip() if isinstance(raw_mode, str) else ""
    if mode not in TUSHARE_REQUEST_MODE_VALUES:
        raise ValidationError({"tushare_request_mode": "请选择标准 Tushare 或统一中继。"})
    if mode == TUSHARE_REQUEST_MODE_UNIFIED_RELAY and not http_url.strip():
        raise ValidationError({"http_url": "统一中继连接必须填写服务地址。"})
    extra_config["tushare_request_mode"] = mode
    return extra_config


@api_view(["GET", "POST"])
@permission_classes([IsAdminUser])
def provider_list_create(request: Request) -> Response:
    """List provider configs or create one with credentials masked in responses."""
    use_case = make_manage_provider_config_use_case()
    if request.method == "GET":
        serializers = ProviderConfigListSerializer(
            [p.to_dict() for p in use_case.list_all()], many=True
        )
        return Response({"results": serializers.data})
    serializer = ProviderConfigSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    created = use_case.create(
        CreateProviderRequest(
            name=data["name"],
            source_type=data["source_type"],
            is_active=data.get("is_active", True),
            priority=data.get("priority", 100),
            api_key=data.get("api_key", ""),
            api_secret=data.get("api_secret", ""),
            http_url=data.get("http_url", ""),
            api_endpoint=data.get("api_endpoint", ""),
            extra_config=_provider_extra_config_with_tushare_mode(
                existing={},
                submitted=data.get("extra_config"),
                submitted_mode=data.get("tushare_request_mode"),
                source_type=data["source_type"],
                http_url=data.get("http_url", ""),
            ),
            description=data.get("description", ""),
        )
    )
    refresh_registry()
    return Response(_safe_provider_payload(created), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "PUT", "DELETE"])
@permission_classes([IsAdminUser])
def provider_detail(request: Request, provider_id: int) -> Response:
    """Retrieve, update, or delete one provider configuration."""
    use_case = make_manage_provider_config_use_case()
    if request.method == "GET":
        provider = use_case.get(provider_id)
        return (
            Response(_safe_provider_payload(provider))
            if provider
            else Response({"detail": "Not found."}, status=404)
        )
    if request.method == "DELETE":
        if not use_case.delete(provider_id):
            return Response({"detail": "Not found."}, status=404)
        refresh_registry()
        return Response(status=status.HTTP_204_NO_CONTENT)
    serializer = ProviderConfigSerializer(data=request.data, partial=request.method == "PATCH")
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    existing = use_case.get(provider_id)
    if existing is None:
        return Response({"detail": "Not found."}, status=404)
    if data.get("clear_service_address") and data.get("http_url"):
        raise ValidationError({"http_url": "新服务地址与清除现有服务地址不能同时提交。"})
    source_type = data.get("source_type", existing.source_type)
    http_url = "" if data.get("clear_service_address") else data.get("http_url", existing.http_url)
    updated = use_case.update(
        UpdateProviderRequest(
            provider_id=provider_id,
            name=data.get("name"),
            source_type=data.get("source_type"),
            is_active=data.get("is_active"),
            priority=data.get("priority"),
            api_key=_optional_masked_secret(data.get("api_key"), supplied="api_key" in data),
            api_secret=_optional_masked_secret(
                data.get("api_secret"), supplied="api_secret" in data
            ),
            http_url=http_url if "http_url" in data or data.get("clear_service_address") else None,
            api_endpoint=data.get("api_endpoint"),
            extra_config=_provider_extra_config_with_tushare_mode(
                existing=existing.extra_config,
                submitted=data.get("extra_config") if "extra_config" in data else None,
                submitted_mode=data.get("tushare_request_mode"),
                source_type=source_type,
                http_url=http_url,
            ),
            description=data.get("description"),
        )
    )
    if updated is None:
        return Response({"detail": "Not found."}, status=404)
    refresh_registry()
    return Response(_safe_provider_payload(updated))


@api_view(["GET"])
@permission_classes([IsAdminUser])
def provider_status(request: Request) -> Response:
    """Return DB-backed provider health enriched from the live registry."""
    live: dict[str, list[dict[str, Any]]] = {}
    for snapshot in get_registry().get_all_statuses():
        live.setdefault(snapshot.provider_name, []).append(snapshot.to_dict())
    providers = sorted(
        (p for p in make_manage_provider_config_use_case().list_all() if p.is_active),
        key=lambda p: (p.priority, p.name),
    )
    results: list[dict[str, Any]] = []
    for provider in providers:
        extra_config = provider.extra_config or {}
        if provider.name in live:
            results.extend(
                _enrich_provider_status_snapshot(snapshot, extra_config)
                for snapshot in live[provider.name]
            )
        else:
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
    return Response({"results": ProviderHealthSnapshotSerializer(results, many=True).data})
