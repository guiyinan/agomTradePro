"""Immutable identities for independently approved Portfolio benchmark evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


def _token(value: str) -> None:
    if type(value) is not str or not value or len(value) > 192 or any(c.isspace() for c in value):
        raise ValueError("benchmark identity must be a bounded canonical token")


def _digest(value: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("benchmark content hash is invalid")


@dataclass(frozen=True, slots=True)
class BenchmarkScope:
    """Exact Account owner, tenant and portfolio account shared by every source."""

    account_namespace: str
    account_id: str
    owner_user_id: int
    tenant_id: str
    owner_id: str

    def __post_init__(self) -> None:
        for token in (self.account_namespace, self.account_id, self.tenant_id, self.owner_id):
            _token(token)
        if type(self.owner_user_id) is not int or self.owner_user_id < 1:
            raise ValueError("benchmark owner user is invalid")


@dataclass(frozen=True, slots=True)
class BenchmarkArtifactRef:
    """One immutable upstream definition or activation."""

    artifact_id: str
    artifact_version: str
    content_hash: str

    def __post_init__(self) -> None:
        _token(self.artifact_id)
        _token(self.artifact_version)
        _digest(self.content_hash)


@dataclass(frozen=True, slots=True)
class BenchmarkValuationFacts:
    """One source-verified daily valuation and its configuration heads."""

    valuation_id: UUID
    valuation_version: int
    content_hash: str
    scope: BenchmarkScope
    definition_ref: BenchmarkArtifactRef
    methodology_activation_ref: BenchmarkArtifactRef
    planning_policy_ref: BenchmarkArtifactRef
    planning_activation_ref: BenchmarkArtifactRef
    observation_date: date
    observed_at: datetime
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if (
            type(self.valuation_id) is not UUID
            or type(self.valuation_version) is not int
            or self.valuation_version < 1
        ):
            raise ValueError("valuation identity/version is invalid")
        _digest(self.content_hash)
        if type(self.scope) is not BenchmarkScope or type(self.observation_date) is not date:
            raise ValueError("valuation scope/date is invalid")
        for ref in (
            self.definition_ref,
            self.methodology_activation_ref,
            self.planning_policy_ref,
            self.planning_activation_ref,
        ):
            if type(ref) is not BenchmarkArtifactRef:
                raise ValueError("valuation configuration reference is invalid")
        if any(
            type(t) is not datetime or t.utcoffset() is None
            for t in (self.observed_at, self.recorded_at, self.valid_until)
        ):
            raise ValueError("valuation timestamps must be aware")
        if not self.observed_at <= self.recorded_at < self.valid_until:
            raise ValueError("valuation time order is invalid")


@dataclass(frozen=True, slots=True)
class BenchmarkExecutionReceipt:
    """Portfolio's independent benchmark approval for one exact current valuation."""

    approval_id: UUID
    approval_version: int
    content_hash: str
    valuation: BenchmarkValuationFacts
    valid_until: datetime

    def __post_init__(self) -> None:
        if (
            type(self.approval_id) is not UUID
            or type(self.approval_version) is not int
            or self.approval_version < 1
        ):
            raise ValueError("benchmark approval identity/version is invalid")
        _digest(self.content_hash)
        if (
            type(self.valuation) is not BenchmarkValuationFacts
            or type(self.valid_until) is not datetime
            or self.valid_until.utcoffset() is None
        ):
            raise ValueError("benchmark receipt has invalid valuation or validity")
        if not self.valuation.recorded_at < self.valid_until <= self.valuation.valid_until:
            raise ValueError("benchmark receipt exceeds the valuation validity")

    @property
    def owner(self) -> str:
        """Return the owner of the independently signed benchmark."""
        return "portfolio"

    @property
    def artifact_type(self) -> str:
        """Return the published type of the approved Portfolio artifact."""
        return "policy_benchmark_snapshot"

    @property
    def artifact_id(self) -> str:
        """Return the stable canonical approval identity."""
        return str(self.approval_id)

    @property
    def artifact_version(self) -> str:
        """Return the immutable issuance revision."""
        return str(self.approval_version)
