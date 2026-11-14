"""Refresh real ordinary-owner evidence on the existing fully migrated QA schema."""

from __future__ import annotations

import base64
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.account import simulated_corporate_action_policy_scope_composition as policies
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
)
from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.account.infrastructure.physical_account_row_observation_v2_models import (
    PhysicalAccountRowObservationV2Model,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_repository import (
    DjangoSimulatedCorporateActionWriteGrantRepository,
)
from apps.account.simulated_corporate_action_consent_terms import (
    SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V3,
)
from apps.account.simulated_corporate_action_current_grant_composition import (
    locked_current_simulated_corporate_action_write_grant,
)
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.simulated_trading.application.current_account_ownership import (
    CurrentAccountOwnershipUnavailable,
)
from apps.simulated_trading.corporate_action_account_refresh_composition import (
    refresh_owner_simulated_account_evidence,
)
from apps.simulated_trading.infrastructure.simulated_account_evidence_pipeline import (
    SimulatedAccountEvidencePipeline,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_models import (
    SimulatedAccountRawObservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_repository import (
    DjangoSimulatedAccountRawObservationRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_models import (
    SimulatedAccountRowSourceV2Model,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Repository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from core.exceptions import AuthorizationError
from shared.config.secrets import get_secrets
from tests.component.account.test_simulated_corporate_action_consent_capabilities_http import (
    TERMS_V3_SHA256,
    _owner_client,
)
from tests.component.account.test_simulated_corporate_action_consent_capabilities_http import (
    _post as consent_post,
)
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    _request as authenticated_request,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.support.runtime_config import configure_critical_runtime
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = [
    pytest.mark.django_db(transaction=True, available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS),
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="Migrated native PostgreSQL required"
    ),
]


@pytest.fixture
def refresh_owner(monkeypatch, settings, preserve_account_authority_generation):
    """Create a genuine nonstaff owner/account through actual Session and CSRF APIs."""
    del preserve_account_authority_generation
    with isolated_task_channels():
        monkeypatch.setenv(
            "AGOMTRADEPRO_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"t" * 32).decode()
        )
        get_secrets.cache_clear()
        configure_critical_runtime()
        settings.ROOT_URLCONF = "tests.support.ash07_owner_source_test_urls"
        owner = User.objects.create_user(
            username=f"refresh-owner-{uuid4().hex}",
            is_staff=False,
            is_superuser=False,
            is_active=True,
        )
        AccountProfileModel.objects.update_or_create(
            user=owner,
            defaults={
                "display_name": "Refresh owner",
                "rbac_role": "owner",
                "approval_status": "pending",
            },
        )
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(owner)
        bootstrap = client.get("/csrf/bootstrap/", secure=True)
        assert bootstrap.status_code == 200
        csrf = bootstrap.json()["csrf_token"]
        response = client.post(
            "/api/simulated-trading/accounts/",
            {
                "account_name": "Refresh native",
                "account_type": "simulated",
                "initial_capital": "100000.00",
                "max_position_pct": 20.0,
                "stop_loss_pct": 8.0,
                "commission_rate": 0.0002,
                "slippage_rate": 0.0008,
            },
            format="json",
            secure=True,
            HTTP_ORIGIN="https://testserver",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_IDEMPOTENCY_KEY=f"refresh-create-{uuid4().hex}",
        )
        assert response.status_code == 201, response.content
        row = SimulatedAccountModel.objects.get(pk=response.json()["account"]["account_id"])
        assert row.user_id == owner.pk and not owner.is_staff and not owner.is_superuser
        yield SimpleNamespace(user=owner, row=row, client=client, csrf=csrf)
        get_secrets.cache_clear()


def _counts() -> tuple[int, int, int]:
    return (
        SimulatedAccountRawObservationModel.objects.count(),
        SimulatedAccountRowSourceV2Model.objects.count(),
        PhysicalAccountRowObservationV2Model.objects.count(),
    )


def _advance(row: SimulatedAccountModel) -> None:
    SimulatedAccountModel.objects.filter(pk=row.pk).update(updated_at=timezone.now())
    row.refresh_from_db()


def test_actual_owner_refresh_advances_three_ledgers_and_can_consent_v3(refresh_owner):
    world = refresh_owner
    before = _counts()
    cash = world.row.current_cash
    source_repository = DjangoSimulatedAccountRowSourceV2Repository(using="default")
    old = source_repository.get_physical_account_heads(
        underlying_unified_account_id=world.row.pk, as_of=timezone.now()
    )[0].source
    _advance(world.row)
    receipt = refresh_owner_simulated_account_evidence(
        authenticated_request(world.user), account_id=world.row.pk
    )
    world.row.refresh_from_db()
    source = source_repository.get_physical_account_heads(
        underlying_unified_account_id=world.row.pk, as_of=timezone.now()
    )[0].source
    raw = DjangoSimulatedAccountRawObservationRepository(using="default").get_physical_row_head(
        row_pk=world.row.pk, as_of=timezone.now()
    )
    assert raw is not None
    assert source.content_hash != old.content_hash
    assert source.row_updated_at == world.row.updated_at == raw.observation.row_updated_at
    assert source.raw_observation_content_hash == raw.observation.content_hash
    assert source.is_current_at(timezone.now())
    assert _counts() == tuple(count + 1 for count in before)
    assert receipt.account_id == world.row.pk and receipt.must_not_use_for_decision is True
    assert receipt.blocking_reason == "account_ownership_evidence_only"
    assert world.row.current_cash == cash
    now = timezone.now()
    selected = (Capability.SHARE_STAGE_WRITE, Capability.RIGHTS_NOT_EXERCISED)
    activate_runtime_profile_patch(
        environment="development",
        patch={
            policies.SIMULATED_ACTION_WRITE_POLICY_KEY: {
                "schema_version": policies.SIMULATED_ACTION_WRITE_POLICY_SCHEMA_V3,
                "enabled": True,
                "policies": [
                    {
                        "policy_id": "refresh-native-policy",
                        "policy_version": "1",
                        "canonical_account_id": source.account_id,
                        "owner_user_id": world.user.pk,
                        "tenant_id": "refresh-tenant",
                        "owner_id": "refresh-owner",
                        "valid_from": (now - timedelta(minutes=1)).isoformat(),
                        "valid_until": (now + timedelta(hours=1)).isoformat(),
                        "maximum_grant_seconds": 600,
                        "permission": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION,
                        "service_actor_id": "simulated-trading",
                        "capabilities": sorted(cap.value for cap in selected),
                        "terms_version": SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V3,
                        "terms_sha256": TERMS_V3_SHA256,
                    }
                ],
            }
        },
        actor="refresh-native-test",
        reason="explicit synthetic owner policy; no financial authority default",
    )
    client, headers = _owner_client(world)
    path = f"/api/simulated-trading/accounts/{world.row.pk}/corporate-action-consent/"
    prepared = consent_post(
        client,
        path + "prepare/",
        {
            "cash_dividend": False,
            "tax_assessment": False,
            "tax_withholding": False,
            "share_distribution": True,
            "rights_not_exercised": True,
        },
        headers,
    )
    confirmed = consent_post(
        client,
        path,
        {"consent_token": prepared["continuation"]["input"]["consent_token"], "confirmed": True},
        headers,
    )
    assert confirmed["grant_schema"] == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA
    grant = DjangoSimulatedCorporateActionWriteGrantRepository(
        using="default"
    ).get_current_for_scope("simulated", source.account_id, as_of=timezone.now())[0]
    with transaction.atomic():
        with locked_current_simulated_corporate_action_write_grant(
            selector=grant.selector,
            using="default",
            required_capability=Capability.SHARE_STAGE_WRITE,
        ) as current:
            assert current == grant


def test_actual_final_row_drift_rolls_back_all_refresh_heads(refresh_owner, monkeypatch):
    world = refresh_owner
    _advance(world.row)
    before = _counts()
    before_clock = world.row.updated_at
    original = SimulatedAccountEvidencePipeline.record_update

    def drift(self, mutation, account):
        result = original(self, mutation, account)
        SimulatedAccountModel.objects.filter(pk=world.row.pk).update(updated_at=timezone.now())
        return result

    monkeypatch.setattr(SimulatedAccountEvidencePipeline, "record_update", drift)
    with pytest.raises(CurrentAccountOwnershipUnavailable, match="physical owner row changed"):
        refresh_owner_simulated_account_evidence(
            authenticated_request(world.user), account_id=world.row.pk
        )
    world.row.refresh_from_db()
    assert world.row.updated_at == before_clock and _counts() == before


def test_actual_foreign_owner_cannot_refresh_any_head(refresh_owner):
    foreign = User.objects.create_user(username=f"refresh-foreign-{uuid4().hex}", is_active=True)
    AccountProfileModel.objects.update_or_create(
        user=foreign,
        defaults={"display_name": "Foreign", "rbac_role": "owner", "approval_status": "pending"},
    )
    before = _counts()
    with pytest.raises(AuthorizationError):
        refresh_owner_simulated_account_evidence(
            authenticated_request(foreign), account_id=refresh_owner.row.pk
        )
    assert _counts() == before
