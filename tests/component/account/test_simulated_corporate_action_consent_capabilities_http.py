"""Real owner HTTP capability selection, same-chain replacement and independent withdrawal."""

from __future__ import annotations

import pytest
from django.db import connection
from django.test import Client
from django.utils import timezone

from apps.account import simulated_corporate_action_policy_scope_composition as policies
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
)
from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.account.infrastructure.simulated_corporate_action_write_grant_models import (
    SimulatedCorporateActionWriteGrantModel as GrantRow,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_models import (
    SimulatedCorporateActionWriteGrantRevocationModel as RevocationRow,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_repository import (
    DjangoSimulatedCorporateActionWriteGrantRepository as Repository,
)
from apps.account.simulated_corporate_action_consent_terms import (
    SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
)
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.terminal.application.tui_simulated_corporate_action_consent_result import (
    CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
    project_simulated_corporate_action_consent_result,
)
from core.integration.config_center_runtime import get_active_runtime_value_evidence
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    owner_world as owner_world,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Native migrated PostgreSQL contract; executed by the required PostgreSQL workflow.",
    ),
]
TERMS_SHA256 = "6ee0ad13d2e0b9cff885bfdf9d1e0e2ccb837c0943bf2cab6cf90d8410031165"


def _publish_known_policy(*, version="http-v2", enabled=True):
    """Activate explicit known terms only inside the isolated native test transaction."""
    evidence = get_active_runtime_value_evidence(
        environment="development",
        definition_key=policies.SIMULATED_ACTION_WRITE_POLICY_KEY,
        as_of=timezone.now(),
    )
    item = dict(evidence.value["policies"][0])
    item.update(
        policy_version=version,
        permission=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
        capabilities=sorted(capability.value for capability in Capability),
        terms_version=SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
        terms_sha256=TERMS_SHA256,
    )
    activate_runtime_profile_patch(
        environment="development",
        patch={
            policies.SIMULATED_ACTION_WRITE_POLICY_KEY: {
                "schema_version": policies.SIMULATED_ACTION_WRITE_POLICY_SCHEMA_V2,
                "enabled": enabled,
                "policies": [item] if enabled else [],
            }
        },
        actor="isolated-owner-capability-http",
        reason="explicit test-only consent document; no financial or tax-date activation",
    )


