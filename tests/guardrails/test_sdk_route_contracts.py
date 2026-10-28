"""Guard formal SDK HTTP routes against Django URL drift."""

import pytest
from django.urls import Resolver404, resolve

from scripts.check_sdk_route_contracts import (
    collect_sdk_route_calls,
    validate_sdk_route_contracts,
)

_RECOVERY_HEAD_PATH = (
    "/api/simulated-trading/accounts/1/trades/1/fee-corrections/"
    "recovery/00000000-0000-0000-0000-000000000001/head/"
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
    assert ("GET", "/api/simulated-trading/accounts/1/fee-correction-policy/") in routes
    assert ("PUT", "/api/simulated-trading/accounts/1/fee-correction-policy/") in routes
    assert ("GET", "/api/simulated-trading/accounts/1/trades/1/fee-corrections/head/") in routes
    assert ("POST", "/api/simulated-trading/accounts/1/trades/1/fee-correction-evidence/") in routes
    assert ("POST", "/api/simulated-trading/accounts/1/trades/1/fee-corrections/") in routes
    assert ("POST", "/api/simulated-trading/accounts/1/positions/close/") in routes
    summary = validate_sdk_route_contracts(calls)
    assert summary["unresolved_calls"] == 0
    assert summary["method_mismatches"] == 0


def test_recovery_head_call_uses_the_exact_uuid_route_sample() -> None:
    """The statically collected SDK locator sample must satisfy Django's UUID converter."""

    calls = collect_sdk_route_calls()
    recovery_head_routes = {
        (call.method, call.path)
        for call in calls
        if call.module_file == "sdk/agomtradepro/modules/simulated_fee_corrections.py"
        and "/fee-corrections/recovery/" in call.path
        and call.path.endswith("/head/")
    }

    assert recovery_head_routes == {("GET", _RECOVERY_HEAD_PATH)}
    resolve(_RECOVERY_HEAD_PATH)


def test_recovery_head_route_rejects_a_non_uuid_locator() -> None:
    """An invalid locator must remain unresolved instead of weakening the route check."""

    invalid_path = _RECOVERY_HEAD_PATH.replace("00000000-0000-0000-0000-000000000001", "not-a-uuid")

    with pytest.raises(Resolver404):
        resolve(invalid_path)
