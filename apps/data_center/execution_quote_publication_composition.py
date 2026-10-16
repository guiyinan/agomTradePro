"""Production composition for execution-key quote candidate activation."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from django.db import connections

from apps.data_center.application.current_publication_candidate import CurrentPublicationDataset
from apps.data_center.application.current_publication_rebuild import (
    CurrentPublicationRebuildUseCase,
)
from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStagingUseCase,
)
from apps.data_center.application.execution_quote_activation import (
    ExecutionQuotePointerEpoch,
    ExecutionQuotePublicationActivationBundle,
    ExecutionQuoteResumeCandidate,
    ExecutionQuoteResumeError,
)
from apps.data_center.application.publication_activation import (
    ActivateCanonicalPublicationGroupUseCase,
    CurrentPublicationPointerSnapshot,
    PublicationActivationError,
    PublicationActivationGroupAuditWriter,
    PublicationActivationGroupRequest,
    PublicationActivationManifestAuditWrite,
)
from apps.data_center.domain.execution_quotes import ExecutionQuoteSnapshot
from apps.data_center.domain.raw_audit_manifest import CandidateRawAuditManifest
from apps.data_center.execution_quote_composition import get_execution_quote
from apps.data_center.infrastructure.candidate_raw_audit_manifest_repository import (
    DjangoCandidateRawAuditManifestRepository,
)
from apps.data_center.infrastructure.candidate_raw_audit_metadata_resolver import (
    DjangoCandidateRawAuditMetadataResolver,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.current_publication_staging_repository import (
    DjangoCurrentPublicationStagingRepository,
)
from apps.data_center.infrastructure.execution_quote_repository import (
    DjangoExecutionQuoteCandidateVersionGuard,
)
from apps.data_center.infrastructure.publication_activation_repository import (
    DjangoPublicationActivationRepository,
)
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationPointerModel,
)
from apps.data_center.infrastructure.quote_snapshot_repository import QuoteSnapshotRepository
from core.integration.data_center_audit import (
    SystemAuditCompositionUnavailable,
    SystemAuditEventOutboxCommit,
    SystemAuditReaderContext,
    get_data_publication_activation_audit_verifier,
    get_data_publication_activation_audit_writer,
)
from core.integration.production_account_authority_capture import (
    ProductionAccountAuthorityCapture,
    capture_production_account_authority,
)

_DEFAULT_DATABASE_ALIAS = "default"
_PRODUCTION_ENVIRONMENT = "production"
_DATASET_KEY = "equity.quote.snapshot"
_PUBLICATION_KEY = "execution"


class _CompletedExecutionQuoteAuditAdapter:
    """Adapt a verify-only Audit port to activation's same-current replay seam."""

    def __init__(self, *, expected_epoch: ExecutionQuotePointerEpoch, verifier: object) -> None:
        """Bind one locked pointer epoch to a read-only Audit completion verifier."""

        self._expected_epoch = expected_epoch
        self._verifier = verifier

    @property
    def database_alias(self) -> str:
        """Return the single configured alias used by pointer, Audit, and Outbox reads."""

        return _DEFAULT_DATABASE_ALIAS

    def append_manifest_required(
        self,
        *,
        request: object,
        publication: object,
        members: tuple[object, ...],
        manifest: object,
        observation: object,
    ) -> SystemAuditEventOutboxCommit:
        """Reject the legacy single-write path; this adapter only verifies group replay."""

        del request, publication, members, manifest, observation
        raise PublicationActivationError(
            "completed activation verifier cannot append a single audit event"
        )

    def append_manifest_group_required(
        self,
        *,
        request: PublicationActivationGroupRequest,
        writes: tuple[PublicationActivationManifestAuditWrite, ...],
    ) -> tuple[SystemAuditEventOutboxCommit, ...]:
        """Verify the existing group inside activation's UOW without appending it."""

        connection = connections[_DEFAULT_DATABASE_ALIAS]
        if not connection.in_atomic_block or connection.get_autocommit():
            raise PublicationActivationError(
                "completed activation verification requires the caller-owned transaction"
            )
        rows = tuple(
            CanonicalPublicationPointerModel._default_manager.using(_DEFAULT_DATABASE_ALIAS)
            .select_for_update()
            .filter(
                dataset_key=_DATASET_KEY,
                publication_key=_PUBLICATION_KEY,
            )[:2]
        )
        if len(rows) != 1:
            raise PublicationActivationError("completed execution pointer row is ambiguous")
        pointer = rows[0]
        if (
            str(pointer.pointer_id) != self._expected_epoch.pointer_id
            or str(pointer.publication_id or "") != self._expected_epoch.publication_id
            or pointer.publication_hash != self._expected_epoch.publication_hash
            or pointer.activation_id != self._expected_epoch.activation_id
            or pointer.updated_at != self._expected_epoch.updated_at
        ):
            raise PublicationActivationError("completed execution pointer epoch changed")
        verify = getattr(self._verifier, "verify_manifest_group_required", None)
        if getattr(
            self._verifier, "database_alias", None
        ) != _DEFAULT_DATABASE_ALIAS or not callable(verify):
            raise PublicationActivationError("read-only Audit verifier is unavailable")
        commits = verify(request=request, writes=writes)
        if type(commits) is not tuple or any(
            type(commit) is not SystemAuditEventOutboxCommit for commit in commits
        ):
            raise PublicationActivationError("read-only Audit verifier returned an invalid result")
        return cast(tuple[SystemAuditEventOutboxCommit, ...], commits)


