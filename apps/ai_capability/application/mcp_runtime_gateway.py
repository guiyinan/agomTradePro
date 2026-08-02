"""SDK-backed MCP runtime access for capability synchronization and execution."""

from __future__ import annotations

import importlib
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from threading import RLock
from typing import Any, Protocol, cast

from shared.infrastructure.async_runtime import run_awaitable_sync
from shared.infrastructure.mcp_runtime import call_sdk_mcp_tool as _call_sdk_mcp_tool
from shared.infrastructure.mcp_runtime import ensure_sdk_on_path, load_mcp_env_from_repo_config

_MCP_SERVER_RELOAD_LOCK = RLock()
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_MAX_TOOL_COUNT = 2_000
_MAX_MANIFEST_COUNT = 2_000
_MAX_DISPOSITION_COUNT = 2_000
_MAX_CALL_PARAMS_BYTES = 262_144
_MAX_CALL_RESULT_BYTES = 1_048_576
_MAX_JSON_DEPTH = 24
_MAX_JSON_ITEMS = 20_000


class McpRuntimeValidationError(ValueError):
    """Raised when dynamic MCP runtime data violates the local gateway contract."""


class McpToolView(Protocol):
    """Minimal MCP tool metadata consumed by capability synchronization."""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def inputSchema(self) -> dict[str, Any]: ...


