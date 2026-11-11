"""Real non-staff Session, policy, physical lock and grant transaction contracts."""

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import OperationalError, connection, connections, transaction
from django.middleware.csrf import get_token
from django.test import Client
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.account import simulated_corporate_action_policy_scope_composition as policies
from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.application.simulated_corporate_action_write_issuance import (
    SimulatedCorporateActionGrantConsent,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantBinding,
    SimulatedCorporateActionWriteGrantCurrent,
    SimulatedCorporateActionWriteGrantRecord,
)
from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.account.infrastructure.simulated_corporate_action_write_grant_models import (
    SimulatedCorporateActionWriteGrantModel,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_repository import (
    DjangoSimulatedCorporateActionWriteGrantRepository,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_seal import (
    SimulatedCorporateActionWriteGrantSeal,
)
from apps.account.simulated_corporate_action_write_issuance_composition import (
    issue_authenticated_simulated_corporate_action_grant,
    revoke_authenticated_simulated_corporate_action_grant,
)
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    PersistedSimulatedAccountRowSourceV2,
)
from apps.simulated_trading.corporate_action_write_scope_composition import (
    DjangoSimulatedCorporateActionWriteScopeLocker,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Repository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from core.exceptions import AuthenticationError, AuthorizationError
from core.integration.config_center_runtime import get_active_runtime_value_evidence
from shared.config.secrets import get_secrets
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.runtime_config import configure_critical_runtime

pytestmark = pytest.mark.django_db


def _request(user: User, *, csrf: bool = True) -> Request:
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    raw = APIRequestFactory(enforce_csrf_checks=True).post("/simulated-service-consent", {})
    token = get_token(raw)
    raw.COOKIES["csrftoken"] = raw.META["CSRF_COOKIE"]
    if csrf:
        raw.META["HTTP_X_CSRFTOKEN"] = token
    raw.session = SessionStore(session_key=client.session.session_key)
    AuthenticationMiddleware(lambda request: None).process_request(raw)
    return Request(
        raw,
        authenticators=[SessionAuthentication()],
        parsers=[JSONParser(), FormParser(), MultiPartParser()],
    )


@pytest.fixture
def owner_world(monkeypatch: pytest.MonkeyPatch):
    if connection.vendor != "postgresql":
        pytest.skip("native PostgreSQL credential and physical transaction required")
    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"t" * 32).decode())
    get_secrets.cache_clear()
    configure_critical_runtime()
    User.objects.create_user(username="consent-bootstrap-admin", is_staff=True, is_superuser=True)
    user = User.objects.create_user(
        username="simulated-consent-owner", is_staff=False, is_active=True
    )
    user.refresh_from_db()
    assert not user.is_staff and not user.is_superuser
    AccountProfileModel.objects.get_or_create(user=user, defaults={"display_name": "Owner"})
    row = SimulatedAccountModel.objects.create(
        user=user,
        account_name="Issuer test",
        account_type="simulated",
        is_active=True,
        initial_capital=Decimal("10000"),
        current_cash=Decimal("10000"),
        total_value=Decimal("10000"),
        cash_known=True,
        cash_reconciliation_status="simulated_ledger",
    )
    now = timezone.now()
    end = now + timedelta(hours=1)
    raw = SimulatedAccountRawObservation(
        observation_id="consent-physical",
        observation_version="1",
        row_pk=row.pk,
        row_user_id=user.pk,
        raw_account_type="simulated",
        is_active=True,
        row_created_at=row.created_at,
        row_updated_at=row.updated_at,
        is_present=True,
        is_tombstone=False,
        observed_at=now,
        valid_until=end,
    )
    source = SimulatedAccountRowSourceV2(
        source_id=raw.observation_id,
        source_version=raw.observation_version,
        account_namespace="account",
        account_id="canonical-consent-account",
        underlying_unified_account_namespace="simulated-account-row",
        underlying_unified_account_id=row.pk,
        row_user_id=user.pk,
        raw_account_type="simulated",
        is_active=True,
        row_created_at=row.created_at,
        row_updated_at=row.updated_at,
        is_present=True,
        is_tombstone=False,
        observed_at=now,
        recorded_at=now,
        source_valid_until=end,
        ttl_valid_until=end,
        valid_until=end,
        raw_observation_id=raw.observation_id,
        raw_observation_version=raw.observation_version,
        raw_observation_identity_hash=raw.identity_hash,
        raw_observation_content_hash=raw.content_hash,
        raw_observation_observed_at=raw.observed_at,
        raw_observation_valid_until=raw.valid_until,
    )
    repository = DjangoSimulatedAccountRowSourceV2Repository()
    with repository.atomic():
        repository.append(
            PersistedSimulatedAccountRowSourceV2(source),
            expected_predecessor_hash=None,
            recorded_at=now,
        )
    item = {
        "policy_id": "consent-policy",
        "policy_version": "1",
        "canonical_account_id": source.account_id,
        "owner_user_id": user.pk,
        "tenant_id": "consent-tenant",
        "owner_id": "consent-owner",
        "valid_from": (now - timedelta(minutes=1)).isoformat(),
        "valid_until": end.isoformat(),
        "maximum_grant_seconds": 600,
        "permission": "simulated_corporate_action_stage_write",
        "service_actor_id": "simulated-trading",
    }
    activate_runtime_profile_patch(
        environment="development",
        patch={
            policies.SIMULATED_ACTION_WRITE_POLICY_KEY: {
                "schema_version": "simulated-corporate-action-write-policies.v1",
                "enabled": True,
                "policies": [item],
            }
        },
        actor="test-owner-consent",
        reason="explicit isolated owner service scope",
    )
    evidence = get_active_runtime_value_evidence(
        environment="development",
        definition_key=policies.SIMULATED_ACTION_WRITE_POLICY_KEY,
        as_of=timezone.now(),
    )
    assert evidence is not None
    fingerprint = policies._hash(
        {
            "policy": item,
            "profile_id": evidence.profile_id,
            "profile_version": evidence.profile_version,
            "profile_hash": evidence.profile_content_hash,
            "snapshot_id": evidence.snapshot_id,
            "snapshot_hash": evidence.snapshot_hash,
            "effective_at": evidence.effective_at.isoformat(),
        }
    )
    binding = SimulatedCorporateActionWriteGrantBinding(
        account_namespace="simulated",
        account_id=source.account_id,
        owner_user_id=user.pk,
        tenant_id=item["tenant_id"],
        owner_id=item["owner_id"],
        account_source_id=source.source_id,
        account_source_version=source.source_version,
        account_source_content_hash=source.content_hash,
        policy_id=item["policy_id"],
        policy_version=item["policy_version"],
        policy_content_hash=fingerprint,
    )
    command = SimulatedCorporateActionGrantConsent(
        grant_id="native-owner-consent",
        grant_version="1",
        physical_account_id=row.pk,
        expected_binding=binding,
        valid_until=timezone.now() + timedelta(minutes=2),
        consent=True,
    )
    locker = DjangoSimulatedCorporateActionWriteScopeLocker(
        database_alias="default", runtime_environment="development"
    )
    yield SimpleNamespace(user=user, row=row, command=command, locker=locker, source=source)
    get_secrets.cache_clear()


