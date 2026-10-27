"""Required manifest and quality audit adapter for the M1 reference lane."""

from __future__ import annotations

from apps.data_center.application.publication_activation import (
    PublicationActivationError,
    PublicationActivationGroupAuditWriter,
    PublicationActivationGroupRequest,
    PublicationActivationManifestAuditWrite,
)
from apps.data_center.application.publication_quality import RecordPublicationQualityUseCase
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationMember
from apps.data_center.domain.publication_lanes import M1_REBALANCE_REFERENCE_PUBLICATION_KEY
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditReference,
)
from core.integration.data_center_audit import (
    DataPublicationManifestAuditObservation,
    DataPublicationRawAuditManifestReference,
    SystemAuditEventOutboxCommit,
)

_M1_DATASET_KEY = "equity.price.bar"


class M1ReferencePricePublicationAuditWriter(PublicationActivationGroupAuditWriter):
    """Append canonical manifest and quality audits for one M1 price publication."""

    def __init__(
        self,
        *,
        delegate: PublicationActivationGroupAuditWriter,
        quality_recorder: RecordPublicationQualityUseCase,
    ) -> None:
        """Bind both required writers to the activation transaction's database alias."""

        delegate_alias = getattr(delegate, "database_alias", None)
        quality_alias = getattr(quality_recorder, "database_alias", None)
        if (
            type(delegate_alias) is not str
            or not delegate_alias
            or delegate_alias.strip() != delegate_alias
            or delegate_alias != quality_alias
        ):
            raise PublicationActivationError(
                "M1 reference-price audit writers must share one database alias"
            )
        if not callable(getattr(delegate, "append_manifest_required", None)) or not callable(
            getattr(delegate, "append_manifest_group_required", None)
        ):
            raise PublicationActivationError("manifest activation audit delegate is unavailable")
        if not callable(getattr(quality_recorder, "execute", None)):
            raise PublicationActivationError("publication quality recorder is unavailable")
        self._delegate = delegate
        self._quality_recorder = quality_recorder
        self._database_alias = delegate_alias

    @property
    def database_alias(self) -> str:
        """Return the shared alias used by manifest and quality audit persistence."""

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
        """Reject a single-write path that could omit the required quality audit."""

        del request, publication, members, manifest, observation
        raise PublicationActivationError(
            "M1 reference-price quality audit requires group activation"
        )

    def append_manifest_group_required(
        self,
        *,
        request: PublicationActivationGroupRequest,
        writes: tuple[PublicationActivationManifestAuditWrite, ...],
    ) -> tuple[SystemAuditEventOutboxCommit, ...]:
        """Append manifest evidence, then record quality within the caller's atomic UOW."""

        publication, raw_reference = self._validate_group(request, writes)
        commits = self._delegate.append_manifest_group_required(request=request, writes=writes)
        if type(commits) is not tuple or len(commits) != 1:
            raise PublicationActivationError(
                "M1 reference-price manifest audit returned an invalid commit group"
            )
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
    ) -> tuple[CanonicalPublication, CandidateRawAuditReference]:
        """Require one exact M1 candidate bound to one validated RawAudit lineage."""

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
                "M1 reference-price activation requires one exact candidate and manifest"
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
            or len(write.members) != 1
            or len(write.members) != publication.member_count
            or any(type(member) is not PublicationMember for member in write.members)
        ):
            raise PublicationActivationError("M1 reference-price publication evidence is invalid")

        if (
            candidate.candidate_publication_id != publication.publication_id
            or candidate.candidate_publication_hash != publication.publication_hash
            or publication.dataset_key != _M1_DATASET_KEY
            or publication.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
            or not publication.selected_source
            or manifest.publication_id != publication.publication_id
            or manifest.publication_hash != publication.publication_hash
            or manifest.run_id != publication.run_id
            or manifest.dataset_key != publication.dataset_key
            or manifest.publication_key != publication.publication_key
        ):
            raise PublicationActivationError(
                "M1 reference-price publication or RawAudit identity differs"
            )
        if manifest.raw_audit_count != 1 or len(manifest.raw_audits) != 1:
            raise PublicationActivationError(
                "M1 reference-price manifest must contain exactly one RawAudit"
            )

        raw_reference = manifest.raw_audits[0]
        expected_audit_reference = DataPublicationRawAuditManifestReference(
            raw_audit_id=raw_reference.raw_audit_id,
            version=raw_reference.version,
            content_hash=raw_reference.content_hash,
        )
        if (
            observation.dataset_key != publication.dataset_key
            or observation.publication_key != publication.publication_key
            or observation.publication_id != publication.publication_id
            or observation.publication_version != publication.policy_version
            or observation.publication_hash != publication.publication_hash
            or observation.provider_key != publication.selected_source
            or observation.run_id != publication.run_id
            or observation.manifest_id != manifest.manifest_id
            or observation.manifest_version != manifest.manifest_version
            or observation.manifest_hash != manifest.manifest_hash
            or observation.raw_audit_count != 1
            or observation.raw_audit_hash != manifest.raw_audit_hash
            or observation.raw_audits != (expected_audit_reference,)
            or any(
                member.publication_id != publication.publication_id
                or member.dataset_key != publication.dataset_key
                for member in write.members
            )
        ):
            raise PublicationActivationError(
                "M1 reference-price manifest observation or member lineage differs"
            )

        return publication, raw_reference


__all__ = ["M1ReferencePricePublicationAuditWriter"]
