"""Application contracts for atomic current-market group activation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from django.db import DatabaseError

from apps.data_center.domain.control_plane import CanonicalPublication, PublicationState
from apps.data_center.domain.raw_audit_manifest import CURRENT_MARKET_PUBLICATION_DATASETS
from apps.data_center.domain.target_date_universe import TargetDateAssetUniverseScope
from core.exceptions import DataValidationError
from core.integration import data_center_audit as audit_integration
from core.integration.data_center_audit import SystemAuditReaderContext
from core.integration.task_monitor_runtime import CurrentTaskAttemptIdentity

from .current_publication_rebuild import (
    CoreCurrentPublicationRebuildResult,
    CoreCurrentPublicationRebuildUseCase,
    CurrentPublicationScopeExclusion,
)
from .current_publication_staging import (
    CurrentPublicationStageCommand,
    CurrentPublicationStagedCandidate,
    CurrentPublicationStageRawAuditBinding,
    CurrentPublicationStagingUseCase,
)
from .market_publication_refresh import (
    MarketPublicationRefreshBlocked,
    MarketPublicationRefreshPorts,
)
from .publication_activation import (
    ActivateCanonicalPublicationGroupUseCase,
    CurrentPublicationPointerSnapshot,
    PublicationActivationAuthorityFence,
    PublicationActivationError,
    PublicationActivationGroupAuditWriter,
    PublicationActivationGroupCandidate,
    PublicationActivationGroupRequest,
)

_FULL_MARKET_STAGE_ORDER = (
    "equity.quote.snapshot",
    "equity.price.bar",
    "equity.valuation.fact",
)
_FULL_MARKET_PUBLICATION_KEY = "current"
FULL_MARKET_DATABASE_ALIAS = "default"


class FullMarketData02AuthorityPreflight(Protocol):
    """Type the authority preflight dependency used by the refresh orchestrator."""

    def __call__(
        self,
        *,
        as_of: datetime,
        minimum_window: timedelta,
        expected_actor: str = "",
    ) -> tuple[SystemAuditReaderContext | None, dict[str, object] | None]: ...


class MarketPublicationsRefresh(Protocol):
    """Run the generic coordinator over the full-market refresh callbacks."""

    def __call__(
        self,
        *,
        as_of_date: date,
        batch_size: int,
        ports: MarketPublicationRefreshPorts,
    ) -> dict[str, object]: ...


class TargetDateUniverseScopeResolver(Protocol):
    """Resolve current active A-shares against persisted target-date evidence."""

    def __call__(self, target_date: date) -> TargetDateAssetUniverseScope: ...


class CurrentTaskAttemptIdentityGetter(Protocol):
    """Resolve the active Celery attempt only from Task Monitor authority."""

    def __call__(self) -> CurrentTaskAttemptIdentity: ...


class CurrentMarketPublicationBundle(Protocol):
    """Expose one same-alias preview, candidate staging, and group activation set."""

    @property
    def database_alias(self) -> str: ...

    @property
    def previewer(self) -> CoreCurrentPublicationRebuildUseCase: ...

    @property
    def quote_staging(self) -> CurrentPublicationStagingUseCase: ...

    @property
    def price_staging(self) -> CurrentPublicationStagingUseCase: ...

    @property
    def valuation_staging(self) -> CurrentPublicationStagingUseCase: ...

    @property
    def activate_group(self) -> ActivateCanonicalPublicationGroupUseCase: ...

    @property
    def audit_writer_factory(self) -> Callable[[], PublicationActivationGroupAuditWriter]: ...

    @property
    def authority_capture(self) -> _AuthorityCaptureFactory: ...

    @property
    def current_pointer_reader(
        self,
    ) -> Callable[[str, str], CurrentPublicationPointerSnapshot]: ...


class CurrentMarketPublicationBundleFactory(Protocol):
    """Build the production-bound fixed current-market staging/activation bundle."""

    def __call__(
        self,
        *,
        using: str = "default",
        created_by: str,
    ) -> CurrentMarketPublicationBundle: ...


class _AuthorityCaptureResult(Protocol):
    """Structural complete-authority result exposed by the core integration facade."""

    @property
    def database_alias(self) -> str: ...

    @property
    def authority_fence(self) -> PublicationActivationAuthorityFence: ...

    @property
    def authority_proof(self) -> object: ...


class _AuthorityCaptureFactory(Protocol):
    """Capture one complete Account graph after every market candidate is staged."""

    def __call__(
        self,
        *,
        as_of: datetime,
        preflight_context: SystemAuditReaderContext,
    ) -> _AuthorityCaptureResult: ...


def current_market_publication_blocked(
    error_code: str, message: str
) -> MarketPublicationRefreshBlocked:
    """Create one normalized known-failure result for the generic market coordinator."""

    return MarketPublicationRefreshBlocked(message, code=error_code)


def stage_and_activate_current_market_group(
    *,
    bundle: CurrentMarketPublicationBundle,
    asset_codes: list[str],
    published_at: datetime,
    run_id: str,
    task_attempt_id: str,
    required_observation_date: date,
    scope_exclusions_by_dataset: Mapping[str, tuple[CurrentPublicationScopeExclusion, ...]],
    raw_audit_bindings_by_dataset: Mapping[str, tuple[CurrentPublicationStageRawAuditBinding, ...]],
    preflight_context: SystemAuditReaderContext,
) -> CoreCurrentPublicationRebuildResult:
    """Stage all fixed datasets, then activate their exact candidates as one group."""

    if bundle.database_alias != FULL_MARKET_DATABASE_ALIAS:
        raise current_market_publication_blocked(
            "CURRENT_PUBLICATION_COMPOSITION_ALIAS_MISMATCH",
            "Current market publication components do not share the production alias",
        )
    if set(raw_audit_bindings_by_dataset) != CURRENT_MARKET_PUBLICATION_DATASETS:
        raise current_market_publication_blocked(
            "CURRENT_PUBLICATION_RAW_AUDIT_BINDING_INVALID",
            "Current market staging requires exact bindings for all three datasets",
        )
    seen_raw_audit_ids: set[str] = set()
    for dataset_key in _FULL_MARKET_STAGE_ORDER:
        bindings = raw_audit_bindings_by_dataset[dataset_key]
        binding_ids = tuple(item.reference.raw_audit_id for item in bindings)
        if not bindings or len(binding_ids) != len(set(binding_ids)):
            raise current_market_publication_blocked(
                "CURRENT_PUBLICATION_RAW_AUDIT_BINDING_INVALID",
                "Current market staging received missing or repeated RawAudit bindings",
            )
        if seen_raw_audit_ids.intersection(binding_ids):
            raise current_market_publication_blocked(
                "CURRENT_PUBLICATION_RAW_AUDIT_BINDING_INVALID",
                "Current market staging received a RawAudit bound to multiple datasets",
            )
        seen_raw_audit_ids.update(binding_ids)

    pointer_snapshots: dict[str, CurrentPublicationPointerSnapshot] = {}
    try:
        for dataset_key in _FULL_MARKET_STAGE_ORDER:
            snapshot = bundle.current_pointer_reader(
                dataset_key,
                _FULL_MARKET_PUBLICATION_KEY,
            )
            if type(snapshot) is not CurrentPublicationPointerSnapshot:
                raise PublicationActivationError("current pointer reader returned an invalid pair")
            pointer_snapshots[dataset_key] = snapshot
    except (
        PublicationActivationError,
        audit_integration.SystemAuditCompositionUnavailable,
        DatabaseError,
        TypeError,
        ValueError,
    ) as error:
        raise current_market_publication_blocked(
            "CURRENT_PUBLICATION_CURRENT_POINTER_UNAVAILABLE",
            "Current publication pointer CAS snapshot could not be validated",
        ) from error

    stages: tuple[tuple[str, CurrentPublicationStagingUseCase], ...] = (
        ("equity.quote.snapshot", bundle.quote_staging),
        ("equity.price.bar", bundle.price_staging),
        ("equity.valuation.fact", bundle.valuation_staging),
    )
    staged_by_dataset: dict[str, CurrentPublicationStagedCandidate] = {}
    for dataset_key, staging in stages:
        try:
            staged = staging.execute(
                CurrentPublicationStageCommand(
                    asset_codes=tuple(asset_codes),
                    published_at=published_at,
                    run_id=run_id,
                    task_attempt_id=task_attempt_id,
                    raw_audit_bindings=raw_audit_bindings_by_dataset[dataset_key],
                    scope_exclusions=scope_exclusions_by_dataset.get(dataset_key, ()),
                    required_observation_date=required_observation_date,
                )
            )
            if type(staged) is not CurrentPublicationStagedCandidate:
                raise PublicationActivationError("staging returned an invalid candidate")
            publication = staged.publication
            manifest = staged.manifest
            if (
                publication.dataset_key != dataset_key
                or publication.publication_key != _FULL_MARKET_PUBLICATION_KEY
                or publication.run_id != run_id
                or publication.state is not PublicationState.CANDIDATE
                or publication.published_at is not None
                or manifest.dataset_key != dataset_key
                or manifest.publication_key != _FULL_MARKET_PUBLICATION_KEY
                or manifest.run_id != run_id
                or manifest.task_attempt_id != task_attempt_id
                or publication.publication_id != manifest.publication_id
                or publication.publication_hash != manifest.publication_hash
            ):
                raise PublicationActivationError(
                    "staged candidate differs from its fixed run or task-attempt identity"
                )
            expected_raw_audits = tuple(
                sorted(
                    (
                        item.reference.raw_audit_id,
                        item.reference.version,
                        item.reference.content_hash,
                        item.reference.run_id,
                        item.reference.ingested_run_id,
                    )
                    for item in raw_audit_bindings_by_dataset[dataset_key]
                )
            )
            resolved_raw_audits = tuple(
                sorted(
                    (
                        item.raw_audit_id,
                        item.version,
                        item.content_hash,
                        item.run_id,
                        item.ingested_run_id,
                    )
                    for item in manifest.raw_audits
                )
            )
            if resolved_raw_audits != expected_raw_audits:
                raise PublicationActivationError(
                    "staged RawAudit manifest differs from its exact request bindings"
                )
            staged_by_dataset[dataset_key] = staged
        except (
            DataValidationError,
            PublicationActivationError,
            audit_integration.SystemAuditCompositionUnavailable,
            DatabaseError,
            TypeError,
            ValueError,
        ) as error:
            raise current_market_publication_blocked(
                "CURRENT_PUBLICATION_STAGING_FAILED",
                "Current publication candidate staging failed closed",
            ) from error

    try:
        audit_writer = bundle.audit_writer_factory()
        if audit_writer.database_alias != FULL_MARKET_DATABASE_ALIAS:
            raise audit_integration.SystemAuditCompositionUnavailable(
                "publication activation audit writer uses a different database alias",
                reason_code="composition_alias_mismatch",
            )
    except (audit_integration.SystemAuditCompositionUnavailable, DatabaseError) as error:
        raise current_market_publication_blocked(
            "CURRENT_PUBLICATION_AUDIT_UNAVAILABLE",
            "Manifest-bound publication activation audit is unavailable",
        ) from error

    # Capture the complete graph after all production-bound reads; the group
    # activation call immediately follows request construction and uses this proof.
    activation_at = datetime.now(UTC)
    try:
        capture = bundle.authority_capture(
            as_of=activation_at,
            preflight_context=preflight_context,
        )
        if capture.database_alias != FULL_MARKET_DATABASE_ALIAS:
            raise audit_integration.SystemAuditCompositionUnavailable(
                "complete Account authority capture uses a different database alias",
                reason_code="composition_alias_mismatch",
            )
    except (audit_integration.SystemAuditCompositionUnavailable, DatabaseError) as error:
        raise current_market_publication_blocked(
            "CURRENT_PUBLICATION_AUTHORITY_CAPTURE_FAILED",
            "Complete Account authority could not be captured for group activation",
        ) from error

    activation_id = str(uuid5(NAMESPACE_URL, f"agomtradepro:current-market-activation:{run_id}"))
    try:
        request = PublicationActivationGroupRequest(
            activation_id=activation_id,
            candidates=tuple(
                PublicationActivationGroupCandidate(
                    dataset_key=dataset_key,
                    publication_key=_FULL_MARKET_PUBLICATION_KEY,
                    candidate_publication_id=(
                        staged_by_dataset[dataset_key].publication.publication_id
                    ),
                    candidate_publication_hash=(
                        staged_by_dataset[dataset_key].publication.publication_hash
                    ),
                    expected_current_publication_id=(pointer_snapshots[dataset_key].publication_id),
                    expected_current_publication_hash=(
                        pointer_snapshots[dataset_key].publication_hash
                    ),
                )
                for dataset_key in _FULL_MARKET_STAGE_ORDER
            ),
        )
    except (PublicationActivationError, TypeError, ValueError) as error:
        raise current_market_publication_blocked(
            "CURRENT_PUBLICATION_GROUP_ACTIVATION_FAILED",
            "Current publication group request could not be validated",
        ) from error

    try:
        activated = bundle.activate_group.execute(
            request,
            audit_writer=audit_writer,
            authority_fence=capture.authority_fence,
            authority_proof=capture.authority_proof,
        )
    except (
        DataValidationError,
        audit_integration.SystemAuditCompositionUnavailable,
        DatabaseError,
        audit_integration.SystemAuditPublisherContractViolation,
        audit_integration.SystemAuditEventOutboxUnavailable,
        audit_integration.SystemAuditEventOutboxConflict,
        audit_integration.SystemAuditEventOutboxCorruption,
    ) as error:
        error_code = (
            "CURRENT_PUBLICATION_AUDIT_WRITE_FAILED"
            if isinstance(
                error,
                (
                    audit_integration.SystemAuditPublisherContractViolation,
                    audit_integration.SystemAuditEventOutboxUnavailable,
                    audit_integration.SystemAuditEventOutboxConflict,
                    audit_integration.SystemAuditEventOutboxCorruption,
                ),
            )
            else "CURRENT_PUBLICATION_GROUP_ACTIVATION_FAILED"
        )
        raise current_market_publication_blocked(
            error_code,
            "Current publication group activation failed closed",
        ) from error

    if type(activated) is not tuple or len(activated) != len(_FULL_MARKET_STAGE_ORDER):
        raise current_market_publication_blocked(
            "CURRENT_PUBLICATION_GROUP_ACTIVATION_FAILED",
            "Group activation did not return exactly three current publications",
        )
    activated_by_dataset: dict[str, CanonicalPublication] = {}
    for publication in activated:
        if not isinstance(publication, CanonicalPublication):
            raise current_market_publication_blocked(
                "CURRENT_PUBLICATION_GROUP_ACTIVATION_FAILED",
                "Group activation returned an invalid publication result",
            )
        if publication.dataset_key in activated_by_dataset:
            raise current_market_publication_blocked(
                "CURRENT_PUBLICATION_GROUP_ACTIVATION_FAILED",
                "Group activation returned duplicate dataset results",
            )
        activated_by_dataset[publication.dataset_key] = publication
    if set(activated_by_dataset) != CURRENT_MARKET_PUBLICATION_DATASETS:
        raise current_market_publication_blocked(
            "CURRENT_PUBLICATION_GROUP_ACTIVATION_FAILED",
            "Group activation returned an incomplete dataset set",
        )
    for dataset_key in _FULL_MARKET_STAGE_ORDER:
        publication = activated_by_dataset[dataset_key]
        candidate = staged_by_dataset[dataset_key].publication
        if (
            publication.state is not PublicationState.PUBLISHED
            or publication.published_at is None
            or publication.run_id != run_id
            or publication.publication_id != candidate.publication_id
            or publication.publication_hash != candidate.publication_hash
        ):
            raise current_market_publication_blocked(
                "CURRENT_PUBLICATION_GROUP_ACTIVATION_FAILED",
                "Activated publication differs from its staged candidate",
            )
    return CoreCurrentPublicationRebuildResult(
        publications=tuple(
            activated_by_dataset[dataset_key] for dataset_key in sorted(_FULL_MARKET_STAGE_ORDER)
        ),
        covered_asset_count=len(
            {str(code or "").strip().upper() for code in asset_codes if str(code or "").strip()}
        ),
    )
