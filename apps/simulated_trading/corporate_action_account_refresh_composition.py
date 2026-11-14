"""Refresh one simulated-account ownership evidence chain from its live row."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections, transaction
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist
from rest_framework.request import Request

from apps.account.application.creation_evidence_settings import (
    CanonicalAccountCreationEvidenceSettings,
)
from apps.account.canonical_creation_composition import build_canonical_account_creation_stages
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.simulated_corporate_action_write_issuance_composition import (
    locked_simulated_action_trading_eligibility,
)
from apps.simulated_trading.account_ownership_composition import (
    build_current_account_ownership_reader,
)
from apps.simulated_trading.account_physical_row_v2_composition import (
    build_account_physical_row_v2_provider,
)
from apps.simulated_trading.account_reobservation_composition import (
    build_existing_account_reobserver,
)
from apps.simulated_trading.application.account_row_reobservation import (
    ReobserveExistingAccountRow,
    ReobserveExistingAccountRowCommand,
)
from apps.simulated_trading.application.current_account_ownership import (
    CurrentAccountOwnership,
    CurrentAccountOwnershipReader,
    CurrentAccountOwnershipUnavailable,
)
from apps.simulated_trading.application.simulated_account_raw_observation import (
    SimulatedAccountPhysicalRowMutation,
)
from apps.simulated_trading.creation_composition import build_simulated_account_creation_stages
from apps.simulated_trading.domain.entities import AccountType
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)
from apps.simulated_trading.execution_current_reference_composition import (
    get_simulated_execution_runtime_environment,
)
from apps.simulated_trading.infrastructure.simulated_account_evidence_pipeline import (
    SimulatedAccountEvidencePipeline,
    SimulatedAccountEvidencePipelineAliases,
    SimulatedAccountMutationWriterProtocol,
    UnverifiedCanonicalAccountReference,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_repository import (
    DjangoSimulatedAccountRawObservationRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Repository,
)
from core.exceptions import AuthorizationError, BusinessLogicError
from core.integration.account_creation_evidence_runtime import (
    get_active_account_creation_evidence_settings,
)

_OWNERSHIP_ONLY = "account_ownership_evidence_only"


def _blocked(
    message: str, *, code: str = "SIMULATED_ACCOUNT_REFRESH_BLOCKED"
) -> BusinessLogicError:
    """Return the stable public failure used for incomplete owner refresh scope."""

    return BusinessLogicError(message, code=code)


@dataclass(frozen=True, slots=True)
class CorporateActionAccountRefreshResult:
    """Finite ownership-row freshness receipt with no financial or market authority."""

    account_id: int
    row_updated_at: datetime
    source_observed_at: datetime
    source_recorded_at: datetime
    account_recorded_at: datetime
    checked_at: datetime
    valid_until: datetime
    freshness: Literal["fresh"] = "fresh"
    reliability: Literal["owner_row_observed"] = "owner_row_observed"
    must_not_use_for_decision: bool = True
    blocking_reason: str = _OWNERSHIP_ONLY

    def __post_init__(self) -> None:
        """Reject timestamps or flags that could overstate the source evidence."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be an exact positive integer")
        for name in (
            "row_updated_at",
            "source_observed_at",
            "source_recorded_at",
            "account_recorded_at",
            "checked_at",
            "valid_until",
        ):
            value = getattr(self, name)
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if not (
            self.row_updated_at
            <= self.source_observed_at
            <= self.source_recorded_at
            <= self.account_recorded_at
            <= self.checked_at
            < self.valid_until
        ):
            raise ValueError("refresh clocks must remain ordered within the configured window")
        if (
            self.freshness != "fresh"
            or self.reliability != "owner_row_observed"
            or self.must_not_use_for_decision is not True
            or self.blocking_reason != _OWNERSHIP_ONLY
        ):
            raise ValueError("account refresh is ownership evidence only")


