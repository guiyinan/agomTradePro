"""Infrastructure for atomic quote, price, and valuation group activation."""

from __future__ import annotations

from typing import Final
from uuid import UUID

from django.db import connections
from django.db.models import Q
from django.utils import timezone

from apps.data_center.application.publication_activation import (
    PublicationActivationAuthorityFence,
    PublicationActivationAuthorityLease,
    PublicationActivationError,
    PublicationActivationGroupAuditWriter,
    PublicationActivationGroupRequest,
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
from apps.data_center.domain.raw_audit_manifest import CandidateRawAuditManifestError

from .publication_group_activation_evidence import (
    PublicationGroupActivationEvidenceRepository,
)
from .publication_group_activation_state import PublicationGroupActivationStateWriter
from .publication_member_store import publication_fact_content_hashes_and_ingested_runs
from .publication_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)

_DEFAULT_ALIAS: Final[str] = "default"
_CANDIDATE_STATES: Final[frozenset[str]] = frozenset(
    {PublicationState.CANDIDATE.value, PublicationState.PUBLISHED.value}
)


class DjangoPublicationActivationGroupRepository:
    """Validate and switch all three current market publications atomically."""

    def __init__(self, *, using: str = _DEFAULT_ALIAS) -> None:
        """Bind group activation to the Account fence's database alias."""

        if using != _DEFAULT_ALIAS:
            raise ValueError("publication activation currently requires the default database alias")
        self._using = using

    @property
    def database_alias(self) -> str:
        """Return the database alias shared by the complete activation UOW."""

        return self._using

    def activate_candidate_group(
        self,
        request: PublicationActivationGroupRequest,
        *,
        audit_writer: PublicationActivationGroupAuditWriter,
        authority_fence: PublicationActivationAuthorityFence,
        authority_proof: object,
    ) -> tuple[CanonicalPublication, ...]:
        """Atomically activate price, quote, and valuation under one Account fence."""

        if type(request) is not PublicationActivationGroupRequest:
            raise PublicationActivationError("group activation request is invalid")
        connection = connections[self._using]
        if connection.in_atomic_block:
            raise PublicationActivationError("group activation cannot join an ambient transaction")
        if getattr(audit_writer, "database_alias", None) != self._using:
            raise PublicationActivationError("group audit writer database alias differs")
        if not callable(getattr(audit_writer, "append_manifest_required", None)):
            raise PublicationActivationError("manifest-bound group audit writer is unavailable")
        if not callable(getattr(authority_fence, "fence_complete", None)):
            raise PublicationActivationError("complete authority fence is unavailable")
        try:
            with authority_fence.fence_complete(authority_proof) as graph_result:
                lease = publication_activation_lease_from_complete_graph(graph_result)
                if type(lease) is not PublicationActivationAuthorityLease:
                    raise PublicationActivationError("authority lease projection is invalid")
                if lease.database_alias != self._using:
                    raise PublicationActivationError("authority lease database alias differs")
                return self._activate_candidate_group_in_transaction(
                    request,
                    audit_writer,
                    lease,
                )
        except PublicationActivationError:
            raise
        except (CandidateRawAuditManifestError, TypeError, ValueError) as error:
            raise PublicationActivationError(
                "complete authority fence rejected group activation"
            ) from error

    def _activate_candidate_group_in_transaction(
        self,
        request: PublicationActivationGroupRequest,
        audit_writer: PublicationActivationGroupAuditWriter,
        lease: PublicationActivationAuthorityLease,
    ) -> tuple[CanonicalPublication, ...]:
        """Lock and validate the full group before writing any current state."""

        connection = connections[self._using]
        atomic_blocks = getattr(connection, "atomic_blocks", None)
        if (
            not connection.in_atomic_block
            or connection.get_autocommit()
            or not isinstance(atomic_blocks, list)
            or len(atomic_blocks) != 1
        ):
            raise PublicationActivationError(
                "group activation requires the complete fence's outermost transaction"
            )
        if lease.checked_at >= lease.valid_until or timezone.now() >= lease.valid_until:
            raise PublicationActivationError("complete authority lease expired")

        scope_filter = Q()
        for item in request.candidates:
            scope_filter |= Q(dataset_key=item.dataset_key, publication_key=item.publication_key)
        pointers = list(
            CanonicalPublicationPointerModel._default_manager.using(self._using)
            .select_for_update()
            .filter(scope_filter)
            .order_by("dataset_key", "publication_key", "pointer_id")
        )
        if len(pointers) != len(request.candidates):
            raise PublicationActivationError("one or more current publication pointers are missing")
        pointers_by_scope = {(row.dataset_key, row.publication_key): row for row in pointers}

        request_by_id = {item.candidate_publication_id: item for item in request.candidates}
        candidate_ids = tuple(sorted(UUID(item) for item in request_by_id))
        candidate_rows = list(
            CanonicalPublicationModel._default_manager.using(self._using)
            .select_for_update()
            .filter(publication_id__in=candidate_ids)
            .order_by("publication_id")
        )
        if len(candidate_rows) != len(request.candidates):
            raise PublicationActivationError("one or more group candidates are missing")
        candidates_by_id = {str(row.publication_id): row for row in candidate_rows}

        same_current_by_id: dict[str, bool] = {}
        for item in request.candidates:
            pointer = pointers_by_scope.get((item.dataset_key, item.publication_key))
            candidate = candidates_by_id.get(item.candidate_publication_id)
            if pointer is None or candidate is None:
                raise PublicationActivationError("group publication identities are incomplete")
            if (
                candidate.dataset_key != item.dataset_key
                or candidate.publication_key != item.publication_key
                or candidate.publication_hash != item.candidate_publication_hash
                or candidate.state not in _CANDIDATE_STATES
                or candidate.must_not_use_for_decision
            ):
                raise PublicationActivationError("group candidate identity drifted")
            same_current = (
                pointer.publication_id == candidate.publication_id
                and pointer.publication_hash == candidate.publication_hash
            )
            same_current_by_id[item.candidate_publication_id] = same_current
            if same_current:
                if (
                    candidate.state != PublicationState.PUBLISHED.value
                    or pointer.activation_id != request.activation_id
                    or candidate.published_at is None
                    or candidate.published_at > lease.checked_at
                ):
                    raise PublicationActivationError("current group candidate identity differs")
            else:
                if candidate.state == PublicationState.PUBLISHED.value:
                    raise PublicationActivationError(
                        "published group candidate is not its current pointer target"
                    )
                if pointer.publication_id is None:
                    if pointer.publication_hash or pointer.activation_id:
                        raise PublicationActivationError(
                            "empty current pointer contains stale activation identity"
                        )
                    if any(
                        value is not None
                        for value in (
                            item.expected_current_publication_id,
                            item.expected_current_publication_hash,
                        )
                    ):
                        raise PublicationActivationError(
                            "empty current pointer compare-and-swap failed"
                        )
                elif (
                    item.expected_current_publication_id != str(pointer.publication_id)
                    or item.expected_current_publication_hash != pointer.publication_hash
                ):
                    raise PublicationActivationError(
                        "current publication pointer compare-and-swap failed"
                    )

        same_current_count = sum(same_current_by_id.values())
        if same_current_count not in {0, len(request.candidates)}:
            raise PublicationActivationError("group activation contains a partially current set")
        if same_current_count:
            activation_times = {
                candidates_by_id[item.candidate_publication_id].published_at
                for item in request.candidates
            }
            if len(activation_times) != 1 or None in activation_times:
                raise PublicationActivationError("current group activation clocks differ")
            activation_at = next(iter(activation_times))
            if activation_at is None:
                raise PublicationActivationError("current group activation clock is missing")
        else:
            activation_at = lease.checked_at

        same_current_by_scope = {
            (item.dataset_key, item.publication_key): same_current_by_id[
                item.candidate_publication_id
            ]
            for item in request.candidates
        }
        previous_ids = tuple(
            sorted(
                {
                    pointer.publication_id
                    for pointer in pointers
                    if pointer.publication_id is not None
                    and not same_current_by_scope[(pointer.dataset_key, pointer.publication_key)]
                }
            )
        )
        previous_rows = list(
            CanonicalPublicationModel._default_manager.using(self._using)
            .select_for_update()
            .filter(publication_id__in=previous_ids)
            .order_by("publication_id")
        )
        previous_by_id = {str(row.publication_id): row for row in previous_rows}
        for item in request.candidates:
            if same_current_by_id[item.candidate_publication_id]:
                continue
            pointer = pointers_by_scope[(item.dataset_key, item.publication_key)]
            if pointer.publication_id is None:
                continue
            previous = previous_by_id.get(str(pointer.publication_id))
            if (
                previous is None
                or previous.dataset_key != item.dataset_key
                or previous.publication_key != item.publication_key
                or previous.state != PublicationState.PUBLISHED.value
                or previous.publication_hash != pointer.publication_hash
            ):
                raise PublicationActivationError(
                    "current publication pointer target is missing or drifted"
                )
            if previous.published_at is None or previous.published_at >= activation_at:
                raise PublicationActivationError(
                    "group activation publication time is not monotonic"
                )

        candidate_uuids = tuple(UUID(item) for item in request_by_id)
        member_rows = list(
            PublicationMemberModel._default_manager.using(self._using)
            .select_for_update()
            .filter(publication_id__in=candidate_uuids)
            .order_by("publication_id", "natural_key", "member_id")
        )
        members_by_id_lists: dict[str, list[PublicationMember]] = {
            candidate_id: [] for candidate_id in request_by_id
        }
        for row in member_rows:
            candidate_id = str(row.publication_id)
            members_by_id_lists[candidate_id].append(row.to_domain())
        members_by_id = {
            candidate_id: tuple(members) for candidate_id, members in members_by_id_lists.items()
        }
        member_values = tuple(member for group in members_by_id.values() for member in group)
        fact_hashes, fact_ingested_runs = publication_fact_content_hashes_and_ingested_runs(
            member_values,
            lock_rows=True,
        )

        coverage_rows = list(
            CoverageSnapshotModel._default_manager.using(self._using)
            .select_for_update()
            .filter(publication_id__in=candidate_uuids)
            .order_by("publication_id")
        )
        if len(coverage_rows) != len(request.candidates):
            raise PublicationActivationError("group candidate coverage is incomplete")
        coverage_by_id = {str(row.publication_id): row for row in coverage_rows}

        validated_publications: dict[str, CanonicalPublication] = {}
        for candidate_id, _item in request_by_id.items():
            candidate = candidates_by_id[candidate_id]
            publication = candidate.to_domain()
            members = members_by_id[candidate_id]
            self._validate_candidate_shape(publication, members)
            if candidate.members_sealed_at is None or not candidate.member_manifest_hash:
                raise PublicationActivationError("group candidate member manifest is not sealed")
            if candidate.member_manifest_hash != publication_member_manifest_hash(
                members,
                policy_identity=candidate.policy_version,
            ):
                raise PublicationActivationError("group candidate member manifest drifted")
            coverage = coverage_by_id[candidate_id]
            if (
                coverage.requested_count != candidate.coverage_requested_count
                or coverage.eligible_count != candidate.coverage_eligible_count
                or coverage.selected_count != candidate.coverage_selected_count
                or coverage.missing_count != candidate.coverage_missing_count
                or coverage.conflict_count != candidate.coverage_conflict_count
            ):
                raise PublicationActivationError("group candidate coverage snapshot drifted")
            if publication.as_of is None or publication.as_of > activation_at:
                raise PublicationActivationError("group candidate time boundary is invalid")
            for member in members:
                fact_key = (member.fact_table, member.fact_pk)
                if fact_hashes.get(fact_key) != member.fact_content_hash:
                    raise PublicationActivationError("group candidate fact content hash drifted")
                if fact_key not in fact_ingested_runs:
                    raise PublicationActivationError("group candidate fact row is missing")
            expected_hash = publication_hash(
                [
                    member_reference(member)
                    for member in sorted(members, key=lambda value: value.natural_key)
                ],
                policy_identity=(
                    publication.policy_version
                    if publication.policy_version.startswith("p2:")
                    else None
                ),
                scope_blocks=publication.scope_blocks,
            )
            if expected_hash != publication.publication_hash:
                raise PublicationActivationError("group candidate publication hash drifted")
            validated_publications[candidate_id] = publication

        manifests_by_publication, observations_by_id = PublicationGroupActivationEvidenceRepository(
            using=self._using
        ).validate(
            request=request,
            publications=validated_publications,
            members_by_id=members_by_id,
            fact_ingested_runs=fact_ingested_runs,
            candidates_by_id=candidates_by_id,
            same_current_by_id=same_current_by_id,
            activation_at=activation_at,
            lease=lease,
        )

        PublicationGroupActivationStateWriter().switch_group_publications(
            request=request,
            candidates_by_id=candidates_by_id,
            pointers_by_scope=pointers_by_scope,
            previous_by_id=previous_by_id,
            same_current_by_id=same_current_by_id,
            activation_at=activation_at,
        )
        for item in request.candidates:
            candidate_id = item.candidate_publication_id
            publication = validated_publications[candidate_id]
            manifest = manifests_by_publication[candidate_id]
            observation = observations_by_id[candidate_id]
            PublicationGroupActivationStateWriter().append_required_manifest_audit(
                request=request,
                audit_writer=audit_writer,
                publication=publication,
                members=members_by_id[candidate_id],
                manifest=manifest,
                observation=observation,
            )
        return tuple(
            candidates_by_id[item.candidate_publication_id].to_domain()
            for item in request.candidates
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


__all__ = ["DjangoPublicationActivationGroupRepository"]
