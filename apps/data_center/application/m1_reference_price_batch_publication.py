"""Publish one explicit multi-security M1 close-reference candidate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import NAMESPACE_URL, uuid5

from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStageCommand,
    CurrentPublicationStagedCandidate,
    CurrentPublicationStageRawAuditBinding,
    CurrentPublicationStagingUseCase,
)
from apps.data_center.application.dtos import SyncResult
from apps.data_center.application.m1_reference_price_publication import (
    M1_REFERENCE_PRICE_DATABASE_ALIAS,
    M1_REFERENCE_PRICE_DATASET_KEY,
    M1PublicationAuditWriterFactory,
    M1PublicationAuthorityCaptureFactory,
    M1PublicationAuthorityPreflight,
    M1PublicationPointerReader,
)
from apps.data_center.application.publication_activation import (
    ActivateCanonicalPublicationGroupUseCase,
    CurrentPublicationPointerSnapshot,
    PublicationActivationError,
    PublicationActivationGroupCandidate,
    PublicationActivationGroupRequest,
)
from apps.data_center.application.sync_market_use_cases import SyncPriceUseCase
from apps.data_center.application.sync_transaction import DataCenterSyncClock
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationState
from apps.data_center.domain.entities import ProviderConfig, RawAuditReference
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.protocols import ProviderConfigRepositoryProtocol
from apps.data_center.domain.publication_lanes import M1_REBALANCE_REFERENCE_PUBLICATION_KEY
from apps.data_center.domain.raw_audit_manifest import validate_raw_audit_source_type
from apps.data_center.domain.rules import normalize_asset_code
from core.exceptions import DataValidationError
from core.integration.data_center_audit import (
    SystemAuditCompositionUnavailable,
    SystemAuditReaderContext,
)


class M1ReferencePriceBatchPublicationError(DataValidationError):
    """A fixed-scope multi-security M1 reference publication failure."""

    default_message = "M1 reference-price batch publication failed closed"
    default_code = "M1_REFERENCE_PRICE_BATCH_PUBLICATION_FAILED"


@dataclass(frozen=True, slots=True)
class M1ReferencePriceBatchPublicationCommand:
    """One provider, explicit finite security set, and shared market date."""

    provider_id: int
    asset_codes: tuple[str, ...]
    target_trade_date: date

    def __post_init__(self) -> None:
        """Reject invalid provider, fewer than two symbols, or non-date batch scope."""

        if isinstance(self.provider_id, bool) or not isinstance(self.provider_id, int):
            raise M1ReferencePriceBatchPublicationError("provider_id must be a positive integer")
        if self.provider_id < 1:
            raise M1ReferencePriceBatchPublicationError("provider_id must be a positive integer")
        if type(self.asset_codes) is not tuple or len(self.asset_codes) < 2:
            raise M1ReferencePriceBatchPublicationError(
                "asset_codes must be an explicit tuple with at least two securities"
            )
        for asset_code in self.asset_codes:
            if type(asset_code) is not str or not asset_code:
                raise M1ReferencePriceBatchPublicationError(
                    "each asset_code must be canonical Tushare text"
                )
            try:
                normalized = normalize_asset_code(asset_code, "tushare")
            except (TypeError, ValueError):
                normalized = ""
            if normalized != asset_code or asset_code != asset_code.strip().upper():
                raise M1ReferencePriceBatchPublicationError(
                    "each asset_code must be canonical Tushare text"
                )
        if len(set(self.asset_codes)) != len(self.asset_codes):
            raise M1ReferencePriceBatchPublicationError("asset_codes must be unique")
        if type(self.target_trade_date) is not date:
            raise M1ReferencePriceBatchPublicationError("target_trade_date must be a date")


@dataclass(frozen=True, slots=True)
class M1ReferencePriceBatchPublicationResult:
    """The complete exact-sync set and its single activated M1 publication."""

    sync_results: tuple[SyncResult, ...]
    publication: CanonicalPublication

    def __post_init__(self) -> None:
        """Require a multi-member publication with one exact sync per member."""

        if type(self.sync_results) is not tuple or len(self.sync_results) < 2:
            raise M1ReferencePriceBatchPublicationError(
                "batch result requires at least two exact sync results"
            )
        if any(type(result) is not SyncResult for result in self.sync_results):
            raise M1ReferencePriceBatchPublicationError(
                "batch result contains an invalid sync result"
            )
        if (
            type(self.publication) is not CanonicalPublication
            or self.publication.dataset_key != M1_REFERENCE_PRICE_DATASET_KEY
            or self.publication.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
            or self.publication.state is not PublicationState.PUBLISHED
            or self.publication.selected_source != "tushare"
            or self.publication.must_not_use_for_decision
            or self.publication.member_count != len(self.sync_results)
        ):
            raise M1ReferencePriceBatchPublicationError("activated M1 batch publication is invalid")
        if any(
            result.domain != DataCapability.HISTORICAL_PRICE.value
            or result.status != "success"
            or result.stored_count != 1
            or type(result.raw_audit_reference) is not RawAuditReference
            or len(result.stored_asset_codes) != 1
            for result in self.sync_results
        ):
            raise M1ReferencePriceBatchPublicationError(
                "batch result is missing an exact successful RawAudit sync"
            )
        expected_count = len(self.sync_results)
        exact_references = tuple(_sync_reference(result) for result in self.sync_results)
        if (
            len({item.raw_audit_id for item in exact_references}) != expected_count
            or len({item.run_id for item in exact_references}) != expected_count
            or len({item.ingested_run_id for item in exact_references}) != expected_count
            or len({result.provider_name for result in self.sync_results}) != 1
            or len(
                {
                    result.stored_asset_codes[0]
                    for result in self.sync_results
                    if len(result.stored_asset_codes) == 1
                }
            )
            != expected_count
        ):
            raise M1ReferencePriceBatchPublicationError(
                "batch result contains duplicate RawAudit identities"
            )


class M1ReferencePriceBatchPublicationUseCase:
    """Sync a fixed security tuple, stage it once, and activate through one CAS."""

    def __init__(
        self,
        *,
        price_sync: SyncPriceUseCase,
        provider_repository: ProviderConfigRepositoryProtocol,
        staging: CurrentPublicationStagingUseCase,
        activate_group: ActivateCanonicalPublicationGroupUseCase,
        audit_writer_factory: M1PublicationAuditWriterFactory,
        authority_preflight: M1PublicationAuthorityPreflight,
        authority_capture: M1PublicationAuthorityCaptureFactory,
        current_pointer_reader: M1PublicationPointerReader,
        clock: DataCenterSyncClock,
        database_alias: str = M1_REFERENCE_PRICE_DATABASE_ALIAS,
    ) -> None:
        """Bind batch synchronization and activation to the existing M1 collaborators."""

        if database_alias != M1_REFERENCE_PRICE_DATABASE_ALIAS:
            raise M1ReferencePriceBatchPublicationError(
                "M1 price publication requires the default database alias"
            )
        self._price_sync = price_sync
        self._providers = provider_repository
        self._staging = staging
        self._activate_group = activate_group
        self._audit_writer_factory = audit_writer_factory
        self._authority_preflight = authority_preflight
        self._authority_capture = authority_capture
        self._current_pointer_reader = current_pointer_reader
        self._clock = clock
        self._database_alias = database_alias

    def execute(
        self,
        command: M1ReferencePriceBatchPublicationCommand,
    ) -> M1ReferencePriceBatchPublicationResult:
        """Sync every requested security and activate one fully bound candidate."""

        if type(command) is not M1ReferencePriceBatchPublicationCommand:
            raise M1ReferencePriceBatchPublicationError("M1 batch publication command is invalid")
        preflight_at = self._clock.now()
        _require_aware_datetime(preflight_at, "preflight_at")
        preflight_context = self._authority_preflight(as_of=preflight_at)
        if type(
            preflight_context
        ) is not SystemAuditReaderContext or not preflight_context.can_read_at(preflight_at):
            raise M1ReferencePriceBatchPublicationError(
                "current Audit authority is unavailable for M1 reference publication"
            )

        sync_results: list[SyncResult] = []
        providers: list[ProviderConfig] = []
        references: list[RawAuditReference] = []
        for asset_code in command.asset_codes:
            sync_result = self._price_sync.execute_exact_daily(
                provider_id=command.provider_id,
                asset_code=asset_code,
                target_trade_date=command.target_trade_date,
            )
            provider = self._require_exact_sync(
                sync_result,
                provider_id=command.provider_id,
                asset_code=asset_code,
            )
            reference = sync_result.raw_audit_reference
            if reference is None:
                raise M1ReferencePriceBatchPublicationError(
                    "exact daily sync did not return its persisted RawAudit identity"
                )
            sync_results.append(sync_result)
            providers.append(provider)
            references.append(reference)

        self._validate_batch_syncs(
            command=command,
            sync_results=tuple(sync_results),
            providers=tuple(providers),
            references=tuple(references),
        )
        provider = providers[0]
        candidate_run_id = _candidate_run_id(
            target_trade_date=command.target_trade_date,
            asset_codes=command.asset_codes,
            references=tuple(references),
        )
        task_attempt_id = f"m1-reference-price-batch:{candidate_run_id}"

        try:
            pointer_snapshot = self._current_pointer_reader(
                M1_REFERENCE_PRICE_DATASET_KEY,
                M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
            )
            if type(pointer_snapshot) is not CurrentPublicationPointerSnapshot:
                raise PublicationActivationError("M1 pointer reader returned an invalid snapshot")
            published_at = self._clock.now()
            _require_aware_datetime(published_at, "published_at")
            staged = self._staging.execute(
                CurrentPublicationStageCommand(
                    asset_codes=command.asset_codes,
                    published_at=published_at,
                    run_id=candidate_run_id,
                    task_attempt_id=task_attempt_id,
                    raw_audit_bindings=tuple(
                        CurrentPublicationStageRawAuditBinding(
                            reference=reference,
                            expected_source_type="tushare",
                        )
                        for reference in references
                    ),
                    required_observation_date=command.target_trade_date,
                )
            )
            self._validate_staged_candidate(
                staged,
                command=command,
                sync_results=tuple(sync_results),
                provider=provider,
                candidate_run_id=candidate_run_id,
                task_attempt_id=task_attempt_id,
            )
            audit_writer = self._audit_writer_factory()
            if audit_writer.database_alias != self._database_alias:
                raise SystemAuditCompositionUnavailable(
                    "M1 activation audit writer uses a different database alias",
                    reason_code="composition_alias_mismatch",
                )
            activation_at = self._clock.now()
            _require_aware_datetime(activation_at, "activation_at")
            authority = self._authority_capture(
                as_of=activation_at,
                preflight_context=preflight_context,
            )
            if authority.database_alias != self._database_alias:
                raise SystemAuditCompositionUnavailable(
                    "M1 complete authority capture uses a different database alias",
                    reason_code="composition_alias_mismatch",
                )
            request = PublicationActivationGroupRequest(
                activation_id=str(
                    uuid5(
                        NAMESPACE_URL,
                        f"agomtradepro:m1-reference-price-batch:{candidate_run_id}",
                    )
                ),
                candidates=(
                    PublicationActivationGroupCandidate(
                        dataset_key=M1_REFERENCE_PRICE_DATASET_KEY,
                        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
                        candidate_publication_id=staged.publication.publication_id,
                        candidate_publication_hash=staged.publication.publication_hash,
                        expected_current_publication_id=pointer_snapshot.publication_id,
                        expected_current_publication_hash=pointer_snapshot.publication_hash,
                    ),
                ),
            )
            activated = self._activate_group.execute(
                request,
                audit_writer=audit_writer,
                authority_fence=authority.authority_fence,
                authority_proof=authority.authority_proof,
            )
        except M1ReferencePriceBatchPublicationError:
            raise
        except (
            DataValidationError,
            PublicationActivationError,
            SystemAuditCompositionUnavailable,
            TypeError,
            ValueError,
        ) as error:
            raise M1ReferencePriceBatchPublicationError(str(error)) from error

        if (
            type(activated) is not tuple
            or len(activated) != 1
            or type(activated[0]) is not CanonicalPublication
            or activated[0].publication_id != staged.publication.publication_id
            or activated[0].publication_hash != staged.publication.publication_hash
            or activated[0].state is not PublicationState.PUBLISHED
            or activated[0].member_count != len(command.asset_codes)
        ):
            raise M1ReferencePriceBatchPublicationError(
                "M1 group activation returned a different candidate"
            )
        return M1ReferencePriceBatchPublicationResult(
            sync_results=tuple(sync_results),
            publication=activated[0],
        )

    def _require_exact_sync(
        self,
        result: SyncResult,
        *,
        provider_id: int,
        asset_code: str,
    ) -> ProviderConfig:
        """Recheck each exact result and the active Tushare provider identity."""

        if (
            type(result) is not SyncResult
            or result.domain != DataCapability.HISTORICAL_PRICE.value
            or result.status != "success"
            or result.stored_count != 1
            or result.stored_asset_codes != (asset_code,)
            or result.run_id is None
            or result.ingested_run_id is None
            or result.raw_audit_reference is None
        ):
            raise M1ReferencePriceBatchPublicationError(
                "exact daily price sync did not commit the requested single fact"
            )
        provider = self._providers.get_by_id(provider_id)
        if (
            provider is None
            or provider.id != provider_id
            or not provider.is_active
            or provider.name != result.provider_name
        ):
            raise M1ReferencePriceBatchPublicationError(
                "exact daily sync provider identity changed before staging"
            )
        try:
            source_type = validate_raw_audit_source_type(provider.source_type)
        except ValueError as error:
            raise M1ReferencePriceBatchPublicationError(
                "exact daily provider source type is invalid"
            ) from error
        if source_type != "tushare":
            raise M1ReferencePriceBatchPublicationError(
                "M1 exact daily price requires the Tushare source type"
            )
        return provider

    @staticmethod
    def _validate_batch_syncs(
        *,
        command: M1ReferencePriceBatchPublicationCommand,
        sync_results: tuple[SyncResult, ...],
        providers: tuple[ProviderConfig, ...],
        references: tuple[RawAuditReference, ...],
    ) -> None:
        """Reject duplicate or mixed provider/session evidence before staging."""

        if not (len(sync_results) == len(providers) == len(references) == len(command.asset_codes)):
            raise M1ReferencePriceBatchPublicationError(
                "exact daily sync set does not cover the requested security tuple"
            )
        provider_ids = {provider.id for provider in providers}
        provider_names = {provider.name for provider in providers}
        source_types = {provider.source_type for provider in providers}
        if (
            provider_ids != {command.provider_id}
            or len(provider_names) != 1
            or source_types != {"tushare"}
        ):
            raise M1ReferencePriceBatchPublicationError(
                "batch price syncs do not share one active Tushare provider"
            )
        if len({item.raw_audit_id for item in references}) != len(references):
            raise M1ReferencePriceBatchPublicationError(
                "batch price syncs reused a RawAudit identity"
            )
        if len({item.run_id for item in references}) != len(references) or len(
            {item.ingested_run_id for item in references}
        ) != len(references):
            raise M1ReferencePriceBatchPublicationError(
                "batch price syncs reused a run or ingestion identity"
            )
        for result, asset_code, reference in zip(
            sync_results,
            command.asset_codes,
            references,
            strict=True,
        ):
            if (
                result.provider_name != next(iter(provider_names))
                or result.stored_asset_codes != (asset_code,)
                or result.run_id != reference.run_id
                or result.ingested_run_id != reference.ingested_run_id
            ):
                raise M1ReferencePriceBatchPublicationError(
                    "batch RawAudit identity differs from its requested security"
                )

    @staticmethod
    def _validate_staged_candidate(
        staged: CurrentPublicationStagedCandidate,
        *,
        command: M1ReferencePriceBatchPublicationCommand,
        sync_results: tuple[SyncResult, ...],
        provider: ProviderConfig,
        candidate_run_id: str,
        task_attempt_id: str,
    ) -> None:
        """Require exact member count and every source audit in one manifest."""

        publication = staged.publication
        manifest = staged.manifest
        expected_references = tuple(_sync_reference(result) for result in sync_results)
        coverage = publication.coverage
        if (
            publication.dataset_key != M1_REFERENCE_PRICE_DATASET_KEY
            or publication.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
            or publication.state is not PublicationState.CANDIDATE
            or publication.published_at is not None
            or publication.must_not_use_for_decision
            or publication.selected_source != provider.source_type
            or publication.run_id != candidate_run_id
            or publication.member_count != len(command.asset_codes)
            or publication.conflict_count != 0
            or publication.scope_blocks
            or coverage.requested_count != len(command.asset_codes)
            or coverage.publication_id != publication.publication_id
            or coverage.eligible_count != len(command.asset_codes)
            or coverage.selected_count != len(command.asset_codes)
            or coverage.missing_count != 0
            or coverage.conflict_count != 0
            or manifest.dataset_key != M1_REFERENCE_PRICE_DATASET_KEY
            or manifest.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
            or manifest.run_id != candidate_run_id
            or manifest.publication_id != publication.publication_id
            or manifest.publication_hash != publication.publication_hash
            or manifest.task_attempt_id != task_attempt_id
            or manifest.raw_audit_count != len(expected_references)
            or len(manifest.raw_audits) != len(expected_references)
        ):
            raise M1ReferencePriceBatchPublicationError(
                "staged M1 candidate differs from its exact batch scope"
            )

        actual_by_id = {item.raw_audit_id: item for item in manifest.raw_audits}
        expected_by_id = {item.raw_audit_id: item for item in expected_references}
        if len(actual_by_id) != len(expected_by_id) or actual_by_id.keys() != expected_by_id.keys():
            raise M1ReferencePriceBatchPublicationError(
                "staged M1 manifest does not contain the exact RawAudit set"
            )
        for raw_audit_id, expected in expected_by_id.items():
            actual = actual_by_id[raw_audit_id]
            if (
                actual.version != expected.version
                or actual.content_hash != expected.content_hash
                or actual.run_id != expected.run_id
                or actual.ingested_run_id != expected.ingested_run_id
                or actual.provider_name != provider.name
                or actual.capability != DataCapability.HISTORICAL_PRICE.value
            ):
                raise M1ReferencePriceBatchPublicationError(
                    "staged M1 manifest contains a substituted RawAudit reference"
                )


def _candidate_run_id(
    *,
    target_trade_date: date,
    asset_codes: tuple[str, ...],
    references: tuple[RawAuditReference, ...],
) -> str:
    """Derive a publication-candidate correlation ID from exact source pairs."""

    asset_raw_pairs = tuple(
        sorted(
            f"{asset_code}:{reference.raw_audit_id}:{reference.content_hash}:"
            f"{reference.run_id}:{reference.ingested_run_id}"
            for asset_code, reference in zip(asset_codes, references, strict=True)
        )
    )
    lineage = "|".join((target_trade_date.isoformat(), *asset_raw_pairs))
    return str(uuid5(NAMESPACE_URL, f"agomtradepro:m1-reference-price:{lineage}"))


def _sync_reference(result: SyncResult) -> RawAuditReference:
    """Return one exact sync reference after its runtime type check."""

    reference = result.raw_audit_reference
    if type(reference) is not RawAuditReference:
        raise M1ReferencePriceBatchPublicationError("exact RawAudit references are incomplete")
    return reference


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    """Reject naive authority or activation clocks."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise M1ReferencePriceBatchPublicationError(f"{field_name} must be timezone-aware")


__all__ = [
    "M1ReferencePriceBatchPublicationCommand",
    "M1ReferencePriceBatchPublicationError",
    "M1ReferencePriceBatchPublicationResult",
    "M1ReferencePriceBatchPublicationUseCase",
]