class _ReobservedRawWriter(SimulatedAccountMutationWriterProtocol):
    """Make the existing evidence pipeline source its raw stage from the live-row reobserver."""

    def __init__(
        self,
        *,
        observer: ReobserveExistingAccountRow,
        expected: CurrentAccountOwnership,
        observation_id: str,
        observation_version: str,
    ) -> None:
        self._observer = observer
        self._expected = expected
        self._observation_id = observation_id
        self._observation_version = observation_version

    def record_create(
        self, mutation: SimulatedAccountPhysicalRowMutation
    ) -> SimulatedAccountRawObservation:
        """Reject refreshes that would create a new raw-evidence root."""

        raise _blocked("account refresh cannot create a raw observation root")

    def record_update(
        self, mutation: SimulatedAccountPhysicalRowMutation
    ) -> SimulatedAccountRawObservation:
        """Re-read the exact owner row and append only a predecessor-bound successor."""

        if type(mutation) is not SimulatedAccountPhysicalRowMutation:
            raise _blocked("account refresh mutation must be server-generated")
        if (
            mutation.observation_id != self._observation_id
            or mutation.mutation_version != self._observation_version
            or mutation.row_pk != self._expected.row_pk
            or mutation.row_user_id != self._expected.user_id
            or mutation.raw_account_type != self._expected.account_type.value
            or mutation.is_active is not True
            or mutation.row_created_at != self._expected.row_created_at
            or mutation.row_updated_at != self._expected.row_updated_at
            or mutation.observed_at != self._expected.observed_at
        ):
            raise _blocked("account refresh mutation differs from the locked live row")
        expected_user_id = self._expected.user_id
        if type(expected_user_id) is not int or expected_user_id <= 0:
            raise _blocked("account refresh requires a concrete active owner identity")
        return self._observer.execute(
            ReobserveExistingAccountRowCommand(
                observation_id=self._observation_id,
                observation_version=self._observation_version,
                row_pk=self._expected.row_pk,
                expected_user_id=expected_user_id,
                expected_account_type=self._expected.account_type,
                expected_created_at=self._expected.row_created_at,
                minimum_updated_at=self._expected.row_updated_at,
            )
        )

    def record_delete(
        self, mutation: SimulatedAccountPhysicalRowMutation
    ) -> SimulatedAccountRawObservation:
        """Reject refreshes that would append an account tombstone."""

        raise _blocked("account refresh cannot append a raw observation tombstone")


@contextmanager
def _owned_simulated_account_scope(
    *,
    reader: CurrentAccountOwnershipReader,
    account_id: int,
    owner_user_id: int,
) -> Iterator[CurrentAccountOwnership]:
    """Require the exact active simulated owner row while the caller holds its DB UOW."""

    row = reader.read_locked(row_pk=account_id)
    if type(row) is not CurrentAccountOwnership:
        raise AuthorizationError("The simulated account owner row is unavailable")
    row.__post_init__()
    if (
        row.row_pk != account_id
        or row.user_id != owner_user_id
        or row.account_type is not AccountType.SIMULATED
        or row.is_active is not True
    ):
        raise AuthorizationError("Only the active owner of a simulated account may refresh it")
    yield row


def _same_live_row(
    first: CurrentAccountOwnership,
    final: CurrentAccountOwnership,
) -> bool:
    """Compare row facts while allowing the final observation clock to advance."""

    return (
        first.row_pk == final.row_pk
        and first.user_id == final.user_id
        and first.account_type is final.account_type
        and first.is_active is final.is_active
        and first.row_created_at == final.row_created_at
        and first.row_updated_at == final.row_updated_at
    )


