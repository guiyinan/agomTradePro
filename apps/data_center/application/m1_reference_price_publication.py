"""Stage and activate one exact M1 published-close reference price."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStageCommand,
    CurrentPublicationStagedCandidate,
    CurrentPublicationStageRawAuditBinding,
    CurrentPublicationStagingUseCase,
)
from apps.data_center.application.dtos import SyncResult
from apps.data_center.application.publication_activation import (
    ActivateCanonicalPublicationGroupUseCase,
    CurrentPublicationPointerSnapshot,
    PublicationActivationAuthorityFence,
    PublicationActivationError,
    PublicationActivationGroupAuditWriter,
    PublicationActivationGroupCandidate,
    PublicationActivationGroupRequest,
)
from apps.data_center.application.sync_market_use_cases import SyncPriceUseCase
from apps.data_center.application.sync_transaction import DataCenterSyncClock
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationState
from apps.data_center.domain.entities import ProviderConfig
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

M1_REFERENCE_PRICE_DATASET_KEY = "equity.price.bar"
M1_REFERENCE_PRICE_DATABASE_ALIAS = "default"


class M1ReferencePricePublicationError(DataValidationError):
    """A fixed-scope M1 price-reference staging or activation failure."""

    default_message = "M1 reference price publication failed closed"
    default_code = "M1_REFERENCE_PRICE_PUBLICATION_FAILED"


@dataclass(frozen=True, slots=True)
class M1ReferencePricePublicationCommand:
    """One exact provider, canonical A-share, and market date request."""

    provider_id: int
    asset_code: str
    target_trade_date: date

    def __post_init__(self) -> None:
        """Reject ambiguous identity or date inputs before provider access."""

        if isinstance(self.provider_id, bool) or not isinstance(self.provider_id, int):
            raise M1ReferencePricePublicationError("provider_id must be a positive integer")
        if self.provider_id < 1:
            raise M1ReferencePricePublicationError("provider_id must be a positive integer")
        if (
            type(self.asset_code) is not str
            or not self.asset_code
            or self.asset_code != self.asset_code.strip().upper()
            or normalize_asset_code(self.asset_code, "tushare") != self.asset_code
        ):
            raise M1ReferencePricePublicationError("asset_code must be one canonical Tushare code")
        if type(self.target_trade_date) is not date:
            raise M1ReferencePricePublicationError("target_trade_date must be a date")


@dataclass(frozen=True, slots=True)
class M1ReferencePricePublicationResult:
    """Exact committed source sync and its activated M1 price publication."""

    sync_result: SyncResult
    publication: CanonicalPublication

    def __post_init__(self) -> None:
        """Require the result to preserve the committed one-row lineage."""

        if type(self.sync_result) is not SyncResult:
            raise M1ReferencePricePublicationError("sync result is invalid")
        if self.sync_result.raw_audit_reference is None:
            raise M1ReferencePricePublicationError("exact RawAudit reference is missing")
        if (
            self.publication.dataset_key != M1_REFERENCE_PRICE_DATASET_KEY
            or self.publication.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
            or self.publication.state is not PublicationState.PUBLISHED
        ):
            raise M1ReferencePricePublicationError("activated M1 publication is invalid")


class M1PublicationAuthorityCapture(Protocol):
    """Complete Account graph authority proof for the activation transaction."""

    @property
    def database_alias(self) -> str: ...

    @property
    def authority_fence(self) -> PublicationActivationAuthorityFence: ...

    @property
    def authority_proof(self) -> object: ...


class M1PublicationAuthorityCaptureFactory(Protocol):
    """Capture complete account authority for this exact preflight context."""

    def __call__(
        self,
        *,
        as_of: datetime,
        preflight_context: SystemAuditReaderContext,
    ) -> M1PublicationAuthorityCapture: ...


class M1PublicationAuthorityPreflight(Protocol):
    """Validate current Audit authority before any price facts are written."""

    def __call__(self, *, as_of: datetime) -> SystemAuditReaderContext: ...


class M1PublicationAuditWriterFactory(Protocol):
    """Build the manifest and quality audit writer on the activation alias."""

    def __call__(self) -> PublicationActivationGroupAuditWriter: ...


class M1PublicationPointerReader(Protocol):
    """Read the exact current pointer pair before staging and activation."""

    def __call__(
        self,
        dataset_key: str,
        publication_key: str,
    ) -> CurrentPublicationPointerSnapshot: ...


class M1ReferencePricePublicationUseCase:
    """Run exact daily sync, manifest staging, and fenced M1 activation."""

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
        """Bind fixed M1 price publication collaborators to one database alias."""

        if database_alias != M1_REFERENCE_PRICE_DATABASE_ALIAS:
            raise M1ReferencePricePublicationError(
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
        command: M1ReferencePricePublicationCommand,
    ) -> M1ReferencePricePublicationResult:
        """Capture one exact daily bar, stage its lineage, and activate by CAS."""

        if type(command) is not M1ReferencePricePublicationCommand:
            raise M1ReferencePricePublicationError("M1 publication command is invalid")
        preflight_at = self._clock.now()
        _require_aware_datetime(preflight_at, "preflight_at")
        preflight_context = self._authority_preflight(as_of=preflight_at)
        if type(
            preflight_context
        ) is not SystemAuditReaderContext or not preflight_context.can_read_at(preflight_at):
            raise M1ReferencePricePublicationError(
                "current Audit authority is unavailable for M1 reference publication"
            )
        sync_result = self._price_sync.execute_exact_daily(
            provider_id=command.provider_id,
            asset_code=command.asset_code,
            target_trade_date=command.target_trade_date,
        )
        provider = self._require_provider(sync_result, command.provider_id)
        raw_reference = sync_result.raw_audit_reference
        if (
            raw_reference is None
            or sync_result.run_id is None
            or sync_result.ingested_run_id is None
        ):
            raise M1ReferencePricePublicationError(
                "exact daily sync did not return its persisted RawAudit identity"
            )

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
                    asset_codes=(command.asset_code,),
                    published_at=published_at,
                    run_id=sync_result.run_id,
                    task_attempt_id=f"m1-reference-price:{sync_result.run_id}",
                    raw_audit_bindings=(
                        CurrentPublicationStageRawAuditBinding(
                            reference=raw_reference,
                            expected_source_type=validate_raw_audit_source_type(
                                provider.source_type
                            ),
                        ),
                    ),
                    required_observation_date=command.target_trade_date,
                )
            )
            self._validate_staged_candidate(
                staged,
                command=command,
                sync_result=sync_result,
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
                        f"agomtradepro:m1-reference-price:{sync_result.run_id}",
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
        except M1ReferencePricePublicationError:
            raise
        except (
            DataValidationError,
            PublicationActivationError,
            SystemAuditCompositionUnavailable,
            TypeError,
            ValueError,
        ) as error:
            raise M1ReferencePricePublicationError(str(error)) from error

        if (
            type(activated) is not tuple
            or len(activated) != 1
            or activated[0].publication_id != staged.publication.publication_id
            or activated[0].publication_hash != staged.publication.publication_hash
            or activated[0].state is not PublicationState.PUBLISHED
        ):
            raise M1ReferencePricePublicationError(
                "M1 group activation returned a different publication"
            )
        return M1ReferencePricePublicationResult(
            sync_result=sync_result,
            publication=activated[0],
        )

    def _require_provider(self, result: SyncResult, provider_id: int) -> ProviderConfig:
        """Revalidate the exact configured source bound to the committed sync."""

        if (
            type(result) is not SyncResult
            or result.domain != DataCapability.HISTORICAL_PRICE.value
            or result.status != "success"
            or result.stored_count != 1
        ):
            raise M1ReferencePricePublicationError(
                "exact daily price sync did not commit exactly one successful fact"
            )
        provider = self._providers.get_by_id(provider_id)
        if (
            provider is None
            or provider.id != provider_id
            or not provider.is_active
            or provider.name != result.provider_name
        ):
            raise M1ReferencePricePublicationError(
                "exact daily sync provider identity changed before staging"
            )
        try:
            source_type = validate_raw_audit_source_type(provider.source_type)
        except ValueError as error:
            raise M1ReferencePricePublicationError(
                "exact daily provider source type is invalid"
            ) from error
        if source_type != "tushare":
            raise M1ReferencePricePublicationError(
                "M1 exact daily price requires the Tushare source type"
            )
        return provider

    @staticmethod
    def _validate_staged_candidate(
        staged: CurrentPublicationStagedCandidate,
        *,
        command: M1ReferencePricePublicationCommand,
        sync_result: SyncResult,
    ) -> None:
        """Require one sealed candidate bound to the exact sync and requested date."""

        raw_reference = sync_result.raw_audit_reference
        if raw_reference is None:
            raise M1ReferencePricePublicationError("exact RawAudit identity is missing")
        publication = staged.publication
        manifest = staged.manifest
        if (
            publication.dataset_key != M1_REFERENCE_PRICE_DATASET_KEY
            or publication.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
            or publication.state is not PublicationState.CANDIDATE
            or publication.published_at is not None
            or publication.run_id != sync_result.run_id
            or publication.member_count != 1
            or manifest.dataset_key != M1_REFERENCE_PRICE_DATASET_KEY
            or manifest.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
            or manifest.run_id != sync_result.run_id
            or manifest.publication_id != publication.publication_id
            or manifest.publication_hash != publication.publication_hash
            or manifest.task_attempt_id != f"m1-reference-price:{sync_result.run_id}"
            or len(manifest.raw_audits) != 1
        ):
            raise M1ReferencePricePublicationError(
                "staged M1 candidate differs from its exact sync scope"
            )
        raw_audit = manifest.raw_audits[0]
        if (
            raw_audit.raw_audit_id != raw_reference.raw_audit_id
            or raw_audit.content_hash != raw_reference.content_hash
            or raw_audit.run_id != raw_reference.run_id
            or raw_audit.ingested_run_id != raw_reference.ingested_run_id
        ):
            raise M1ReferencePricePublicationError(
                "staged M1 manifest differs from the exact RawAudit reference"
            )
        if (
            sync_result.stored_asset_codes != (command.asset_code,)
            or raw_reference.run_id != sync_result.run_id
            or raw_reference.ingested_run_id != sync_result.ingested_run_id
        ):
            raise M1ReferencePricePublicationError(
                "exact daily sync identity differs from the requested M1 asset"
            )


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    """Reject a naive clock value before candidate or activation work."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise M1ReferencePricePublicationError(f"{field_name} must be timezone-aware")


__all__ = [
    "M1ReferencePricePublicationCommand",
    "M1ReferencePricePublicationError",
    "M1ReferencePricePublicationResult",
    "M1ReferencePricePublicationUseCase",
    "M1PublicationAuthorityPreflight",
    "M1_REFERENCE_PRICE_DATABASE_ALIAS",
    "M1_REFERENCE_PRICE_DATASET_KEY",
]