def test_native_nonstaff_owner_consent_is_sealed_and_exact_retry_is_idempotent(owner_world):
    world = owner_world
    assert not world.user.is_staff
    request = _request(world.user)
    result = issue_authenticated_simulated_corporate_action_grant(
        request, command=world.command, scope_locker=world.locker, using="default"
    )
    assert SimulatedCorporateActionWriteGrantSeal().verify(result)
    assert result.binding.owner_user_id == world.user.pk
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 1
    assert (
        issue_authenticated_simulated_corporate_action_grant(
            request, command=world.command, scope_locker=world.locker, using="default"
        )
        == result
    )
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 1


def test_native_missing_csrf_cannot_append_owner_grant(owner_world):
    with pytest.raises(PermissionDenied):
        issue_authenticated_simulated_corporate_action_grant(
            _request(owner_world.user, csrf=False),
            command=owner_world.command,
            scope_locker=owner_world.locker,
            using="default",
        )
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 0


def test_native_other_authenticated_user_cannot_consent_for_account(owner_world):
    other = User.objects.create_user(username="other-consent-owner", is_active=True, is_staff=False)
    AccountProfileModel.objects.get_or_create(user=other, defaults={"display_name": "Other"})
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        issue_authenticated_simulated_corporate_action_grant(
            _request(other),
            command=owner_world.command,
            scope_locker=owner_world.locker,
            using="default",
        )
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 0


