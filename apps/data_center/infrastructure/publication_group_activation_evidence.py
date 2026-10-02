"""Locked manifest, source-lineage, policy, and freshness validation for group activation."""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from django.db import connections

from apps.data_center.application.publication_activation import (
    PublicationActivationAuthorityLease,
    PublicationActivationError,
    PublicationActivationGroupRequest,
)
from apps.data_center.domain.contracts import PublicationPolicy
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationMember
from apps.data_center.domain.entities import raw_audit_content_hash
from apps.data_center.domain.publication_evidence import validate_publication_evidence
from apps.data_center.domain.publication_snapshot_policy import (
    validate_publication_snapshot_policy,
)
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditManifestError,
    CandidateRawAuditReference,
    canonical_capability_for_publication_dataset,
    validate_raw_audit_source_type,
)
from core.integration.data_center_audit import (
    AuditScopeRef,
    DataPublicationManifestAuditObservation,
    DataPublicationRawAuditManifestReference,
)

from .candidate_raw_audit_manifest_models import (
    CandidateRawAuditManifestMemberModel,
    CandidateRawAuditManifestModel,
)
from .catalog_models import DatasetPublicationPolicyModel
from .fact_and_operational_models import RawAuditModel
from .provider_state_repositories import RawAuditRepository
from .publication_models import CanonicalPublicationModel

_DEFAULT_ALIAS: Final[str] = "default"


