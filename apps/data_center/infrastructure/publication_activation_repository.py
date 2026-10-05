"""Infrastructure for candidate staging and the short current activation UOW."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Final
from uuid import UUID

from django.db import connections, transaction
from django.utils import timezone

from apps.data_center.application.publication_activation import (
    PublicationActivationAuditWriter,
    PublicationActivationAuthorityFence,
    PublicationActivationAuthorityLease,
    PublicationActivationError,
    PublicationActivationGroupAuditWriter,
    PublicationActivationGroupRequest,
    PublicationActivationRequest,
    publication_activation_lease_from_complete_graph,
)
from apps.data_center.application.publication_utils import (
    member_reference,
    publication_hash,
    publication_member_manifest_hash,
)
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.publication_evidence import validate_publication_evidence
from apps.data_center.domain.publication_snapshot_policy import (
    validate_publication_snapshot_policy,
)
from apps.data_center.domain.raw_audit_manifest import requires_group_publication_activation
from core.integration.data_center_audit import (
    AuditOutcome,
    DataPublicationAuditObservation,
    SystemAuditEventOutboxCommit,
)

from .fact_and_operational_models import RawAuditModel
from .publication_fact_identity import publication_fact_model_registry
from .publication_fact_write_lock import acquire_publication_fact_activation_locks
from .publication_group_activation_repository import (
    DjangoPublicationActivationGroupRepository,
)
from .publication_member_store import publication_fact_content_hashes
from .publication_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from .publication_policy_repository import PublicationPolicyRepository

_DEFAULT_ALIAS: Final[str] = "default"
_CANDIDATE_STATES: Final[frozenset[str]] = frozenset(
    {PublicationState.CANDIDATE.value, PublicationState.PUBLISHED.value}
)


class DjangoPublicationActivationRepository:
    """Stage immutable members and atomically activate one exact candidate."""

    def __init__(self, *, using: str = _DEFAULT_ALIAS) -> None:
        if using != _DEFAULT_ALIAS:
            raise ValueError("publication activation currently requires the default database alias")
        self._using = using

    @transaction.atomic
    def stage_candidate_with_members(
        self,
        publication: CanonicalPublication,
        members: Sequence[PublicationMember],
    ) -> CanonicalPublication:
        """Persist an invisible candidate, its coverage and exact member rows."""

        self._validate_candidate_shape(publication, tuple(members))
        if publication.state is not PublicationState.CANDIDATE:
            raise PublicationActivationError("candidate staging requires CANDIDATE state")
        publication_id = UUID(publication.publication_id)
        existing = CanonicalPublicationModel._default_manager.filter(
            publication_id=publication_id
        ).first()
        if existing is not None:
            if (
                existing.member_manifest_hash
                != publication_member_manifest_hash(
                    tuple(members), policy_identity=publication.policy_version
                )
                or existing.members_sealed_at is None
            ):
                raise PublicationActivationError("candidate member manifest is not identical")
            coverage = CoverageSnapshotModel._default_manager.filter(
                publication_id=publication_id
            ).first()
            if coverage is None or (
                coverage.coverage_id != UUID(publication.coverage.coverage_id)
                or coverage.requested_count != publication.coverage.requested_count
                or coverage.eligible_count != publication.coverage.eligible_count
                or coverage.selected_count != publication.coverage.selected_count
                or coverage.missing_count != publication.coverage.missing_count
                or coverage.conflict_count != publication.coverage.conflict_count
                or coverage.generated_at != publication.coverage.generated_at
            ):
                raise PublicationActivationError(
                    "candidate coverage identity already contains different content"
                )
            persisted = existing.to_domain()
            expected = replace(
                publication,
                coverage=replace(
                    publication.coverage,
                    coverage_id=str(existing.publication_id),
                    generated_at=existing.created_at,
                ),
            )
            if persisted != expected:
                raise PublicationActivationError(
                    "candidate identity already contains different content"
                )
            persisted_rows = tuple(
                PublicationMemberModel._default_manager.filter(
                    publication_id=publication_id
                ).order_by("natural_key")
            )
            if tuple(row.to_domain() for row in persisted_rows) != tuple(
                sorted(members, key=lambda item: item.natural_key)
            ):
                raise PublicationActivationError(
                    "candidate member identity already contains different content"
                )
            return publication

        manifest_hash = publication_member_manifest_hash(
            tuple(members), policy_identity=publication.policy_version
        )
        CanonicalPublicationModel._default_manager.create(
            publication_id=publication_id,
            dataset_key=publication.dataset_key,
            publication_key=publication.publication_key,
            policy_version=publication.policy_version,
            state=publication.state.value,
            selected_source=publication.selected_source,
            publication_hash=publication.publication_hash,
            member_manifest_hash=manifest_hash,
            member_count=publication.member_count,
            conflict_count=publication.conflict_count,
            coverage_requested_count=publication.coverage.requested_count,
            coverage_eligible_count=publication.coverage.eligible_count,
            coverage_selected_count=publication.coverage.selected_count,
            coverage_missing_count=publication.coverage.missing_count,
            coverage_conflict_count=publication.coverage.conflict_count,
            as_of=publication.as_of,
            published_at=None,
            superseded_at=None,
            reinstated_at=None,
            must_not_use_for_decision=publication.must_not_use_for_decision,
            blocked_reason=publication.blocked_reason,
            created_by=publication.created_by,
            run_id=UUID(publication.run_id) if publication.run_id else None,
            scope_blocks=[block.to_dict() for block in publication.scope_blocks],
        )
        CoverageSnapshotModel._default_manager.create(
            coverage_id=UUID(publication.coverage.coverage_id),
            publication_id=publication_id,
            requested_count=publication.coverage.requested_count,
            eligible_count=publication.coverage.eligible_count,
            selected_count=publication.coverage.selected_count,
            missing_count=publication.coverage.missing_count,
            conflict_count=publication.coverage.conflict_count,
            generated_at=publication.coverage.generated_at,
        )
        PublicationMemberModel._default_manager.bulk_create(
            [self._member_model(member) for member in members],
            batch_size=1000,
        )
        CanonicalPublicationModel._default_manager.filter(
            publication_id=publication_id,
        ).update(members_sealed_at=timezone.now())
        CanonicalPublicationPointerModel._default_manager.get_or_create(
            dataset_key=publication.dataset_key,
            publication_key=publication.publication_key,
        )
        return publication

    def activate_candidate(
        self,
        request: PublicationActivationRequest,
        *,
        audit_writer: PublicationActivationAuditWriter,
        authority_fence: PublicationActivationAuthorityFence,
        authority_proof: object,
    ) -> CanonicalPublication:
        """Run activation only while the caller's complete authority fence is open."""

        if requires_group_publication_activation(request.dataset_key):
            raise PublicationActivationError(
                "current market publication requires atomic group activation"
            )
        connection = connections[self._using]
        if connection.in_atomic_block:
            raise PublicationActivationError("activation cannot join an ambient transaction")
        writer_alias = getattr(audit_writer, "database_alias", None)
        if writer_alias != self._using:
            raise PublicationActivationError("audit writer database alias differs")
        if not callable(getattr(authority_fence, "fence_complete", None)):
            raise PublicationActivationError("complete authority fence is unavailable")
        try:
            with authority_fence.fence_complete(authority_proof) as graph_result:
                lease = publication_activation_lease_from_complete_graph(graph_result)
                if type(lease) is not PublicationActivationAuthorityLease:
                    raise PublicationActivationError("authority lease projection is invalid")
                self._validate_authority_lease(request, lease)
                return self._activate_in_transaction(request, audit_writer, lease)
        except PublicationActivationError:
            raise
        except (TypeError, ValueError) as error:
            raise PublicationActivationError(
                "complete authority fence rejected activation"
            ) from error

    def activate_candidate_group(
        self,
        request: PublicationActivationGroupRequest,
        *,
        audit_writer: PublicationActivationGroupAuditWriter,
        authority_fence: PublicationActivationAuthorityFence,
        authority_proof: object,
    ) -> tuple[CanonicalPublication, ...]:
        """Activate the fixed quote/price/valuation group under one Account fence."""

        return DjangoPublicationActivationGroupRepository(
            using=self._using
        ).activate_candidate_group(
            request,
            audit_writer=audit_writer,
            authority_fence=authority_fence,
            authority_proof=authority_proof,
        )

    def _activate_in_transaction(
        self,
        request: PublicationActivationRequest,
        audit_writer: PublicationActivationAuditWriter,
        lease: PublicationActivationAuthorityLease,
    ) -> CanonicalPublication:
        """Run pointer lock, candidate validation, switch and required append."""

        connection = connections[self._using]
        if not connection.in_atomic_block or connection.get_autocommit():
            raise PublicationActivationError(
                "activation requires the complete fence's outer transaction"
            )
        atomic_blocks = getattr(connection, "atomic_blocks", None)
        if not isinstance(atomic_blocks, list) or len(atomic_blocks) != 1:
            raise PublicationActivationError(
                "activation requires the complete fence's outermost transaction"
            )

        fact_model = publication_fact_model_registry().get(request.dataset_key)
        if fact_model is None:
            raise PublicationActivationError("activation fact model is not registered")
        acquire_publication_fact_activation_locks((fact_model,), using=self._using)

        pointer = (
            CanonicalPublicationPointerModel._default_manager.select_for_update()
            .filter(dataset_key=request.dataset_key, publication_key=request.publication_key)
            .first()
        )
        if pointer is None:
            raise PublicationActivationError("current publication pointer is missing")
        try:
            candidate_id = UUID(request.candidate_publication_id)
        except (TypeError, ValueError) as error:
            raise PublicationActivationError("candidate publication id is invalid") from error
        candidate = (
            CanonicalPublicationModel._default_manager.select_for_update()
            .filter(publication_id=candidate_id)
            .first()
        )
        if candidate is None:
            raise PublicationActivationError("candidate publication is missing")
        if (
            candidate.dataset_key != request.dataset_key
            or candidate.publication_key != request.publication_key
            or candidate.publication_hash != request.candidate_publication_hash
            or candidate.state not in _CANDIDATE_STATES
            or candidate.must_not_use_for_decision
        ):
            raise PublicationActivationError("candidate publication identity drifted")

        same_current = (
            pointer.publication_id == candidate.publication_id
            and pointer.publication_hash == candidate.publication_hash
        )
        if not same_current and (
            pointer.publication_id is not None
            and (
                request.expected_current_publication_id != str(pointer.publication_id)
                or request.expected_current_publication_hash != pointer.publication_hash
            )
        ):
            raise PublicationActivationError("current publication pointer compare-and-swap failed")
        if (
            not same_current
            and pointer.publication_id is None
            and (pointer.publication_hash or pointer.activation_id)
        ):
            raise PublicationActivationError(
                "empty current pointer contains stale activation identity"
            )
        if (
            not same_current
            and pointer.publication_id is None
            and any(
                value is not None
                for value in (
                    request.expected_current_publication_id,
                    request.expected_current_publication_hash,
                )
            )
        ):
            raise PublicationActivationError("empty current pointer compare-and-swap failed")

        if candidate.state == PublicationState.PUBLISHED.value and not same_current:
            raise PublicationActivationError(
                "published candidate is not the current pointer target"
            )
        activation_at = lease.checked_at
        if same_current:
            if candidate.state != PublicationState.PUBLISHED.value:
                raise PublicationActivationError(
                    "current pointer references a non-published candidate"
                )
            if pointer.activation_id != request.activation_id:
                raise PublicationActivationError("current pointer activation identity differs")
            if candidate.published_at is None or candidate.published_at > lease.checked_at:
                raise PublicationActivationError("current publication cutoff is invalid")
            activation_at = candidate.published_at
        effective_observation = replace(
            request.audit_observation,
            recorded_at=activation_at,
        )
        self._validate_audit_observation(
            effective_observation,
            candidate.to_domain(),
            activation_at,
        )

        members = tuple(
            row.to_domain()
            for row in PublicationMemberModel._default_manager.filter(
                publication_id=candidate.publication_id
            )
            .select_for_update()
            .order_by("natural_key")
        )
        self._validate_candidate_shape(candidate.to_domain(), members)
        if candidate.members_sealed_at is None or not candidate.member_manifest_hash:
            raise PublicationActivationError("candidate member manifest is not sealed")
        if candidate.member_manifest_hash != publication_member_manifest_hash(
            members, policy_identity=candidate.policy_version
        ):
            raise PublicationActivationError("candidate member manifest drifted")
        self._validate_fact_snapshot(candidate.to_domain(), members)
        self._validate_policy_snapshot(candidate.to_domain(), members, activation_at)
        activated = replace(
            candidate.to_domain(),
            state=PublicationState.PUBLISHED,
            published_at=activation_at,
            superseded_at=None,
        )
        if activated.as_of is None or activated.as_of > activation_at:
            raise PublicationActivationError("candidate publication time boundary is invalid")

        if same_current:
            self._append_required_audit(
                request=request,
                audit_writer=audit_writer,
                publication=candidate.to_domain(),
                members=members,
                observation=effective_observation,
            )
            return candidate.to_domain()

        previous = None
        if pointer.publication_id is not None:
            previous = (
                CanonicalPublicationModel._default_manager.select_for_update()
                .filter(
                    publication_id=pointer.publication_id,
                    dataset_key=request.dataset_key,
                    publication_key=request.publication_key,
                    state=PublicationState.PUBLISHED.value,
                    publication_hash=pointer.publication_hash,
                )
                .first()
            )
            if previous is None:
                raise PublicationActivationError("current pointer target is missing or drifted")

        if previous is not None:
            if previous.published_at is None or previous.published_at >= activation_at:
                raise PublicationActivationError("activation publication time is not monotonic")
            previous.state = PublicationState.SUPERSEDED.value
            previous.superseded_at = activation_at
            previous.save(update_fields=("state", "superseded_at", "updated_at"))
        candidate.state = PublicationState.PUBLISHED.value
        candidate.published_at = activation_at
        candidate.superseded_at = None
        candidate.save(update_fields=("state", "published_at", "superseded_at", "updated_at"))
        self._compare_and_swap_pointer(
            pointer,
            publication_id=candidate.publication_id,
            publication_hash=candidate.publication_hash,
            activation_id=request.activation_id,
            updated_at=activation_at,
        )
        self._append_required_audit(
            request=request,
            audit_writer=audit_writer,
            publication=activated,
            members=members,
            observation=effective_observation,
        )
        return candidate.to_domain()

    @staticmethod
    def _compare_and_swap_pointer(
        pointer: CanonicalPublicationPointerModel,
        *,
        publication_id: UUID,
        publication_hash: str,
        activation_id: str,
        updated_at: datetime,
    ) -> None:
        """Compare all observed pointer identity fields before changing the target."""

        updated = CanonicalPublicationPointerModel._default_manager.filter(
            pointer_id=pointer.pointer_id,
            publication_id=pointer.publication_id,
            publication_hash=pointer.publication_hash,
            activation_id=pointer.activation_id,
        ).update(
            publication_id=publication_id,
            publication_hash=publication_hash,
            activation_id=activation_id,
            updated_at=updated_at,
        )
        if updated != 1:
            raise PublicationActivationError("current publication pointer compare-and-swap failed")
        pointer.publication_id = publication_id
        pointer.publication_hash = publication_hash
        pointer.activation_id = activation_id

    @staticmethod
    def _append_required_audit(
        *,
        request: PublicationActivationRequest,
        audit_writer: PublicationActivationAuditWriter,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
        observation: DataPublicationAuditObservation,
    ) -> None:
        """Append and type-check the required event/outbox commit in place."""

        append_required = getattr(audit_writer, "append_required", None)
        if not callable(append_required):
            raise PublicationActivationError("required audit/outbox writer is unavailable")
        commit = append_required(
            request=request,
            publication=publication,
            members=members,
            observation=observation,
        )
        if not isinstance(commit, SystemAuditEventOutboxCommit):
            raise PublicationActivationError(
                "required audit/outbox writer returned an invalid commit"
            )

    @staticmethod
    def _validate_authority_lease(
        request: PublicationActivationRequest,
        lease: PublicationActivationAuthorityLease,
    ) -> None:
        """Bind the immutable audit scope and activation cutoff to the fence."""

        if lease.database_alias != _DEFAULT_ALIAS:
            raise PublicationActivationError("authority lease database alias differs")
        scope = request.audit_observation.scope
        if scope is None:
            raise PublicationActivationError("publication audit scope is missing")
        if scope.tenant_id != lease.tenant_id or scope.owner_id != lease.owner_id:
            raise PublicationActivationError("publication audit scope differs from authority lease")

    @staticmethod
    def _validate_audit_observation(
        observation: DataPublicationAuditObservation,
        publication: CanonicalPublication,
        activation_at: datetime,
    ) -> None:
        """Require the prebuilt publication audit evidence to match the candidate."""

        if (
            observation.dataset_key != publication.dataset_key
            or observation.publication_key != publication.publication_key
            or observation.publication_id != publication.publication_id
            or observation.publication_version != publication.policy_version
            or observation.publication_hash != publication.publication_hash
            or observation.member_count != publication.member_count
            or observation.coverage_requested_count != publication.coverage.requested_count
            or observation.coverage_eligible_count != publication.coverage.eligible_count
            or observation.coverage_selected_count != publication.coverage.selected_count
            or observation.provider_key != publication.selected_source
            or observation.outcome is not AuditOutcome.PUBLISHED
            or observation.blocked_reason is not None
            or observation.error_class is not None
        ):
            raise PublicationActivationError("publication audit evidence differs from candidate")
        if (
            observation.occurred_at > activation_at
            or observation.recorded_at != activation_at
            or not publication.run_id
            or observation.run_id != publication.run_id
            or observation.raw_audit_version != "1"
        ):
            raise PublicationActivationError("publication audit timing or run evidence differs")
        if not observation.raw_audit_id.isdecimal() or int(observation.raw_audit_id) <= 0:
            raise PublicationActivationError("publication raw audit identity is invalid")
        raw_audit = (
            RawAuditModel._default_manager.select_for_update()
            .filter(pk=int(observation.raw_audit_id))
            .first()
        )
        if raw_audit is None:
            raise PublicationActivationError("publication raw audit evidence is missing")
        if (
            raw_audit.content_hash != observation.raw_audit_content_hash
            or (str(raw_audit.run_id) if raw_audit.run_id else "") != observation.run_id
            or (str(raw_audit.ingested_run_id) if raw_audit.ingested_run_id else "")
            != observation.ingested_run_id
            or raw_audit.provider_name != observation.provider_key
        ):
            raise PublicationActivationError("publication raw audit evidence drifted")

    @staticmethod
    def _member_model(member: PublicationMember) -> PublicationMemberModel:
        """Convert one domain member into an immutable ORM row."""

        return PublicationMemberModel(
            member_id=UUID(member.member_id),
            publication_id=UUID(member.publication_id),
            dataset_key=member.dataset_key,
            natural_key=member.natural_key,
            source=member.source,
            source_record_id=member.source_record_id,
            fact_table=member.fact_table,
            fact_pk=member.fact_pk,
            observed_at=member.observed_at,
            raw_payload_hash=member.raw_payload_hash,
            quality_status=member.quality_status,
            revision_number=member.revision_number,
            available_at=member.available_at,
            fetched_at=member.fetched_at,
            source_published_at=member.source_published_at,
            raw_payload_scope=member.raw_payload_scope,
            fact_content_hash=member.fact_content_hash,
        )

    @staticmethod
    def _validate_candidate_shape(
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
    ) -> None:
        """Validate exact candidate/member identity before any state change."""

        if (
            publication.as_of is None
            or publication.coverage.publication_id != publication.publication_id
        ):
            raise PublicationActivationError("candidate publication boundary is incomplete")
        if publication.member_count != len(members) or publication.coverage.selected_count != len(
            members
        ):
            raise PublicationActivationError("candidate member count is incomplete")
        if len({member.natural_key for member in members}) != len(members):
            raise PublicationActivationError("candidate member natural keys are not unique")
        if len({(member.fact_table, member.fact_pk) for member in members}) != len(members):
            raise PublicationActivationError("candidate fact references are not unique")
        for member in members:
            if (
                member.dataset_key != publication.dataset_key
                or member.publication_id != publication.publication_id
                or member.observed_at is None
                or member.observed_at > publication.as_of
            ):
                raise PublicationActivationError("candidate member scope is invalid")

    @staticmethod
    def _validate_fact_snapshot(
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
    ) -> None:
        """Recompute member hashes and the publication hash from exact fact rows."""

        fact_hashes = publication_fact_content_hashes(members, lock_rows=True)
        if any(
            fact_hashes.get((member.fact_table, member.fact_pk)) != member.fact_content_hash
            for member in members
        ):
            raise PublicationActivationError("candidate fact content hash drifted")
        references = [
            member_reference(member)
            for member in sorted(members, key=lambda item: item.natural_key)
        ]
        expected_hash = publication_hash(
            references,
            policy_identity=(
                publication.policy_version if publication.policy_version.startswith("p2:") else None
            ),
            scope_blocks=publication.scope_blocks,
        )
        if expected_hash != publication.publication_hash:
            raise PublicationActivationError("candidate publication hash drifted")

    @staticmethod
    def _validate_policy_snapshot(
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
        activated_at: datetime,
    ) -> None:
        """Revalidate current policy and evidence immediately before switching."""

        policy = PublicationPolicyRepository().get_locked_active(publication.dataset_key)
        if policy is None or policy.identity != publication.policy_version:
            raise PublicationActivationError("publication active policy changed")
        try:
            validate_publication_snapshot_policy(policy, publication, members=members)
            validate_publication_evidence(policy, members, published_at=activated_at)
        except (TypeError, ValueError) as error:
            raise PublicationActivationError("publication policy or evidence drifted") from error


__all__ = ["DjangoPublicationActivationRepository"]
