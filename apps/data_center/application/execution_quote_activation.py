"""Application workflow for staging and activating execution quote candidates."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import DatabaseError

from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStageCommand,
    CurrentPublicationStagedCandidate,
    CurrentPublicationStageRawAuditBinding,
    CurrentPublicationStagingUseCase,
)
from apps.data_center.application.execution_quotes import ExecutionQuoteUnavailable
from apps.data_center.application.publication_activation import (
    ActivateCanonicalPublicationGroupUseCase,
    CurrentPublicationPointerSnapshot,
    PublicationActivationAuthorityFence,
    PublicationActivationError,
    PublicationActivationGroupAuditWriter,
    PublicationActivationGroupCandidate,
    PublicationActivationGroupRequest,
)
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.execution_quotes import ExecutionQuoteSnapshot
from apps.data_center.domain.raw_audit_manifest import CandidateRawAuditManifest
from core.exceptions import DataValidationError
from core.integration.data_center_audit import (
    SystemAuditCompositionUnavailable,
    SystemAuditEventOutboxConflict,
    SystemAuditEventOutboxCorruption,
    SystemAuditEventOutboxUnavailable,
    SystemAuditPublisherContractViolation,
    SystemAuditReaderContext,
)

_EXECUTION_QUOTE_DATASET = "equity.quote.snapshot"
_EXECUTION_PUBLICATION_KEY = "execution"
_DEFAULT_DATABASE_ALIAS = "default"


class ExecutionQuoteAuthorityCapture(Protocol):
    """Opaque complete-graph authority result consumed by the activation UOW."""

    @property
    def database_alias(self) -> str:
        """Return the alias used by the complete Account graph transaction."""

    @property
    def authority_fence(self) -> PublicationActivationAuthorityFence:
        """Return the live complete-graph fence capability."""

    @property
    def authority_proof(self) -> object:
        """Return the opaque proof accepted by the authority fence."""


class ExecutionQuoteAuthorityCaptureFactory(Protocol):
    """Capture the complete Account graph after staging has finished."""

    def __call__(
        self,
        *,
        as_of: datetime,
        preflight_context: SystemAuditReaderContext,
    ) -> ExecutionQuoteAuthorityCapture:
        """Capture the complete Account graph for one exact activation cutoff."""


class ExecutionQuotePointerReader(Protocol):
    """Read the exact execution pointer identity for compare-and-swap."""

    def __call__(
        self,
        dataset_key: str,
        publication_key: str,
    ) -> CurrentPublicationPointerSnapshot:
        """Read the requested pointer's exact id/hash CAS pair."""


class ExecutionQuoteCompletedManifestReader(Protocol):
    """Read the bounded exact run/task manifest set used by resume."""

    def __call__(
        self,
        *,
        run_id: str,
        task_attempt_id: str,
    ) -> tuple[CandidateRawAuditManifest, ...]:
        """Return at most two execution manifests so ambiguity can be rejected."""


class ExecutionQuoteResumeCandidateReader(Protocol):
    """Resolve a complete stored publication from one exact validated manifest."""

    def __call__(
        self,
        manifest: CandidateRawAuditManifest,
    ) -> ExecutionQuoteResumeCandidate:
        """Validate and return the publication, facts, and exact asset bindings."""


class ExecutionQuotePointerEpochReader(Protocol):
    """Read the entire persisted execution pointer epoch without a fallback."""

    def __call__(self) -> ExecutionQuotePointerEpoch:
        """Return the exact execution pointer row identity and timestamp."""


class ExecutionQuoteSnapshotReader(Protocol):
    """Read an execution quote through its full decision freshness contract."""

    def __call__(self, asset_code: str, *, as_of: datetime) -> ExecutionQuoteSnapshot:
        """Return one fresh exact current execution quote or a typed block."""


class ExecutionQuotePublicationActivationError(DataValidationError):
    """Stable fail-closed error from the execution quote activation workflow."""

    default_message = "Execution quote publication activation failed closed"
    default_code = "EXECUTION_QUOTE_ACTIVATION_FAILED"


