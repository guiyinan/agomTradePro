"""Application boundary for server-owned R4 candidate-family construction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from apps.portfolio.domain.macro_factor_risk_optimizer import (
    MacroRiskCandidateFamilyResult,
    MacroRiskCandidateFamilySource,
    MacroRiskSolverPolicy,
    build_macro_risk_candidate_family,
)


def _require_text(value: str, field_name: str, *, maximum: int = 160) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")


def _require_hash(value: str, field_name: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field_name} must be a sha256 digest")
    if any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a sha256 digest")


def _require_utc(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field_name} must be UTC")


class MacroRiskCandidateFamilyUnavailable(RuntimeError):
    """Raised when an exact sealed dependency cannot be resolved unchanged."""


@dataclass(frozen=True)
class BuildMacroRiskCandidateFamilyCommand:
    """ID-only command; optimized weights are deliberately not accepted."""

    source_id: str
    source_version: str
    expected_source_hash: str
    policy_id: str
    policy_version: str
    expected_policy_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_id", self.source_id),
            ("source_version", self.source_version),
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
        ):
            _require_text(value, field_name)
        _require_hash(self.expected_source_hash, "expected_source_hash")
        _require_hash(self.expected_policy_hash, "expected_policy_hash")
        _require_utc(self.as_of, "as_of")


class MacroRiskCandidateFamilySourceProvider(Protocol):
    """Resolve an exact sealed optimizer source without fallback."""

    def get_exact(self, *, source_id: str, source_version: str, content_hash: str) -> object:
        """Return the exact requested source or a non-source sentinel."""


class MacroRiskSolverPolicyProvider(Protocol):
    """Resolve an exact sealed solver policy without fallback."""

    def get_exact(self, *, policy_id: str, policy_version: str, policy_hash: str) -> object:
        """Return the exact requested policy or a non-policy sentinel."""


class MacroRiskCandidateFamilyClock(Protocol):
    """Provide the current UTC cutoff for future-request rejection."""

    def now(self) -> datetime:
        """Return current UTC time."""


class BuildMacroRiskCandidateFamily:
    """Resolve exact inputs and invoke the pure deterministic optimizer."""

    def __init__(
        self,
        *,
        source_provider: MacroRiskCandidateFamilySourceProvider,
        policy_provider: MacroRiskSolverPolicyProvider,
        clock: MacroRiskCandidateFamilyClock,
    ) -> None:
        self._source_provider = source_provider
        self._policy_provider = policy_provider
        self._clock = clock

    def execute(
        self, command: BuildMacroRiskCandidateFamilyCommand
    ) -> MacroRiskCandidateFamilyResult:
        """Build a research-only family after live exact-identity verification."""

        if type(command) is not BuildMacroRiskCandidateFamilyCommand:  # noqa: E721
            raise MacroRiskCandidateFamilyUnavailable(
                "command must be the exact BuildMacroRiskCandidateFamilyCommand type"
            )
        try:
            BuildMacroRiskCandidateFamilyCommand.__post_init__(command)
        except ValueError as error:
            raise MacroRiskCandidateFamilyUnavailable("command live validation failed") from error
        now = self._clock.now()
        _require_utc(now, "clock.now")
        if command.as_of > now:
            raise MacroRiskCandidateFamilyUnavailable("as_of cannot be in the future")
        resolved_source = self._source_provider.get_exact(
            source_id=command.source_id,
            source_version=command.source_version,
            content_hash=command.expected_source_hash,
        )
        if type(resolved_source) is not MacroRiskCandidateFamilySource:  # noqa: E721
            raise MacroRiskCandidateFamilyUnavailable("exact source is unavailable")
        try:
            MacroRiskCandidateFamilySource.__post_init__(resolved_source)
        except ValueError as error:
            raise MacroRiskCandidateFamilyUnavailable("source seal validation failed") from error
        if resolved_source.source_id != command.source_id:
            raise MacroRiskCandidateFamilyUnavailable("source id mismatch")
        if resolved_source.source_version != command.source_version:
            raise MacroRiskCandidateFamilyUnavailable("source version mismatch")
        if resolved_source.content_hash.lower() != command.expected_source_hash.lower():
            raise MacroRiskCandidateFamilyUnavailable("source hash mismatch")
        resolved_policy = self._policy_provider.get_exact(
            policy_id=command.policy_id,
            policy_version=command.policy_version,
            policy_hash=command.expected_policy_hash,
        )
        if type(resolved_policy) is not MacroRiskSolverPolicy:  # noqa: E721
            raise MacroRiskCandidateFamilyUnavailable("exact solver policy is unavailable")
        try:
            MacroRiskSolverPolicy.__post_init__(resolved_policy)
        except ValueError as error:
            raise MacroRiskCandidateFamilyUnavailable("policy seal validation failed") from error
        if resolved_policy.policy_id != command.policy_id:
            raise MacroRiskCandidateFamilyUnavailable("policy id mismatch")
        if resolved_policy.policy_version != command.policy_version:
            raise MacroRiskCandidateFamilyUnavailable("policy version mismatch")
        if resolved_policy.policy_hash.lower() != command.expected_policy_hash.lower():
            raise MacroRiskCandidateFamilyUnavailable("policy hash mismatch")
        return build_macro_risk_candidate_family(
            source=resolved_source,
            policy=resolved_policy,
            evaluated_at=command.as_of,
        )
