"""OpenAPI contracts for the session-only saved-plan HTTP journey."""

from __future__ import annotations

from typing import cast

from django.urls import path
from drf_spectacular.generators import SchemaGenerator

from apps.simulated_trading.interface.rebalance_plan_journey_views import (
    RebalancePlanExactAPIView,
    RebalancePlanListCreateAPIView,
    RebalancePlanOrderPreviewAPIView,
    RebalancePlanReconciliationAPIView,
    RebalancePlanReviewAPIView,
    RebalancePlanSuccessorAPIView,
)


def _generated_schema() -> dict[str, object]:
    """Generate only the plan routes, without depending on database state."""

    generated = SchemaGenerator(
        patterns=[
            path(
                "api/simulated-trading/accounts/<int:account_id>/rebalance-plans/",
                RebalancePlanListCreateAPIView.as_view(),
            ),
            path(
                "api/simulated-trading/accounts/<int:account_id>/rebalance-plans/<str:plan_id>/",
                RebalancePlanExactAPIView.as_view(),
            ),
            path(
                "api/simulated-trading/accounts/<int:account_id>/rebalance-plans/<str:plan_id>/review/",
                RebalancePlanReviewAPIView.as_view(),
            ),
            path(
                "api/simulated-trading/accounts/<int:account_id>/rebalance-plans/<str:plan_id>/successor/",
                RebalancePlanSuccessorAPIView.as_view(),
            ),
            path(
                "api/simulated-trading/accounts/<int:account_id>/rebalance-plans/<str:plan_id>/reconciliation/",
                RebalancePlanReconciliationAPIView.as_view(),
            ),
            path(
                "api/simulated-trading/accounts/<int:account_id>/rebalance-plans/<str:plan_id>/orders/<int:order_ordinal>/preview/",
                RebalancePlanOrderPreviewAPIView.as_view(),
            ),
        ]
    ).get_schema(public=True)
    assert generated is not None
    return cast(dict[str, object], generated)


def _operation(schema: dict[str, object], path_name: str, method: str) -> dict[str, object]:
    """Return one generated OpenAPI operation with explicit structural checks."""

    paths = cast(dict[str, object], schema["paths"])
    path_item = cast(dict[str, object], paths[path_name])
    return cast(dict[str, object], path_item[method])


def _request_properties(schema: dict[str, object], operation: dict[str, object]) -> set[str]:
    """Resolve one request serializer's published JSON properties."""

    request_body = cast(dict[str, object], operation["requestBody"])
    content = cast(dict[str, object], request_body["content"])
    media = cast(dict[str, object], content["application/json"])
    request_schema = cast(dict[str, object], media["schema"])
    components = cast(dict[str, object], schema["components"])
    schemas = cast(dict[str, object], components["schemas"])

    def properties_from(node: dict[str, object]) -> set[str]:
        reference = node.get("$ref")
        if isinstance(reference, str):
            return properties_from(cast(dict[str, object], schemas[reference.rsplit("/", 1)[-1]]))
        result: set[str] = set()
        properties = node.get("properties")
        if isinstance(properties, dict):
            result.update(cast(dict[str, object], properties))
        for part in cast(list[object], node.get("allOf", [])):
            if isinstance(part, dict):
                result.update(properties_from(cast(dict[str, object], part)))
        return result

    return properties_from(request_schema)


def test_openapi_publishes_all_plan_routes_exact_pins_and_mutation_keys() -> None:
    schema = _generated_schema()
    base = "/api/simulated-trading/accounts/{account_id}/rebalance-plans/"
    plan = f"{base}{{plan_id}}/"
    preview_path = f"{plan}orders/{{order_ordinal}}/preview/"

    base_operations = cast(dict[str, object], cast(dict[str, object], schema["paths"])[base])
    assert {"get", "post"} <= set(base_operations)
    for path_name, method in (
        (plan, "get"),
        (f"{plan}review/", "post"),
        (f"{plan}successor/", "post"),
        (f"{plan}reconciliation/", "get"),
        (preview_path, "post"),
    ):
        _operation(schema, path_name, method)

    for method in ("post",):
        operation = _operation(schema, base, method)
        assert _request_properties(schema, operation) == {"target_weights", "reference_price_basis"}

    for path_name, method, required_body in (
        (base, "post", {"target_weights", "reference_price_basis"}),
        (f"{plan}review/", "post", {"plan_version", "revision_hash", "confirmed"}),
        (
            f"{plan}successor/",
            "post",
            {
                "plan_version",
                "revision_hash",
                "confirmed",
                "target_weights",
                "reference_price_basis",
            },
        ),
        (
            preview_path,
            "post",
            {
                "plan_version",
                "revision_hash",
                "order_content_hash",
                "plan_order_binding_id",
                "quantity",
                "limit_price",
                "reason",
            },
        ),
    ):
        operation = _operation(schema, path_name, method)
        assert required_body <= _request_properties(schema, operation)
        responses = cast(dict[str, object], operation["responses"])
        assert "200" in responses
        success_response = cast(dict[str, object], responses["200"])
        success_content = cast(dict[str, object], success_response["content"])
        assert "application/json" in success_content
        parameters = cast(list[dict[str, object]], operation["parameters"])
        assert any(
            item.get("name") == "Idempotency-Key"
            and item.get("in") == "header"
            and item.get("required") is True
            for item in parameters
        )

    for path_name in (plan, f"{plan}reconciliation/"):
        operation = _operation(schema, path_name, "get")
        parameters = cast(list[dict[str, object]], operation["parameters"])
        assert {item.get("name") for item in parameters if item.get("in") == "query"} == {
            "plan_version",
            "revision_hash",
        }

    forbidden = {"cash", "positions", "price", "fees", "asset_code", "security_id", "side"}
    for path_name, method in (
        (base, "post"),
        (f"{plan}review/", "post"),
        (f"{plan}successor/", "post"),
        (preview_path, "post"),
    ):
        assert not forbidden.intersection(
            _request_properties(schema, _operation(schema, path_name, method))
        )
