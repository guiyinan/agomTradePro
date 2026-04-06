"""
API Capability Collector.

Auto-collects internal Django/DRF APIs and converts them to capabilities.
"""

import logging
import re
from typing import Any, Optional

from django.urls import get_resolver
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSetMixin

from apps.ai_capability.domain.entities import (
    CapabilityDefinition,
    ExecutionKind,
    ReviewStatus,
    RiskLevel,
    RouteGroup,
    SourceType,
    Visibility,
)

logger = logging.getLogger(__name__)


def _clean_pattern_str(raw: str) -> str:
    """Strip regex anchors (^, $) and collapse duplicate slashes from URL pattern strings."""
    cleaned = raw.lstrip("^").rstrip("$")
    cleaned = re.sub(r"/+", "/", cleaned)
    return cleaned


def _normalize_api_path(raw: str) -> str | None:
    """Convert Django regex/path patterns into a readable API path."""
    if "(?P<format>" in raw:
        return None

    cleaned = _clean_pattern_str(raw)
    cleaned = cleaned.replace("\\Z", "")
    cleaned = cleaned.replace("\\", "")
    cleaned = re.sub(
        r"\(\?P<(?P<name>[^>]+)>[^)]+\)",
        lambda match: f"<{match.group('name').lower()}>",
        cleaned,
    )
    cleaned = cleaned.replace("?", "")
    cleaned = re.sub(r"/+", "/", cleaned)
    return cleaned


