"""Explicit, source-bound pressure runs retained as Scenario evidence only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from apps.risk_center.application.portfolio_exit_pressure_dtos import (
    PortfolioPressureProjection,
    RunPortfolioExitPressureCommand,
)
from apps.risk_center.application.portfolio_exit_pressure_ports import (
    PortfolioPressureProjectionProviderProtocol,
    ScenarioPressureClockProtocol,
    ScenarioPressurePreviewProtocol,
)
from apps.risk_center.application.portfolio_pressure_report import (
    build_portfolio_pressure_report_template,
)
from apps.risk_center.application.portfolio_risk_contracts import PortfolioRiskReportPayload
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
    portfolio_risk_content_hash,
)
from apps.risk_center.application.scenario_dtos import ScenarioRunRequestDTO
from apps.risk_center.application.scenario_impact_context import ScenarioImpactContext
from apps.risk_center.application.scenario_ports import ScenarioRunEvidenceRepositoryProtocol
from apps.risk_center.application.scenario_use_cases import ScenarioRunBlockedError
from apps.risk_center.domain.portfolio_exit_pressure import (
    PortfolioExitPressureAssessment,
    PortfolioExitPressureInput,
    evaluate_portfolio_exit_pressure,
)
from apps.risk_center.domain.scenarios import (
    ScenarioRunEvidence,
    scenario_run_snapshot_hash,
)
from core.exceptions import DuplicateResourceError


@dataclass(frozen=True, slots=True)
class PortfolioExitPressureRunResult:
    """One impact context, exit assessment, and persisted evidence record."""

    context: ScenarioImpactContext
    assessment: PortfolioExitPressureAssessment
    evidence: ScenarioRunEvidence
    public_report_template: PortfolioRiskReportPayload


def _require_aware(value: datetime) -> None:
    """Require a server clock value with a concrete timezone offset."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ScenarioRunBlockedError("portfolio_pressure_cutoff_not_aware")


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    """Retain source identity order while removing duplicate references."""

    return tuple(dict.fromkeys(values))


def portfolio_pressure_run_id(
    *,
    actor_user_id: int,
    account_id: int,
    idempotency_key: str,
) -> str:
    """Return the deterministic evidence identity for one actor/account/key."""

    return str(
        uuid5(
            NAMESPACE_URL,
            f"simulated-account-pressure:{actor_user_id}:{account_id}:{idempotency_key}",
        )
    )


def _scenario_market_data_hash(context: ScenarioImpactContext) -> str:
    """Seal every exact market object and clock returned by the preview call."""

    market_data = context.market_data
    return portfolio_risk_content_hash(
        {
            "scenario_revision_id": context.revision.revision_id,
            "scenario_revision_hash": context.revision.content_hash,
            "as_of_time": context.request.as_of_time,
            "evidence_ids": market_data.evidence_ids,
            "observation_precision": market_data.observation_precision,
            "observed_at": market_data.observed_at,
            "observed_on": market_data.observed_on,
            "published_at": market_data.published_at,
            "return_series": market_data.return_series,
            "must_not_use_for_decision": market_data.must_not_use_for_decision,
            "blocked_reason": market_data.blocked_reason,
        }
    )


