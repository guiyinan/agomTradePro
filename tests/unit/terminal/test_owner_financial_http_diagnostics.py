"""Signed test continuations must never appear in failure diagnostics."""

from types import SimpleNamespace

import pytest

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from tests.component.simulated_trading import test_corporate_action_owner_nav_postgres as nav
from tests.component.simulated_trading import (
    test_corporate_action_owner_workflow_http_postgres as http,
)

_OPAQUE = "synthetic-sealed-value-must-not-appear-in-diagnostics"


@pytest.mark.parametrize(
    "module,helper",
    [(http, http._issue_v3_cash_tax_consent), (nav, nav._select_cash_and_tax_capabilities)],
)
def test_wrong_consent_schema_never_renders_the_signed_value(monkeypatch, module, helper):
    world = SimpleNamespace(
        account_id=17, owner=SimpleNamespace(client=object(), csrf_token="synthetic-csrf")
    )
    payload = {
        "selected_capabilities": sorted(
            [
                Capability.CASH_STAGE_WRITE.value,
                Capability.TAX_ASSESS.value,
                Capability.TAX_WITHHOLD.value,
            ]
        ),
        "continuation": {"input": {"consent_token": _OPAQUE}},
    }
    monkeypatch.setattr(module, "_post", lambda *a, **k: payload)
    with pytest.raises(AssertionError) as failure:
        helper(world)
    assert _OPAQUE not in str(failure.value)


@pytest.mark.parametrize("operation", ["post", "read"])
def test_owner_http_status_failure_never_renders_response_body(operation):
    response = SimpleNamespace(status_code=503, content=_OPAQUE.encode())
    client = SimpleNamespace(post=lambda *a, **k: response, get=lambda *a, **k: response)
    with pytest.raises(AssertionError) as failure:
        if operation == "post":
            http._post(client, "/synthetic/", {}, {})
        else:
            http._read(client, "/synthetic/", {})
    assert _OPAQUE not in str(failure.value)
