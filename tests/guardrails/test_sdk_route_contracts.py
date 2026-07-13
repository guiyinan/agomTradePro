"""Guard formal SDK HTTP routes against Django URL drift."""

from scripts.check_sdk_route_contracts import (
    collect_sdk_route_calls,
    validate_sdk_route_contracts,
)


def test_formal_sdk_routes_resolve_with_supported_http_methods() -> None:
    """Every statically declared SDK endpoint must resolve in Django."""

    calls = collect_sdk_route_calls()
    assert calls
    routes = {(call.method, call.path) for call in calls}
    assert ("GET", "/api/account/positions/read-only/") in routes
    assert ("GET", "/api/account/transactions/") in routes
    assert ("GET", "/api/account/capital-flows/") in routes
    assert ("GET", "/api/regime/navigator/") in routes
    assert ("GET", "/api/regime/action/") in routes
    summary = validate_sdk_route_contracts(calls)
    assert summary["unresolved_calls"] == 0
    assert summary["method_mismatches"] == 0
