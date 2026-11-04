"""Isolated real-Account owner and SystemAudit authority setup for ASH-07 tests."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.models import User
from django.db import connection, transaction
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.account.account_owner_assignment_evidence_v5_composition import (
    build_account_owner_assignment_evidence_v5_facade,
)
from apps.account.application.account_actor_authority_raw_source_publisher_v3 import (
    AccountActorAuthorityRawSourcePublicationReceiptV3,
    AccountActorAuthorityRawSourceSelectorV3,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
    ApproveAccountOwnerAssignmentEvidenceV5Command,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    IssueAccountOwnerAssignmentProvenanceReceiptV5,
    IssueAccountOwnerAssignmentProvenanceReceiptV5Command,
)
from apps.account.application.account_owner_assignment_subject_v5 import (
    RegisterAccountOwnerAssignmentSubjectV5,
    RegisterAccountOwnerAssignmentSubjectV5Command,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    GetExactCanonicalAccountCreationBindingV2Command,
)
from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    RecordCanonicalAccountOwnershipReobservationV1,
    RecordCanonicalAccountOwnershipReobservationV1Command,
)
from apps.account.application.creation_evidence_settings import (
    CanonicalAccountCreationEvidenceSettings,
)
from apps.account.application.owner_tenant_authority_v3 import (
    IssueOwnerTenantAuthorityV3Command,
)
from apps.account.application.physical_account_row_observation_v2 import (
    CapturePhysicalAccountRowObservationV2Command,
)
from apps.account.canonical_creation_composition import build_canonical_account_creation_stages
from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v5 import (
    AccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.domain.account_owner_assignment_subject_v5 import (
    AccountOwnerAssignmentSubjectV5,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_repository import (
    DjangoAccountOwnerAssignmentSubjectV5Repository,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_repository import (
    DjangoCanonicalAccountOwnershipReobservationV1Repository,
)
from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.account.owner_tenant_authority_v3_composition import (
    build_owner_tenant_authority_v3_facade,
)
from apps.account.single_owner_authority_policy_composition import (
    build_current_single_owner_participants_provider,
    build_current_single_owner_policy_resolver,
)
from apps.audit.application.system_audit_authority_provider import (
    SystemAuditAuthorityBundleSelector,
)
from apps.audit.application.system_audit_authority_schema import (
    SYSTEM_AUDIT_SCOPE_SCHEMA_V3,
)
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.simulated_trading.account_physical_row_v2_composition import (
    build_account_physical_row_v2_provider,
)
from apps.simulated_trading.account_reobservation_composition import (
    build_existing_account_reobserver,
)
from apps.simulated_trading.application.account_row_reobservation import (
    ReobserveExistingAccountRowCommand,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    CaptureSimulatedAccountRowSourceV2Command,
)
from apps.simulated_trading.creation_composition import (
    build_simulated_account_creation_stages,
)
from apps.simulated_trading.domain.entities import AccountType
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from core.integration.account_creation_evidence_runtime import (
    get_active_account_creation_evidence_settings,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

_ACCOUNT_CREATE_PATH = "/api/simulated-trading/accounts/"
ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS = (
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "apps.account",
    "apps.audit",
    "apps.config_center",
    "apps.data_center",
    "apps.prompt",
    "apps.risk_center",
    "apps.simulated_trading",
    "apps.strategy",
    "apps.terminal",
)


@dataclass(frozen=True, slots=True)
class OwnerAccountSeed:
    """Carry one real test owner, public session, Account row, and Binding V2."""

    owner: User
    client: APIClient
    csrf_token: str
    account: SimulatedAccountModel
    binding: CanonicalAccountCreationBindingV2
    environment: str


def create_owner_account_seed() -> OwnerAccountSeed:
    """Create a dedicated Auth/Profile user and simulated Account through public APIs."""

    if connection.vendor != "postgresql":
        raise RuntimeError("ASH-07 owner acceptance requires the isolated native PostgreSQL DB")
    assert_native_postgres_test_database()
    environment = _runtime_environment()
    settings_value = get_active_account_creation_evidence_settings(environment)
    if type(settings_value) is not CanonicalAccountCreationEvidenceSettings:
        raise RuntimeError("canonical Account creation settings are not active")

    suffix = uuid4().hex
    owner = User(
        username=f"ash07-owner-{suffix}",
        is_active=True,
        is_staff=True,
        is_superuser=False,
    )
    owner.set_password(uuid4().hex)
    owner.save(using="default")
    AccountProfileModel.objects.using("default").update_or_create(
        user=owner,
        defaults={
            "display_name": f"ASH-07 owner {owner.pk}",
            "rbac_role": "admin",
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
        raise RuntimeError("Django Session/CSRF bootstrap is unavailable")
    csrf_payload = cast(dict[str, object], csrf_response.json())
    csrf_value = csrf_payload.get("csrf_token")
    csrf_cookie = client.cookies.get(settings.CSRF_COOKIE_NAME)
    if (
        type(csrf_value) is not str
        or not csrf_value
        or csrf_cookie is None
        or not csrf_cookie.value
    ):
        raise RuntimeError("Django CSRF token or cookie is missing")
    # get_token returns a masked token; the cookie contains its unmasked secret.
    # The ensuing public POST verifies their binding through SessionAuthentication.
    csrf_token = csrf_value
    client.force_login(owner)
    account_response = client.post(
        _ACCOUNT_CREATE_PATH,
        {
            "account_name": f"ASH-07 public owner account {suffix[:12]}",
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
        HTTP_IDEMPOTENCY_KEY=f"ash07-owner-account-{suffix}",
    )
    if account_response.status_code != 201:
        raise RuntimeError("public canonical Account creation failed")
    account_id_value = account_response.json()["account"]["account_id"]
    if type(account_id_value) is not int:
        raise RuntimeError("public Account response omitted its exact integer identity")
    account = SimulatedAccountModel.objects.using("default").get(pk=account_id_value)
    if account.user_id != owner.pk or account.account_type != "simulated":
        raise RuntimeError("public Account row is not bound to the test owner")

    binding_row = CanonicalAccountCreationBindingV2Model.objects.using("default").get(
        consumption_claim__consumer_generation="v2",
        underlying_unified_account_id_claim=account.pk,
    )
    requester = CanonicalAccountCreationRequester(
        actor_id=f"django-user:{owner.pk}",
        user_id=owner.pk,
    )
    creation_stages = build_canonical_account_creation_stages(
        using="default",
        settings=settings_value,
        requester=requester,
        physical_row_provider=build_account_physical_row_v2_provider(using="default"),
    )
    binding = creation_stages.get_exact_binding.execute(
        GetExactCanonicalAccountCreationBindingV2Command(
            binding_id=binding_row.binding_id,
            binding_version=binding_row.binding_version,
            expected_content_hash=binding_row.content_hash,
            as_of=datetime.now(UTC),
        )
    )
    if (
        binding is None
        or binding.allocation.requested_row_user_id != owner.pk
        or binding.underlying_unified_account_id_claim != account.pk
    ):
        raise RuntimeError("public Account creation Binding V2 is unavailable or foreign")
    return OwnerAccountSeed(owner, client, csrf_token, account, binding, environment)


def owner_policy_runtime_patch(seed: OwnerAccountSeed) -> dict[str, object]:
    """Build the exact declaration/settings pair for public policy publication."""

    now_text = datetime.now(UTC).isoformat()
    source_id = f"ash07-owner-declaration-{seed.owner.pk}-{seed.account.pk}"
    source_version = "v1"
    declaration = {
        "schema": "sprint-owner-account-authorization.v1",
        "recorded_at": now_text,
        "source": {
            "kind": "interactive_user_declaration",
            "account_binding_answer": "The named test owner controls this isolated simulated account.",
        },
        "owner_account": {
            "username": seed.owner.username,
            "user_id": seed.owner.pk,
            "role": "project_owner_and_human_approver",
            "binding_basis": "explicit_user_designation",
        },
    }
    body = json.dumps(
        declaration,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    source_hash = hashlib.sha256(body).hexdigest()
    return {
        "account.single_owner_policy.authorization_source": {
            "schema_version": "account.single_owner_policy.authorization_source.v1",
            "source_id": source_id,
            "source_version": source_version,
            "content_hash": source_hash,
            "document_base64": base64.b64encode(body).decode("ascii"),
        },
        "account.single_owner_policy.publication_settings": {
            "schema_version": "account.single_owner_policy.publication_settings.v1",
            "owner_username": seed.owner.username,
            "tenant_id": f"ash07-test-tenant-{seed.owner.pk}",
            "owner_id": f"ash07-test-owner-{seed.owner.pk}",
            "authorization_source_id": source_id,
            "authorization_source_version": source_version,
            "authorization_content_hash": source_hash,
            "ttl_seconds": 1800,
        },
    }


def publish_current_owner_policy(seed: OwnerAccountSeed) -> dict[str, object]:
    """Activate one owner-bound declaration, then publish through Account's HTTP API."""

    activate_runtime_profile_patch(
        environment=seed.environment,
        patch=owner_policy_runtime_patch(seed),
        actor="ash07-owner-test-setup",
        reason="bind the public single-owner policy to the actual isolated test user",
    )
    response = seed.client.post(
        reverse("api_account:authority-policy-publish"),
        {
            "binding_id": seed.binding.binding_id,
            "binding_version": seed.binding.binding_version,
            "binding_content_hash": seed.binding.content_hash,
        },
        format="json",
        secure=True,
        HTTP_ORIGIN="https://testserver",
        HTTP_X_CSRFTOKEN=seed.csrf_token,
        HTTP_IDEMPOTENCY_KEY=f"ash07-owner-policy-{seed.account.pk}",
    )
    if response.status_code != 200:
        raise RuntimeError("public single-owner policy publication failed")
    payload = response.json()["policy"]
    if type(payload) is not dict:
        raise RuntimeError("public owner policy response is not an object")
    return cast(dict[str, object], payload)


