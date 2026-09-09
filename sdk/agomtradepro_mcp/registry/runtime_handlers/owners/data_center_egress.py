"""SDK-backed native egress handlers with safe previews and bounded JSON inputs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from urllib.parse import urlsplit

from requests.exceptions import RequestException

from agomtradepro.exceptions import AgomTradeProAPIError
from agomtradepro_mcp.registry.modules.owners.data_center_egress_capabilities import (
    EGRESS_MANIFESTS_BY_REF,
)

_SAFE_RESULT_FIELDS = frozenset(
    {
        "id",
        "name",
        "region",
        "protocol",
        "host",
        "port",
        "enabled",
        "concurrency_limit",
        "username_configured",
        "password_configured",
        "created_at",
        "updated_at",
        "provider_id",
        "provider_name",
        "dataset_key",
        "domain_pattern",
        "deployment_region",
        "strategy",
        "strategy_label",
        "fixed_egress_id",
        "egress_name",
        "priority",
        "rule_id",
        "egress_id",
        "allowed_egress_ids",
        "reason",
        "matched_domain",
        "outcome",
        "error_code",
        "message",
        "request_id",
        "route",
        "attempts",
        "checked_at",
        "attempt",
        "status_code",
        "latency_ms",
        "observed_ip",
        "success",
    }
)


def _safe_result(value: Any) -> Any:
    """Project the egress response contract, excluding credentials and debug fields."""
    if isinstance(value, dict):
        return {
            key: _safe_result(item) for key, item in value.items() if key in _SAFE_RESULT_FIELDS
        }
    if isinstance(value, list):
        return [_safe_result(item) for item in value]
    return value


def _validate_arguments(ref: str, arguments: dict[str, Any]) -> dict[str, Any]:
    manifest = EGRESS_MANIFESTS_BY_REF[ref]
    properties = manifest.input_schema["properties"]
    if any(key not in properties for key in arguments):
        raise ValueError("Unsupported egress argument.")
    if any(key not in arguments for key in manifest.input_schema["required"]):
        raise ValueError("Missing required egress argument.")
    for key, value in arguments.items():
        field = properties[key]
        kinds = field["type"]
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if value is None and "null" in kinds:
            continue
        valid = (
            ("integer" in kinds and type(value) is int)
            or ("boolean" in kinds and type(value) is bool)
            or ("string" in kinds and isinstance(value, str))
        )
        if not valid:
            raise ValueError(f"Invalid type for {key}.")
        if isinstance(value, str):
            if len(value) < field.get("minLength", 0) or len(value) > field.get("maxLength", 4096):
                raise ValueError(f"Invalid length for {key}.")
            if not key.startswith("credential_") and not value.strip():
                raise ValueError(f"Blank value for {key}.")
        if type(value) is int:
            if value < field.get("minimum", value) or value > field.get("maximum", value):
                raise ValueError(f"Out of range: {key}.")
        if "enum" in field and value not in field["enum"]:
            raise ValueError(f"Invalid choice for {key}.")
    if "url" in arguments:
        try:
            parts = urlsplit(arguments["url"])
            valid_url = (
                parts.scheme in {"http", "https"}
                and bool(parts.hostname)
                and parts.username is None
                and parts.password is None
                and not parts.fragment
                and (parts.port is None or parts.port > 0)
                and "*" not in parts.netloc
            )
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ValueError(
                "Target must be a concrete HTTP(S) URL without credentials or fragments."
            )
        if any("*" in arguments[key] for key in ("dataset_key", "deployment_region")):
            raise ValueError(
                "Diagnostic context must use a concrete dataset and deployment region."
            )
    payload = {key: value for key, value in arguments.items() if key != "idempotency_key"}
    if ".update." in manifest.capability_key and len(payload) == 1:
        raise ValueError("At least one configuration field must be supplied.")
    return payload


def _call_sdk(method: str, *arguments: object) -> Any:
    """Call only a handler-selected SDK method and keep transport details private."""
    from agomtradepro import AgomTradeProClient

    try:
        client = AgomTradeProClient()
        call = cast(Callable[..., Any], getattr(client.data_center, method))
        return _safe_result(call(*arguments))
    except (AgomTradeProAPIError, RequestException, ValueError) as exc:
        status_code = exc.status_code if isinstance(exc, AgomTradeProAPIError) else None
        raise AgomTradeProAPIError(
            "Egress request failed; check permissions, configuration and service availability.",
            status_code=status_code,
        ) from None


def _execute(
    ref: str,
    method: str,
    arguments: dict[str, Any],
    *,
    preview_only: bool = False,
    id_key: str | None = None,
    current_method: str | None = None,
    network: bool = False,
) -> dict[str, Any]:
    payload = _validate_arguments(ref, arguments)
    resource_id = payload.pop(id_key) if id_key is not None else None
    if preview_only:
        safe_changes = {
            key: value for key, value in payload.items() if not key.startswith("credential_")
        }
        # Targets can contain query-string API keys. A preview needs only its origin/path.
        if "url" in safe_changes:
            target = urlsplit(safe_changes["url"])
            safe_changes["url"] = target._replace(query="").geturl()
        credentials = {
            key.removeprefix("credential_"): "replace" if payload[key] else "preserve"
            for key in ("credential_username", "credential_password")
            if key in payload
        }
        preview: dict[str, Any] = {
            "preview_only": True,
            "requested_changes": safe_changes,
            "credential_changes": credentials,
            "side_effects": {"external_request": network, "configuration_write": not network},
            "message": "No changes or network probes performed; server validates the configuration on confirmation.",
        }
        if id_key is not None:
            preview[id_key] = resource_id
        if current_method is not None:
            preview["current"] = _call_sdk(current_method, resource_id)
        if method == "diagnose_egress_route":
            preview["route"] = _call_sdk("preview_egress_route", payload)
        return preview
    for source, target_key in (
        ("credential_username", "username"),
        ("credential_password", "password"),
    ):
        if source in payload:
            payload[target_key] = payload.pop(source)
    positional: list[object] = []
    if id_key is not None:
        positional.append(resource_id)
    if payload:
        positional.append(payload)
    result = _call_sdk(method, *positional)
    if isinstance(result, list):
        return {"results": result, "total_count": len(result)}
    if not isinstance(result, dict):
        raise AgomTradeProAPIError("Invalid egress response.")
    return cast(dict[str, Any], result)


def _internal_handler_data_center_read_egress_endpoints(**arguments: Any) -> dict[str, Any]:
    """Execute the governed list_egress_endpoints SDK contract."""
    return _execute("data_center_read_egress_endpoints", "list_egress_endpoints", arguments)


def _internal_handler_data_center_read_egress_endpoint(**arguments: Any) -> dict[str, Any]:
    """Execute the governed get_egress_endpoint SDK contract."""
    return _execute(
        "data_center_read_egress_endpoint", "get_egress_endpoint", arguments, id_key="endpoint_id"
    )


def _internal_handler_data_center_create_egress_endpoint(
    preview_only: bool = False, **arguments: Any
) -> dict[str, Any]:
    """Execute the governed create_egress_endpoint SDK contract."""
    return _execute(
        "data_center_create_egress_endpoint",
        "create_egress_endpoint",
        arguments,
        preview_only=preview_only,
    )


def _internal_handler_data_center_update_egress_endpoint(
    preview_only: bool = False, **arguments: Any
) -> dict[str, Any]:
    """Execute the governed update_egress_endpoint SDK contract."""
    return _execute(
        "data_center_update_egress_endpoint",
        "update_egress_endpoint",
        arguments,
        preview_only=preview_only,
        id_key="endpoint_id",
        current_method="get_egress_endpoint",
    )


def _internal_handler_data_center_run_egress_endpoint_test(
    preview_only: bool = False, **arguments: Any
) -> dict[str, Any]:
    """Execute the governed test_egress_endpoint SDK contract."""
    return _execute(
        "data_center_run_egress_endpoint_test",
        "test_egress_endpoint",
        arguments,
        preview_only=preview_only,
        id_key="endpoint_id",
        current_method="get_egress_endpoint",
        network=True,
    )


def _internal_handler_data_center_read_egress_rules(**arguments: Any) -> dict[str, Any]:
    """Execute the governed list_egress_rules SDK contract."""
    return _execute("data_center_read_egress_rules", "list_egress_rules", arguments)


def _internal_handler_data_center_read_egress_rule(**arguments: Any) -> dict[str, Any]:
    """Execute the governed get_egress_rule SDK contract."""
    return _execute("data_center_read_egress_rule", "get_egress_rule", arguments, id_key="rule_id")


def _internal_handler_data_center_create_egress_rule(
    preview_only: bool = False, **arguments: Any
) -> dict[str, Any]:
    """Execute the governed create_egress_rule SDK contract."""
    return _execute(
        "data_center_create_egress_rule", "create_egress_rule", arguments, preview_only=preview_only
    )


def _internal_handler_data_center_update_egress_rule(
    preview_only: bool = False, **arguments: Any
) -> dict[str, Any]:
    """Execute the governed update_egress_rule SDK contract."""
    return _execute(
        "data_center_update_egress_rule",
        "update_egress_rule",
        arguments,
        preview_only=preview_only,
        id_key="rule_id",
        current_method="get_egress_rule",
    )


def _internal_handler_data_center_read_egress_route_preview(**arguments: Any) -> dict[str, Any]:
    """Execute the governed preview_egress_route SDK contract."""
    return _execute("data_center_read_egress_route_preview", "preview_egress_route", arguments)


def _internal_handler_data_center_run_egress_diagnostics(
    preview_only: bool = False, **arguments: Any
) -> dict[str, Any]:
    """Execute the governed diagnose_egress_route SDK contract."""
    return _execute(
        "data_center_run_egress_diagnostics",
        "diagnose_egress_route",
        arguments,
        preview_only=preview_only,
        network=True,
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {}
GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "data_center_read_egress_endpoints": _internal_handler_data_center_read_egress_endpoints,
    "data_center_read_egress_endpoint": _internal_handler_data_center_read_egress_endpoint,
    "data_center_create_egress_endpoint": _internal_handler_data_center_create_egress_endpoint,
    "data_center_update_egress_endpoint": _internal_handler_data_center_update_egress_endpoint,
    "data_center_run_egress_endpoint_test": _internal_handler_data_center_run_egress_endpoint_test,
    "data_center_read_egress_rules": _internal_handler_data_center_read_egress_rules,
    "data_center_read_egress_rule": _internal_handler_data_center_read_egress_rule,
    "data_center_create_egress_rule": _internal_handler_data_center_create_egress_rule,
    "data_center_update_egress_rule": _internal_handler_data_center_update_egress_rule,
    "data_center_read_egress_route_preview": _internal_handler_data_center_read_egress_route_preview,
    "data_center_run_egress_diagnostics": _internal_handler_data_center_run_egress_diagnostics,
}