class PublicationGroupActivationEvidenceRepository:
    """Lock and validate candidate manifests and the policy-bound fact evidence."""

    def __init__(self, *, using: str = _DEFAULT_ALIAS) -> None:
        """Bind group evidence reads to the activation database."""

        if using != _DEFAULT_ALIAS:
            raise ValueError("publication activation currently requires the default database alias")
        self._using = using

    def validate(
        self,
        *,
        request: PublicationActivationGroupRequest,
        publications: dict[str, CanonicalPublication],
        members_by_id: dict[str, tuple[PublicationMember, ...]],
        fact_ingested_runs: dict[tuple[str, str], str | None],
        candidates_by_id: dict[str, CanonicalPublicationModel],
        same_current_by_id: dict[str, bool],
        activation_at: datetime,
        lease: PublicationActivationAuthorityLease,
    ) -> tuple[
        dict[str, CandidateRawAuditManifest],
        dict[str, DataPublicationManifestAuditObservation],
    ]:
        """Validate all locked evidence before any pointer or publication write."""

        manifests = self._lock_and_validate_group_manifests(
            request=request,
            publications=publications,
            members_by_id=members_by_id,
            fact_ingested_runs=fact_ingested_runs,
        )
        policies = self._lock_group_policies(request)
        observations: dict[str, DataPublicationManifestAuditObservation] = {}
        for item in request.candidates:
            candidate_id = item.candidate_publication_id
            publication = publications[candidate_id]
            manifest = manifests[candidate_id]
            policy = policies[item.dataset_key]
            try:
                if policy.identity != publication.policy_version:
                    raise ValueError("publication active policy changed")
                validate_publication_snapshot_policy(
                    policy,
                    publication,
                    members=members_by_id[candidate_id],
                )
                validate_publication_evidence(
                    policy,
                    members_by_id[candidate_id],
                    published_at=activation_at,
                )
            except (TypeError, ValueError) as error:
                raise PublicationActivationError(
                    "group publication policy or freshness evidence drifted"
                ) from error
            recorded_at = (
                candidates_by_id[candidate_id].published_at
                if same_current_by_id[candidate_id]
                else activation_at
            )
            if recorded_at is None:
                raise PublicationActivationError("group activation timestamp is missing")
            observations[candidate_id] = self._manifest_audit_observation(
                publication=publication,
                manifest=manifest,
                recorded_at=recorded_at,
                lease=lease,
            )
        return manifests, observations

    def _lock_and_validate_group_manifests(
        self,
        *,
        request: PublicationActivationGroupRequest,
        publications: dict[str, CanonicalPublication],
        members_by_id: dict[str, tuple[PublicationMember, ...]],
        fact_ingested_runs: dict[tuple[str, str], str | None],
    ) -> dict[str, CandidateRawAuditManifest]:
        """Lock complete manifest graphs and close source lineage in both directions."""

        publication_ids = tuple(UUID(item.candidate_publication_id) for item in request.candidates)
        headers = list(
            CandidateRawAuditManifestModel._default_manager.using(self._using)
            .select_for_update()
            .filter(publication_id__in=publication_ids)
            .order_by("publication_id", "manifest_id")
        )
        if len(headers) != len(request.candidates):
            raise PublicationActivationError("one or more candidate RawAudit manifests are missing")
        header_by_publication = {
            str(header_row.publication_id): header_row for header_row in headers
        }
        manifest_ids = tuple(header_row.manifest_id for header_row in headers)
        children = list(
            CandidateRawAuditManifestMemberModel._default_manager.using(self._using)
            .select_for_update()
            .filter(manifest_id__in=manifest_ids)
            .order_by("manifest_id", "ordinal", "id")
        )
        children_by_manifest: dict[str, list[CandidateRawAuditReference]] = {
            str(row.manifest_id): [] for row in headers
        }
        ordinals_by_manifest: dict[str, list[int]] = {str(row.manifest_id): [] for row in headers}
        references_by_raw_id: dict[int, CandidateRawAuditReference] = {}
        for child_row in children:
            manifest_id = str(child_row.manifest_id)
            reference = CandidateRawAuditReference(
                raw_audit_id=str(child_row.raw_audit_id),
                version=child_row.raw_audit_version,
                content_hash=child_row.raw_audit_content_hash,
                provider_name=child_row.provider_name,
                capability=child_row.capability,
                run_id=str(child_row.run_id),
                ingested_run_id=str(child_row.ingested_run_id),
            )
            existing_reference = references_by_raw_id.get(child_row.raw_audit_id)
            if existing_reference is not None and existing_reference != reference:
                raise PublicationActivationError(
                    "shared RawAudit manifest references disagree on immutable identity"
                )
            references_by_raw_id[child_row.raw_audit_id] = reference
            children_by_manifest[manifest_id].append(reference)
            ordinals_by_manifest[manifest_id].append(child_row.ordinal)

        manifests: dict[str, CandidateRawAuditManifest] = {}
        for item in request.candidates:
            publication_id = item.candidate_publication_id
            publication = publications[publication_id]
            header = header_by_publication.get(publication_id)
            if header is None:
                raise PublicationActivationError("candidate RawAudit manifest header is missing")
            references = tuple(children_by_manifest[str(header.manifest_id)])
            ordinals = tuple(ordinals_by_manifest[str(header.manifest_id)])
            if ordinals != tuple(range(len(references))):
                raise PublicationActivationError(
                    "candidate RawAudit manifest child ordinals drifted"
                )
            try:
                manifest = CandidateRawAuditManifest(
                    manifest_id=str(header.manifest_id),
                    manifest_version=header.manifest_version,
                    publication_id=str(header.publication_id),
                    publication_hash=header.publication_hash,
                    run_id=str(header.run_id),
                    dataset_key=header.dataset_key,
                    publication_key=header.publication_key,
                    task_attempt_id=header.task_attempt_id,
                    raw_audits=references,
                    raw_audit_count=header.raw_audit_count,
                    raw_audit_hash=header.raw_audit_hash,
                    manifest_hash=header.manifest_hash,
                )
            except CandidateRawAuditManifestError as error:
                raise PublicationActivationError(
                    "candidate RawAudit manifest seal is invalid"
                ) from error
            if (
                manifest.publication_id != publication.publication_id
                or manifest.publication_hash != publication.publication_hash
                or manifest.run_id != publication.run_id
                or manifest.dataset_key != publication.dataset_key
                or manifest.publication_key != publication.publication_key
            ):
                raise PublicationActivationError(
                    "candidate RawAudit manifest publication identity drifted"
                )
            manifests[publication_id] = manifest

        raw_audit_ids = tuple(sorted(references_by_raw_id))
        batch_size = connections[self._using].features.max_query_params or 10_000
        raw_rows: list[RawAuditModel] = []
        for start in range(0, len(raw_audit_ids), max(1, batch_size)):
            batch = raw_audit_ids[start : start + max(1, batch_size)]
            raw_rows.extend(
                RawAuditModel._default_manager.using(self._using)
                .select_for_update()
                .filter(pk__in=batch)
                .order_by("pk")
            )
        raw_by_id = {int(raw_row.pk): raw_row for raw_row in raw_rows}
        if raw_by_id.keys() != references_by_raw_id.keys():
            raise PublicationActivationError("one or more candidate RawAudit rows are missing")
        source_type_by_raw_id: dict[int, str] = {}
        for raw_audit_id, reference in references_by_raw_id.items():
            raw_row = raw_by_id[raw_audit_id]
            audit = RawAuditRepository._from_model(raw_row)
            if raw_row.status != "ok" or raw_row.row_count <= 0:
                raise PublicationActivationError(
                    "candidate RawAudit sources must be successful and non-empty"
                )
            if (
                raw_row.content_hash != reference.content_hash
                or raw_audit_content_hash(audit) != reference.content_hash
                or raw_row.provider_name != reference.provider_name
                or raw_row.capability != reference.capability
                or str(raw_row.run_id or "") != reference.run_id
                or str(raw_row.ingested_run_id or "") != reference.ingested_run_id
            ):
                raise PublicationActivationError("candidate RawAudit row differs from its manifest")
            source_type_by_raw_id[raw_audit_id] = self._canonical_raw_audit_source_type(audit.extra)

        for item in request.candidates:
            expected_capability = canonical_capability_for_publication_dataset(item.dataset_key)
            if expected_capability is None:
                raise PublicationActivationError(
                    "group candidate dataset has no canonical provider capability"
                )
            manifest = manifests[item.candidate_publication_id]
            for reference in manifest.raw_audits:
                raw_audit_id = int(reference.raw_audit_id)
                raw_row = raw_by_id[raw_audit_id]
                if (
                    reference.capability != expected_capability
                    or raw_row.capability != expected_capability
                ):
                    raise PublicationActivationError(
                        "candidate RawAudit capability does not match its dataset"
                    )

        raw_source_pairs_by_publication: dict[str, set[tuple[str, str]]] = {}
        for item in request.candidates:
            manifest = manifests[item.candidate_publication_id]
            source_pairs: set[tuple[str, str]] = set()
            for reference in manifest.raw_audits:
                source_pair = (
                    reference.ingested_run_id,
                    source_type_by_raw_id[int(reference.raw_audit_id)],
                )
                if source_pair in source_pairs:
                    raise PublicationActivationError(
                        "candidate RawAudit manifest has ambiguous duplicate source lineage"
                    )
                source_pairs.add(source_pair)
            raw_source_pairs_by_publication[item.candidate_publication_id] = source_pairs

        for item in request.candidates:
            publication_id = item.candidate_publication_id
            manifest = manifests[publication_id]
            fact_source_pairs: set[tuple[str, str]] = set()
            for member in members_by_id[publication_id]:
                key = (member.fact_table, member.fact_pk)
                ingested_run_id = fact_ingested_runs.get(key)
                if ingested_run_id is None:
                    raise PublicationActivationError(
                        "candidate publication member has no ingestion lineage"
                    )
                fact_source_pairs.add((ingested_run_id, member.source))
            audit_source_pairs = raw_source_pairs_by_publication[publication_id]
            if not fact_source_pairs or fact_source_pairs != audit_source_pairs:
                raise PublicationActivationError(
                    "candidate RawAudit sources do not exactly match member fact lineage"
                )
        return manifests

    @staticmethod
    def _canonical_raw_audit_source_type(extra: object) -> str:
        """Read the hash-bound canonical fact source from RawAudit.extra."""

        source_type: object = extra.get("source_type") if isinstance(extra, dict) else None
        if not isinstance(source_type, str):
            raise PublicationActivationError(
                "candidate RawAudit source_type is missing or non-canonical"
            )
        try:
            return validate_raw_audit_source_type(source_type)
        except CandidateRawAuditManifestError as error:
            raise PublicationActivationError(
                "candidate RawAudit source_type is missing or non-canonical"
            ) from error

    def _lock_group_policies(
        self,
        request: PublicationActivationGroupRequest,
    ) -> dict[str, PublicationPolicy]:
        """Lock each active policy in stable dataset order with one query."""

        dataset_keys = tuple(sorted(item.dataset_key for item in request.candidates))
        rows = list(
            DatasetPublicationPolicyModel._default_manager.using(self._using)
            .select_for_update()
            .filter(dataset_key__in=dataset_keys, active=True)
            .order_by("dataset_key", "id")
        )
        if len(rows) != len(dataset_keys) or len({row.dataset_key for row in rows}) != len(
            dataset_keys
        ):
            raise PublicationActivationError("one or more group active policies are unavailable")
        policies: dict[str, PublicationPolicy] = {}
        for row in rows:
            try:
                policy = row.to_domain()
            except (TypeError, ValueError) as error:
                raise PublicationActivationError("group active policy is malformed") from error
            if type(policy) is not PublicationPolicy:
                raise PublicationActivationError("group active policy projection is invalid")
            policies[row.dataset_key] = policy
        return policies

    @staticmethod
    def _manifest_audit_observation(
        *,
        publication: CanonicalPublication,
        manifest: CandidateRawAuditManifest,
        recorded_at: datetime,
        lease: PublicationActivationAuthorityLease,
    ) -> DataPublicationManifestAuditObservation:
        """Bind candidate and full ordered manifest evidence to the fenced audit scope."""

        if publication.as_of is None:
            raise PublicationActivationError("group publication observation time is missing")
        return DataPublicationManifestAuditObservation(
            dataset_key=publication.dataset_key,
            publication_key=publication.publication_key,
            publication_id=publication.publication_id,
            publication_version=publication.policy_version,
            publication_hash=publication.publication_hash,
            provider_key=publication.selected_source,
            run_id=publication.run_id,
            member_count=publication.member_count,
            coverage_requested_count=publication.coverage.requested_count,
            coverage_eligible_count=publication.coverage.eligible_count,
            coverage_selected_count=publication.coverage.selected_count,
            manifest_id=manifest.manifest_id,
            manifest_version=manifest.manifest_version,
            manifest_hash=manifest.manifest_hash,
            raw_audit_count=manifest.raw_audit_count,
            raw_audit_hash=manifest.raw_audit_hash,
            raw_audits=tuple(
                DataPublicationRawAuditManifestReference(
                    raw_audit_id=reference.raw_audit_id,
                    version=reference.version,
                    content_hash=reference.content_hash,
                )
                for reference in manifest.raw_audits
            ),
            occurred_at=publication.as_of,
            recorded_at=recorded_at,
            scope=AuditScopeRef(tenant_id=lease.tenant_id, owner_id=lease.owner_id),
        )


__all__ = ["PublicationGroupActivationEvidenceRepository"]