def _owner_client(world):
    """Use a real authenticated Django session and managed CSRF cookie."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(world.user)
    csrf = client.get("/csrf/bootstrap/", secure=True, HTTP_ORIGIN="https://testserver").json()[
        "csrf_token"
    ]
    return client, {
        "secure": True,
        "HTTP_ORIGIN": "https://testserver",
        "HTTP_X_CSRFTOKEN": csrf,
    }


def _post(client, path, body, headers):
    """Require the actual JSON status and content-type contract."""
    response = client.post(path, body, content_type="application/json", **headers)
    assert response.status_code == 200, response.content
    assert response.headers["Content-Type"].startswith("application/json")
    return response.json()


def test_native_http_selected_capabilities_replace_same_chain_and_withdraw_after_policy_loss(
    owner_world, settings
):
    """Checkboxes bind the exact document and subset; narrowing never preserves old rights."""
    settings.ROOT_URLCONF = "tests.support.ash07_owner_source_test_urls"
    world = owner_world
    client, headers = _owner_client(world)
    path = f"/api/simulated-trading/accounts/{world.row.pk}/corporate-action-consent/"
    baseline = CorporateActionPostingModel.objects.count()
    cash = {"cash_dividend": True, "tax_assessment": False, "tax_withholding": False}
    legacy = _post(client, path + "prepare/", cash, headers)
    assert legacy["grant_schema"] is None
    first = _post(
        client,
        path,
        {"consent_token": legacy["continuation"]["input"]["consent_token"], "confirmed": True},
        headers,
    )
    _publish_known_policy()
    both = {"cash_dividend": True, "tax_assessment": True, "tax_withholding": False}
    prepared = _post(client, path + "prepare/", both, headers)
    assert prepared["grant_schema"] == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
    assert prepared["selected_capabilities"] == [
        Capability.TAX_ASSESS.value,
        Capability.CASH_STAGE_WRITE.value,
    ]
    assert prepared["terms_version"] == SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2
    assert prepared["terms_sha256"] == TERMS_SHA256
    assert "模拟税额评估" in prepared["terms_text"]
    assert "模拟税款扣除" in prepared["terms_text"]
    assert "替换" in prepared["summary"]
    assert prepared["consent_token"] is None
    rendered = project_simulated_corporate_action_consent_result(
        CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
        {key: value for key, value in prepared.items() if key != "continuation"},
        http_status=200,
        requested_params={"account_id": world.row.pk, **both},
    )
    assert rendered["outcome"] == "success", rendered
    assert GrantRow.objects.count() == 1
    body = {"consent_token": prepared["continuation"]["input"]["consent_token"], "confirmed": True}
    assert body["consent_token"].startswith("v2.")
    denied = client.post(path, body, content_type="application/json", secure=True)
    assert denied.status_code == 403
    upgraded = _post(client, path, body, headers)
    assert upgraded["grant_id"] == first["grant_id"]
    assert upgraded["grant_version"] != first["grant_version"]
    assert (
        _post(client, path, body, headers)["grant_content_hash"] == upgraded["grant_content_hash"]
    )
    assert GrantRow.objects.count() == 2
    narrowed = _post(
        client,
        path + "prepare/",
        {"cash_dividend": False, "tax_assessment": True, "tax_withholding": False},
        headers,
    )
    final = _post(
        client,
        path,
        {"consent_token": narrowed["continuation"]["input"]["consent_token"], "confirmed": True},
        headers,
    )
    assert final["selected_capabilities"] == [Capability.TAX_ASSESS.value]
    heads = Repository().get_current_for_scope(
        "simulated", world.source.account_id, as_of=timezone.now()
    )
    assert len(heads) == 1 and heads[0].content_hash == final["grant_content_hash"]
    assert heads[0].identity_hash == GrantRow.objects.order_by("pk").first().identity_hash
    assert heads[0].supports_capability(Capability.CASH_STAGE_WRITE) is False
    assert heads[0].supports_capability(Capability.TAX_WITHHOLD) is False
    AccountProfileModel.objects.filter(user_id=world.user.pk).update(rbac_role="read_only")
    _publish_known_policy(enabled=False)
    withdrawal = _post(client, path + "withdraw/prepare/", {}, headers)
    removed = _post(
        client,
        path + "withdraw/",
        {
            "withdrawal_token": withdrawal["continuation"]["input"]["withdrawal_token"],
            "confirmed": True,
        },
        headers,
    )
    assert removed["consent_status"] == "revoked"
    assert removed["selected_capabilities"] == [Capability.TAX_ASSESS.value]
    assert GrantRow.objects.count() == 3 and RevocationRow.objects.count() == 1
    assert CorporateActionPostingModel.objects.count() == baseline
    world.row.refresh_from_db()
    assert world.row.current_cash == world.row.total_value == 10000


def test_native_http_current_policy_change_blocks_prepared_capability_confirmation(
    owner_world, settings
):
    """An authenticated old token cannot authorize a new policy revision."""
    settings.ROOT_URLCONF = "tests.support.ash07_owner_source_test_urls"
    world = owner_world
    _publish_known_policy()
    client, headers = _owner_client(world)
    path = f"/api/simulated-trading/accounts/{world.row.pk}/corporate-action-consent/"
    prepared = _post(
        client,
        path + "prepare/",
        {"cash_dividend": False, "tax_assessment": True, "tax_withholding": False},
        headers,
    )
    _publish_known_policy(version="http-v2-changed")
    rejected = client.post(
        path,
        {"consent_token": prepared["continuation"]["input"]["consent_token"], "confirmed": True},
        content_type="application/json",
        **headers,
    )
    assert rejected.status_code == 422
    assert rejected.headers["Content-Type"].startswith("application/json")
    assert GrantRow.objects.count() == RevocationRow.objects.count() == 0


def test_native_http_unknown_historical_terms_can_still_be_withdrawn(owner_world, settings):
    """Unavailable old prose never makes the removal of permission depend on policy lookup."""
    from tests.component.account.test_simulated_corporate_action_capability_issuance_postgres import (
        _request,
        _v2_command,
        issue,
    )

    settings.ROOT_URLCONF = "tests.support.ash07_owner_source_test_urls"
    world = owner_world
    command = _v2_command(world)
    grant = issue(_request(world.user), command=command, scope_locker=world.locker, using="default")
    client, headers = _owner_client(world)
    path = f"/api/simulated-trading/accounts/{world.row.pk}/corporate-action-consent/"
    prepared = _post(client, path + "withdraw/prepare/", {}, headers)
    assert prepared["outcome"] == "success" and prepared["terms_text"] == ""
    assert prepared["selected_capabilities"] == [Capability.TAX_ASSESS.value]
    removed = _post(
        client,
        path + "withdraw/",
        {
            "withdrawal_token": prepared["continuation"]["input"]["withdrawal_token"],
            "confirmed": True,
        },
        headers,
    )
    assert removed["consent_status"] == "revoked" and removed["terms_text"] == ""
    assert removed["grant_content_hash"] == grant.content_hash
    assert RevocationRow.objects.count() == 1