@pytest.mark.parametrize("mutation", ["session", "user", "role"])
def test_native_credential_revocation_before_commit_rolls_grant_back(owner_world, mutation):
    request = _request(owner_world.user)
    actual = owner_world.locker

    class RevokeBeforeCommit:
        database_alias = "default"

        @contextmanager
        def lock_owned_scope(self, **kwargs):
            with actual.lock_owned_scope(**kwargs) as scope:
                yield scope
                if mutation == "session":
                    Session.objects.filter(
                        session_key=request._request.session.session_key
                    ).delete()
                elif mutation == "user":
                    User.objects.filter(pk=owner_world.user.pk).update(is_active=False)
                else:
                    AccountProfileModel.objects.filter(user_id=owner_world.user.pk).update(
                        rbac_role="read_only"
                    )

    with pytest.raises((AuthenticationError, AuthorizationError)):
        issue_authenticated_simulated_corporate_action_grant(
            request, command=owner_world.command, scope_locker=RevokeBeforeCommit(), using="default"
        )
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 0
    assert Session.objects.filter(session_key=request._request.session.session_key).exists()
    owner_world.user.refresh_from_db()
    assert owner_world.user.is_active


def test_native_read_only_owner_cannot_issue_service_write_grant(owner_world):
    AccountProfileModel.objects.filter(user_id=owner_world.user.pk).update(rbac_role="read_only")
    with pytest.raises(AuthorizationError):
        issue_authenticated_simulated_corporate_action_grant(
            _request(owner_world.user),
            command=owner_world.command,
            scope_locker=owner_world.locker,
            using="default",
        )
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 0


def test_native_policy_or_source_change_cannot_be_signed_as_original_scope(owner_world):
    command = replace(
        owner_world.command,
        expected_binding=replace(
            owner_world.command.expected_binding, account_source_content_hash="f" * 64
        ),
    )
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        issue_authenticated_simulated_corporate_action_grant(
            _request(owner_world.user),
            command=command,
            scope_locker=owner_world.locker,
            using="default",
        )
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 0


def test_native_read_only_owner_can_withdraw_after_policy_is_disabled(owner_world):
    world = owner_world
    request = _request(world.user)
    grant = issue_authenticated_simulated_corporate_action_grant(
        request, command=world.command, scope_locker=world.locker, using="default"
    )
    AccountProfileModel.objects.filter(user_id=world.user.pk).update(rbac_role="read_only")
    activate_runtime_profile_patch(
        environment="development",
        patch={
            policies.SIMULATED_ACTION_WRITE_POLICY_KEY: {
                "schema_version": "simulated-corporate-action-write-policies.v1",
                "enabled": False,
                "policies": [],
            }
        },
        actor="test-owner-consent",
        reason="disable new service writes without preventing withdrawal",
    )
    result = revoke_authenticated_simulated_corporate_action_grant(
        request,
        selector=grant.selector,
        revocation_id="native-withdrawal",
        revocation_version="1",
        using="default",
    )
    assert SimulatedCorporateActionWriteGrantSeal().verify_revocation(result)
    assert (
        revoke_authenticated_simulated_corporate_action_grant(
            request,
            selector=grant.selector,
            revocation_id="native-withdrawal",
            revocation_version="1",
            using="default",
        )
        == result
    )
    repository = DjangoSimulatedCorporateActionWriteGrantRepository()
    assert repository.get_current_grant(selector=grant.selector, as_of=timezone.now()) is None
    historical = repository.get_exact_record(selector=grant.selector, as_of=timezone.now())
    assert type(historical) is SimulatedCorporateActionWriteGrantRecord
    assert not isinstance(historical, SimulatedCorporateActionWriteGrantCurrent)
    assert historical.revocation == result