def issue_current_owner_audit_selector(
    seed: OwnerAccountSeed,
) -> SystemAuditAuthorityBundleSelector:
    """Issue current V5/V3 Account evidence from real session and physical-row facts."""

    actor_response = seed.client.post(
        reverse("api_account:authority-raw-publish"),
        {},
        format="json",
        secure=True,
        HTTP_ORIGIN="https://testserver",
        HTTP_X_CSRFTOKEN=seed.csrf_token,
    )
    if actor_response.status_code != 201:
        raise RuntimeError("public authenticated Account authority publication failed")
    actor_receipt = _decode_actor_receipt(actor_response.json()["data"])
    if actor_receipt.user_id != seed.owner.pk:
        raise RuntimeError("published Account actor belongs to another user")
    principal = AuthenticatedAccountPrincipalV3(
        principal_id=actor_receipt.principal_id,
        user_id=actor_receipt.user_id,
        authentication_context_hash=actor_receipt.authentication_context.content_hash,
        authenticated_at=actor_receipt.observed_at,
        valid_until=actor_receipt.valid_until,
    )

    as_of = datetime.now(UTC)
    policy_binding = build_current_single_owner_policy_resolver(using="default").resolve(
        account_namespace=seed.binding.account_namespace_claim,
        account_id=seed.binding.account_id_claim,
        owner_user_id=seed.owner.pk,
        as_of=as_of,
    )
    if policy_binding is None:
        raise RuntimeError("the actual owner policy is not current for this exact binding")
    participants = build_current_single_owner_participants_provider(
        principal=principal,
        policy_binding=policy_binding,
        actor_source_id=actor_receipt.actor.source_id,
        actor_source_version=actor_receipt.actor.source_version,
        actor_source_content_hash=actor_receipt.actor.content_hash,
        using="default",
    ).get_current(as_of=as_of)
    if participants is None or participants.policy.owner_user_id != seed.owner.pk:
        raise RuntimeError("current Account owner and staff participant facts are unavailable")
    policy = participants.policy

    reobservation = _capture_current_reobservation(seed)
    now = datetime.now(UTC)
    valid_until = min(policy.valid_until, reobservation.valid_until, actor_receipt.valid_until)
    if now >= valid_until:
        raise RuntimeError("Account evidence expired before the authority graph was issued")
    suffix = uuid4().hex
    receipt = AccountOwnerAssignmentProvenanceReceiptV5(
        receipt_id=f"ash07-owner-receipt-{suffix}",
        receipt_version="v5.1",
        policy=policy,
        policy_identity_hash=policy.identity_hash,
        policy_content_hash=policy.content_hash,
        binding=seed.binding,
        reobservation=reobservation,
        account_namespace=seed.binding.account_namespace_claim,
        account_id=seed.binding.account_id_claim,
        underlying_unified_account_namespace=(
            seed.binding.underlying_unified_account_namespace_claim
        ),
        underlying_unified_account_id=seed.binding.underlying_unified_account_id_claim,
        allocation_identity_hash=seed.binding.allocation.identity_hash,
        allocation_content_hash=seed.binding.allocation.content_hash,
        binding_identity_hash=seed.binding.identity_hash,
        binding_content_hash=seed.binding.content_hash,
        account_claim_hash=seed.binding.account_claim_hash,
        underlying_claim_hash=seed.binding.underlying_claim_hash,
        reobservation_identity_hash=reobservation.identity_hash,
        reobservation_content_hash=reobservation.content_hash,
        current_physical_observation_content_hash=reobservation.current_physical.content_hash,
        current_physical_source_content_hash=reobservation.current_physical.source_content_hash,
        current_physical_raw_observation_content_hash=(
            reobservation.current_physical.raw_observation_content_hash
        ),
        assigned_owner_user_id=seed.owner.pk,
        claimant=AccountOwnerAssignmentActor(
            actor_id=f"django-user:{seed.owner.pk}",
            user_id=seed.owner.pk,
            role="account_owner_claimant",
            is_staff=seed.owner.is_staff,
        ),
        issued_at=now,
        recorded_at=now,
        valid_until=valid_until,
    )
    receipt = IssueAccountOwnerAssignmentProvenanceReceiptV5(
        DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository(using="default")
    ).execute(IssueAccountOwnerAssignmentProvenanceReceiptV5Command(receipt))
    subject = _subject_for_receipt(receipt, suffix=suffix, requested_at=now)
    subject = RegisterAccountOwnerAssignmentSubjectV5(
        DjangoAccountOwnerAssignmentSubjectV5Repository(using="default")
    ).execute(RegisterAccountOwnerAssignmentSubjectV5Command(subject))

    physical_provider = build_account_physical_row_v2_provider(using="default")
    evidence_facade = build_account_owner_assignment_evidence_v5_facade(
        principal=principal,
        policy_binding=policy_binding,
        actor_source_id=actor_receipt.actor.source_id,
        actor_source_version=actor_receipt.actor.source_version,
        actor_source_content_hash=actor_receipt.actor.content_hash,
        validity_period=timedelta(minutes=10),
        physical_row_provider=physical_provider,
        using="default",
    )
    assignment = evidence_facade.approve(
        ApproveAccountOwnerAssignmentEvidenceV5Command(
            evidence_id=f"ash07-owner-evidence-{suffix}",
            evidence_version="v5.1",
            subject_id=subject.subject_id,
            subject_version=subject.subject_version,
            expected_subject_content_hash=subject.content_hash,
        )
    )
    authority = build_owner_tenant_authority_v3_facade(
        principal=principal,
        policy_binding=policy_binding,
        actor_source_id=actor_receipt.actor.source_id,
        actor_source_version=actor_receipt.actor.source_version,
        actor_source_content_hash=actor_receipt.actor.content_hash,
        validity_period=timedelta(minutes=10),
        physical_row_provider=physical_provider,
        using="default",
    ).issue(
        IssueOwnerTenantAuthorityV3Command(
            authority_id=f"ash07-owner-scope-{suffix}",
            authority_version="v3.1",
            assignment_evidence_id=assignment.evidence_id,
            assignment_evidence_version=assignment.evidence_version,
            expected_assignment_evidence_content_hash=assignment.content_hash,
        )
    )
    return SystemAuditAuthorityBundleSelector(
        actor_source_id=actor_receipt.actor.source_id,
        actor_source_version=actor_receipt.actor.source_version,
        actor_content_hash=actor_receipt.actor.content_hash,
        scope_source_id=authority.authority_id,
        scope_source_version=authority.authority_version,
        scope_content_hash=authority.content_hash,
        scope_schema=SYSTEM_AUDIT_SCOPE_SCHEMA_V3,
    )


