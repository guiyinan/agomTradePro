"""Application-boundary TDD for server-owned R4 candidate construction."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime

import pytest

from apps.portfolio.application.build_macro_risk_candidate_family import (
    BuildMacroRiskCandidateFamily,
    BuildMacroRiskCandidateFamilyCommand,
    MacroRiskCandidateFamilyUnavailable,
)
from apps.portfolio.domain.macro_factor_risk_optimizer import (
    MacroRiskCandidateFamilySource,
    MacroRiskSolverPolicy,
)
from tests.unit.portfolio.test_macro_factor_risk_optimizer import _policy, _source


class _SourceProvider:
    def __init__(self, source: MacroRiskCandidateFamilySource) -> None:
        self.source = source
        self.calls: list[tuple[str, str, str]] = []

    def get_exact(self, *, source_id: str, source_version: str, content_hash: str) -> object:
        self.calls.append((source_id, source_version, content_hash))
        return self.source


class _PolicyProvider:
    def __init__(self, policy: MacroRiskSolverPolicy) -> None:
        self.policy = policy
        self.calls: list[tuple[str, str, str]] = []

    def get_exact(self, *, policy_id: str, policy_version: str, policy_hash: str) -> object:
        self.calls.append((policy_id, policy_version, policy_hash))
        return self.policy


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def _command(
    source: MacroRiskCandidateFamilySource,
    policy: MacroRiskSolverPolicy,
) -> BuildMacroRiskCandidateFamilyCommand:
    return BuildMacroRiskCandidateFamilyCommand(
        source_id=source.source_id,
        source_version=source.source_version,
        expected_source_hash=source.content_hash,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        expected_policy_hash=policy.policy_hash,
        as_of=source.selection_as_of,
    )


def test_application_command_contains_only_sealed_ids_hashes_and_cutoff() -> None:
    names = {field.name for field in fields(BuildMacroRiskCandidateFamilyCommand)}

    assert names == {
        "source_id",
        "source_version",
        "expected_source_hash",
        "policy_id",
        "policy_version",
        "expected_policy_hash",
        "as_of",
    }


def test_application_resolves_exact_sealed_inputs_and_builds_family() -> None:
    source = _source()
    policy = _policy()
    source_provider = _SourceProvider(source)
    policy_provider = _PolicyProvider(policy)
    service = BuildMacroRiskCandidateFamily(
        source_provider=source_provider,
        policy_provider=policy_provider,
        clock=_Clock(source.selection_as_of),
    )

    result = service.execute(_command(source, policy))

    assert result.source_hash == source.content_hash
    assert source_provider.calls == [(source.source_id, source.source_version, source.content_hash)]
    assert policy_provider.calls == [(policy.policy_id, policy.policy_version, policy.policy_hash)]


def test_application_rejects_provider_substitution() -> None:
    source = _source()
    policy = _policy()
    service = BuildMacroRiskCandidateFamily(
        source_provider=_SourceProvider(source),
        policy_provider=_PolicyProvider(policy),
        clock=_Clock(source.selection_as_of),
    )
    command = _command(source, policy)

    with pytest.raises(MacroRiskCandidateFamilyUnavailable, match="source hash mismatch"):
        service.execute(
            BuildMacroRiskCandidateFamilyCommand(
                source_id=command.source_id,
                source_version=command.source_version,
                expected_source_hash="f" * 64,
                policy_id=command.policy_id,
                policy_version=command.policy_version,
                expected_policy_hash=command.expected_policy_hash,
                as_of=command.as_of,
            )
        )


class _CommandSubclass(BuildMacroRiskCandidateFamilyCommand):
    pass


def test_command_subclass_is_rejected_before_any_provider_call() -> None:
    source = _source()
    policy = _policy()
    source_provider = _SourceProvider(source)
    policy_provider = _PolicyProvider(policy)
    service = BuildMacroRiskCandidateFamily(
        source_provider=source_provider,
        policy_provider=policy_provider,
        clock=_Clock(source.selection_as_of),
    )
    original = _command(source, policy)
    command = _CommandSubclass(
        source_id=original.source_id,
        source_version=original.source_version,
        expected_source_hash=original.expected_source_hash,
        policy_id=original.policy_id,
        policy_version=original.policy_version,
        expected_policy_hash=original.expected_policy_hash,
        as_of=original.as_of,
    )

    with pytest.raises(MacroRiskCandidateFamilyUnavailable, match="exact"):
        service.execute(command)

    assert source_provider.calls == []
    assert policy_provider.calls == []


def test_noop_instance_validator_cannot_reach_any_provider() -> None:
    source = _source()
    policy = _policy()
    source_provider = _SourceProvider(source)
    policy_provider = _PolicyProvider(policy)
    service = BuildMacroRiskCandidateFamily(
        source_provider=source_provider,
        policy_provider=policy_provider,
        clock=_Clock(source.selection_as_of),
    )
    command = _command(source, policy)
    object.__setattr__(command, "expected_source_hash", "invalid")
    object.__setattr__(command, "__post_init__", lambda: None)

    with pytest.raises(MacroRiskCandidateFamilyUnavailable, match="live validation"):
        service.execute(command)

    assert source_provider.calls == []
    assert policy_provider.calls == []


def test_provider_source_noop_validator_cannot_bypass_live_seal() -> None:
    source = _source()
    policy = _policy()
    object.__setattr__(source, "content_hash", "f" * 64)
    object.__setattr__(source, "__post_init__", lambda: None)
    source_provider = _SourceProvider(source)
    policy_provider = _PolicyProvider(policy)
    service = BuildMacroRiskCandidateFamily(
        source_provider=source_provider,
        policy_provider=policy_provider,
        clock=_Clock(source.selection_as_of),
    )
    command = BuildMacroRiskCandidateFamilyCommand(
        source_id=source.source_id,
        source_version=source.source_version,
        expected_source_hash=source.content_hash,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        expected_policy_hash=policy.policy_hash,
        as_of=source.selection_as_of,
    )

    with pytest.raises(MacroRiskCandidateFamilyUnavailable, match="seal validation"):
        service.execute(command)

    assert len(source_provider.calls) == 1
    assert policy_provider.calls == []