def _require_existing_source_chain(
    *,
    source: SimulatedAccountRowSourceV2,
    raw: SimulatedAccountRawObservation,
    row: CurrentAccountOwnership,
) -> None:
    """Bind the existing source head to this real owner row and raw predecessor."""

    if type(source) is not SimulatedAccountRowSourceV2:
        raise _blocked("the current SourceV2 head is unavailable")
    source.__post_init__()
    if type(raw) is not SimulatedAccountRawObservation:
        raise _blocked("the current raw owner head is unavailable")
    raw.__post_init__()
    if (
        source.account_namespace != "account"
        or source.account_id == ""
        or source.underlying_unified_account_namespace != "simulated-account-row"
        or source.underlying_unified_account_id != row.row_pk
        or source.row_user_id != row.user_id
        or source.raw_account_type != AccountType.SIMULATED.value
        or source.is_active is not True
        or source.is_present is not True
        or source.is_tombstone is not False
        or source.row_created_at != row.row_created_at
        or source.row_updated_at > row.row_updated_at
        or source.row_updated_at != raw.row_updated_at
        or source.row_created_at != raw.row_created_at
        or source.row_user_id != raw.row_user_id
        or source.raw_account_type != raw.raw_account_type
        or source.is_active != raw.is_active
        or source.is_present != raw.is_present
        or source.is_tombstone != raw.is_tombstone
        or source.observed_at != raw.observed_at
        or source.source_valid_until != raw.valid_until
        or source.raw_observation_supersedes_content_hash != raw.supersedes_content_hash
        or source.source_id != raw.observation_id
        or source.source_version != raw.observation_version
        or source.raw_observation_content_hash != raw.content_hash
        or source.raw_observation_identity_hash != raw.identity_hash
        or raw.row_pk != row.row_pk
        or raw.row_user_id != row.user_id
        or raw.raw_account_type != AccountType.SIMULATED.value
        or raw.is_active is not True
        or raw.is_present is not True
        or raw.is_tombstone is not False
        or raw.row_created_at != row.row_created_at
        or raw.row_updated_at > row.row_updated_at
    ):
        raise _blocked("existing owner/source/raw evidence does not identify this live row")