def audit_runtime_patch(selector: SystemAuditAuthorityBundleSelector) -> dict[str, object]:
    """Return only the required Audit keys for merging into the final runtime patch."""

    selector.__post_init__()
    return {
        "audit.system_event.mode": "required",
        "audit.system_event.outbox_enabled": True,
        "audit.system_event.authority_selector": {
            "actor_source_id": selector.actor_source_id,
            "actor_source_version": selector.actor_source_version,
            "actor_content_hash": selector.actor_content_hash,
            "scope_source_id": selector.scope_source_id,
            "scope_source_version": selector.scope_source_version,
            "scope_content_hash": selector.scope_content_hash,
            "scope_schema": selector.scope_schema,
        },
    }


def _capture_current_reobservation(
    seed: OwnerAccountSeed,
) -> CanonicalAccountOwnershipReobservationV1:
    """Capture and persist a current V1 observation from the actual Account row."""

    settings_value = get_active_account_creation_evidence_settings(seed.environment)
    if type(settings_value) is not CanonicalAccountCreationEvidenceSettings:
        raise RuntimeError("canonical Account creation settings expired")
    requester = CanonicalAccountCreationRequester(
        actor_id=f"django-user:{seed.owner.pk}",
        user_id=seed.owner.pk,
    )
    physical_provider = build_account_physical_row_v2_provider(using="default")
    owner_stages = build_simulated_account_creation_stages(using="default", settings=settings_value)
    account_stages = build_canonical_account_creation_stages(
        using="default",
        settings=settings_value,
        requester=requester,
        physical_row_provider=physical_provider,
    )
    observer = build_existing_account_reobserver(using="default", settings=settings_value)
    original = seed.binding.creation_root.physical_observation
    version = f"ash07-owner-reobserve-{uuid4().hex}"
    with transaction.atomic(using="default"):
        raw = observer.execute(
            ReobserveExistingAccountRowCommand(
                observation_id=original.observation_id,
                observation_version=version,
                row_pk=seed.account.pk,
                expected_user_id=seed.owner.pk,
                expected_account_type=AccountType.SIMULATED,
                expected_created_at=original.row_created_at,
                minimum_updated_at=original.row_updated_at,
            )
        )
        source = owner_stages.source_capture.execute(
            CaptureSimulatedAccountRowSourceV2Command(
                source_id=raw.observation_id,
                source_version=version,
                expected_raw_observation_content_hash=raw.content_hash,
                account_namespace=original.account_namespace,
                account_id=original.account_id,
                underlying_unified_account_namespace=(
                    original.underlying_unified_account_namespace
                ),
                underlying_unified_account_id=seed.account.pk,
            )
        )
        physical = account_stages.physical_capture.execute(
            CapturePhysicalAccountRowObservationV2Command(
                observation_id=original.observation_id,
                observation_version=version,
                source_id=source.source_id,
                source_version=source.source_version,
                expected_source_content_hash=source.content_hash,
                account_namespace=original.account_namespace,
                account_id=original.account_id,
                underlying_unified_account_namespace=(
                    original.underlying_unified_account_namespace
                ),
                underlying_unified_account_id=seed.account.pk,
            )
        )
    recorded_at = timezone.now().astimezone(UTC)
    reobservation = CanonicalAccountOwnershipReobservationV1(
        observation_id=original.observation_id,
        observation_version=version,
        binding=seed.binding,
        current_physical=physical,
        recorded_at=recorded_at,
        valid_until=physical.valid_until,
    )
    return RecordCanonicalAccountOwnershipReobservationV1(
        DjangoCanonicalAccountOwnershipReobservationV1Repository(using="default")
    ).execute(RecordCanonicalAccountOwnershipReobservationV1Command(reobservation))