class McpManifestView(Protocol):
    """Minimal governed manifest metadata consumed by catalog projection."""

    @property
    def capability_key(self) -> str: ...

    @property
    def summary(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def owner_app(self) -> str: ...

    @property
    def risk_level(self) -> str: ...

    @property
    def tags(self) -> tuple[str, ...]: ...

    @property
    def audit_tags(self) -> tuple[str, ...]: ...

    @property
    def legacy_tool_names(self) -> tuple[str, ...]: ...

    @property
    def input_schema(self) -> dict[str, Any]: ...

    @property
    def idempotency(self) -> str: ...

    @property
    def idempotency_argument_name(self) -> str: ...

    @property
    def required_roles(self) -> tuple[str, ...]: ...

    @property
    def requires_confirmation(self) -> bool: ...


class McpLegacyDispositionView(Protocol):
    """Minimal legacy-tool governance record consumed by catalog projection."""

    @property
    def tool_name(self) -> str: ...

    @property
    def owner_app(self) -> str: ...

    @property
    def disposition(self) -> str: ...

    @property
    def rationale(self) -> str: ...

    @property
    def recommended_capability_keys(self) -> tuple[str, ...]: ...


class _RegistryLoaderView(Protocol):
    def build_registry(self) -> Mapping[str, McpManifestView]:
        """Return capability-key indexed manifests."""


def list_sdk_mcp_tools(*, include_legacy: bool = False) -> list[McpToolView]:
    """List an isolated core or legacy-inclusive MCP tool surface."""

    if not isinstance(include_legacy, bool):
        raise McpRuntimeValidationError("mcp_include_legacy_must_be_boolean")
    ensure_sdk_on_path()
    load_mcp_env_from_repo_config()

    with _MCP_SERVER_RELOAD_LOCK:
        server_module = importlib.import_module("agomtradepro_mcp.server")
        previous_legacy_flag = os.environ.get("AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS")
        os.environ["AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS"] = "true" if include_legacy else "false"
        try:
            scoped_module = importlib.reload(server_module)
            raw_tools = run_awaitable_sync(scoped_module.server.list_tools)
            return _validated_tools(raw_tools)
        finally:
            if previous_legacy_flag is None:
                os.environ.pop("AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS", None)
            else:
                os.environ["AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS"] = previous_legacy_flag
            importlib.reload(server_module)


def list_sdk_mcp_core_tool_names() -> set[str]:
    """Return the validated fixed core MCP tool names."""

    ensure_sdk_on_path()
    module = importlib.import_module("agomtradepro_mcp.tools.core_tools")
    raw_names: object = module.CORE_TOOL_NAMES
    if not isinstance(raw_names, Sequence) or isinstance(raw_names, (str, bytes)):
        raise McpRuntimeValidationError("mcp_core_tool_names_invalid")
    names = {_tool_name(name) for name in raw_names}
    if not names or len(names) != len(raw_names):
        raise McpRuntimeValidationError("mcp_core_tool_names_invalid")
    return names


def list_sdk_mcp_capability_manifests() -> list[McpManifestView]:
    """Return validated governed manifests from the canonical registry loader."""

    ensure_sdk_on_path()
    module = importlib.import_module("agomtradepro_mcp.registry.loader")
    loader_type: object = module.CapabilityRegistryLoader
    if not isinstance(loader_type, type):
        raise McpRuntimeValidationError("mcp_manifest_loader_invalid")
    loader = cast(_RegistryLoaderView, loader_type())
    registry = loader.build_registry()
    if not isinstance(registry, Mapping) or len(registry) > _MAX_MANIFEST_COUNT:
        raise McpRuntimeValidationError("mcp_manifest_registry_invalid")
    manifests: list[McpManifestView] = []
    for key, manifest in registry.items():
        if not isinstance(key, str) or not _is_manifest(manifest):
            raise McpRuntimeValidationError("mcp_manifest_registry_invalid")
        if key != manifest.capability_key:
            raise McpRuntimeValidationError("mcp_manifest_registry_key_mismatch")
        manifests.append(manifest)
    return manifests


def list_sdk_mcp_legacy_dispositions() -> list[McpLegacyDispositionView]:
    """Return validated governance decisions for unreplaced raw MCP tools."""

    ensure_sdk_on_path()
    module = importlib.import_module("agomtradepro_mcp.legacy_dispositions")
    loader: object = module.list_legacy_tool_dispositions
    if not callable(loader):
        raise McpRuntimeValidationError("mcp_legacy_disposition_loader_invalid")
    raw_dispositions = loader()
    if (
        not isinstance(raw_dispositions, Sequence)
        or isinstance(raw_dispositions, (str, bytes))
        or len(raw_dispositions) > _MAX_DISPOSITION_COUNT
    ):
        raise McpRuntimeValidationError("mcp_legacy_dispositions_invalid")
    dispositions: list[McpLegacyDispositionView] = []
    for disposition in raw_dispositions:
        if not _is_legacy_disposition(disposition):
            raise McpRuntimeValidationError("mcp_legacy_dispositions_invalid")
        dispositions.append(disposition)
    return dispositions


def get_sdk_mcp_legacy_disposition(
    tool_name: str,
) -> McpLegacyDispositionView | None:
    """Return the validated governance decision for one raw tool."""

    normalized_name = _tool_name(tool_name)
    ensure_sdk_on_path()
    module = importlib.import_module("agomtradepro_mcp.legacy_dispositions")
    loader: object = module.get_legacy_tool_disposition
    if not callable(loader):
        raise McpRuntimeValidationError("mcp_legacy_disposition_loader_invalid")
    disposition: object = loader(normalized_name)
    if disposition is None:
        return None
    if not _is_legacy_disposition(disposition):
        raise McpRuntimeValidationError("mcp_legacy_disposition_invalid")
    validated = cast(McpLegacyDispositionView, disposition)
    if validated.tool_name != normalized_name:
        raise McpRuntimeValidationError("mcp_legacy_disposition_invalid")
    return validated


def call_sdk_mcp_tool(
    tool_name: str,
    params: dict[str, Any],
    *,
    user_id: int | None = None,
    username: str = "",
) -> object:
    """Execute one bounded MCP tool call through the SDK server contract."""

    normalized_name = _tool_name(tool_name)
    normalized_params = _bounded_json_object(
        params,
        label="mcp_call_params_invalid",
        maximum=_MAX_CALL_PARAMS_BYTES,
    )
    result = _call_sdk_mcp_tool(
        normalized_name,
        normalized_params,
        user_id=user_id,
        username=username,
    )
    return _bounded_json_value(
        result,
        label="mcp_call_result_invalid",
        maximum=_MAX_CALL_RESULT_BYTES,
    )


def _validated_tools(value: object) -> list[McpToolView]:
    """Return validated tool metadata with bounded cardinality."""

    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) > _MAX_TOOL_COUNT
    ):
        raise McpRuntimeValidationError("mcp_tool_list_invalid")
    tools: list[McpToolView] = []
    names: set[str] = set()
    for tool in value:
        if not _is_tool(tool):
            raise McpRuntimeValidationError("mcp_tool_metadata_invalid")
        name = _tool_name(tool.name)
        _bounded_json_object(
            tool.inputSchema,
            label="mcp_tool_input_schema_invalid",
            maximum=_MAX_CALL_PARAMS_BYTES,
        )
        if name in names:
            raise McpRuntimeValidationError("mcp_tool_name_duplicate")
        names.add(name)
        tools.append(tool)
    return tools


