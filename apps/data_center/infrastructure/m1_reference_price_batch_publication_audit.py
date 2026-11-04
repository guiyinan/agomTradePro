"""Required group audit adapter for one explicit multi-security M1 snapshot."""

from __future__ import annotations

from apps.data_center.application.publication_activation import (
    PublicationActivationError,
    PublicationActivationGroupAuditWriter,
    PublicationActivationGroupRequest,
    PublicationActivationManifestAuditWrite,
)
from apps.data_center.application.publication_quality import RecordPublicationQualityUseCase
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.publication_lanes import M1_REBALANCE_REFERENCE_PUBLICATION_KEY
from apps.data_center.domain.raw_audit_manifest import CandidateRawAuditManifest
from core.integration.data_center_audit import (
    DataPublicationManifestAuditObservation,
    DataPublicationRawAuditManifestReference,
    SystemAuditEventOutboxCommit,
)

_M1_DATASET_KEY = "equity.price.bar"


class M1ReferencePriceBatchPublicationAuditWriter(PublicationActivationGroupAuditWriter):
    """Audit a multi-member M1 candidate without weakening the single-member writer."""

    def __init__(
        self,
        *,
        delegate: PublicationActivationGroupAuditWriter,
        quality_recorder: RecordPublicationQualityUseCase,
    ) -> None:
        """Bind the manifest and quality audit writers to one transaction alias."""

        delegate_alias = getattr(delegate, "database_alias", None)
        quality_alias = getattr(quality_recorder, "database_alias", None)
        if (
            type(delegate_alias) is not str
            or not delegate_alias
            or delegate_alias.strip() != delegate_alias
            or delegate_alias != quality_alias
        ):
            raise PublicationActivationError("M1 batch audit writers must share one database alias")
        if not callable(getattr(delegate, "append_manifest_group_required", None)):
            raise PublicationActivationError("manifest activation audit delegate is unavailable")
        if not callable(getattr(quality_recorder, "execute", None)):
            raise PublicationActivationError("publication quality recorder is unavailable")
        self._delegate = delegate
        self._quality_recorder = quality_recorder
        self._database_alias = delegate_alias

    @property
    def database_alias(self) -> str:
        """Return the shared database alias used by both required audit writers."""

        return self._database_alias

    def append_manifest_required(
        self,
        *,
        request: PublicationActivationGroupRequest,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
        manifest: CandidateRawAuditManifest,
        observation: DataPublicationManifestAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Reject activation paths that could bypass the atomic group contract."""

        del request, publication, members, manifest, observation
        raise PublicationActivationError("M1 batch publication requires group activation")

    def append_manifest_group_required(
        self,
        *,
        request: PublicationActivationGroupRequest,
        writes: tuple[PublicationActivationManifestAuditWrite, ...],
    ) -> tuple[SystemAuditEventOutboxCommit, ...]:
        """Append one complete manifest and each source-lineage quality audit."""

        publication, manifest = self._validate_group(request, writes)
        commits = self._delegate.append_manifest_group_required(
            request=request,
            writes=writes,
        )
        if type(commits) is not tuple or len(commits) != 1:
            raise PublicationActivationError(
                "M1 batch manifest audit returned an invalid commit group"
            )
        for raw_reference in manifest.raw_audits:
            self._quality_recorder.execute(
                publication_id=publication.publication_id,
                run_id=raw_reference.run_id,
                ingested_run_id=raw_reference.ingested_run_id,
                provider_key=publication.selected_source,
            )
        return commits

    @staticmethod
    def _validate_group(
        request: PublicationActivationGroupRequest,
        writes: tuple[PublicationActivationManifestAuditWrite, ...],
    ) -> tuple[CanonicalPublication, CandidateRawAuditManifest]:
        """Require one exact candidate, all members, and every bound RawAudit."""

        if (
            type(request) is not PublicationActivationGroupRequest
            or len(request.candidates) != 1
            or request.candidates[0].dataset_key != _M1_DATASET_KEY
            or request.candidates[0].publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
            or type(writes) is not tuple
            or len(writes) != 1
            or type(writes[0]) is not PublicationActivationManifestAuditWrite
        ):
            raise PublicationActivationError(
                "M1 batch activation requires one exact candidate and manifest"
            )

        write = writes[0]
        publication = write.publication
        manifest = write.manifest
        observation = write.observation
        candidate = request.candidates[0]
        if (
            type(publication) is not CanonicalPublication
            or type(manifest) is not CandidateRawAuditManifest
            or type(observation) is not DataPublicationManifestAuditObservation
            or type(write.members) is not tuple
            or any(type(member) is not PublicationMember for member in write.members)
        ):
            raise PublicationActivationError("M1 batch publication evidence is incomplete")
        member_count = publication.member_count
        if member_count < 2 or len(write.members) != member_count:
            raise PublicationActivationError("M1 batch publication evidence is incomplete")
        if (
            candidate.candidate_publication_id != publication.publication_id
            or candidate.candidate_publication_hash != publication.publication_hash
            or publication.dataset_key != _M1_DATASET_KEY
            or publication.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
            or publication.state not in (PublicationState.CANDIDATE, PublicationState.PUBLISHED)
            or publication.selected_source != "tushare"
            or publication.must_not_use_for_decision
            or publication.conflict_count != 0
            or publication.scope_blocks
            or manifest.publication_id != publication.publication_id
            or manifest.publication_hash != publication.publication_hash
            or manifest.run_id != publication.run_id
            or manifest.dataset_key != publication.dataset_key
            or manifest.publication_key != publication.publication_key
            or manifest.raw_audit_count != member_count
            or len(manifest.raw_audits) != member_count
            or publication.coverage.requested_count != member_count
            or publication.coverage.publication_id != publication.publication_id
            or publication.coverage.eligible_count != member_count
            or publication.coverage.selected_count != member_count
            or publication.coverage.missing_count != 0
            or publication.coverage.conflict_count != 0
        ):
            raise PublicationActivationError("M1 batch publication or RawAudit identity differs")

        expected_audits = tuple(
            DataPublicationRawAuditManifestReference(
                raw_audit_id=item.raw_audit_id,
                version=item.version,
                content_hash=item.content_hash,
            )
            for item in manifest.raw_audits
        )
        if (
            observation.dataset_key != publication.dataset_key
            or observation.publication_key != publication.publication_key
            or observation.publication_id != publication.publication_id
            or observation.publication_version != publication.policy_version
            or observation.publication_hash != publication.publication_hash
            or observation.provider_key != publication.selected_source
            or observation.run_id != publication.run_id
            or observation.member_count != member_count
            or observation.coverage_requested_count != publication.coverage.requested_count
            or observation.coverage_eligible_count != publication.coverage.eligible_count
            or observation.coverage_selected_count != publication.coverage.selected_count
            or observation.manifest_id != manifest.manifest_id
            or observation.manifest_version != manifest.manifest_version
            or observation.manifest_hash != manifest.manifest_hash
            or observation.raw_audit_count != manifest.raw_audit_count
            or observation.raw_audit_hash != manifest.raw_audit_hash
            or observation.raw_audits != expected_audits
        ):
            raise PublicationActivationError("M1 batch audit observation differs from its manifest")
        members = write.members
        if (
            any(
                member.publication_id != publication.publication_id
                or member.dataset_key != publication.dataset_key
                or member.source != publication.selected_source
                for member in members
            )
            or len({member.natural_key for member in members}) != member_count
            or any(
                raw_reference.capability != DataCapability.HISTORICAL_PRICE.value
                for raw_reference in manifest.raw_audits
            )
            or len({raw_reference.provider_name for raw_reference in manifest.raw_audits}) != 1
        ):
            raise PublicationActivationError(
                "M1 batch members or source lineage differs from its manifest"
            )
        return publication, manifest


__all__ = ["M1ReferencePriceBatchPublicationAuditWriter"]