def _subject_for_receipt(
    receipt: AccountOwnerAssignmentProvenanceReceiptV5,
    *,
    suffix: str,
    requested_at: datetime,
) -> AccountOwnerAssignmentSubjectV5:
    """Construct a V5 subject solely from its exact durable receipt parents."""

    binding = receipt.binding
    reobservation = receipt.reobservation
    current = reobservation.current_physical
    return AccountOwnerAssignmentSubjectV5(
        subject_id=f"ash07-owner-subject-{suffix}",
        subject_version="v5.1",
        receipt=receipt,
        binding=binding,
        reobservation=reobservation,
        receipt_identity_hash=receipt.identity_hash,
        receipt_content_hash=receipt.content_hash,
        policy_identity_hash=receipt.policy.identity_hash,
        policy_content_hash=receipt.policy.content_hash,
        binding_identity_hash=binding.identity_hash,
        binding_content_hash=binding.content_hash,
        allocation_identity_hash=binding.allocation.identity_hash,
        allocation_content_hash=binding.allocation.content_hash,
        account_claim_hash=binding.account_claim_hash,
        underlying_claim_hash=binding.underlying_claim_hash,
        reobservation_identity_hash=reobservation.identity_hash,
        reobservation_content_hash=reobservation.content_hash,
        current_physical_observation_content_hash=current.content_hash,
        current_physical_source_content_hash=current.source_content_hash,
        current_physical_raw_observation_content_hash=current.raw_observation_content_hash,
        requested_at=requested_at,
        valid_until=receipt.valid_until,
    )