class ExecutionQuoteResumeError(DataValidationError):
    """Stable fail-closed error when no exact completed activation can be resumed."""

    default_message = "Completed execution quote activation could not be resumed"
    default_code = "EXECUTION_QUOTE_RESUME_BLOCKED"


class ExecutionQuoteResumeCorruption(DataValidationError):
    """Stable error when persisted completion audit evidence is incomplete or altered."""

    default_message = "Completed execution quote activation evidence is corrupt"
    default_code = "EXECUTION_QUOTE_RESUME_CORRUPT"


@dataclass(frozen=True, slots=True)
class ExecutionQuotePointerEpoch:
    """Complete persisted pointer identity for one completed execution activation."""

    pointer_id: str
    publication_id: str
    publication_hash: str
    activation_id: str
    updated_at: datetime

    def __post_init__(self) -> None:
        """Require a complete pointer identity and aware epoch timestamp."""

        for field_name in (
            "pointer_id",
            "publication_id",
            "publication_hash",
            "activation_id",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or not value:
                raise ExecutionQuoteResumeError(f"pointer epoch {field_name} is missing")
        if len(self.publication_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.publication_hash
        ):
            raise ExecutionQuoteResumeError("pointer epoch publication hash is invalid")
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ExecutionQuoteResumeError("pointer epoch timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ExecutionQuoteResumeCandidate:
    """Persisted publication, manifest, and members resolved for completed-only resume."""

    publication: CanonicalPublication
    manifest: CandidateRawAuditManifest
    members: tuple[PublicationMember, ...]
    asset_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require the exact domain values returned by the completion repository."""

        if type(self.publication) is not CanonicalPublication:
            raise ExecutionQuoteResumeError("resume publication is invalid")
        if type(self.manifest) is not CandidateRawAuditManifest:
            raise ExecutionQuoteResumeError("resume manifest is invalid")
        if not isinstance(self.members, tuple) or any(
            type(member) is not PublicationMember for member in self.members
        ):
            raise ExecutionQuoteResumeError("resume member set is invalid")
        if not isinstance(self.asset_codes, tuple) or any(
            type(asset_code) is not str or not asset_code for asset_code in self.asset_codes
        ):
            raise ExecutionQuoteResumeError("resume asset set is invalid")


@dataclass(frozen=True, slots=True)
class ExecutionQuotePublicationActivationBundle:
    """One alias-bound stage, authority, audit, and group-activation composition."""

    database_alias: str
    quote_staging: CurrentPublicationStagingUseCase
    activate_group: ActivateCanonicalPublicationGroupUseCase
    audit_writer_factory: Callable[[], PublicationActivationGroupAuditWriter]
    authority_capture: ExecutionQuoteAuthorityCaptureFactory
    current_pointer_reader: ExecutionQuotePointerReader
    completed_manifest_reader: ExecutionQuoteCompletedManifestReader
    resume_candidate_reader: ExecutionQuoteResumeCandidateReader
    current_pointer_epoch_reader: ExecutionQuotePointerEpochReader
    audit_verifier_factory: Callable[
        [ExecutionQuotePointerEpoch], PublicationActivationGroupAuditWriter
    ]
    execution_quote_reader: ExecutionQuoteSnapshotReader


def stage_and_activate_execution_quote_candidate(
    *,
    bundle: ExecutionQuotePublicationActivationBundle,
    asset_codes: Sequence[str],
    published_at: datetime,
    run_id: str,
    task_attempt_id: str,
    raw_audit_bindings: tuple[CurrentPublicationStageRawAuditBinding, ...],
    preflight_context: SystemAuditReaderContext,
) -> CanonicalPublication:
    """Stage exact quote evidence, then activate its execution pointer atomically."""

    if type(bundle) is not ExecutionQuotePublicationActivationBundle:
        raise ExecutionQuotePublicationActivationError("activation bundle is invalid")
    if bundle.database_alias != _DEFAULT_DATABASE_ALIAS:
        raise ExecutionQuotePublicationActivationError("activation database alias differs")
    if not isinstance(raw_audit_bindings, tuple) or not raw_audit_bindings:
        raise ExecutionQuotePublicationActivationError("exact RawAudit bindings are required")
    raw_ids = tuple(item.reference.raw_audit_id for item in raw_audit_bindings)
    if len(raw_ids) != len(set(raw_ids)):
        raise ExecutionQuotePublicationActivationError("RawAudit bindings must be unique")

    try:
        pointer = bundle.current_pointer_reader(
            _EXECUTION_QUOTE_DATASET,
            _EXECUTION_PUBLICATION_KEY,
        )
        if type(pointer) is not CurrentPublicationPointerSnapshot:
            raise PublicationActivationError("execution pointer reader returned an invalid pair")
    except (PublicationActivationError, DatabaseError, TypeError, ValueError) as error:
        raise ExecutionQuotePublicationActivationError(
            "execution pointer CAS snapshot could not be validated"
        ) from error

    try:
        staged = bundle.quote_staging.execute(
            CurrentPublicationStageCommand(
                asset_codes=tuple(asset_codes),
                published_at=published_at,
                run_id=run_id,
                task_attempt_id=task_attempt_id,
                raw_audit_bindings=raw_audit_bindings,
            )
        )
        _validate_staged_execution_candidate(
            staged,
            run_id=run_id,
            task_attempt_id=task_attempt_id,
            raw_audit_bindings=raw_audit_bindings,
        )
    except (DataValidationError, DatabaseError, TypeError, ValueError) as error:
        raise ExecutionQuotePublicationActivationError(
            "execution quote candidate staging failed"
        ) from error

    try:
        audit_writer = bundle.audit_writer_factory()
        if getattr(audit_writer, "database_alias", None) != _DEFAULT_DATABASE_ALIAS or not callable(
            getattr(audit_writer, "append_manifest_group_required", None)
        ):
            raise SystemAuditCompositionUnavailable(
                "manifest-bound group audit writer is unavailable",
                reason_code="composition_not_wired",
            )
    except (SystemAuditCompositionUnavailable, DatabaseError) as error:
        raise ExecutionQuotePublicationActivationError(
            "manifest-bound publication activation audit is unavailable"
        ) from error

    activation_at = datetime.now(UTC)
    try:
        capture = bundle.authority_capture(
            as_of=activation_at,
            preflight_context=preflight_context,
        )
        if capture.database_alias != _DEFAULT_DATABASE_ALIAS:
            raise SystemAuditCompositionUnavailable(
                "complete Account authority capture uses a different database alias",
                reason_code="composition_alias_mismatch",
            )
    except (SystemAuditCompositionUnavailable, DatabaseError) as error:
        raise ExecutionQuotePublicationActivationError(
            "complete Account authority could not be captured"
        ) from error

    publication = staged.publication
    activation_id = str(uuid5(NAMESPACE_URL, f"agomtradepro:execution-quote-activation:{run_id}"))
    try:
        request = PublicationActivationGroupRequest(
            activation_id=activation_id,
            candidates=(
                PublicationActivationGroupCandidate(
                    dataset_key=_EXECUTION_QUOTE_DATASET,
                    publication_key=_EXECUTION_PUBLICATION_KEY,
                    candidate_publication_id=publication.publication_id,
                    candidate_publication_hash=publication.publication_hash,
                    expected_current_publication_id=pointer.publication_id,
                    expected_current_publication_hash=pointer.publication_hash,
                ),
            ),
        )
        activated = bundle.activate_group.execute(
            request,
            audit_writer=audit_writer,
            authority_fence=capture.authority_fence,
            authority_proof=capture.authority_proof,
        )
    except (
        DataValidationError,
        SystemAuditCompositionUnavailable,
        DatabaseError,
        SystemAuditPublisherContractViolation,
        SystemAuditEventOutboxUnavailable,
        SystemAuditEventOutboxConflict,
        SystemAuditEventOutboxCorruption,
    ) as error:
        raise ExecutionQuotePublicationActivationError(
            "execution quote group activation failed closed"
        ) from error

    if (
        type(activated) is not tuple
        or len(activated) != 1
        or not isinstance(activated[0], CanonicalPublication)
        or activated[0].state is not PublicationState.PUBLISHED
        or activated[0].publication_id != publication.publication_id
        or activated[0].publication_hash != publication.publication_hash
        or activated[0].dataset_key != _EXECUTION_QUOTE_DATASET
        or activated[0].publication_key != _EXECUTION_PUBLICATION_KEY
    ):
        raise ExecutionQuotePublicationActivationError(
            "execution quote activation returned a different publication"
        )
    return activated[0]


def resume_completed_execution_quote_activation(
    *,
    bundle: ExecutionQuotePublicationActivationBundle,
    run_id: str,
    task_attempt_id: str,
    asset_codes: tuple[str, ...],
    preflight_context: SystemAuditReaderContext,
) -> CanonicalPublication:
    """Verify and return one already completed execution activation without writes."""

    if type(bundle) is not ExecutionQuotePublicationActivationBundle:
        raise ExecutionQuoteResumeError("resume bundle is invalid")
    if bundle.database_alias != _DEFAULT_DATABASE_ALIAS:
        raise ExecutionQuoteResumeError("resume database alias differs")
    if type(run_id) is not str or not run_id:
        raise ExecutionQuoteResumeError("resume run identity is invalid")
    try:
        if str(UUID(run_id)) != run_id:
            raise ValueError("run id is not canonical")
    except (TypeError, ValueError) as error:
        raise ExecutionQuoteResumeError("resume run identity is invalid") from error
    if (
        type(task_attempt_id) is not str
        or not task_attempt_id
        or len(task_attempt_id) > 160
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:/-"
            for character in task_attempt_id
        )
    ):
        raise ExecutionQuoteResumeError("resume task attempt identity is invalid")
    if (
        type(asset_codes) is not tuple
        or not asset_codes
        or any(
            type(asset_code) is not str
            or not asset_code
            or asset_code.strip() != asset_code
            or asset_code.upper() != asset_code
            for asset_code in asset_codes
        )
        or len(set(asset_codes)) != len(asset_codes)
    ):
        raise ExecutionQuoteResumeError("resume asset identities are invalid")
    if type(preflight_context) is not SystemAuditReaderContext:
        raise ExecutionQuoteResumeError("resume authority preflight context is invalid")

    try:
        manifests = bundle.completed_manifest_reader(
            run_id=run_id,
            task_attempt_id=task_attempt_id,
        )
    except (DataValidationError, DatabaseError, TypeError, ValueError) as error:
        raise ExecutionQuoteResumeError("completed manifest lookup failed") from error
    if type(manifests) is not tuple or len(manifests) != 1:
        raise ExecutionQuoteResumeError("completed manifest identity is missing or ambiguous")
    manifest = manifests[0]
    if (
        type(manifest) is not CandidateRawAuditManifest
        or manifest.dataset_key != _EXECUTION_QUOTE_DATASET
        or manifest.publication_key != _EXECUTION_PUBLICATION_KEY
        or manifest.run_id != run_id
        or manifest.task_attempt_id != task_attempt_id
        or not manifest.raw_audits
        or any(reference.run_id != run_id for reference in manifest.raw_audits)
    ):
        raise ExecutionQuoteResumeError("completed manifest binding differs")

    try:
        candidate = bundle.resume_candidate_reader(manifest)
        pointer_epoch = bundle.current_pointer_epoch_reader()
    except (DataValidationError, DatabaseError, TypeError, ValueError) as error:
        raise ExecutionQuoteResumeError("completed publication lookup failed") from error
    if type(candidate) is not ExecutionQuoteResumeCandidate:
        raise ExecutionQuoteResumeError("completed publication reader returned an invalid value")
    if type(pointer_epoch) is not ExecutionQuotePointerEpoch:
        raise ExecutionQuoteResumeError("execution pointer epoch reader returned an invalid value")

    publication = candidate.publication
    activation_id = str(uuid5(NAMESPACE_URL, f"agomtradepro:execution-quote-activation:{run_id}"))
    expected_assets = tuple(sorted(candidate.asset_codes))
    if (
        publication.dataset_key != _EXECUTION_QUOTE_DATASET
        or publication.publication_key != _EXECUTION_PUBLICATION_KEY
        or publication.run_id != run_id
        or publication.state is not PublicationState.PUBLISHED
        or publication.must_not_use_for_decision
        or publication.published_at is None
        or publication.published_at.tzinfo is None
        or publication.published_at.utcoffset() is None
        or publication.as_of is None
        or publication.as_of > publication.published_at
        or publication.publication_id != manifest.publication_id
        or publication.publication_hash != manifest.publication_hash
        or publication.member_count != len(candidate.members)
        or manifest.publication_id != publication.publication_id
        or manifest.publication_hash != publication.publication_hash
        or manifest.dataset_key != publication.dataset_key
        or manifest.publication_key != publication.publication_key
        or manifest.run_id != publication.run_id
        or tuple(candidate.asset_codes) != expected_assets
        or expected_assets != asset_codes
        or pointer_epoch.publication_id != publication.publication_id
        or pointer_epoch.publication_hash != publication.publication_hash
        or pointer_epoch.activation_id != activation_id
        or pointer_epoch.updated_at != publication.published_at
    ):
        raise ExecutionQuoteResumeError("completed publication or pointer epoch differs")

    fact_ids_by_asset: dict[str, set[str]] = {}
    for member in candidate.members:
        if (
            member.dataset_key != _EXECUTION_QUOTE_DATASET
            or member.fact_table != "data_center_quote_snapshot"
            or member.dataset_key != publication.dataset_key
            or not member.natural_key
        ):
            raise ExecutionQuoteResumeError("completed quote fact binding is invalid")
        asset_code = member.natural_key.split(":", maxsplit=1)[0]
        if asset_code not in asset_codes:
            raise ExecutionQuoteResumeError("completed quote asset binding differs")
        fact_ids_by_asset.setdefault(asset_code, set()).add(member.fact_pk)
    if set(fact_ids_by_asset) != set(asset_codes) or any(
        not fact_ids_by_asset[asset_code] for asset_code in asset_codes
    ):
        raise ExecutionQuoteResumeError("completed quote fact coverage differs")

    try:
        authority_capture = bundle.authority_capture(
            as_of=datetime.now(UTC),
            preflight_context=preflight_context,
        )
        if authority_capture.database_alias != _DEFAULT_DATABASE_ALIAS:
            raise ExecutionQuoteResumeError("current Account authority alias differs")
        request = PublicationActivationGroupRequest(
            activation_id=activation_id,
            candidates=(
                PublicationActivationGroupCandidate(
                    dataset_key=_EXECUTION_QUOTE_DATASET,
                    publication_key=_EXECUTION_PUBLICATION_KEY,
                    candidate_publication_id=publication.publication_id,
                    candidate_publication_hash=publication.publication_hash,
                    expected_current_publication_id=pointer_epoch.publication_id,
                    expected_current_publication_hash=pointer_epoch.publication_hash,
                ),
            ),
        )
        verifier = bundle.audit_verifier_factory(pointer_epoch)
        if getattr(verifier, "database_alias", None) != _DEFAULT_DATABASE_ALIAS or not callable(
            getattr(verifier, "append_manifest_group_required", None)
        ):
            raise ExecutionQuoteResumeError("read-only completion audit verifier is unavailable")
        activated = bundle.activate_group.execute(
            request,
            audit_writer=verifier,
            authority_fence=authority_capture.authority_fence,
            authority_proof=authority_capture.authority_proof,
        )
    except SystemAuditEventOutboxCorruption as error:
        raise ExecutionQuoteResumeCorruption(
            "completed Audit or Outbox evidence is incomplete"
        ) from error
    except (
        DataValidationError,
        SystemAuditCompositionUnavailable,
        SystemAuditEventOutboxConflict,
        SystemAuditEventOutboxUnavailable,
        DatabaseError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, (ExecutionQuoteResumeError, ExecutionQuoteResumeCorruption)):
            raise
        raise ExecutionQuoteResumeError("completed activation verification failed") from error

    if (
        type(activated) is not tuple
        or len(activated) != 1
        or type(activated[0]) is not CanonicalPublication
        or activated[0].publication_id != publication.publication_id
        or activated[0].publication_hash != publication.publication_hash
        or activated[0].state is not PublicationState.PUBLISHED
    ):
        raise ExecutionQuoteResumeError("completed activation returned a different publication")

    read_at = datetime.now(UTC)
    try:
        for asset_code in asset_codes:
            snapshot = bundle.execution_quote_reader(asset_code, as_of=read_at)
            if (
                type(snapshot) is not ExecutionQuoteSnapshot
                or snapshot.asset_code != asset_code
                or snapshot.publication_id != publication.publication_id
                or snapshot.publication_hash != publication.publication_hash
                or snapshot.fact_pk not in fact_ids_by_asset[asset_code]
            ):
                raise ExecutionQuoteResumeError("current execution decision read differs")
    except ExecutionQuoteUnavailable as error:
        raise ExecutionQuoteResumeError("current execution decision read is blocked") from error
    return activated[0]


def _validate_staged_execution_candidate(
    staged: CurrentPublicationStagedCandidate,
    *,
    run_id: str,
    task_attempt_id: str,
    raw_audit_bindings: tuple[CurrentPublicationStageRawAuditBinding, ...],
) -> None:
    """Require staging to return the exact CANDIDATE and manifest requested."""

    if type(staged) is not CurrentPublicationStagedCandidate:
        raise PublicationActivationError("staging returned an invalid candidate")
    publication = staged.publication
    manifest = staged.manifest
    if (
        publication.dataset_key != _EXECUTION_QUOTE_DATASET
        or publication.publication_key != _EXECUTION_PUBLICATION_KEY
        or publication.run_id != run_id
        or publication.state is not PublicationState.CANDIDATE
        or publication.published_at is not None
        or manifest.dataset_key != _EXECUTION_QUOTE_DATASET
        or manifest.publication_key != _EXECUTION_PUBLICATION_KEY
        or manifest.run_id != run_id
        or manifest.task_attempt_id != task_attempt_id
        or manifest.publication_id != publication.publication_id
        or manifest.publication_hash != publication.publication_hash
    ):
        raise PublicationActivationError("staged execution quote candidate identity differs")
    expected = tuple(
        sorted(
            (
                binding.reference.raw_audit_id,
                binding.reference.version,
                binding.reference.content_hash,
                binding.reference.run_id,
                binding.reference.ingested_run_id,
            )
            for binding in raw_audit_bindings
        )
    )
    actual = tuple(
        sorted(
            (
                reference.raw_audit_id,
                reference.version,
                reference.content_hash,
                reference.run_id,
                reference.ingested_run_id,
            )
            for reference in manifest.raw_audits
        )
    )
    if actual != expected:
        raise PublicationActivationError("staged RawAudit manifest differs from its bindings")


__all__ = [
    "ExecutionQuotePublicationActivationBundle",
    "ExecutionQuotePublicationActivationError",
    "ExecutionQuotePointerEpoch",
    "ExecutionQuoteResumeCandidate",
    "ExecutionQuoteResumeCorruption",
    "ExecutionQuoteResumeError",
    "resume_completed_execution_quote_activation",
    "stage_and_activate_execution_quote_candidate",
]