class ApiCapabilityCollector:
    """Collects internal API endpoints as capabilities."""

    UNSAFE_PATTERNS = [
        r"delete",
        r"reset",
        r"toggle",
        r"approve",
        r"execute",
        r"admin",
        r"token",
        r"secret",
        r"credential",
        r"bootstrap",
        r"migrate",
        r"config.?center",
        r"system.?settings",
        r"runtime.?settings",
    ]

    READ_METHODS = {"GET", "HEAD", "OPTIONS"}
    WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def collect(self) -> list[CapabilityDefinition]:
        """Collect all API capabilities from Django URL resolver."""
        capabilities = []
        resolver = get_resolver()

        for pattern in resolver.url_patterns:
            self._collect_from_pattern(pattern, capabilities)

        return capabilities

    def _collect_from_pattern(
        self,
        pattern: Any,
        capabilities: list[CapabilityDefinition],
        prefix: str = "",
    ) -> None:
        """Recursively collect capabilities from URL patterns."""
        from django.urls.resolvers import URLPattern, URLResolver

        if isinstance(pattern, URLResolver):
            normalized = _normalize_api_path(str(pattern.pattern))
            if normalized is None:
                return

            new_prefix = prefix + normalized
            for sub_pattern in pattern.url_patterns:
                self._collect_from_pattern(sub_pattern, capabilities, new_prefix)

        elif isinstance(pattern, URLPattern):
            normalized = _normalize_api_path(str(pattern.pattern))
            if normalized is None:
                return

            path = prefix + normalized
            callback = pattern.callback

            if not path.startswith("api/"):
                return

            if path.startswith("api/schema") or path.startswith("api/docs"):
                return

            caps = self._create_capabilities_from_view(path, callback)
            capabilities.extend(caps)

    def _create_capabilities_from_view(
        self,
        path: str,
        callback: Any,
    ) -> list[CapabilityDefinition]:
        """Create capabilities from a view callback."""
        capabilities = []

        view_class = None
        if hasattr(callback, "view_class"):
            view_class = callback.view_class
        elif hasattr(callback, "cls"):
            view_class = callback.cls

        if view_class is None:
            cap = self._create_capability_for_path(path, "GET")
            if cap:
                capabilities.append(cap)
            return capabilities

        methods = self._get_view_methods(view_class)

        for method in methods:
            cap = self._create_capability_for_view(path, method, view_class)
            if cap:
                capabilities.append(cap)

        return capabilities

    def _get_view_methods(self, view_class: type) -> list[str]:
        """Get allowed HTTP methods for a view class."""
        methods = []

        if isinstance(view_class, type) and issubclass(view_class, ViewSetMixin):
            actions = ["list", "create", "retrieve", "update", "partial_update", "destroy"]
            method_map = {
                "list": "GET",
                "create": "POST",
                "retrieve": "GET",
                "update": "PUT",
                "partial_update": "PATCH",
                "destroy": "DELETE",
            }
            for action in actions:
                if hasattr(view_class, action):
                    methods.append(method_map[action])
        elif isinstance(view_class, type) and issubclass(view_class, APIView):
            for method in self.READ_METHODS | self.WRITE_METHODS:
                if hasattr(view_class, method.lower()):
                    methods.append(method)

        return list(set(methods))

    def _create_capability_for_path(
        self,
        path: str,
        method: str,
    ) -> CapabilityDefinition | None:
        """Create a basic capability for a path without view class."""
        route_group = self._determine_route_group(path, method, None)
        risk_level = self._determine_risk_level(path, method, None)

        if route_group == RouteGroup.UNSAFE_API:
            return None

        capability_key = self._create_capability_key(path, method)

        return CapabilityDefinition(
            capability_key=capability_key,
            source_type=SourceType.API,
            source_ref=f"{method} {path}",
            name=self._create_name(path, method),
            summary=f"API endpoint: {method} {path}",
            description=f"Internal API endpoint at {path}",
            route_group=route_group,
            category=self._determine_category(path),
            tags=["api", "internal"],
            when_to_use=[],
            when_not_to_use=[],
            examples=[],
            input_schema={},
            execution_kind=ExecutionKind.SYNC,
            execution_target={
                "type": "api",
                "method": method,
                "path": path,
            },
            risk_level=risk_level,
            requires_mcp=False,
            requires_confirmation=route_group == RouteGroup.WRITE_API,
            enabled_for_routing=route_group != RouteGroup.UNSAFE_API,
            enabled_for_terminal=True,
            enabled_for_chat=False,
            enabled_for_agent=True,
            visibility=Visibility.INTERNAL,
            auto_collected=True,
            review_status=ReviewStatus.AUTO,
        )

    def _create_capability_for_view(
        self,
        path: str,
        method: str,
        view_class: type,
    ) -> CapabilityDefinition | None:
        """Create a capability for a view with class information."""
        route_group = self._determine_route_group(path, method, view_class)
        risk_level = self._determine_risk_level(path, method, view_class)

        if route_group == RouteGroup.UNSAFE_API:
            enabled_for_routing = False
        else:
            enabled_for_routing = True

        capability_key = self._create_capability_key(path, method)

        docstring = self._get_docstring(view_class, method)
        permission_classes = self._get_permission_classes(view_class)

        return CapabilityDefinition(
            capability_key=capability_key,
            source_type=SourceType.API,
            source_ref=f"{method} {path}",
            name=self._create_name(path, method),
            summary=docstring[:200] if docstring else f"API endpoint: {method} {path}",
            description=docstring or f"Internal API endpoint at {path}",
            route_group=route_group,
            category=self._determine_category(path),
            tags=self._extract_tags(path, view_class),
            when_to_use=[],
            when_not_to_use=[],
            examples=[],
            input_schema=self._extract_input_schema(view_class, method),
            execution_kind=ExecutionKind.SYNC,
            execution_target={
                "type": "api",
                "method": method,
                "path": path,
                "view_class": f"{view_class.__module__}.{view_class.__name__}",
            },
            risk_level=risk_level,
            requires_mcp=False,
            requires_confirmation=route_group == RouteGroup.WRITE_API,
            enabled_for_routing=enabled_for_routing,
            enabled_for_terminal=True,
            enabled_for_chat=False,
            enabled_for_agent=True,
            visibility=self._determine_visibility(permission_classes),
            auto_collected=True,
            review_status=ReviewStatus.AUTO,
        )

    def _create_capability_key(self, path: str, method: str) -> str:
        """Create a unique capability key from path and method."""
        clean_path = re.sub(r"[<>/]", ".", path)
        clean_path = re.sub(r"\.+", ".", clean_path)
        clean_path = clean_path.strip(".")
        return f"api.{method.lower()}.{clean_path}"

    def _create_name(self, path: str, method: str) -> str:
        """Create a human-readable name."""
        parts = []
        for part in path.strip("/").split("/"):
            if part == "api":
                continue
            if part.startswith("<") and part.endswith(">"):
                parts.append(part[1:-1].replace("_", " "))
                continue
            parts.append(part.replace("-", " "))

        name = " ".join(parts[-3:])
        return f"{method} {name}".title()

    def _determine_route_group(
        self,
        path: str,
        method: str,
        view_class: type | None,
    ) -> RouteGroup:
        """Determine route group based on path, method, and view."""
        if self._is_unsafe(path, method, view_class):
            return RouteGroup.UNSAFE_API

        if method in self.WRITE_METHODS:
            return RouteGroup.WRITE_API

        return RouteGroup.READ_API

    def _determine_risk_level(
        self,
        path: str,
        method: str,
        view_class: type | None,
    ) -> RiskLevel:
        """Determine risk level for the endpoint."""
        if self._is_unsafe(path, method, view_class):
            return RiskLevel.CRITICAL

        if method in self.WRITE_METHODS:
            return RiskLevel.MEDIUM

        return RiskLevel.SAFE

    def _is_unsafe(
        self,
        path: str,
        method: str,
        view_class: type | None,
    ) -> bool:
        """Check if the endpoint is considered unsafe."""
        path_lower = path.lower()

        for pattern in self.UNSAFE_PATTERNS:
            if re.search(pattern, path_lower):
                return True

        if view_class:
            permission_classes = self._get_permission_classes(view_class)
            for perm in permission_classes:
                perm_name = perm.__name__ if hasattr(perm, "__name__") else str(perm)
                if "admin" in perm_name.lower() or "staff" in perm_name.lower():
                    return True

        return False

    def _determine_category(self, path: str) -> str:
        """Determine category from path."""
        parts = path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "api":
            return parts[1]
        return "api"

    def _determine_visibility(self, permission_classes: list) -> Visibility:
        """Determine visibility from permission classes."""
        for perm in permission_classes:
            perm_name = perm.__name__ if hasattr(perm, "__name__") else str(perm)
            if "admin" in perm_name.lower():
                return Visibility.ADMIN
            if "authenticated" in perm_name.lower():
                return Visibility.INTERNAL
        return Visibility.PUBLIC

    def _get_docstring(self, view_class: type, method: str) -> str:
        """Get docstring from view or method."""
        method_lower = method.lower()

        if hasattr(view_class, method_lower):
            method_func = getattr(view_class, method_lower)
            if method_func.__doc__:
                return method_func.__doc__.strip()

        if view_class.__doc__:
            return view_class.__doc__.strip()

        return ""

    def _get_permission_classes(self, view_class: type) -> list:
        """Get permission classes from view."""
        if hasattr(view_class, "permission_classes"):
            return list(view_class.permission_classes)
        return []

    def _extract_tags(self, path: str, view_class: type) -> list[str]:
        """Extract tags from path and view."""
        tags = ["api", "internal"]

        parts = path.strip("/").split("/")
        for part in parts:
            if not part.startswith("<") and not part.startswith("api"):
                tags.append(part)

        return list(set(tags))[:5]

    def _extract_input_schema(self, view_class: type, method: str) -> dict:
        """Extract input schema from serializer if available."""
        schema = {"type": "object", "properties": {}}

        if hasattr(view_class, "serializer_class"):
            serializer = view_class.serializer_class
            if hasattr(serializer, "get_fields"):
                try:
                    fields = serializer().get_fields()
                    for field_name, field in fields.items():
                        schema["properties"][field_name] = {
                            "type": "string",
                            "description": getattr(field, "help_text", ""),
                        }
                except Exception:
                    pass

        return schema