def _validate_snapshot_binding(
    *,
    projection: PortfolioPressureProjection,
    context: ScenarioImpactContext,
    account_id: int,
) -> None:
    """Reject pressure inputs not matching the exact simulated-account snapshot."""

    if (
        projection.scenario_revision_id != context.revision.revision_id
        or projection.scenario_revision_hash != context.revision.content_hash
    ):
        raise ScenarioRunBlockedError("portfolio_pressure_scenario_revision_mismatch")
    expected_namespace = f"simulated-account:{account_id}"
    if not projection.portfolio_snapshot_id.startswith(f"{expected_namespace}:"):
        raise ScenarioRunBlockedError("portfolio_pressure_snapshot_namespace_mismatch")
    if context.snapshot.account_id not in {expected_namespace, str(account_id)}:
        raise ScenarioRunBlockedError("portfolio_pressure_account_scope_mismatch")
    if context.snapshot.snapshot_id != projection.portfolio_snapshot_id:
        raise ScenarioRunBlockedError("portfolio_pressure_snapshot_id_mismatch")
    if context.request.portfolio_snapshot_id != projection.portfolio_snapshot_id:
        raise ScenarioRunBlockedError("portfolio_pressure_request_snapshot_mismatch")

    snapshot_values = {
        position.asset_code: position.market_value
        for position in context.snapshot.positions
        if position.market_value > 0
    }
    projected_values = {
        position.asset_code: position.market_value for position in projection.positions
    }
    if set(snapshot_values) != set(projected_values):
        raise ScenarioRunBlockedError("portfolio_pressure_position_scope_mismatch")
    if any(snapshot_values[asset_code] != value for asset_code, value in projected_values.items()):
        raise ScenarioRunBlockedError("portfolio_pressure_position_value_mismatch")

    window_source_ids = {
        source_id
        for position in projection.positions
        for window in position.capacity_windows
        for source_id in window.source_evidence_ids
    }
    if not window_source_ids.issubset(set(projection.source_evidence_ids)):
        raise ScenarioRunBlockedError("portfolio_pressure_capacity_source_unbound")
    typed_source_ids = {
        f"{item.source_id}:{item.source_record_id}" for item in projection.source_evidence
    }
    if not typed_source_ids.issubset(set(projection.source_evidence_ids)):
        raise ScenarioRunBlockedError("portfolio_pressure_source_record_unbound")
    if not window_source_ids.issubset(typed_source_ids):
        raise ScenarioRunBlockedError("portfolio_pressure_capacity_record_unbound")


def _input_snapshot_json(
    *,
    command: RunPortfolioExitPressureCommand,
    request: ScenarioRunRequestDTO,
    context: ScenarioImpactContext,
    projection: PortfolioPressureProjection,
    pressure_input: PortfolioExitPressureInput,
) -> str:
    """Retain every typed source, account, revision, and pressure input as canonical JSON."""

    return canonical_portfolio_risk_json(
        {
            "schema": "simulated-account-pressure-input.v1",
            "command": command,
            "request": request,
            "scenario_context": context,
            "account_projection": projection,
            "original_report_json": projection.original_report_json,
            "pressure_input": pressure_input,
        }
    )


def _result_snapshot_json(
    *,
    context: ScenarioImpactContext,
    assessment: PortfolioExitPressureAssessment,
    public_report_template: PortfolioRiskReportPayload,
) -> str:
    """Retain the impact and public report template without a result-hash cycle."""

    return canonical_portfolio_risk_json(
        {
            "schema": "simulated-account-pressure-result.v1",
            "scenario_revision": context.revision,
            "scenario_impact": context.impact,
            "assessment": assessment,
            "public_report_template": public_report_template,
        }
    )