def test_native_final_grant_expiry_check_runs_after_credential_revalidation(
    owner_world, monkeypatch
):
    from apps.account import simulated_corporate_action_write_issuance_composition as issuer

    actual_now = timezone.now()
    ticks = iter((actual_now, actual_now, owner_world.command.valid_until))
    monkeypatch.setattr(issuer, "timezone", SimpleNamespace(now=lambda: next(ticks)))
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        issue_authenticated_simulated_corporate_action_grant(
            _request(owner_world.user),
            command=owner_world.command,
            scope_locker=owner_world.locker,
            using="default",
        )
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 0


def test_native_get_method_cannot_issue_consent_through_csrf_safe_method(owner_world):
    request = _request(owner_world.user)
    request._request.method = "GET"
    with pytest.raises(AuthorizationError):
        issue_authenticated_simulated_corporate_action_grant(
            request, command=owner_world.command, scope_locker=owner_world.locker, using="default"
        )
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_native_issuer_holds_credential_and_owner_locks_until_commit(owner_world):
    """A second connection cannot revoke locked identity or transfer the account mid-issue."""
    world = owner_world
    request = _request(world.user)
    actual = world.locker
    attempts = {}

    def mutate_from_second_connection(target):
        connections.close_all()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '300ms'")
                if target == "session":
                    Session.objects.filter(session_key=request._request.session.session_key).update(
                        expire_date=timezone.now()
                    )
                elif target == "user":
                    User.objects.filter(pk=world.user.pk).update(is_active=False)
                elif target == "role":
                    AccountProfileModel.objects.filter(user_id=world.user.pk).update(
                        rbac_role="read_only"
                    )
                else:
                    SimulatedAccountModel.objects.filter(pk=world.row.pk).update(is_active=False)
        except OperationalError as error:
            return error.__cause__.sqlstate
        finally:
            connections.close_all()
        raise AssertionError("concurrent mutation unexpectedly bypassed the owner transaction")

    class ProbeHeldLocks:
        database_alias = "default"

        def __init__(self, target):
            self.target = target

        @contextmanager
        def lock_owned_scope(self, **kwargs):
            with actual.lock_owned_scope(**kwargs) as scope:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    attempts[self.target] = executor.submit(
                        mutate_from_second_connection, self.target
                    ).result(timeout=10)
                yield scope

    for target in ("session", "user", "role", "physical_account"):
        grant = issue_authenticated_simulated_corporate_action_grant(
            request, command=world.command, scope_locker=ProbeHeldLocks(target), using="default"
        )
        assert SimulatedCorporateActionWriteGrantSeal().verify(grant)
    assert attempts == dict.fromkeys(("session", "user", "role", "physical_account"), "55P03")
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 1
    world.user.refresh_from_db()
    world.row.refresh_from_db()
    assert world.user.is_active and world.row.is_active