def build_production_execution_quote_publication_bundle(
    *,
    using: str = _DEFAULT_DATABASE_ALIAS,
    created_by: str = "ops.execution_quote_publication",
) -> ExecutionQuotePublicationActivationBundle:
    """Compose one quote-only execution candidate stage and fenced activation."""

    alias = _require_default_database_alias(using)
    rebuilder = CurrentPublicationRebuildUseCase(
        dataset=CurrentPublicationDataset(
            dataset_key=_DATASET_KEY,
            fact_table="data_center_quote_snapshot",
            created_by=created_by,
        ),
        candidate_repository=QuoteSnapshotRepository(),
        publication_repository=CanonicalPublicationRepository(),
        policy_repository=PublicationPolicyRepository(),
        publication_key=_PUBLICATION_KEY,
        execution_candidate_guard=DjangoExecutionQuoteCandidateVersionGuard(using=alias),
    )
    resolver = DjangoCandidateRawAuditMetadataResolver(using=alias)
    staging_repository = DjangoCurrentPublicationStagingRepository(using=alias)
    activation_repository = DjangoPublicationActivationRepository(using=alias)
    if any(
        component.database_alias != alias
        for component in (resolver, staging_repository, activation_repository)
    ):
        raise SystemAuditCompositionUnavailable(
            "execution quote publication components use different database aliases",
            reason_code="composition_alias_mismatch",
        )
    quote_staging = CurrentPublicationStagingUseCase(
        rebuilder=rebuilder,
        raw_audit_resolver=resolver,
        repository=staging_repository,
    )

    def build_audit_writer() -> PublicationActivationGroupAuditWriter:
        """Return the required canonical Audit/outbox writer for this alias."""

        writer = get_data_publication_activation_audit_writer(
            environment=_PRODUCTION_ENVIRONMENT,
            using=alias,
        )
        if getattr(writer, "database_alias", None) != alias or not callable(
            getattr(writer, "append_manifest_group_required", None)
        ):
            raise SystemAuditCompositionUnavailable(
                "manifest-bound publication activation audit is unavailable",
                reason_code="composition_not_wired",
            )
        return cast(PublicationActivationGroupAuditWriter, writer)

    def capture_authority(
        *,
        as_of: datetime,
        preflight_context: SystemAuditReaderContext,
    ) -> ProductionAccountAuthorityCapture:
        """Capture the complete Account authority graph on the default alias."""

        capture = capture_production_account_authority(
            using=alias,
            as_of=as_of,
            preflight_context=preflight_context,
        )
        if type(capture) is not ProductionAccountAuthorityCapture:
            raise SystemAuditCompositionUnavailable(
                "production Account authority capture returned an invalid result",
                reason_code="authority_capture_invalid",
            )
        if capture.database_alias != alias:
            raise SystemAuditCompositionUnavailable(
                "production Account authority capture uses a different database alias",
                reason_code="composition_alias_mismatch",
            )
        return capture

    def read_execution_pointer(
        dataset_key: str,
        publication_key: str,
    ) -> CurrentPublicationPointerSnapshot:
        """Read one exact execution pointer identity for the activation CAS."""

        if dataset_key != _DATASET_KEY or publication_key != _PUBLICATION_KEY:
            raise SystemAuditCompositionUnavailable(
                "execution quote pointer reader received an unsupported scope",
                reason_code="publication_scope_mismatch",
            )
        pointer = (
            CanonicalPublicationPointerModel._default_manager.using(alias)
            .filter(dataset_key=dataset_key, publication_key=publication_key)
            .first()
        )
        if pointer is None:
            return CurrentPublicationPointerSnapshot(None, None)
        if pointer.publication_id is None:
            if pointer.publication_hash or pointer.activation_id:
                raise SystemAuditCompositionUnavailable(
                    "empty execution quote pointer contains stale identity",
                    reason_code="publication_pointer_empty_identity_invalid",
                )
            return CurrentPublicationPointerSnapshot(None, None)
        try:
            return CurrentPublicationPointerSnapshot(
                str(pointer.publication_id),
                pointer.publication_hash,
            )
        except PublicationActivationError as error:
            raise SystemAuditCompositionUnavailable(
                "execution quote pointer identity is malformed",
                reason_code="publication_pointer_identity_invalid",
            ) from error

    def read_completed_manifests(
        *,
        run_id: str,
        task_attempt_id: str,
    ) -> tuple[CandidateRawAuditManifest, ...]:
        """Read at most two execution manifests for the exact run and task attempt."""

        return DjangoCandidateRawAuditManifestRepository(using=alias).list_for_execution_resume(
            run_id=run_id,
            task_attempt_id=task_attempt_id,
        )

    def load_resume_candidate(
        manifest: CandidateRawAuditManifest,
    ) -> ExecutionQuoteResumeCandidate:
        """Validate the persisted manifest and reconstruct its exact publication members."""

        manifest_repository = DjangoCandidateRawAuditManifestRepository(using=alias)
        persisted_manifest = manifest_repository.validate(manifest.publication_id)
        if persisted_manifest != manifest:
            raise ExecutionQuoteResumeError("completed manifest changed during resolution")
        publications = CanonicalPublicationRepository()
        publication = publications.get_by_id(manifest.publication_id)
        if publication is None:
            raise ExecutionQuoteResumeError("completed publication is missing")
        members = tuple(publications.list_members(publication.publication_id))
        asset_codes = tuple(
            sorted({member.natural_key.split(":", maxsplit=1)[0] for member in members})
        )
        return ExecutionQuoteResumeCandidate(
            publication=publication,
            manifest=persisted_manifest,
            members=members,
            asset_codes=asset_codes,
        )

    def read_execution_pointer_epoch() -> ExecutionQuotePointerEpoch:
        """Read the one complete execution pointer row, rejecting missing or ambiguous state."""

        rows = tuple(
            CanonicalPublicationPointerModel._default_manager.using(alias)
            .filter(dataset_key=_DATASET_KEY, publication_key=_PUBLICATION_KEY)
            .order_by("pointer_id")[:2]
        )
        if len(rows) != 1:
            raise ExecutionQuoteResumeError("execution pointer is missing or ambiguous")
        pointer = rows[0]
        if (
            pointer.publication_id is None
            or not pointer.publication_hash
            or not pointer.activation_id
        ):
            raise ExecutionQuoteResumeError("execution pointer is not a completed activation")
        try:
            return ExecutionQuotePointerEpoch(
                pointer_id=str(pointer.pointer_id),
                publication_id=str(pointer.publication_id),
                publication_hash=pointer.publication_hash,
                activation_id=pointer.activation_id,
                updated_at=pointer.updated_at,
            )
        except (TypeError, ValueError) as error:
            raise ExecutionQuoteResumeError("execution pointer epoch is malformed") from error

    def build_resume_audit_verifier(
        expected_epoch: ExecutionQuotePointerEpoch,
    ) -> PublicationActivationGroupAuditWriter:
        """Compose an exact pointer-epoch guard around the read-only Audit verifier."""

        verifier = get_data_publication_activation_audit_verifier(
            environment=_PRODUCTION_ENVIRONMENT,
            using=alias,
        )
        if getattr(verifier, "database_alias", None) != alias or not callable(
            getattr(verifier, "verify_manifest_group_required", None)
        ):
            raise SystemAuditCompositionUnavailable(
                "completed execution Audit verifier is unavailable",
                reason_code="composition_not_wired",
            )
        return cast(
            PublicationActivationGroupAuditWriter,
            _CompletedExecutionQuoteAuditAdapter(
                expected_epoch=expected_epoch,
                verifier=verifier,
            ),
        )

    def read_current_execution_quote(
        asset_code: str,
        *,
        as_of: datetime,
    ) -> ExecutionQuoteSnapshot:
        """Read one quote through the exact current execution gate and TTL contract."""

        return get_execution_quote(asset_code, as_of=as_of)

    return ExecutionQuotePublicationActivationBundle(
        database_alias=alias,
        quote_staging=quote_staging,
        activate_group=ActivateCanonicalPublicationGroupUseCase(activation_repository),
        audit_writer_factory=build_audit_writer,
        authority_capture=capture_authority,
        current_pointer_reader=read_execution_pointer,
        completed_manifest_reader=read_completed_manifests,
        resume_candidate_reader=load_resume_candidate,
        current_pointer_epoch_reader=read_execution_pointer_epoch,
        audit_verifier_factory=build_resume_audit_verifier,
        execution_quote_reader=read_current_execution_quote,
    )


def _require_default_database_alias(value: object) -> str:
    """Reject unsupported aliases before constructing execution components."""

    if type(value) is not str or value != _DEFAULT_DATABASE_ALIAS:
        raise SystemAuditCompositionUnavailable(
            "execution quote publication requires the default database",
            reason_code="composition_alias_mismatch",
        )
    return _DEFAULT_DATABASE_ALIAS


__all__ = ["build_production_execution_quote_publication_bundle"]
