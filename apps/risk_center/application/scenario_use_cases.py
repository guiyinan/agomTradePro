"""Application orchestration for governed and reproducible stress scenarios."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from apps.risk_center.application.scenario_dtos import (
    ActivateScenarioSetCommandDTO,
    CreateScenarioRevisionCommandDTO,
    PortfolioSnapshotDTO,
    ScenarioMarketDataDTO,
    ScenarioRunRequestDTO,
    ScenarioRunResultDTO,
    ScenarioSummaryDTO,
    ScenarioValidationDTO,
)
from apps.risk_center.application.scenario_ports import (
    PortfolioSnapshotProviderProtocol,
    ScenarioActivationRepositoryProtocol,
    ScenarioMarketDataProviderProtocol,
    ScenarioQueryRepositoryProtocol,
    ScenarioRevisionRepositoryProtocol,
    ScenarioRunEvidenceRepositoryProtocol,
)
from apps.risk_center.domain.scenarios import (
    PortfolioExposure,
    ScenarioActivation,
    ScenarioImpact,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioRunEvidence,
    ScenarioSetRevision,
    ScenarioType,
    evaluate_scenario,
)


class ScenarioConfigurationError(RuntimeError):
    """Raised when canonical scenario configuration is absent or inconsistent."""


class ScenarioNotFoundError(LookupError):
    """Raised when an explicitly versioned scenario object is missing."""


class ScenarioRunBlockedError(RuntimeError):
    """Raised when stale, unpublished, missing, or future data blocks a run."""


class ListScenarioDefinitionsUseCase:
    """List repository-driven scenarios and fail closed on an empty catalog."""

    def __init__(self, repository: ScenarioQueryRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        scenario_type: ScenarioType | None = None,
        include_inactive: bool = False,
    ) -> tuple[ScenarioSummaryDTO, ...]:
        """Return current revisions without any static catalog fallback."""

        definitions = self._repository.list_definitions(include_retired=include_inactive)
        revisions = self._repository.list_current_revisions(
            scenario_type=scenario_type,
            include_inactive=include_inactive,
        )
        if not definitions or not revisions:
            raise ScenarioConfigurationError(
                "stress scenario catalog is empty; initialize or configure Risk Center"
            )
        definitions_by_key = {item.scenario_key: item for item in definitions}
        summaries = tuple(
            ScenarioSummaryDTO(definition=definitions_by_key[item.scenario_key], revision=item)
            for item in revisions
            if item.scenario_key in definitions_by_key
        )
        if not summaries:
            raise ScenarioConfigurationError("stress scenario catalog has no eligible revisions")
        return summaries


class GetScenarioRevisionUseCase:
    """Resolve an immutable scenario revision by id, key, or legacy alias."""

    def __init__(self, repository: ScenarioQueryRepositoryProtocol) -> None:
        self._repository = repository

    def execute(self, identifier: str, *, version: int | None = None) -> ScenarioRevision:
        """Return the requested revision or a stable not-found error."""

        revision = self._repository.get_revision(identifier, version=version)
        if revision is None:
            raise ScenarioNotFoundError(f"stress scenario not found: {identifier}")
        return revision


class ListScenarioRevisionsUseCase:
    """Return the append-only history for one scenario identity."""

    def __init__(self, repository: ScenarioQueryRepositoryProtocol) -> None:
        self._repository = repository

    def execute(self, identifier: str) -> tuple[ScenarioRevision, ...]:
        """Return newest-first history or a stable not-found error."""

        revisions = self._repository.list_revisions(identifier)
        if not revisions:
            raise ScenarioNotFoundError(f"stress scenario not found: {identifier}")
        return revisions


class GetActiveScenarioSetUseCase:
    """Read the active scenario-set revision for one runtime scope."""

    def __init__(self, repository: ScenarioQueryRepositoryProtocol) -> None:
        self._repository = repository

    def execute(self, *, environment: str, purpose: str) -> ScenarioSetRevision:
        """Fail closed when no active set is configured."""

        revision = self._repository.get_active_set_revision(
            environment=environment,
            purpose=purpose,
        )
        if revision is None:
            raise ScenarioConfigurationError(
                f"no active scenario set for environment={environment}, purpose={purpose}"
            )
        return revision


class CreateScenarioRevisionDraftUseCase:
    """Append a validated draft/candidate without activating it."""

    def __init__(self, repository: ScenarioRevisionRepositoryProtocol) -> None:
        self._repository = repository

    def execute(self, command: CreateScenarioRevisionCommandDTO) -> ScenarioRevision:
        """Allocate revision id/version under a repository lock and append it."""

        return self._repository.append_next_revision(command)


class ActivateScenarioSetRevisionUseCase:
    """Delegate the atomic active-pointer transition to the persistence boundary."""

    def __init__(self, repository: ScenarioActivationRepositoryProtocol) -> None:
        self._repository = repository

    def execute(self, command: ActivateScenarioSetCommandDTO) -> ScenarioActivation:
        """Activate an already-approved set revision with optimistic locking."""

        return self._repository.activate_set_revision(command)


class ValidateScenarioRevisionUseCase:
    """Provide a side-effect-free validation projection."""

    def execute(self, revision: ScenarioRevision) -> ScenarioValidationDTO:
        """Return validated hash evidence for an already typed revision."""

        return ScenarioValidationDTO(
            valid=True,
            scenario_revision_id=revision.revision_id,
            content_hash=revision.content_hash,
        )


def _validate_inputs(
    request: ScenarioRunRequestDTO,
    snapshot: PortfolioSnapshotDTO,
    market_data: ScenarioMarketDataDTO,
) -> None:
    if snapshot.snapshot_id != request.portfolio_snapshot_id:
        raise ScenarioRunBlockedError("portfolio_snapshot_id_mismatch")
    if snapshot.as_of_time > request.as_of_time:
        raise ScenarioRunBlockedError("portfolio_snapshot_from_future")
    if market_data.observed_at > request.as_of_time:
        raise ScenarioRunBlockedError("market_observation_from_future")
    if market_data.published_at > request.as_of_time:
        raise ScenarioRunBlockedError("market_publication_from_future")
    if market_data.must_not_use_for_decision:
        raise ScenarioRunBlockedError(market_data.blocked_reason)


def _calculate_impact(
    revision: ScenarioRevision,
    snapshot: PortfolioSnapshotDTO,
    market_data: ScenarioMarketDataDTO,
) -> ScenarioImpact:
    exposures = tuple(
        PortfolioExposure(
            asset_code=item.asset_code,
            weight=item.market_value / snapshot.net_asset_value,
            attributes=item.attributes,
        )
        for item in snapshot.positions
        if item.market_value > 0
    )
    return evaluate_scenario(
        revision,
        exposures=exposures,
        initial_value=snapshot.net_asset_value,
        return_series=market_data.return_series,
    )


class PreviewScenarioImpactUseCase:
    """Calculate a scenario impact with zero Risk Center writes."""

    def __init__(
        self,
        scenario_repository: ScenarioQueryRepositoryProtocol,
        portfolio_provider: PortfolioSnapshotProviderProtocol,
        market_data_provider: ScenarioMarketDataProviderProtocol,
    ) -> None:
        self._scenarios = scenario_repository
        self._portfolios = portfolio_provider
        self._market_data = market_data_provider

    def execute(self, request: ScenarioRunRequestDTO) -> ScenarioImpact:
        """Return an impact only when every input is exact and decision-usable."""

        revision = self._scenarios.get_revision(request.scenario_revision_id)
        if revision is None:
            raise ScenarioNotFoundError("stress scenario revision not found")
        if revision.status not in {
            ScenarioRevisionStatus.APPROVED,
            ScenarioRevisionStatus.ACTIVE,
        }:
            raise ScenarioRunBlockedError("scenario_revision_not_approved")
        snapshot = self._portfolios.get_snapshot(
            request.portfolio_snapshot_id,
            as_of_time=request.as_of_time,
        )
        if snapshot is None:
            raise ScenarioRunBlockedError("portfolio_snapshot_missing")
        data = self._market_data.get_market_data(
            revision,
            asset_codes=tuple(item.asset_code for item in snapshot.positions),
            as_of_time=request.as_of_time,
        )
        _validate_inputs(request, snapshot, data)
        return _calculate_impact(revision, snapshot, data)


class RunPortfolioStressTestUseCase:
    """Calculate and persist the exact evidence for a portfolio stress test."""

    def __init__(
        self,
        scenario_repository: ScenarioQueryRepositoryProtocol,
        run_evidence_repository: ScenarioRunEvidenceRepositoryProtocol,
        portfolio_provider: PortfolioSnapshotProviderProtocol,
        market_data_provider: ScenarioMarketDataProviderProtocol,
    ) -> None:
        self._scenarios = scenario_repository
        self._evidence = run_evidence_repository
        self._portfolios = portfolio_provider
        self._market_data = market_data_provider

    def execute(self, request: ScenarioRunRequestDTO) -> ScenarioRunResultDTO:
        """Persist append-only evidence only after all fail-closed checks pass."""

        revision = self._scenarios.get_revision(request.scenario_revision_id)
        if revision is None:
            raise ScenarioNotFoundError("stress scenario revision not found")
        if revision.status not in {
            ScenarioRevisionStatus.APPROVED,
            ScenarioRevisionStatus.ACTIVE,
        }:
            raise ScenarioRunBlockedError("scenario_revision_not_approved")
        snapshot = self._portfolios.get_snapshot(
            request.portfolio_snapshot_id,
            as_of_time=request.as_of_time,
        )
        if snapshot is None:
            raise ScenarioRunBlockedError("portfolio_snapshot_missing")
        data = self._market_data.get_market_data(
            revision,
            asset_codes=tuple(item.asset_code for item in snapshot.positions),
            as_of_time=request.as_of_time,
        )
        _validate_inputs(request, snapshot, data)
        impact = _calculate_impact(revision, snapshot, data)
        evidence = ScenarioRunEvidence(
            run_id=str(uuid4()),
            scenario_revision_id=revision.revision_id,
            scenario_set_revision_id=request.scenario_set_revision_id,
            portfolio_snapshot_id=snapshot.snapshot_id,
            portfolio_snapshot_hash=snapshot.content_hash,
            as_of_time=request.as_of_time,
            data_evidence_ids=data.evidence_ids,
            result_hash=impact.result_hash,
            allocation_policy_version=request.allocation_policy_version,
            code_version=request.code_version,
            created_at=datetime.now(UTC),
        )
        return ScenarioRunResultDTO(
            impact=impact,
            evidence=self._evidence.save_run_evidence(evidence),
        )


ListScenarioDefinitions = ListScenarioDefinitionsUseCase
GetActiveScenarioSet = GetActiveScenarioSetUseCase
CreateScenarioRevisionDraft = CreateScenarioRevisionDraftUseCase
ValidateScenarioRevision = ValidateScenarioRevisionUseCase
PreviewScenarioImpact = PreviewScenarioImpactUseCase
RunPortfolioStressTest = RunPortfolioStressTestUseCase
ActivateScenarioSetRevision = ActivateScenarioSetRevisionUseCase


__all__ = [
    "ActivateScenarioSetRevision",
    "ActivateScenarioSetRevisionUseCase",
    "CreateScenarioRevisionDraft",
    "CreateScenarioRevisionDraftUseCase",
    "GetActiveScenarioSet",
    "GetActiveScenarioSetUseCase",
    "GetScenarioRevisionUseCase",
    "ListScenarioRevisionsUseCase",
    "ListScenarioDefinitions",
    "ListScenarioDefinitionsUseCase",
    "PreviewScenarioImpact",
    "PreviewScenarioImpactUseCase",
    "RunPortfolioStressTest",
    "RunPortfolioStressTestUseCase",
    "ScenarioConfigurationError",
    "ScenarioNotFoundError",
    "ScenarioRunBlockedError",
    "ValidateScenarioRevision",
    "ValidateScenarioRevisionUseCase",
]