def test_native_owner_consent_http_prepare_confirm_retry_and_readonly_withdraw(
    owner_world, settings
):
    """The real Session/CSRF API completes explicit consent and exact withdrawal without posting."""
    from apps.account.infrastructure.simulated_corporate_action_write_grant_models import (
        SimulatedCorporateActionWriteGrantRevocationModel,
    )
    from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
        CorporateActionPostingModel,
    )

    settings.ROOT_URLCONF = "tests.support.ash07_owner_source_test_urls"
    world = owner_world
    client = Client(enforce_csrf_checks=True)
    client.force_login(world.user)
    bootstrap = client.get("/csrf/bootstrap/", secure=True, HTTP_ORIGIN="https://testserver")
    csrf = bootstrap.json()["csrf_token"]
    path = f"/api/simulated-trading/accounts/{world.row.pk}/corporate-action-consent/"
    headers = {"secure": True, "HTTP_ORIGIN": "https://testserver", "HTTP_X_CSRFTOKEN": csrf}
    before_ledger = CorporateActionPostingModel.objects.count()
    preview = client.get(path, **headers)
    assert preview.status_code == 200
    assert preview.headers["Content-Type"].startswith("application/json")
    terms = preview.json()
    assert terms["consent_status"] == "awaiting_confirmation"
    assert terms["source_observed_at"] == world.source.observed_at.isoformat()
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 0
    prepared = client.post(path + "prepare/", {}, content_type="application/json", **headers)
    assert prepared.status_code == 200, prepared.content
    assert prepared.headers["Content-Type"].startswith("application/json")
    assert prepared.json()["consent_token"] is None
    assert prepared.json()["withdrawal_token"] is None
    continuation = prepared.json()["continuation"]
    assert continuation["action_key"] == "simulated-trading.corporate-action-consent-confirm"
    body = {"consent_token": continuation["input"]["consent_token"], "confirmed": True}
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 0
    denied = client.post(path, body, content_type="application/json", secure=True)
    assert denied.status_code == 403
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 0
    accepted = client.post(path, body, content_type="application/json", **headers)
    assert accepted.status_code == 200, accepted.content
    assert accepted.headers["Content-Type"].startswith("application/json")
    repeated = client.post(path, body, content_type="application/json", **headers)
    assert repeated.status_code == 200, repeated.content
    assert accepted.json()["grant_content_hash"] == repeated.json()["grant_content_hash"]
    assert SimulatedCorporateActionWriteGrantModel.objects.count() == 1
    AccountProfileModel.objects.filter(user_id=world.user.pk).update(rbac_role="read_only")
    activate_runtime_profile_patch(
        environment="development",
        patch={
            policies.SIMULATED_ACTION_WRITE_POLICY_KEY: {
                "schema_version": "simulated-corporate-action-write-policies.v1",
                "enabled": False,
                "policies": [],
            }
        },
        actor="native-consent-http",
        reason="withdrawal must remain available",
    )
    active = client.get(path, **headers)
    assert active.status_code == 200
    assert active.json()["outcome"] == "blocked"
    assert active.json()["withdrawal_token"]
    removal = client.post(
        path + "withdraw/prepare/", {}, content_type="application/json", **headers
    )
    assert removal.status_code == 200, removal.content
    assert removal.headers["Content-Type"].startswith("application/json")
    assert removal.json()["outcome"] == "success"
    assert removal.json()["withdrawal_token"] is None
    assert (
        removal.json()["continuation"]["action_key"]
        == "simulated-trading.corporate-action-consent-withdraw"
    )
    withdrawal_body = {
        "withdrawal_token": removal.json()["continuation"]["input"]["withdrawal_token"],
        "confirmed": True,
    }
    withdrawn = client.post(
        path + "withdraw/", withdrawal_body, content_type="application/json", **headers
    )
    assert withdrawn.status_code == 200, withdrawn.content
    assert withdrawn.headers["Content-Type"].startswith("application/json")
    assert withdrawn.json()["consent_status"] == "revoked"
    assert (
        client.post(
            path + "withdraw/", withdrawal_body, content_type="application/json", **headers
        ).status_code
        == 200
    )
    assert SimulatedCorporateActionWriteGrantRevocationModel.objects.count() == 1
    assert CorporateActionPostingModel.objects.count() == before_ledger


