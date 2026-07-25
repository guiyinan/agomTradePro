"""URL normalization and capability classification contracts for API discovery."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.http import HttpResponse
from django.urls import include, path
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from apps.ai_capability.domain.entities import (
    RiskLevel,
    RouteGroup,
    Visibility,
)
from apps.ai_capability.infrastructure.collectors import api_collector
from apps.ai_capability.infrastructure.collectors.api_collector import (
    ApiCapabilityCollector,
    _clean_pattern_str,
    _derive_semantic_key,
    _normalize_api_path,
)


class IsAuthenticated:
    pass


class IsAdminUser:
    pass


class FakeSerializer:
    def get_fields(self) -> dict[str, SimpleNamespace]:
        return {
            "name": SimpleNamespace(help_text="Display name"),
            "count": SimpleNamespace(help_text=None),
        }


class SampleView(APIView):
    """Sample endpoint."""

    permission_classes = [IsAuthenticated]
    serializer_class = FakeSerializer

    def get(self, request: object) -> None:
        """List samples."""

    def post(self, request: object) -> None:
        pass


class SampleViewSet(ViewSet):
    def list(self, request: object) -> None:
        pass

    def create(self, request: object) -> None:
        pass

    def retrieve(self, request: object) -> None:
        pass

    def update(self, request: object) -> None:
        pass

    def partial_update(self, request: object) -> None:
        pass

    def destroy(self, request: object) -> None:
        pass


def plain_view(request: object) -> HttpResponse:
    return HttpResponse("ok")


def test_path_normalization_semantics_keys_and_labels() -> None:
    assert _clean_pattern_str("^api//items/$") == "api/items/"
    assert _normalize_api_path(r"^api/items/(?P<ITEM_ID>\d+)/\Z$") == (
        "api/items/<item_id>/"
    )
    assert _normalize_api_path("api/items.<(?P<format>json)>") is None
    assert _derive_semantic_key("api/data-center/items/<item_id>/") == (
        "data_center.items"
    )
    collector = ApiCapabilityCollector()
    assert collector._create_capability_key("api/items/<id>/", "GET") == (
        "api.get.api.items.id"
    )
    assert collector._create_name("api/items/<item_id>/history/", "GET") == (
        "Get Items Item Id History"
    )


def test_collect_recurses_real_url_patterns_and_skips_non_api_docs() -> None:
    nested = [
        path("items/", SampleView.as_view()),
        path("plain/", plain_view),
        path("schema/", plain_view),
    ]
    root = path("api/", include((nested, "test")))
    non_api = path("health/", plain_view)
    capabilities = []
    collector = ApiCapabilityCollector()
    collector._collect_from_pattern(root, capabilities)
    collector._collect_from_pattern(non_api, capabilities)
    assert {cap.source_ref for cap in capabilities} >= {
        "GET api/items/",
        "POST api/items/",
        "GET api/plain/",
    }
    assert all("schema" not in cap.source_ref for cap in capabilities)


def test_collect_uses_resolver_and_viewset_method_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = path(
        "api/",
        include(([path("sets/", SampleViewSet.as_view({"get": "list"}))], "test")),
    )
    monkeypatch.setattr(
        api_collector,
        "get_resolver",
        lambda: SimpleNamespace(url_patterns=[root]),
    )
    collected = ApiCapabilityCollector().collect()
    assert collected
    methods = ApiCapabilityCollector()._get_view_methods(SampleViewSet)
    assert set(methods) == {"GET", "POST", "PUT", "PATCH", "DELETE"}
    assert ApiCapabilityCollector()._get_view_methods(object) == []


def test_capability_creation_classifies_read_write_and_unsafe_routes() -> None:
    collector = ApiCapabilityCollector()
    read = collector._create_capability_for_path("api/items/", "GET")
    write = collector._create_capability_for_path("api/items/", "POST")
    assert read is not None
    assert read.route_group == RouteGroup.READ_API
    assert read.risk_level == RiskLevel.SAFE
    assert write is not None
    assert write.route_group == RouteGroup.WRITE_API
    assert write.requires_confirmation is True
    assert collector._create_capability_for_path("api/admin/reset/", "POST") is None

    unsafe_view = type(
        "UnsafeView",
        (APIView,),
        {"permission_classes": [IsAdminUser], "post": lambda self, request: None},
    )
    unsafe = collector._create_capability_for_view(
        "api/items/", "POST", unsafe_view
    )
    assert unsafe is not None
    assert unsafe.route_group == RouteGroup.UNSAFE_API
    assert unsafe.risk_level == RiskLevel.CRITICAL
    assert unsafe.enabled_for_routing is False
    assert unsafe.visibility == Visibility.ADMIN


def test_view_metadata_docstrings_permissions_tags_and_schema() -> None:
    collector = ApiCapabilityCollector()
    capability = collector._create_capability_for_view(
        "api/data-center/items/<item_id>/", "GET", SampleView
    )
    assert capability is not None
    assert capability.summary == "List samples."
    assert capability.visibility == Visibility.INTERNAL
    assert capability.semantic_key == "data_center.items"
    assert capability.input_schema["properties"]["name"]["description"] == (
        "Display name"
    )
    assert "data-center" in capability.tags
    assert collector._determine_category("api/data-center/items/") == "data-center"
    assert collector._determine_category("health/") == "api"
    assert collector._determine_visibility([]) == Visibility.PUBLIC
    assert collector._get_permission_classes(object) == []


def test_metadata_fallbacks_and_serializer_errors_are_safe() -> None:
    collector = ApiCapabilityCollector()

    class BrokenSerializer:
        def get_fields(self) -> dict[str, object]:
            raise RuntimeError("schema unavailable")

    class BareView(APIView):
        serializer_class = BrokenSerializer

        def get(self, request: object) -> None:
            pass

    assert collector._get_docstring(BareView, "get") == ""
    assert collector._extract_input_schema(BareView, "GET") == {
        "type": "object",
        "properties": {},
    }
    assert collector._extract_input_schema(object, "GET") == {
        "type": "object",
        "properties": {},
    }
    assert collector._is_unsafe("api/token/", "GET", None) is True
    assert collector._is_unsafe("api/items/", "GET", SampleView) is False

