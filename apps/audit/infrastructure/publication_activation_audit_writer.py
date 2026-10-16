"""Caller-owned audit adapter for the feature-off publication activation path."""

from __future__ import annotations

from datetime import datetime

from apps.audit.application.data_publication_audit import (
    AppendDataPublicationAuditObservationUseCase,
    VerifyDataPublicationManifestGroupUseCase,
)
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCorruption
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_repository import (
    SystemAuditCorruption,
    SystemAuditUnavailable,
)
from apps.data_center.application.publication_activation import (
    PublicationActivationAuditWriter,
    PublicationActivationGroupAuditWriter,
    PublicationActivationGroupRequest,
    PublicationActivationManifestAuditWrite,
    PublicationActivationRequest,
)
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationMember
from apps.data_center.domain.raw_audit_manifest import CandidateRawAuditManifest
from core.integration.data_center_audit import (
    DataPublicationAuditObservation,
    DataPublicationManifestAuditObservation,
    SystemAuditEventOutboxCommit,
)


class _CallerOwnedScopeProvider:
    """Reject accidental use of the scope resolving API on this adapter."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Require activation to provide its already-fenced scope explicitly."""

        del as_of
        raise RuntimeError("publication activation audit requires the caller-owned path")


class DjangoPublicationActivationAuditWriter(
    PublicationActivationAuditWriter,
    PublicationActivationGroupAuditWriter,
):
    """Write the required event and outbox row in activation's outer UOW."""

    def __init__(
        self,
        coordinator: DjangoSystemAuditEventOutboxCoordinator,
    ) -> None:
        if not isinstance(coordinator, DjangoSystemAuditEventOutboxCoordinator):
            raise TypeError("publication activation requires the canonical audit coordinator")
        self._coordinator = coordinator
        self._use_case = AppendDataPublicationAuditObservationUseCase(
            coordinator,
            _CallerOwnedScopeProvider(),
        )

    @property
    def database_alias(self) -> str:
        """Return the alias shared by publication and audit persistence."""

        return self._coordinator.database_alias

    def append_required(
        self,
        *,
        request: PublicationActivationRequest,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
        observation: DataPublicationAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Append one exact activation observation with no nested transaction."""

        del request, publication, members
        return self._use_case.execute_in_caller_transaction(observation)

    def append_manifest_required(
        self,
        *,
        request: PublicationActivationGroupRequest,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
        manifest: CandidateRawAuditManifest,
        observation: DataPublicationManifestAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Append one exact manifest-bound activation event in the outer UOW."""

        if (
            manifest.publication_id != publication.publication_id
            or observation.publication_id != publication.publication_id
            or observation.manifest_id != manifest.manifest_id
            or observation.manifest_hash != manifest.manifest_hash
            or len(members) != publication.member_count
            or not any(
                candidate.candidate_publication_id == publication.publication_id
                for candidate in request.candidates
            )
        ):
            raise ValueError("manifest activation audit input differs from the exact candidate")
        return self._use_case.execute_manifest_in_caller_transaction(observation)

    def append_manifest_group_required(
        self,
        *,
        request: PublicationActivationGroupRequest,
        writes: tuple[PublicationActivationManifestAuditWrite, ...],
    ) -> tuple[SystemAuditEventOutboxCommit, ...]:
        """Append the exact activation group's manifest events in one caller UOW."""

        candidate_ids = tuple(item.candidate_publication_id for item in request.candidates)
        if (
            len(writes) != len(candidate_ids)
            or tuple(write.publication.publication_id for write in writes) != candidate_ids
        ):
            raise ValueError("manifest activation audit group differs from the request")
        for write in writes:
            write.__post_init__()
            if (
                write.observation.manifest_id != write.manifest.manifest_id
                or write.observation.manifest_hash != write.manifest.manifest_hash
            ):
                raise ValueError("manifest activation audit input differs from the exact candidate")
        return self._use_case.execute_manifest_group_in_caller_transaction(
            tuple(write.observation for write in writes)
        )


class DjangoPublicationActivationAuditVerifier:
    """Read and validate an already committed execution activation audit pair."""

    def __init__(
        self,
        coordinator: DjangoSystemAuditEventOutboxCoordinator,
    ) -> None:
        """Bind read-only completion checks to the canonical same-alias coordinator."""

        if not isinstance(coordinator, DjangoSystemAuditEventOutboxCoordinator):
            raise TypeError(
                "publication activation verification requires the canonical coordinator"
            )
        self._coordinator = coordinator
        self._use_case = VerifyDataPublicationManifestGroupUseCase(coordinator)

    @property
    def database_alias(self) -> str:
        """Return the database alias used by the exact event/outbox selectors."""

        return self._coordinator.database_alias

    def verify_manifest_group_required(
        self,
        *,
        request: PublicationActivationGroupRequest,
        writes: tuple[PublicationActivationManifestAuditWrite, ...],
    ) -> tuple[SystemAuditEventOutboxCommit, ...]:
        """Verify only a single completed execution quote and never append or repair."""

        candidate_ids = tuple(item.candidate_publication_id for item in request.candidates)
        if (
            not request.is_execution_quote_activation
            or len(candidate_ids) != 1
            or len(writes) != 1
            or tuple(write.publication.publication_id for write in writes) != candidate_ids
        ):
            raise ValueError("completion verification requires one exact execution quote")
        write = writes[0]
        write.__post_init__()
        if (
            write.publication.state.value != "published"
            or write.publication.dataset_key != "equity.quote.snapshot"
            or write.publication.publication_key != "execution"
            or write.manifest.publication_id != write.publication.publication_id
            or write.manifest.publication_hash != write.publication.publication_hash
            or write.manifest.run_id != write.publication.run_id
            or write.manifest.dataset_key != write.publication.dataset_key
            or write.manifest.publication_key != write.publication.publication_key
            or write.observation.publication_id != write.publication.publication_id
            or write.observation.manifest_id != write.manifest.manifest_id
            or write.observation.manifest_hash != write.manifest.manifest_hash
            or write.observation.recorded_at != write.publication.published_at
            or write.observation.run_id != write.publication.run_id
        ):
            raise ValueError("completion audit evidence differs from the exact publication")
        try:
            return self._use_case.execute_manifest_group_in_caller_transaction((write.observation,))
        except (SystemAuditCorruption, SystemAuditUnavailable) as error:
            raise SystemAuditEventOutboxCorruption(
                "completed Audit evidence cannot be restored in its original scope"
            ) from error


__all__ = [
    "DjangoPublicationActivationAuditVerifier",
    "DjangoPublicationActivationAuditWriter",
]
