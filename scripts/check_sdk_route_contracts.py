#!/usr/bin/env python
"""Validate statically declared SDK HTTP calls against Django URL contracts."""

from __future__ import annotations

import ast
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.urls import Resolver404, resolve

REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_MODULE_DIR = REPO_ROOT / "sdk" / "agomtradepro" / "modules"
HTTP_CALLS = {
    "_get": "GET",
    "_post": "POST",
    "_put": "PUT",
    "_patch": "PATCH",
    "_delete": "DELETE",
}
DIRECT_HTTP_CALLS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
}


@dataclass(frozen=True)
class SDKRouteCall:
    """One statically identifiable SDK HTTP call."""

    module_file: str
    line: int
    method: str
    path: str


@dataclass(frozen=True)
class _DynamicRouteHelper:
    """One SDK helper whose transport path comes from a method argument."""

    helper_name: str
    parameter_name: str
    parameter_index: int
    method: str
    prefix: str | None
    is_direct_client_call: bool
    line: int


def setup_django() -> None:
    """Initialize Django URL configuration for contract resolution."""

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import django

    django.setup()


def _sample_formatted_value(node: ast.FormattedValue) -> str:
    """Return a route-compatible representative for one f-string expression."""

    expression = ast.unparse(node.value).lower()
    if "domain" in expression:
        return "research"
    if "client_order_id" in expression:
        return "00000000-0000-0000-0000-000000000001"
    if any(token in expression for token in ("id", "limit", "version", "pk")):
        return "1"
    if any(token in expression for token in ("code", "asset", "stock", "symbol")):
        return "000001.SZ"
    if "date" in expression:
        return "2026-01-01"
    return "sample"


def _static_path(node: ast.AST) -> str | None:
    """Evaluate literals and f-strings without executing SDK code."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if not isinstance(node, ast.JoinedStr):
        return None
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue):
            parts.append(_sample_formatted_value(value))
        else:
            return None
    return "".join(parts)


def _module_base_path(tree: ast.Module) -> str | None:
    """Read the BaseModule prefix from its super constructor call."""

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "__init__"
            and isinstance(func.value, ast.Call)
            and isinstance(func.value.func, ast.Name)
            and func.value.func.id == "super"
        ):
            continue
        prefix = _static_path(node.args[1])
        if prefix is not None:
            return prefix
    return None


def _is_direct_client_call(node: ast.Call) -> bool:
    """Return whether a call targets ``self._client.<http_method>``."""

    return bool(
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute)
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "self"
        and node.func.value.attr == "_client"
    )


def _transport_method(node: ast.Call) -> tuple[str | None, bool]:
    """Return the HTTP method and direct-client flag for one transport call."""

    if not isinstance(node.func, ast.Attribute):
        return None, False
    is_direct_client_call = _is_direct_client_call(node)
    if is_direct_client_call:
        return DIRECT_HTTP_CALLS.get(node.func.attr), True
    is_base_module_call = isinstance(node.func.value, ast.Name) and node.func.value.id == "self"
    if not is_base_module_call:
        return None, False
    return HTTP_CALLS.get(node.func.attr), False


def _route_from_suffix(
    *,
    prefix: str | None,
    suffix: str,
    is_direct_client_call: bool,
) -> str | None:
    """Build one canonical API route from a static transport suffix."""

    if is_direct_client_call:
        return suffix if suffix.startswith("/api/") else None
    if prefix is None:
        return None
    route = f"{prefix.rstrip('/')}/{suffix.lstrip('/')}"
    if suffix == "":
        return f"{prefix.rstrip('/')}/"
    return route


def _function_parameter_index(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    parameter_name: str,
) -> int | None:
    """Return a helper argument's positional index after ``self``."""

    parameters = [*function.args.posonlyargs, *function.args.args]
    if parameters and parameters[0].arg in {"self", "cls"}:
        parameters = parameters[1:]
    for index, parameter in enumerate(parameters):
        if parameter.arg == parameter_name:
            return index
    return None


def _helper_call_argument(
    node: ast.Call,
    helper: _DynamicRouteHelper,
) -> ast.AST | None:
    """Return the path argument supplied to one dynamic SDK helper call."""

    if len(node.args) > helper.parameter_index:
        return node.args[helper.parameter_index]
    for keyword in node.keywords:
        if keyword.arg == helper.parameter_name:
            return keyword.value
    return None


