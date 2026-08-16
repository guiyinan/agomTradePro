"""Unwired three-ledger evidence pipeline for SimulatedAccount mutations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from django.db import connections

from apps.account.application.physical_account_row_observation_v2 import (
    CapturePhysicalAccountRowObservationV2Command,
)
from apps.account.domain.physical_account_row_observation_v2 import PhysicalAccountRowObservationV2
from apps.simulated_trading.application.simulated_account_raw_observation import (
    SimulatedAccountPhysicalRowMutation,
    SimulatedAccountRawObservationConflict,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    CaptureSimulatedAccountRowSourceV2Command,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)


class SimulatedAccountEvidencePipelineCorruption(ValueError):
    """An evidence stage substituted an untrusted or malformed result."""


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


@dataclass(frozen=True, slots=True)
class UnverifiedCanonicalAccountReference:
    """Canonical-form Account identity that is not owner-authoritative evidence."""

    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int

    def __post_init__(self) -> None:
        for field_name in (
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
        ):
            _require_token(getattr(self, field_name), field_name)
        if (
            type(self.underlying_unified_account_id) is not int
            or self.underlying_unified_account_id <= 0
        ):
            raise ValueError("underlying_unified_account_id must be an exact positive integer")


@dataclass(frozen=True, slots=True)
class SimulatedAccountEvidencePipelineAliases:
    """Explicit database aliases for all three persistence stages."""

    owner: str
    raw: str
    source_v2: str
    account_v2: str

    def __post_init__(self) -> None:
        for field_name in ("owner", "raw", "source_v2", "account_v2"):
            _require_token(getattr(self, field_name), field_name)
        if len({self.owner, self.raw, self.source_v2, self.account_v2}) != 1:
            raise ValueError("all evidence stages must share the owner database alias")


@dataclass(frozen=True, slots=True)
class SimulatedAccountEvidencePipelineResult:
    """Exact outputs from the raw, source-v2, and Account-v2 stages."""

    raw: SimulatedAccountRawObservation
    source_v2: SimulatedAccountRowSourceV2
    account_v2: PhysicalAccountRowObservationV2

    def __post_init__(self) -> None:
        if type(self.raw) is not SimulatedAccountRawObservation:
            raise TypeError("raw must be an exact SimulatedAccountRawObservation")
        SimulatedAccountRawObservation.__post_init__(self.raw)
        if type(self.source_v2) is not SimulatedAccountRowSourceV2:
            raise TypeError("source_v2 must be an exact SimulatedAccountRowSourceV2")
        SimulatedAccountRowSourceV2.__post_init__(self.source_v2)
        if type(self.account_v2) is not PhysicalAccountRowObservationV2:
            raise TypeError("account_v2 must be an exact PhysicalAccountRowObservationV2")
        PhysicalAccountRowObservationV2.__post_init__(self.account_v2)


class SimulatedAccountMutationWriterProtocol(Protocol):
    """Record one owner mutation without selecting a v1 fallback."""

    def record_create(
        self, mutation: SimulatedAccountPhysicalRowMutation
    ) -> SimulatedAccountRawObservation: ...

    def record_update(
        self, mutation: SimulatedAccountPhysicalRowMutation
    ) -> SimulatedAccountRawObservation: ...

    def record_delete(
        self, mutation: SimulatedAccountPhysicalRowMutation
    ) -> SimulatedAccountRawObservation: ...


class SimulatedAccountRowSourceV2CaptureProtocol(Protocol):
    """Capture the raw-bound owner source-v2 projection."""

    def execute(
        self, command: CaptureSimulatedAccountRowSourceV2Command
    ) -> SimulatedAccountRowSourceV2: ...


class PhysicalAccountRowObservationV2CaptureProtocol(Protocol):
    """Capture the Account-owned v2 observation with its configured recorder."""

    def execute(
        self, command: CapturePhysicalAccountRowObservationV2Command
    ) -> PhysicalAccountRowObservationV2: ...


class SimulatedAccountEvidencePipeline:
    """Run all evidence stages inside one caller-owned database transaction."""

    __slots__ = (
        "_account_capture",
        "_aliases",
        "_raw_writer",
        "_source_capture",
    )

    def __init__(
        self,
        *,
        aliases: SimulatedAccountEvidencePipelineAliases,
        raw_writer: SimulatedAccountMutationWriterProtocol,
        source_capture: SimulatedAccountRowSourceV2CaptureProtocol,
        account_capture: PhysicalAccountRowObservationV2CaptureProtocol,
    ) -> None:
        if type(aliases) is not SimulatedAccountEvidencePipelineAliases:
            raise TypeError("aliases must be exact SimulatedAccountEvidencePipelineAliases")
        SimulatedAccountEvidencePipelineAliases.__post_init__(aliases)
        self._aliases = aliases
        self._raw_writer = raw_writer
        self._source_capture = source_capture
        self._account_capture = account_capture

    def record_create(
        self,
        mutation: SimulatedAccountPhysicalRowMutation,
        account: UnverifiedCanonicalAccountReference,
    ) -> SimulatedAccountEvidencePipelineResult:
        """Run raw, source-v2, and Account-v2 capture for a create event."""

        return self._run("create", mutation, account)

    def record_update(
        self,
        mutation: SimulatedAccountPhysicalRowMutation,
        account: UnverifiedCanonicalAccountReference,
    ) -> SimulatedAccountEvidencePipelineResult:
        """Run raw, source-v2, and Account-v2 capture for an update event."""

        return self._run("update", mutation, account)

    def record_delete(
        self,
        mutation: SimulatedAccountPhysicalRowMutation,
        account: UnverifiedCanonicalAccountReference,
    ) -> SimulatedAccountEvidencePipelineResult:
        """Run all three stages and preserve the terminal tombstone revision."""

        return self._run("delete", mutation, account)

    def _run(
        self,
        operation: str,
        mutation: SimulatedAccountPhysicalRowMutation,
        account: UnverifiedCanonicalAccountReference,
    ) -> SimulatedAccountEvidencePipelineResult:
        if type(mutation) is not SimulatedAccountPhysicalRowMutation:
            raise TypeError("mutation must be an exact SimulatedAccountPhysicalRowMutation")
        SimulatedAccountPhysicalRowMutation.__post_init__(mutation)
        if type(account) is not UnverifiedCanonicalAccountReference:
            raise TypeError("account must be an exact UnverifiedCanonicalAccountReference")
        UnverifiedCanonicalAccountReference.__post_init__(account)
        if mutation.row_pk != account.underlying_unified_account_id:
            raise ValueError("physical mutation row and canonical Account reference differ")
        if not connections[self._aliases.owner].in_atomic_block:
            raise SimulatedAccountRawObservationConflict(
                "evidence pipeline requires the caller-owned database transaction"
            )
        raw_method = {
            "create": self._raw_writer.record_create,
            "update": self._raw_writer.record_update,
            "delete": self._raw_writer.record_delete,
        }[operation]
        raw = raw_method(mutation)
        if type(raw) is not SimulatedAccountRawObservation:
            raise SimulatedAccountEvidencePipelineCorruption(
                "raw stage substituted the observation"
            )
        SimulatedAccountRawObservation.__post_init__(raw)
        source = self._source_capture.execute(
            CaptureSimulatedAccountRowSourceV2Command(
                source_id=raw.observation_id,
                source_version=raw.observation_version,
                expected_raw_observation_content_hash=raw.content_hash,
                account_namespace=account.account_namespace,
                account_id=account.account_id,
                underlying_unified_account_namespace=(account.underlying_unified_account_namespace),
                underlying_unified_account_id=account.underlying_unified_account_id,
            )
        )
        if type(source) is not SimulatedAccountRowSourceV2:
            raise SimulatedAccountEvidencePipelineCorruption(
                "source-v2 stage substituted the source"
            )
        SimulatedAccountRowSourceV2.__post_init__(source)
        account_observation = self._account_capture.execute(
            CapturePhysicalAccountRowObservationV2Command(
                observation_id=raw.observation_id,
                observation_version=raw.observation_version,
                source_id=source.source_id,
                source_version=source.source_version,
                expected_source_content_hash=source.content_hash,
                account_namespace=account.account_namespace,
                account_id=account.account_id,
                underlying_unified_account_namespace=(account.underlying_unified_account_namespace),
                underlying_unified_account_id=account.underlying_unified_account_id,
            )
        )
        if type(account_observation) is not PhysicalAccountRowObservationV2:
            raise SimulatedAccountEvidencePipelineCorruption(
                "Account-v2 stage substituted the observation"
            )
        PhysicalAccountRowObservationV2.__post_init__(account_observation)
        return SimulatedAccountEvidencePipelineResult(
            raw=raw,
            source_v2=source,
            account_v2=account_observation,
        )


__all__ = [
    "PhysicalAccountRowObservationV2CaptureProtocol",
    "SimulatedAccountEvidencePipeline",
    "SimulatedAccountEvidencePipelineAliases",
    "SimulatedAccountEvidencePipelineCorruption",
    "SimulatedAccountEvidencePipelineResult",
    "SimulatedAccountMutationWriterProtocol",
    "SimulatedAccountRowSourceV2CaptureProtocol",
    "UnverifiedCanonicalAccountReference",
]
