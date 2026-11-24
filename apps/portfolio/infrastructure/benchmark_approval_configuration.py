"""Exact current planning policy and benchmark methodology checks at issuance and use."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import connections

from apps.portfolio.domain.benchmark_execution_approval import BenchmarkValuationFacts

from .planning_policy_activation_repository import DjangoPlanningPolicyActivationRepository
from .planning_policy_definition_repository import DjangoPlanningPolicyDefinitionRepository
from .policy_benchmark_daily_valuation_models import PortfolioBenchmarkValuationEpochModel
from .policy_benchmark_definition_repository import DjangoPolicyBenchmarkDefinitionRepository
from .policy_benchmark_methodology_activation_repository import (
    DjangoPolicyBenchmarkMethodologyActivationRepository,
)


@dataclass(frozen=True, slots=True)
class _DatabaseCutoff:
    instant: datetime

    def now(self) -> datetime:
        return self.instant


def valuation_owner_selector(valuation_id: UUID, using: str) -> int | None:
    """Read only the candidate owner header before looking up any external account facts."""
    return (
        PortfolioBenchmarkValuationEpochModel._default_manager.using(using)
        .filter(pk=valuation_id)
        .values_list("owner_user_id", flat=True)
        .first()
    )


def lock_benchmark_configuration(using: str) -> None:
    """Exclude replacement, raw mutation and truncation of the low-write configuration ledgers."""
    with connections[using].cursor() as c:
        c.execute("""
            LOCK TABLE portfolio_planning_policy_definition, portfolio_planning_policy_activation_subject,
                       portfolio_planning_policy_activation,
                       portfolio_policy_benchmark_definition,
                       portfolio_policy_benchmark_method_activation_subject,
                       portfolio_policy_benchmark_method_activation IN SHARE MODE NOWAIT
        """)


def configuration_valid_until(
    *, facts: BenchmarkValuationFacts, as_of: datetime, using: str
) -> datetime | None:
    """Reconstruct both real two-person activation heads and their exact definition identities."""
    clock = _DatabaseCutoff(as_of)
    definition_ref = facts.definition_ref
    definition = DjangoPolicyBenchmarkDefinitionRepository(using=using, clock=clock).get_exact(
        definition_id=definition_ref.artifact_id,
        definition_version=definition_ref.artifact_version,
        expected_content_hash=definition_ref.content_hash,
        as_of=as_of,
    )
    if definition is None:
        return None
    methodology = DjangoPolicyBenchmarkMethodologyActivationRepository(
        using=using, clock=clock
    ).get_current_head(
        definition_id=definition.definition_id,
        as_of=as_of,
    )
    planning = DjangoPlanningPolicyActivationRepository(using=using, clock=clock).get_current_head(
        policy_id=facts.planning_policy_ref.artifact_id,
        as_of=as_of,
    )
    policy_ref = facts.planning_policy_ref
    planning_definition = DjangoPlanningPolicyDefinitionRepository(
        using=using, clock=clock
    ).get_exact(
        policy_id=policy_ref.artifact_id,
        policy_version=policy_ref.artifact_version,
        expected_content_hash=policy_ref.content_hash,
        as_of=as_of,
    )
    if methodology is None or planning is None or planning_definition is None:
        return None
    method_ref = facts.methodology_activation_ref
    policy = facts.planning_policy_ref
    activation = facts.planning_activation_ref
    if (
        (methodology.activation_id, methodology.activation_version, methodology.content_hash)
        != (method_ref.artifact_id, method_ref.artifact_version, method_ref.content_hash)
        or (methodology.subject.definition_version, methodology.subject.definition_content_hash)
        != (definition.definition_version, definition.content_hash)
        or (planning.activation_id, planning.activation_version, planning.content_hash)
        != (activation.artifact_id, activation.artifact_version, activation.content_hash)
        or (
            planning.subject.policy_id,
            planning.subject.policy_version,
            planning.subject.definition_content_hash,
        )
        != (policy.artifact_id, policy.artifact_version, policy.content_hash)
    ):
        return None
    return min(
        definition.valid_until,
        methodology.valid_until,
        planning_definition.valid_until,
        planning.valid_until,
    )