def collect_sdk_route_calls() -> list[SDKRouteCall]:
    """Collect all statically provable SDK routes, including helper call sites."""

    calls: list[SDKRouteCall] = []
    unvalidated: list[str] = []
    for path in sorted(SDK_MODULE_DIR.glob("*.py")):
        if path.name in {"__init__.py", "base.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        prefix = _module_base_path(tree)
        module_file = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        helpers: list[_DynamicRouteHelper] = []
        functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        for function in functions:
            for node in ast.walk(function):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                method, is_direct_client_call = _transport_method(node)
                if method is None:
                    continue
                suffix = _static_path(node.args[0])
                if suffix is not None:
                    route = _route_from_suffix(
                        prefix=prefix,
                        suffix=suffix,
                        is_direct_client_call=is_direct_client_call,
                    )
                    if route is None:
                        unvalidated.append(f"{module_file}:{node.lineno} {method} {suffix!r}")
                        continue
                    calls.append(
                        SDKRouteCall(
                            module_file=module_file,
                            line=node.lineno,
                            method=method,
                            path=route,
                        )
                    )
                    continue

                endpoint_node = node.args[0]
                if isinstance(endpoint_node, ast.Name):
                    parameter_index = _function_parameter_index(
                        function,
                        endpoint_node.id,
                    )
                    if parameter_index is not None:
                        helpers.append(
                            _DynamicRouteHelper(
                                helper_name=function.name,
                                parameter_name=endpoint_node.id,
                                parameter_index=parameter_index,
                                method=method,
                                prefix=prefix,
                                is_direct_client_call=is_direct_client_call,
                                line=node.lineno,
                            )
                        )
                        continue
                unvalidated.append(
                    f"{module_file}:{node.lineno} {method} {ast.unparse(endpoint_node)}"
                )

        for helper in helpers:
            helper_calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
                and node.func.attr == helper.helper_name
            ]
            if not helper_calls:
                unvalidated.append(
                    f"{module_file}:{helper.line} {helper.method} "
                    f"dynamic helper {helper.helper_name} has no static call sites"
                )
                continue
            for helper_call in helper_calls:
                argument = _helper_call_argument(helper_call, helper)
                suffix = _static_path(argument) if argument is not None else None
                route = (
                    _route_from_suffix(
                        prefix=helper.prefix,
                        suffix=suffix,
                        is_direct_client_call=helper.is_direct_client_call,
                    )
                    if suffix is not None
                    else None
                )
                if route is None:
                    expression = ast.unparse(argument) if argument is not None else "<missing>"
                    unvalidated.append(
                        f"{module_file}:{helper_call.lineno} {helper.method} "
                        f"{helper.helper_name}({expression})"
                    )
                    continue
                calls.append(
                    SDKRouteCall(
                        module_file=module_file,
                        line=helper_call.lineno,
                        method=helper.method,
                        path=route,
                    )
                )

    if unvalidated:
        raise ValueError(
            "SDK route collection found unvalidated transport paths:\n- " + "\n- ".join(unvalidated)
        )
    return calls


def _allowed_methods(callback: Any) -> set[str]:
    """Infer methods exposed by DRF ViewSets and class-based views."""

    actions = getattr(callback, "actions", None)
    if actions:
        return {method.upper() for method in actions}
    view_class = getattr(callback, "view_class", None) or getattr(callback, "cls", None)
    if view_class is None:
        return set()
    return {
        method.upper()
        for method in ("get", "post", "put", "patch", "delete")
        if method in getattr(view_class, "__dict__", {})
    }


def validate_sdk_route_contracts(calls: list[SDKRouteCall]) -> dict[str, int]:
    """Raise when an SDK route is absent or uses an unsupported HTTP method."""

    unresolved: list[SDKRouteCall] = []
    method_mismatches: list[tuple[SDKRouteCall, set[str]]] = []
    for call in calls:
        try:
            match = resolve(call.path)
        except Resolver404:
            unresolved.append(call)
            continue
        allowed = _allowed_methods(match.func)
        if allowed and call.method not in allowed:
            method_mismatches.append((call, allowed))

    if unresolved or method_mismatches:
        messages = ["SDK route contract validation failed:"]
        messages.extend(
            f"- unresolved: {item.method} {item.path} ({item.module_file}:{item.line})"
            for item in unresolved
        )
        messages.extend(
            f"- method mismatch: {item.method} {item.path}; allowed={sorted(allowed)} "
            f"({item.module_file}:{item.line})"
            for item, allowed in method_mismatches
        )
        raise ValueError("\n".join(messages))

    return {
        "checked_calls": len(calls),
        "unresolved_calls": 0,
        "method_mismatches": 0,
    }


def main() -> int:
    """CLI entrypoint."""

    setup_django()
    summary = validate_sdk_route_contracts(collect_sdk_route_calls())
    print("SDK route contracts OK")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