def refresh_owner_simulated_account_evidence(
    request: Request,
    *,
    account_id: int,
    using: str = DEFAULT_DB_ALIAS,
) -> CorporateActionAccountRefreshResult:
    """Refresh the caller's active simulated-account ownership evidence atomically.

    The operation reads the physical owner row under its PostgreSQL lock and
    advances its existing Raw, SourceV2, and AccountV2 histories on one alias.
    It records no financial, market, or tax authority.
    """

    user = getattr(request, "user", None)
    owner_user_id = getattr(user, "pk", None)
    if (
        getattr(user, "is_authenticated", False) is not True
        or type(owner_user_id) is not int
        or owner_user_id <= 0
    ):
        raise AuthorizationError("An authenticated account owner is required")
    if type(account_id) is not int or account_id <= 0:
        raise _blocked("a positive physical simulated-account id is required")
    if (
        type(using) is not str
        or not using
        or using.strip() != using
        or any(character.isspace() for character in using)
    ):
        raise _blocked("one explicit database alias is required")
    environment = get_simulated_execution_runtime_environment()
    settings = get_active_account_creation_evidence_settings(environment)
    if type(settings) is not CanonicalAccountCreationEvidenceSettings:
        raise _blocked("active account-evidence settings are unavailable")
    settings.__post_init__()
    try:
        settings.deadline_at(timezone.now())
        connection = connections[using]
    except (ConnectionDoesNotExist, KeyError, TypeError, ValueError, OverflowError) as error:
        raise _blocked("account-evidence configuration or database alias is unavailable") from error
    if connection.vendor != "postgresql":
        raise _blocked("owner account evidence refresh requires PostgreSQL")

    try:
        with transaction.atomic(using=using):
            if not connections[using].in_atomic_block:
                raise _blocked("account refresh must own one same-alias transaction")
            with locked_simulated_action_trading_eligibility(user_id=owner_user_id, using=using):
                reader = build_current_account_ownership_reader(using=using)
                with _owned_simulated_account_scope(
                    reader=reader,
                    account_id=account_id,
                    owner_user_id=owner_user_id,
                ) as row:
                    source_repository = DjangoSimulatedAccountRowSourceV2Repository(using=using)
                    source_repository.lock_current_sources_for_read()
                    cutoff = timezone.now()
                    heads = source_repository.get_physical_account_heads(
                        underlying_unified_account_id=account_id,
                        as_of=cutoff,
                    )
                    if len(heads) != 1:
                        raise _blocked("one exact existing SourceV2 identity is required")
                    source = heads[0].source
                    raw_repository = DjangoSimulatedAccountRawObservationRepository(using=using)
                    raw_head = raw_repository.get_physical_row_head(
                        row_pk=account_id,
                        as_of=cutoff,
                    )
                    if raw_head is None:
                        raise _blocked("an existing raw owner observation is required")
                    raw = raw_head.observation
                    _require_existing_source_chain(source=source, raw=raw, row=row)

                    version = f"refresh-{uuid4().hex}"
                    observer = build_existing_account_reobserver(using=using, settings=settings)
                    owner_stages = build_simulated_account_creation_stages(
                        using=using,
                        settings=settings,
                    )
                    account_stages = build_canonical_account_creation_stages(
                        using=using,
                        settings=settings,
                        requester=CanonicalAccountCreationRequester(
                            actor_id=f"django-user:{owner_user_id}",
                            user_id=owner_user_id,
                        ),
                        physical_row_provider=build_account_physical_row_v2_provider(using=using),
                    )
                    if (
                        owner_stages.database_alias != using
                        or account_stages.database_alias != using
                    ):
                        raise _blocked("all owner evidence stages must share one database alias")
                    pipeline = SimulatedAccountEvidencePipeline(
                        aliases=SimulatedAccountEvidencePipelineAliases(
                            owner=using,
                            raw=using,
                            source_v2=using,
                            account_v2=using,
                        ),
                        raw_writer=_ReobservedRawWriter(
                            observer=observer,
                            expected=row,
                            observation_id=raw.observation_id,
                            observation_version=version,
                        ),
                        source_capture=owner_stages.source_capture,
                        account_capture=account_stages.physical_capture,
                    )
                    mutation = SimulatedAccountPhysicalRowMutation(
                        observation_id=raw.observation_id,
                        mutation_version=version,
                        row_pk=row.row_pk,
                        row_user_id=row.user_id,
                        raw_account_type=row.account_type.value,
                        is_active=row.is_active,
                        row_created_at=row.row_created_at,
                        row_updated_at=row.row_updated_at,
                        observed_at=row.observed_at,
                    )
                    account_reference = UnverifiedCanonicalAccountReference(
                        account_namespace=source.account_namespace,
                        account_id=source.account_id,
                        underlying_unified_account_namespace=(
                            source.underlying_unified_account_namespace
                        ),
                        underlying_unified_account_id=source.underlying_unified_account_id,
                    )
                    refreshed = pipeline.record_update(mutation, account_reference)
                    final = reader.read_locked(row_pk=account_id)
                    if type(final) is not CurrentAccountOwnership or not _same_live_row(row, final):
                        raise CurrentAccountOwnershipUnavailable(
                            "physical owner row changed during evidence refresh"
                        )
                    completed_at = timezone.now()
                    valid_until = min(
                        refreshed.raw.valid_until,
                        refreshed.source_v2.valid_until,
                        refreshed.account_v2.valid_until,
                    )
                    if (
                        refreshed.raw.row_updated_at != final.row_updated_at
                        or refreshed.source_v2.row_updated_at != final.row_updated_at
                        or refreshed.account_v2.row_updated_at != final.row_updated_at
                        or refreshed.source_v2.account_id != source.account_id
                        or refreshed.account_v2.account_id != source.account_id
                        or refreshed.source_v2.is_current_at(completed_at) is False
                        or refreshed.account_v2.is_current_at(completed_at) is False
                        or completed_at >= valid_until
                    ):
                        raise _blocked("refreshed account evidence is not current within its TTL")
            final_after_role = reader.read_locked(row_pk=account_id)
            if type(final_after_role) is not CurrentAccountOwnership or not _same_live_row(
                row, final_after_role
            ):
                raise CurrentAccountOwnershipUnavailable(
                    "physical owner row changed during final role verification"
                )
            if get_active_account_creation_evidence_settings(environment) != settings:
                raise _blocked("active account-evidence configuration changed during refresh")
            finished_at = timezone.now()
            if finished_at < completed_at or finished_at >= valid_until:
                raise _blocked(
                    "account evidence expired or its clock moved backwards during final verification"
                )
            return CorporateActionAccountRefreshResult(
                account_id=account_id,
                row_updated_at=final_after_role.row_updated_at,
                source_observed_at=refreshed.raw.observed_at,
                source_recorded_at=refreshed.source_v2.recorded_at,
                account_recorded_at=refreshed.account_v2.recorded_at,
                checked_at=finished_at,
                valid_until=valid_until,
            )
    except AuthorizationError:
        raise
    except CurrentAccountOwnershipUnavailable:
        raise
    except DatabaseError as error:
        raise _blocked("account ownership evidence could not be refreshed") from error


__all__ = [
    "CorporateActionAccountRefreshResult",
    "refresh_owner_simulated_account_evidence",
]