class RunPortfolioExitPressureUseCase:
    """Run an explicit pressure assessment without touching account or order ledgers."""

    def __init__(
        self,
        *,
        preview: ScenarioPressurePreviewProtocol,
        run_evidence_repository: ScenarioRunEvidenceRepositoryProtocol,
        projection_provider: PortfolioPressureProjectionProviderProtocol,
        clock: ScenarioPressureClockProtocol,
    ) -> None:
        self._preview = preview
        self._evidence = run_evidence_repository
        self._projection = projection_provider
        self._clock = clock

    def execute(self, command: RunPortfolioExitPressureCommand) -> PortfolioExitPressureRunResult:
        """Preview once, bind all exact inputs, assess, then persist one run record."""

        as_of_time = self._clock.now()
        _require_aware(as_of_time)
        projection = self._projection.get_pressure_projection(
            actor_user_id=command.actor_user_id,
            account_id=command.account_id,
            scenario_revision_id=command.scenario_version_id,
            as_of_time=as_of_time,
        )
        if projection is None:
            raise ScenarioRunBlockedError("portfolio_pressure_projection_unavailable")
        if projection.original_report_json is None or projection.scenario_label is None:
            raise ScenarioRunBlockedError("portfolio_pressure_original_report_missing")
        if projection.account_snapshot.owner_user_id != command.actor_user_id:
            raise ScenarioRunBlockedError("portfolio_pressure_owner_write_required")
        if projection.account_snapshot.account_id != command.account_id:
            raise ScenarioRunBlockedError("portfolio_pressure_account_scope_mismatch")
        if projection.account_snapshot.read_at > as_of_time:
            raise ScenarioRunBlockedError("portfolio_pressure_account_snapshot_after_cutoff")
        if not projection.portfolio_snapshot_id.startswith(
            f"simulated-account:{command.account_id}:"
        ):
            raise ScenarioRunBlockedError("portfolio_pressure_snapshot_namespace_mismatch")
        if any(item.decision_cutoff != as_of_time for item in projection.source_evidence):
            raise ScenarioRunBlockedError("portfolio_pressure_source_cutoff_mismatch")

        request = ScenarioRunRequestDTO(
            scenario_revision_id=command.scenario_version_id,
            portfolio_snapshot_id=projection.portfolio_snapshot_id,
            as_of_time=as_of_time,
            allocation_policy_version=projection.allocation_policy_version,
            code_version=projection.code_version,
        )
        context = self._preview.execute_with_context(request)
        if context.request != request:
            raise ScenarioRunBlockedError("portfolio_pressure_preview_context_mismatch")
        _validate_snapshot_binding(
            projection=projection,
            context=context,
            account_id=command.account_id,
        )

        source_evidence_ids = _ordered_unique(
            projection.source_evidence_ids
            + context.market_data.evidence_ids
            + tuple(
                source_id
                for position in projection.positions
                for window in position.capacity_windows
                for source_id in window.source_evidence_ids
            )
        )
        pressure_input = PortfolioExitPressureInput(
            scenario_revision=context.revision,
            scenario_impact=context.impact,
            portfolio_snapshot_id=projection.portfolio_snapshot_id,
            portfolio_snapshot_hash=context.snapshot.content_hash,
            as_of_time=as_of_time,
            allocation_policy_version=projection.allocation_policy_version,
            code_version=projection.code_version,
            scenario_market_data_hash=_scenario_market_data_hash(context),
            source_evidence=projection.source_evidence,
            source_evidence_ids=source_evidence_ids,
            positions=projection.positions,
        )
        assessment = evaluate_portfolio_exit_pressure(pressure_input)
        run_id = portfolio_pressure_run_id(
            actor_user_id=command.actor_user_id,
            account_id=command.account_id,
            idempotency_key=command.idempotency_key,
        )
        public_report_template = build_portfolio_pressure_report_template(
            original_report_json=projection.original_report_json,
            scenario_label=projection.scenario_label,
            as_of_time=as_of_time,
            revision=context.revision,
            assessment=assessment,
            projection=projection,
            run_evidence_id=run_id,
            source_evidence_ids=source_evidence_ids,
        )
        input_snapshot_json = _input_snapshot_json(
            command=command,
            request=request,
            context=context,
            projection=projection,
            pressure_input=pressure_input,
        )
        result_snapshot_json = _result_snapshot_json(
            context=context,
            assessment=assessment,
            public_report_template=public_report_template,
        )
        evidence = ScenarioRunEvidence(
            run_id=run_id,
            scenario_revision_id=context.revision.revision_id,
            portfolio_snapshot_id=projection.portfolio_snapshot_id,
            portfolio_snapshot_hash=context.snapshot.content_hash,
            as_of_time=as_of_time,
            data_evidence_ids=source_evidence_ids,
            result_hash=scenario_run_snapshot_hash(
                input_snapshot_json=input_snapshot_json,
                result_snapshot_json=result_snapshot_json,
            ),
            allocation_policy_version=projection.allocation_policy_version,
            code_version=projection.code_version,
            must_not_use_for_decision=public_report_template["must_not_use_for_decision"],
            blocked_reason=(
                "portfolio_pressure_report_not_decision_usable"
                if public_report_template["must_not_use_for_decision"]
                else ""
            ),
            created_at=as_of_time,
            input_snapshot_json=input_snapshot_json,
            result_snapshot_json=result_snapshot_json,
        )
        try:
            persisted = self._evidence.save_run_evidence(evidence)
        except ValueError as error:
            if str(error) == "scenario run id already exists with different evidence":
                raise DuplicateResourceError(
                    message="该运行标识已用于不同的压力输入，请重新读取后再提交。"
                ) from error
            raise
        return PortfolioExitPressureRunResult(
            context=context,
            assessment=assessment,
            evidence=persisted,
            public_report_template=public_report_template,
        )


__all__ = [
    "PortfolioExitPressureRunResult",
    "RunPortfolioExitPressureUseCase",
    "portfolio_pressure_run_id",
]
