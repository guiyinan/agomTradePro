"""Authenticated admin owner-scope V3 graph on disposable PostgreSQL."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import timedelta
from typing import cast

import pytest
from django.contrib.auth.models import User
from django.db import connections
from django.test import Client, override_settings
from django.urls import path
from django.utils import timezone

from apps.account.account_actor_authority_raw_source_publisher_composition import (
    build_account_actor_authority_raw_source_publisher,
)
from apps.account.account_owner_assignment_evidence_v5_composition import (
    build_account_owner_assignment_evidence_v5_facade,
)
from apps.account.application.account_actor_authority_raw_source_publisher_v3 import (
    PublishAccountActorAuthorityRawSourceV3,
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
from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    PersistedCanonicalAccountOwnershipReobservationV1,
)
from apps.account.application.owner_tenant_authority_v2 import (
    GetCurrentOwnerTenantAuthorityV2Command,
)
from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
    IssueOwnerTenantAuthorityV3Command,
    RevokeOwnerTenantAuthorityV3Command,
)
from apps.account.application.single_owner_actor_authority import SingleOwnerPolicyBinding
from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_provenance_receipt_v5 import (
    AccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.domain.account_owner_assignment_subject_v5 import (
    AccountOwnerAssignmentSubjectV5,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_repository import (
    DjangoAccountOwnerAssignmentSubjectV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_v5_models import (
    AccountOwnerAssignmentEvidenceV5Model,
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    AccountOwnerAssignmentSubjectV5Model,
)
from apps.account.infrastructure.canonical_account_creation_binding_v2_codec import (
    decode_canonical_account_creation_binding_v2,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_models import (
    CanonicalAccountOwnershipReobservationV1Model,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_repository import (
    DjangoCanonicalAccountOwnershipReobservationV1Repository,
)
from apps.account.infrastructure.owner_tenant_authority_v3_models import (
    OwnerTenantAuthorityV3Model,
    OwnerTenantAuthorityV3RevocationModel,
)
from apps.account.infrastructure.physical_account_row_observation_v2_models import (
    PhysicalAccountRowObservationV2Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_codec import (
    decode_single_owner_authority_policy_v1,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from apps.account.interface.account_actor_authority_raw_source_api_views import (
    AccountActorAuthorityRawSourcePublishView,
)
from apps.account.owner_tenant_authority_v3_composition import (
    build_owner_tenant_authority_v3_facade,
)
from apps.research.evidence_composition import make_evidence_read_repository
from apps.research.infrastructure.evidence_models import (
    EvidenceEnvelopeModel,
    EvidenceOperatorSpecModel,
    EvidenceTrackRecordModel,
)
from apps.research.infrastructure.evidence_repository import _build_evidence_store
from core.integration import config_center_runtime
from core.integration.canonical_account_ownership_reobservation import (
    CanonicalAccountOwnershipReobservationCommand,
    reobserve_canonical_account_ownership,
)
from core.integration.owner_tenant_evidence_scope_v3 import (
    OwnerTenantAuthorityV3EvidenceReadFacade,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_http import (
    _csrf_token,
    _post_json,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _new_user,
)
from tests.component.account.test_authenticated_creation_http_postgres import _post
from tests.component.account.test_authenticated_creation_http_postgres import (
    creation_http_alias as creation_http_alias,
)
from tests.component.account.test_bound_policy_publication_postgres import (
    _publish,
    _PublishView,
    _values,
)
from tests.component.account.test_bound_policy_publication_postgres import (
    urlpatterns as policy_urls,
)
from tests.unit.research.test_evidence_contracts import _spec
from tests.unit.simulated_trading.test_creation_composition import _settings

pytest_plugins = (
    "tests.component.account.test_current_account_ownership_postgres",
    "tests.component.account.creation_chain_postgres_fixture",
)

urlpatterns = [
    *policy_urls,
    path(
        "api/account/authority/raw/publish/",
        AccountActorAuthorityRawSourcePublishView.as_view(),
    ),
]

_EXTRA_MODELS = (
    SingleOwnerAuthorityPolicyV1Model,
    CanonicalAccountOwnershipReobservationV1Model,
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    AccountOwnerAssignmentSubjectV5Model,
    AccountOwnerAssignmentEvidenceV5Model,
    OwnerTenantAuthorityV3Model,
    OwnerTenantAuthorityV3RevocationModel,
    EvidenceOperatorSpecModel,
    EvidenceTrackRecordModel,
    EvidenceEnvelopeModel,
)


@pytest.fixture
def owner_scope_v3_alias(creation_http_alias: str) -> Iterator[str]:
    """Extend the real auth/creation schema with the final EVID-07 ledgers."""

    connection = connections[creation_http_alias]
    created: list[type] = []
    try:
        with connection.schema_editor() as editor:
            for model in _EXTRA_MODELS:
                editor.create_model(model)
                created.append(model)
        yield creation_http_alias
    finally:
        with connection.schema_editor() as editor:
            for model in reversed(created):
                editor.delete_model(model)


def _admin_client(alias: str) -> tuple[Client, User, str]:
    """Create and authenticate the explicitly designated admin/User ID 1."""

    user, _ = _new_user(alias, username="admin")
    assert user.pk == 1
    client = Client(enforce_csrf_checks=True)
    assert client.login(username="admin", password="evid06-test-password") is True
    return client, user, _csrf_token(client)


def test_authenticated_admin_materializes_owner_scope_and_denies_substitution(
    owner_scope_v3_alias: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove the real admin session through creation, V5 approval, V3 authority, and scope."""

    import apps.account.interface.account_actor_authority_raw_source_api_views as actor_views

    alias = owner_scope_v3_alias

    def build_actor_source(
        *, authenticated_user: object, session: object
    ) -> PublishAccountActorAuthorityRawSourceV3:
        return build_account_actor_authority_raw_source_publisher(
            authenticated_user=authenticated_user,
            session=session,
            using=alias,
        )

    monkeypatch.setattr(
        actor_views,
        "build_account_actor_authority_raw_source_publisher",
        build_actor_source,
    )
    monkeypatch.setattr(_PublishView, "alias", alias)
    with override_settings(ROOT_URLCONF=__name__):
        client, admin_user, csrf = _admin_client(alias)
        actor_response = _post_json(client, {}, csrf_token=csrf)
        assert actor_response.status_code == 201, actor_response.content
        created = _post(client, csrf)
        assert created.status_code == 201, created.content
        binding_row = CanonicalAccountCreationBindingV2Model.objects.using(alias).get()
        binding = decode_canonical_account_creation_binding_v2(binding_row.canonical_payload)

        runtime_values = _values(admin_user)

        def read_runtime(*, environment: str, definition_key: str) -> object | None:
            assert environment == "test"
            return runtime_values.get(definition_key)

        monkeypatch.setattr(config_center_runtime, "get_active_runtime_value", read_runtime)
        policy_response = _publish(client, csrf, binding_row)
        assert policy_response.status_code == 200, policy_response.content
        policy = decode_single_owner_authority_policy_v1(policy_response.json())

        physical = PhysicalAccountRowObservationV2Model.objects.using(alias).get()
        reobservation = reobserve_canonical_account_ownership(
            command=CanonicalAccountOwnershipReobservationCommand(
                binding_id=binding.binding_id,
                binding_version=binding.binding_version,
                expected_binding_content_hash=binding.content_hash,
                observation_id=physical.observation_id,
                observation_version="admin-scope-current-v1",
            ),
            requester=CanonicalAccountCreationRequester(
                actor_id=f"django-user:{admin_user.pk}", user_id=admin_user.pk
            ),
            using=alias,
            settings=_settings(),
        )
        reobservation_repository = DjangoCanonicalAccountOwnershipReobservationV1Repository(
            using=alias
        )
        with reobservation_repository.atomic():
            reobservation_repository.append(
                PersistedCanonicalAccountOwnershipReobservationV1(reobservation),
                recorded_at=reobservation.recorded_at,
            )

        actor_row = (
            AccountOwnerAssignmentActorAuthoritySourceV3Model.objects.using(alias)
            .filter(user_id=admin_user.pk)
            .order_by("-recorded_at")
            .first()
        )
        assert actor_row is not None
        stable_clock = max(
            policy.observed_at,
            reobservation.recorded_at,
            actor_row.recorded_at,
        ) + timedelta(microseconds=1)
        graph_deadline = min(policy.valid_until, reobservation.valid_until, actor_row.valid_until)
        assert stable_clock < graph_deadline
        monkeypatch.setattr("django.utils.timezone.now", lambda: stable_clock)
        claimant = AccountOwnerAssignmentActor(
            actor_id=actor_row.actor_id,
            user_id=admin_user.pk,
            role="account_owner_claimant",
            is_staff=True,
        )
        receipt_clock = timezone.now()
        receipt = AccountOwnerAssignmentProvenanceReceiptV5(
            receipt_id="admin-owner-receipt",
            receipt_version="v5.1",
            policy=policy,
            policy_identity_hash=policy.identity_hash,
            policy_content_hash=policy.content_hash,
            binding=binding,
            reobservation=reobservation,
            account_namespace=binding.account_namespace_claim,
            account_id=binding.account_id_claim,
            underlying_unified_account_namespace=(
                binding.underlying_unified_account_namespace_claim
            ),
            underlying_unified_account_id=binding.underlying_unified_account_id_claim,
            allocation_identity_hash=binding.allocation.identity_hash,
            allocation_content_hash=binding.allocation.content_hash,
            binding_identity_hash=binding.identity_hash,
            binding_content_hash=binding.content_hash,
            account_claim_hash=binding.account_claim_hash,
            underlying_claim_hash=binding.underlying_claim_hash,
            reobservation_identity_hash=reobservation.identity_hash,
            reobservation_content_hash=reobservation.content_hash,
            current_physical_observation_content_hash=reobservation.current_physical.content_hash,
            current_physical_source_content_hash=reobservation.current_physical.source_content_hash,
            current_physical_raw_observation_content_hash=(
                reobservation.current_physical.raw_observation_content_hash
            ),
            assigned_owner_user_id=admin_user.pk,
            claimant=claimant,
            issued_at=receipt_clock,
            recorded_at=receipt_clock,
            valid_until=graph_deadline,
        )
        receipt_service = IssueAccountOwnerAssignmentProvenanceReceiptV5(
            DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository(using=alias)
        )
        assert (
            receipt_service.execute(IssueAccountOwnerAssignmentProvenanceReceiptV5Command(receipt))
            == receipt
        )

        subject_clock = timezone.now()
        subject = AccountOwnerAssignmentSubjectV5(
            subject_id="admin-owner-subject",
            subject_version="v5.1",
            receipt=receipt,
            binding=binding,
            reobservation=reobservation,
            receipt_identity_hash=receipt.identity_hash,
            receipt_content_hash=receipt.content_hash,
            policy_identity_hash=policy.identity_hash,
            policy_content_hash=policy.content_hash,
            binding_identity_hash=binding.identity_hash,
            binding_content_hash=binding.content_hash,
            allocation_identity_hash=binding.allocation.identity_hash,
            allocation_content_hash=binding.allocation.content_hash,
            account_claim_hash=binding.account_claim_hash,
            underlying_claim_hash=binding.underlying_claim_hash,
            reobservation_identity_hash=reobservation.identity_hash,
            reobservation_content_hash=reobservation.content_hash,
            current_physical_observation_content_hash=reobservation.current_physical.content_hash,
            current_physical_source_content_hash=reobservation.current_physical.source_content_hash,
            current_physical_raw_observation_content_hash=(
                reobservation.current_physical.raw_observation_content_hash
            ),
            requested_at=subject_clock,
            valid_until=graph_deadline,
        )
        subject_service = RegisterAccountOwnerAssignmentSubjectV5(
            DjangoAccountOwnerAssignmentSubjectV5Repository(using=alias)
        )
        assert (
            subject_service.execute(RegisterAccountOwnerAssignmentSubjectV5Command(subject))
            == subject
        )

        principal = AuthenticatedAccountPrincipalV3(
            principal_id=actor_row.principal_id,
            user_id=admin_user.pk,
            authentication_context_hash=actor_row.authentication_context_content_hash,
            authenticated_at=actor_row.recorded_at,
            valid_until=actor_row.valid_until,
        )
        policy_binding = SingleOwnerPolicyBinding(
            policy.policy_id,
            policy.policy_version,
            policy.content_hash,
            policy.tenant_id,
            policy.owner_id,
            policy.account_namespace,
            policy.account_id,
        )
        evidence_facade = build_account_owner_assignment_evidence_v5_facade(
            principal=principal,
            policy_binding=policy_binding,
            actor_source_id=actor_row.source_id,
            actor_source_version=actor_row.source_version,
            actor_source_content_hash=actor_row.content_hash,
            validity_period=timedelta(minutes=4),
            using=alias,
        )
        evidence = evidence_facade.approve(
            ApproveAccountOwnerAssignmentEvidenceV5Command(
                "admin-owner-evidence",
                "v5.1",
                subject.subject_id,
                subject.subject_version,
                subject.content_hash,
            )
        )
        assert evidence.assigned_owner_user_id == admin_user.pk

        authority_facade = build_owner_tenant_authority_v3_facade(
            principal=principal,
            policy_binding=policy_binding,
            actor_source_id=actor_row.source_id,
            actor_source_version=actor_row.source_version,
            actor_source_content_hash=actor_row.content_hash,
            validity_period=timedelta(minutes=4),
            using=alias,
        )
        authority = authority_facade.issue(
            IssueOwnerTenantAuthorityV3Command(
                "admin-owner-authority",
                "v3.1",
                evidence.evidence_id,
                evidence.evidence_version,
                evidence.content_hash,
            )
        )
        selector = GetCurrentOwnerTenantAuthorityV3Command(
            authority.authority_id,
            authority.authority_version,
            authority.content_hash,
        )

        spec = replace(
            _spec(),
            activated_at=authority.recorded_at - timedelta(seconds=1),
            valid_until=authority.valid_until,
            content_hash="",
        )
        store = _build_evidence_store(using=alias)
        with store.atomic():
            store.append_operator_spec(
                spec, recorded_at=authority.recorded_at - timedelta(microseconds=1)
            )
        scoped_reader = OwnerTenantAuthorityV3EvidenceReadFacade(
            authority_reader=authority_facade,
            evidence_reader=make_evidence_read_repository(using=alias),
            authority_command=selector,
            server_bound_artifacts=frozenset({spec.artifact_ref}),
            scope_ttl=timedelta(seconds=30),
            using=alias,
        )
        assert (
            scoped_reader.get_operator_spec(
                operator_id=spec.operator_id,
                operator_version=spec.operator_version,
                expected_content_hash=spec.content_hash,
                evidence_as_of=authority.recorded_at,
            )
            == spec
        )

        other_user, _ = _new_user(alias, username="other-owner")
        other_principal = AuthenticatedAccountPrincipalV3(
            actor_row.principal_id,
            cast(int, other_user.pk),
            "0" * 64,
            actor_row.recorded_at,
            actor_row.valid_until,
        )
        other_authority = build_owner_tenant_authority_v3_facade(
            principal=other_principal,
            policy_binding=policy_binding,
            actor_source_id=actor_row.source_id,
            actor_source_version=actor_row.source_version,
            actor_source_content_hash=actor_row.content_hash,
            validity_period=timedelta(minutes=1),
            using=alias,
        )
        assert other_authority.get_current(selector) is None

        mismatched_tenant = build_owner_tenant_authority_v3_facade(
            principal=principal,
            policy_binding=SingleOwnerPolicyBinding(
                policy.policy_id,
                policy.policy_version,
                policy.content_hash,
                "other-tenant",
                policy.owner_id,
                policy.account_namespace,
                policy.account_id,
            ),
            actor_source_id=actor_row.source_id,
            actor_source_version=actor_row.source_version,
            actor_source_content_hash=actor_row.content_hash,
            validity_period=timedelta(minutes=1),
            using=alias,
        )
        assert mismatched_tenant.get_current(selector) is None

        with pytest.raises(TypeError):
            OwnerTenantAuthorityV3EvidenceReadFacade(
                authority_reader=authority_facade,
                evidence_reader=make_evidence_read_repository(using=alias),
                authority_command=cast(
                    GetCurrentOwnerTenantAuthorityV3Command,
                    GetCurrentOwnerTenantAuthorityV2Command(
                        authority.authority_id,
                        "v2.1",
                        authority.content_hash,
                    ),
                ),
                server_bound_artifacts=frozenset({spec.artifact_ref}),
                scope_ttl=timedelta(seconds=30),
                using=alias,
            )
        with pytest.raises(TypeError):
            cast(Callable[..., object], scoped_reader.get_operator_spec)(
                operator_id=spec.operator_id,
                operator_version=spec.operator_version,
                expected_content_hash=spec.content_hash,
                evidence_as_of=authority.recorded_at,
                mode="owner",
            )

        authority_facade.revoke(
            RevokeOwnerTenantAuthorityV3Command(
                authority.authority_id,
                authority.authority_version,
                authority.content_hash,
                "authenticated-test-revocation",
            )
        )
        assert (
            scoped_reader.get_operator_spec(
                operator_id=spec.operator_id,
                operator_version=spec.operator_version,
                expected_content_hash=spec.content_hash,
                evidence_as_of=authority.recorded_at,
            )
            is None
        )