def _is_tool(value: object) -> bool:
    """Return whether dynamic MCP tool metadata satisfies the local contract."""

    return (
        hasattr(value, "name")
        and isinstance(value.name, str)
        and hasattr(value, "description")
        and isinstance(value.description, str)
        and len(value.description) <= 10_000
        and "\x00" not in value.description
        and hasattr(value, "inputSchema")
        and isinstance(value.inputSchema, dict)
    )


def _is_manifest(value: object) -> bool:
    """Return whether dynamic manifest metadata satisfies the projection contract."""

    candidate = cast(McpManifestView, value)
    string_fields = (
        "capability_key",
        "summary",
        "description",
        "owner_app",
        "risk_level",
        "idempotency",
        "idempotency_argument_name",
    )
    tuple_fields = ("tags", "audit_tags", "legacy_tool_names", "required_roles")
    return (
        all(
            hasattr(value, field)
            and isinstance(getattr(value, field), str)
            and bool(getattr(value, field).strip())
            for field in string_fields
        )
        and all(
            hasattr(value, field)
            and isinstance(getattr(value, field), tuple)
            and all(isinstance(item, str) and bool(item.strip()) for item in getattr(value, field))
            for field in tuple_fields
        )
        and hasattr(value, "input_schema")
        and isinstance(value.input_schema, dict)
        and hasattr(value, "requires_confirmation")
        and isinstance(value.requires_confirmation, bool)
        and _TOOL_NAME_PATTERN.fullmatch(candidate.capability_key) is not None
    )


def _is_legacy_disposition(value: object) -> bool:
    """Return whether dynamic legacy governance data satisfies the local contract."""

    return (
        hasattr(value, "tool_name")
        and isinstance(value.tool_name, str)
        and _TOOL_NAME_PATTERN.fullmatch(value.tool_name) is not None
        and hasattr(value, "owner_app")
        and isinstance(value.owner_app, str)
        and bool(value.owner_app.strip())
        and hasattr(value, "disposition")
        and isinstance(value.disposition, str)
        and bool(value.disposition.strip())
        and hasattr(value, "rationale")
        and isinstance(value.rationale, str)
        and bool(value.rationale.strip())
        and hasattr(value, "recommended_capability_keys")
        and isinstance(value.recommended_capability_keys, tuple)
        and all(
            isinstance(item, str) and bool(item.strip())
            for item in value.recommended_capability_keys
        )
    )


def _tool_name(value: object) -> str:
    """Return one canonical bounded MCP tool/capability identifier."""

    if not isinstance(value, str):
        raise McpRuntimeValidationError("mcp_tool_name_invalid")
    normalized = value.strip()
    if _TOOL_NAME_PATTERN.fullmatch(normalized) is None:
        raise McpRuntimeValidationError("mcp_tool_name_invalid")
    return normalized


def _bounded_json_object(
    value: object,
    *,
    label: str,
    maximum: int,
) -> dict[str, object]:
    """Return one bounded string-keyed finite JSON object."""

    normalized = _bounded_json_value(value, label=label, maximum=maximum)
    if not isinstance(normalized, dict):
        raise McpRuntimeValidationError(label)
    return normalized


def _bounded_json_value(value: object, *, label: str, maximum: int) -> object:
    """Return a detached finite JSON value with depth/cardinality/size limits."""

    counter = [0]
    _validate_json_value(value, label=label, depth=0, counter=counter)
    detached = deepcopy(value)
    try:
        encoded = json.dumps(detached, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise McpRuntimeValidationError(label) from exc
    if len(encoded.encode("utf-8")) > maximum:
        raise McpRuntimeValidationError(label)
    return detached


def _validate_json_value(
    value: object,
    *,
    label: str,
    depth: int,
    counter: list[int],
) -> None:
    """Validate one JSON tree without permissive coercion."""

    if depth > _MAX_JSON_DEPTH:
        raise McpRuntimeValidationError(label)
    counter[0] += 1
    if counter[0] > _MAX_JSON_ITEMS:
        raise McpRuntimeValidationError(label)
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise McpRuntimeValidationError(label)
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise McpRuntimeValidationError(label)
        for item in value.values():
            _validate_json_value(
                item,
                label=label,
                depth=depth + 1,
                counter=counter,
            )
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _validate_json_value(
                item,
                label=label,
                depth=depth + 1,
                counter=counter,
            )
        return
    raise McpRuntimeValidationError(label)