def _decode_actor_receipt(value: object) -> AccountActorAuthorityRawSourcePublicationReceiptV3:
    """Restore the exact selector-only publication receipt returned by Account HTTP."""

    if type(value) is not dict:
        raise RuntimeError("Account actor publication response is malformed")
    payload = cast(dict[str, object], value)
    required = {
        "outcome",
        "status",
        "user_id",
        "principal_id",
        "observed_at",
        "valid_until",
        "authentication_context",
        "user",
        "rbac",
        "actor",
    }
    if set(payload) != required:
        raise RuntimeError("Account actor publication response fields differ")
    return AccountActorAuthorityRawSourcePublicationReceiptV3(
        authentication_context=_decode_selector(payload["authentication_context"]),
        user=_decode_selector(payload["user"]),
        rbac=_decode_selector(payload["rbac"]),
        actor=_decode_selector(payload["actor"]),
        user_id=cast(int, payload["user_id"]),
        principal_id=cast(str, payload["principal_id"]),
        observed_at=_parse_aware(payload["observed_at"]),
        valid_until=_parse_aware(payload["valid_until"]),
        outcome=cast(str, payload["outcome"]),
        status=cast(str, payload["status"]),
    )


def _decode_selector(value: object) -> AccountActorAuthorityRawSourceSelectorV3:
    """Decode one exact Account source selector without coercing its fields."""

    if type(value) is not dict:
        raise RuntimeError("Account actor source selector is malformed")
    payload = cast(dict[str, object], value)
    if set(payload) != {"source_id", "source_version", "content_hash"}:
        raise RuntimeError("Account actor source selector fields differ")
    return AccountActorAuthorityRawSourceSelectorV3(
        source_id=cast(str, payload["source_id"]),
        source_version=cast(str, payload["source_version"]),
        content_hash=cast(str, payload["content_hash"]),
    )


def _parse_aware(value: object) -> datetime:
    """Parse only an exact aware ISO timestamp from the Account response."""

    if type(value) is not str:
        raise RuntimeError("Account authority timestamp is malformed")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError("Account authority timestamp is not timezone-aware")
    return parsed


def _runtime_environment() -> str:
    """Return the same non-secret environment selection used by Account API views."""

    module_name = str(getattr(settings, "SETTINGS_MODULE", "") or "")
    if not module_name:
        import os

        module_name = os.environ.get("DJANGO_SETTINGS_MODULE", "")
    return "production" if module_name.endswith(".production") else "development"


__all__ = [
    "ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS",
    "OwnerAccountSeed",
    "audit_runtime_patch",
    "create_owner_account_seed",
    "issue_current_owner_audit_selector",
    "owner_policy_runtime_patch",
    "publish_current_owner_policy",
]
