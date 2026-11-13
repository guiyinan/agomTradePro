"""Public nonstaff owner setup for the simulated tax native acceptance test."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.models import User
from django.db import connection
from django.test import override_settings
from rest_framework.test import APIClient

from apps.account.application.canonical_account_creation_binding_v2 import (
    GetExactCanonicalAccountCreationBindingV2Command,
)
from apps.account.application.creation_evidence_settings import (
    CanonicalAccountCreationEvidenceSettings,
)
from apps.account.canonical_creation_composition import build_canonical_account_creation_stages
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
)
from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.simulated_trading.account_physical_row_v2_composition import (
    build_account_physical_row_v2_provider,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from core.integration.account_creation_evidence_runtime import (
    get_active_account_creation_evidence_settings,
)
from tests.support.ash07_owner_account_authority import OwnerAccountSeed
from tests.support.native_postgres_database import assert_native_postgres_test_database


def create_public_nonstaff_tax_owner_seed(*, as_of: datetime) -> OwnerAccountSeed:
    """Create a real ordinary user and account through Session/CSRF public APIs.

    The caller supplies the historical creation clock while the database test
    runs. The exact canonical creation binding is then reopened at that same
    cutoff; this helper does not construct an ownership anchor or source row.
    """

    if connection.vendor != "postgresql":
        raise RuntimeError("native simulated tax owner creation requires PostgreSQL")
    assert_native_postgres_test_database()
    if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("owner creation requires the explicit aware operation clock")
    environment = "development"
    settings_value = get_active_account_creation_evidence_settings(environment)
    if type(settings_value) is not CanonicalAccountCreationEvidenceSettings:
        raise RuntimeError("canonical Account creation evidence is unavailable")

    suffix = uuid4().hex
    owner = User(
        username=f"ash05-tax-owner-{suffix}",
        is_active=True,
        is_staff=False,
        is_superuser=False,
    )
    owner.set_password(uuid4().hex)
    owner.save(using="default")
    AccountProfileModel.objects.using("default").update_or_create(
        user=owner,
        defaults={
            "display_name": f"ASH-05 ordinary tax owner {owner.pk}",
            "rbac_role": "owner",
            "approval_status": "pending",
        },
    )

    client = APIClient(enforce_csrf_checks=True)
    with override_settings(ROOT_URLCONF="tests.support.ash07_owner_source_test_urls"):
        csrf_response = client.get(
            "/csrf/bootstrap/",
            secure=True,
            HTTP_ORIGIN="https://testserver",
        )
    if csrf_response.status_code != 200:
        raise RuntimeError("Session/CSRF bootstrap failed for the nonstaff owner")
    csrf_payload = cast(dict[str, object], csrf_response.json())
    csrf_token = csrf_payload.get("csrf_token")
    csrf_cookie = client.cookies.get(settings.CSRF_COOKIE_NAME)
    if type(csrf_token) is not str or not csrf_token or csrf_cookie is None:
        raise RuntimeError("nonstaff owner session lacks its exact CSRF binding")
    client.force_login(owner)
    response = client.post(
        "/api/simulated-trading/accounts/",
        {
            "account_name": f"ASH-05 simulated tax {suffix[:12]}",
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
        HTTP_X_CSRFTOKEN=csrf_token,
        HTTP_IDEMPOTENCY_KEY=f"ash05-tax-account-{suffix}",
    )
    if response.status_code != 201:
        raise RuntimeError(f"public nonstaff Account creation failed: {response.content!r}")
    account_id = response.json()["account"]["account_id"]
    if type(account_id) is not int:
        raise RuntimeError("public Account receipt omitted its exact integer ID")
    account = SimulatedAccountModel.objects.using("default").get(pk=account_id)
    owner.refresh_from_db(using="default")
    if (
        account.user_id != owner.pk
        or account.account_type != "simulated"
        or owner.is_staff
        or owner.is_superuser
        or owner.is_active is not True
    ):
        raise RuntimeError("public-created simulated account is not bound to an ordinary owner")

    binding_row = CanonicalAccountCreationBindingV2Model.objects.using("default").get(
        consumption_claim__consumer_generation="v2",
        underlying_unified_account_id_claim=account.pk,
    )
    requester = CanonicalAccountCreationRequester(
        actor_id=f"django-user:{owner.pk}",
        user_id=owner.pk,
    )
    binding = build_canonical_account_creation_stages(
        using="default",
        settings=settings_value,
        requester=requester,
        physical_row_provider=build_account_physical_row_v2_provider(using="default"),
    ).get_exact_binding.execute(
        GetExactCanonicalAccountCreationBindingV2Command(
            binding_id=binding_row.binding_id,
            binding_version=binding_row.binding_version,
            expected_content_hash=binding_row.content_hash,
            as_of=as_of.astimezone(UTC),
        )
    )
    if (
        type(binding) is not CanonicalAccountCreationBindingV2
        or binding.allocation.requested_row_user_id != owner.pk
        or binding.underlying_unified_account_id_claim != account.pk
    ):
        raise RuntimeError("actual canonical Account creation binding is unavailable")
    return OwnerAccountSeed(
        owner=owner,
        client=client,
        csrf_token=csrf_token,
        account=account,
        binding=binding,
        environment=environment,
    )