def test_native_expired_grant_source_and_policy_can_still_prepare_exact_owner_withdrawal(
    owner_world, settings, monkeypatch
):
    """Historical withdrawal keeps its original expiry while the UI uses the live session deadline."""
    from apps.account import simulated_corporate_action_write_issuance_composition as issuer
    from apps.simulated_trading import corporate_action_consent_composition as consent_service
    from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
        DjangoSimulatedAccountRowSourceV2Clock,
    )

    settings.ROOT_URLCONF = "tests.support.ash07_owner_source_test_urls"
    world = owner_world
    client = Client(enforce_csrf_checks=True)
    client.force_login(world.user)
    csrf = client.get("/csrf/bootstrap/", secure=True, HTTP_ORIGIN="https://testserver").json()[
        "csrf_token"
    ]
    headers = {"secure": True, "HTTP_ORIGIN": "https://testserver", "HTTP_X_CSRFTOKEN": csrf}
    path = f"/api/simulated-trading/accounts/{world.row.pk}/corporate-action-consent/"
    prepared = client.post(path + "prepare/", {}, content_type="application/json", **headers)
    assert prepared.status_code == 200, prepared.content
    body = {
        "consent_token": prepared.json()["continuation"]["input"]["consent_token"],
        "confirmed": True,
    }
    issued = client.post(path, body, content_type="application/json", **headers)
    assert issued.status_code == 200, issued.content
    original_expiry = issued.json()["consent_valid_until"]
    AccountProfileModel.objects.filter(user_id=world.user.pk).update(rbac_role="read_only")
    activate_runtime_profile_patch(
        environment="development",
        patch={
            policies.SIMULATED_ACTION_WRITE_POLICY_KEY: {
                "schema_version": "simulated-corporate-action-write-policies.v1",
                "enabled": False,
                "policies": [],
            }
        },
        actor="native-expired-withdrawal",
        reason="historical withdrawal cannot need old policy",
    )
    # Advance only the owned clock ports, never global Django time or source timestamps.
    expired = world.source.valid_until + timedelta(seconds=1)
    monkeypatch.setattr(consent_service, "timezone", SimpleNamespace(now=lambda: expired))
    monkeypatch.setattr(issuer, "timezone", SimpleNamespace(now=lambda: expired))
    monkeypatch.setattr(DjangoSimulatedAccountRowSourceV2Clock, "now", lambda self: expired)
    removal = client.post(
        path + "withdraw/prepare/", {}, content_type="application/json", **headers
    )
    assert removal.status_code == 200, removal.content
    payload = removal.json()
    assert payload["outcome"] == "success" and payload["consent_status"] == "expired"
    assert payload["consent_valid_until"] == original_expiry
    assert payload["source_observed_at"] == world.source.observed_at.isoformat()
    expiry = datetime.fromisoformat(payload["continuation"]["expires_at"].replace("Z", "+00:00"))
    assert expiry > expired
    repository = DjangoSimulatedCorporateActionWriteGrantRepository()
    original = repository.get_scope_records("simulated", world.source.account_id, as_of=expired)[0]
    assert type(original) is SimulatedCorporateActionWriteGrantRecord
    assert repository.get_current_grant(selector=original.grant.selector, as_of=expired) is None
    result = client.post(
        path + "withdraw/",
        {
            "withdrawal_token": payload["continuation"]["input"]["withdrawal_token"],
            "confirmed": True,
        },
        content_type="application/json",
        **headers,
    )
    assert result.status_code == 200, result.content
    assert result.json()["consent_status"] == "revoked"
    stored = repository.get_exact_record(selector=original.grant.selector, as_of=expired)
    assert stored is not None and stored.revocation is not None


def test_native_rotated_issuer_key_does_not_prevent_owner_withdrawal_or_restore_permission(
    owner_world, settings, monkeypatch
):
    """A current real owner can withdraw old-key metadata, and restoring that key cannot undo it."""
    settings.ROOT_URLCONF = "tests.support.ash07_owner_source_test_urls"
    world = owner_world
    grant = issue_authenticated_simulated_corporate_action_grant(
        _request(world.user), command=world.command, scope_locker=world.locker, using="default"
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(world.user)
    csrf = client.get("/csrf/bootstrap/", secure=True, HTTP_ORIGIN="https://testserver").json()[
        "csrf_token"
    ]
    headers = {"secure": True, "HTTP_ORIGIN": "https://testserver", "HTTP_X_CSRFTOKEN": csrf}
    path = f"/api/simulated-trading/accounts/{world.row.pk}/corporate-action-consent/"
    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"u" * 32).decode())
    get_secrets.cache_clear()
    assert not SimulatedCorporateActionWriteGrantSeal().verify(grant)
    AccountProfileModel.objects.filter(user_id=world.user.pk).update(rbac_role="read_only")
    prepared = client.post(
        path + "withdraw/prepare/", {}, content_type="application/json", **headers
    )
    assert prepared.status_code == 200, prepared.content
    assert prepared.json()["outcome"] == "success"
    result = client.post(
        path + "withdraw/",
        {
            "withdrawal_token": prepared.json()["continuation"]["input"]["withdrawal_token"],
            "confirmed": True,
        },
        content_type="application/json",
        **headers,
    )
    assert result.status_code == 200, result.content
    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"t" * 32).decode())
    get_secrets.cache_clear()
    assert SimulatedCorporateActionWriteGrantSeal().verify(grant)
    assert (
        DjangoSimulatedCorporateActionWriteGrantRepository().get_current_grant(
            selector=grant.selector, as_of=timezone.now()
        )
        is None
    )
