"""API capability collector routing and visibility regression tests."""

from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.viewsets import ViewSet

from apps.ai_capability.domain.entities import RouteGroup, Visibility
from apps.ai_capability.infrastructure.collectors.api_collector import (
    ApiCapabilityCollector,
)


class _InventoryViewSet(ViewSet):
    def list(self, request):
        return None

    def create(self, request):
        return None

    def retrieve(self, request, pk=None):
        return None

    def destroy(self, request, pk=None):
        return None


def test_viewset_collection_uses_only_actions_bound_to_the_url() -> None:
    collector = ApiCapabilityCollector()
    list_callback = _InventoryViewSet.as_view(
        {
            "get": "list",
            "post": "create",
        }
    )

    capabilities = collector._create_capabilities_from_view(
        "api/inventory/",
        list_callback,
    )

    assert [capability.source_ref for capability in capabilities] == [
        "GET api/inventory/",
        "POST api/inventory/",
    ]
    assert all("DELETE" not in capability.source_ref for capability in capabilities)


def test_detail_viewset_does_not_publish_unbound_create_action() -> None:
    collector = ApiCapabilityCollector()
    detail_callback = _InventoryViewSet.as_view(
        {
            "get": "retrieve",
            "delete": "destroy",
        }
    )

    capabilities = collector._create_capabilities_from_view(
        "api/inventory/<pk>/",
        detail_callback,
    )

    assert [capability.source_ref for capability in capabilities] == [
        "DELETE api/inventory/<pk>/",
        "GET api/inventory/<pk>/",
    ]
    assert capabilities[0].route_group == RouteGroup.WRITE_API
    assert capabilities[0].requires_confirmation is True


def test_admin_permission_takes_precedence_over_authenticated_visibility() -> None:
    collector = ApiCapabilityCollector()

    visibility = collector._determine_visibility([IsAuthenticated, IsAdminUser])

    assert visibility == Visibility.ADMIN


def test_tags_preserve_stable_path_order() -> None:
    collector = ApiCapabilityCollector()

    tags = collector._extract_tags("api/portfolio/positions/portfolio/", _InventoryViewSet)

    assert tags == ["api", "internal", "portfolio", "positions"]
