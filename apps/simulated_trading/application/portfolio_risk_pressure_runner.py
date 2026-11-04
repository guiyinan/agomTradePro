"""Run an approved pressure Scenario against one prepared simulated account."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import cast

from apps.risk_center.application.portfolio_exit_pressure_dtos import (
    PortfolioPressureProjection,
    RunPortfolioExitPressureCommand,
)
from apps.risk_center.application.portfolio_exit_pressure_ports import (
    PortfolioPressureProjectionProviderProtocol,
    ScenarioPressureClockProtocol,
)
from apps.risk_center.application.portfolio_exit_pressure_use_cases import portfolio_pressure_run_id
from apps.risk_center.application.portfolio_pressure_projection_builder import (
    build_portfolio_pressure_projection,
)
from apps.risk_center.application.portfolio_pressure_report import (
    bind_portfolio_pressure_evidence_hash,
    decode_portfolio_risk_report_json,
    report_payload_from_object,
)
from apps.risk_center.application.portfolio_risk_contracts import (
    PortfolioRiskCheckPayload,
    PortfolioRiskOutcome,
    PortfolioRiskReportPayload,
)
from apps.risk_center.application.portfolio_risk_runtime import PortfolioRiskRuntime
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
)
from apps.risk_center.application.scenario_dtos import PortfolioSnapshotDTO
from apps.risk_center.application.scenario_ports import (
    ScenarioRunEvidenceReadWriteRepositoryProtocol,
)
from apps.risk_center.application.scenario_public import list_scenarios
from apps.risk_center.application.scenario_use_cases import (
    ScenarioConfigurationError,
    ScenarioRunBlockedError,
)
from apps.risk_center.domain.scenarios import (
    ScenarioDefinitionStatus,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioRunEvidence,
)
from apps.simulated_trading.application.portfolio_risk_context import (
    PortfolioRiskClock,
    PortfolioRiskPressureRunner,
    PreparedPortfolioRisk,
)
from apps.simulated_trading.application.portfolio_risk_public import (
    PortfolioRiskAccountAccessDenied,
    PortfolioRiskUnavailable,
)
from core.exceptions import DuplicateResourceError, InvalidInputError, MissingConfigError


class _PreparedScenarioClock(ScenarioPressureClockProtocol):
    """Keep every pressure read on the cutoff already captured by preparation."""

    def __init__(self, value: datetime) -> None:
        """Retain one immutable prepared cutoff."""

        self._value = value

    def now(self) -> datetime:
        """Return the cutoff used by the account, policy, source, and calendar reads."""

        return self._value


@dataclass(frozen=True, slots=True)
class _PreparedPortfolioSnapshotProvider:
    """Expose only the exact holding projection produced from PreparedPortfolioRisk."""

    snapshot: PortfolioSnapshotDTO
    as_of_time: datetime

    def get_snapshot(
        self,
        snapshot_id: str,
        *,
        as_of_time: datetime,
    ) -> PortfolioSnapshotDTO | None:
        """Return the retained snapshot only for its exact identity and cutoff."""

        if snapshot_id != self.snapshot.snapshot_id or as_of_time != self.as_of_time:
            return None
        return self.snapshot


@dataclass(frozen=True, slots=True)
class _PreparedPressureProjectionProvider(PortfolioPressureProjectionProviderProtocol):
    """Expose one built projection without repeating account, source, or policy reads."""

    actor_user_id: int
    account_id: int
    scenario_revision: ScenarioRevision
    as_of_time: datetime
    projection: PortfolioPressureProjection

    def get_pressure_projection(
        self,
        *,
        actor_user_id: int,
        account_id: int,
        scenario_revision_id: str,
        as_of_time: datetime,
    ) -> PortfolioPressureProjection | None:
        """Return the exact prepared projection only to its matching actor and revision."""

        if (
            actor_user_id != self.actor_user_id
            or account_id != self.account_id
            or scenario_revision_id != self.scenario_revision.revision_id
            or as_of_time != self.as_of_time
            or self.projection.scenario_revision_hash != self.scenario_revision.content_hash
        ):
            return None
        return self.projection


class PortfolioRiskPressureRunnerService(PortfolioRiskPressureRunner):
    """Connect a frozen risk context to existing Scenario preview and evidence ports."""

    def __init__(
        self,
        *,
        runtime: PortfolioRiskRuntime,
        code_version: str,
        clock: PortfolioRiskClock,
    ) -> None:
        """Inject Risk Center's Scenario factory and the actual server clock."""

        if type(code_version) is not str or not code_version.strip():
            raise PortfolioRiskUnavailable(code="PORTFOLIO_PRESSURE_CODE_VERSION_UNKNOWN")
        self._runtime = runtime
        self._code_version = code_version
        self._clock = clock

    def run(
        self,
        *,
        prepared: PreparedPortfolioRisk,
        scenario_identifier: str,
        idempotency_key: str,
    ) -> PortfolioRiskReportPayload:
        """Build once from prepared inputs, run the existing Scenario flow, and explain it."""

        if (
            type(scenario_identifier) is not str
            or not scenario_identifier.strip()
            or type(idempotency_key) is not str
            or not idempotency_key.strip()
        ):
            raise InvalidInputError(code="PORTFOLIO_PRESSURE_IDENTITY_REQUIRED")
        if (
            prepared.actor_user_id != prepared.snapshot.owner_user_id
            or prepared.report["account_id"] != prepared.snapshot.account_id
        ):
            raise PortfolioRiskAccountAccessDenied()
        command = RunPortfolioExitPressureCommand(
            actor_user_id=prepared.actor_user_id,
            account_id=prepared.snapshot.account_id,
            scenario_version_id=scenario_identifier,
            idempotency_key=idempotency_key,
            confirmed=True,
        )

        _require_aware(prepared.as_of, code="PORTFOLIO_PRESSURE_PREPARED_CUTOFF_INVALID")
        server_now = self._clock.now()
        _require_aware(server_now, code="PORTFOLIO_PRESSURE_SERVER_CLOCK_INVALID")
        if server_now < prepared.as_of:
            raise PortfolioRiskUnavailable(code="PORTFOLIO_PRESSURE_SERVER_CLOCK_REGRESSED")

        saved_report = _read_existing_pressure_report(
            repository=self._runtime.pressure_evidence_repository,
            actor_user_id=prepared.actor_user_id,
            account_id=prepared.snapshot.account_id,
            scenario_revision_id=command.scenario_version_id,
            idempotency_key=command.idempotency_key,
        )
        if saved_report is not None:
            return saved_report

        revision, scenario_label = _approved_revision(
            scenario_identifier=scenario_identifier,
            as_of=prepared.as_of,
        )
        policy_binding_sha256 = prepared.policy_binding_sha256
        if policy_binding_sha256 is None:
            return _failure_report(
                prepared=prepared,
                revision=revision,
                scenario_label=scenario_label,
                reason_codes=("PORTFOLIO_PRESSURE_POLICY_BINDING_UNKNOWN",),
            )
        policy = prepared.policy
        if policy is None:
            return _failure_report(
                prepared=prepared,
                revision=revision,
                scenario_label=scenario_label,
                reason_codes=("PORTFOLIO_PRESSURE_POLICY_VERSION_UNKNOWN",),
            )
        native_limits = prepared.resources.native_account_limits
        if native_limits is None:
            return _failure_report(
                prepared=prepared,
                revision=revision,
                scenario_label=scenario_label,
                reason_codes=("PORTFOLIO_PRESSURE_NATIVE_LIMITS_UNKNOWN",),
            )

        calendar = prepared.calendar
        open_sessions = calendar.open_sessions if calendar.requested_session_qualified else None
        built = build_portfolio_pressure_projection(
            account_snapshot=prepared.snapshot,
            native_account_limits=native_limits,
            identity_bindings=prepared.identity_bindings,
            assessment=prepared.assessment,
            asset_inputs=prepared.assets,
            scenario_revision=revision,
            open_sessions=open_sessions,
            as_of_time=prepared.as_of,
            risk_policy_version=f"{policy.profile_key}@{policy.profile_version}",
            policy_binding_sha256=policy_binding_sha256,
            allocation_policy_version=f"portfolio-risk-binding:{policy_binding_sha256}",
            code_version=self._code_version,
            calendar_evidence_json=calendar.canonical_evidence_json,
        )
        if built.projection is None or built.portfolio_snapshot is None:
            return _failure_report(
                prepared=prepared,
                revision=revision,
                scenario_label=scenario_label,
                reason_codes=(built.reason_codes or ("PORTFOLIO_PRESSURE_PROJECTION_UNAVAILABLE",)),
            )
        bound_projection = replace(
            built.projection,
            original_report_json=canonical_portfolio_risk_json(prepared.report),
            scenario_label=scenario_label,
        )

        snapshot_provider = _PreparedPortfolioSnapshotProvider(
            snapshot=built.portfolio_snapshot,
            as_of_time=prepared.as_of,
        )
        projection_provider = _PreparedPressureProjectionProvider(
            actor_user_id=prepared.actor_user_id,
            account_id=prepared.snapshot.account_id,
            scenario_revision=revision,
            as_of_time=prepared.as_of,
            projection=bound_projection,
        )
        try:
            use_case = self._runtime.pressure_factory.build(
                portfolio_provider=snapshot_provider,
                projection_provider=projection_provider,
                clock=_PreparedScenarioClock(prepared.as_of),
            )
        except MissingConfigError as error:
            raise PortfolioRiskUnavailable(
                code="PORTFOLIO_PRESSURE_SCENARIO_STORE_UNAVAILABLE"
            ) from error

        try:
            execution_command = RunPortfolioExitPressureCommand(
                actor_user_id=prepared.actor_user_id,
                account_id=prepared.snapshot.account_id,
                scenario_version_id=revision.revision_id,
                idempotency_key=command.idempotency_key,
                confirmed=True,
            )
            result = use_case.execute(execution_command)
        except DuplicateResourceError:
            concurrent_report = _read_existing_pressure_report(
                repository=self._runtime.pressure_evidence_repository,
                actor_user_id=prepared.actor_user_id,
                account_id=prepared.snapshot.account_id,
                scenario_revision_id=command.scenario_version_id,
                idempotency_key=command.idempotency_key,
            )
            if concurrent_report is None:
                raise
            return concurrent_report
        except ScenarioRunBlockedError as error:
            if str(error) == "portfolio_pressure_owner_write_required":
                raise PortfolioRiskAccountAccessDenied() from error
            return _failure_report(
                prepared=prepared,
                revision=revision,
                scenario_label=scenario_label,
                reason_codes=(_reason_code(error),),
            )
        return bind_portfolio_pressure_evidence_hash(
            result.public_report_template,
            result.evidence.result_hash,
        )


def _read_existing_pressure_report(
    *,
    repository: ScenarioRunEvidenceReadWriteRepositoryProtocol,
    actor_user_id: int,
    account_id: int,
    scenario_revision_id: str,
    idempotency_key: str,
) -> PortfolioRiskReportPayload | None:
    """Replay one exact saved report or reject an old/conflicting evidence row."""

    run_id = portfolio_pressure_run_id(
        actor_user_id=actor_user_id,
        account_id=account_id,
        idempotency_key=idempotency_key,
    )
    evidence = repository.get_run_evidence(run_id)
    if evidence is None:
        return None
    if not _stored_command_matches(
        evidence=evidence,
        actor_user_id=actor_user_id,
        account_id=account_id,
        scenario_revision_id=scenario_revision_id,
        idempotency_key=idempotency_key,
    ):
        raise DuplicateResourceError(message="该幂等标识已绑定其他压力请求。")
    report_template = _stored_report_template(
        evidence=evidence,
        actor_user_id=actor_user_id,
        account_id=account_id,
        scenario_revision_id=scenario_revision_id,
        idempotency_key=idempotency_key,
    )
    if report_template is None:
        raise DuplicateResourceError(message="该幂等标识已有旧证据，无法安全复原原始压力报告。")
    return bind_portfolio_pressure_evidence_hash(report_template, evidence.result_hash)


def _stored_command_matches(
    *,
    evidence: ScenarioRunEvidence,
    actor_user_id: int,
    account_id: int,
    scenario_revision_id: str,
    idempotency_key: str,
) -> bool:
    """Check saved actor, account, key, and immutable Scenario revision identity."""

    if evidence.input_snapshot_json is None:
        return False
    input_snapshot = _json_mapping(evidence.input_snapshot_json)
    command = _mapping(input_snapshot.get("command")) if input_snapshot else None
    return (
        evidence.run_id
        == portfolio_pressure_run_id(
            actor_user_id=actor_user_id,
            account_id=account_id,
            idempotency_key=idempotency_key,
        )
        and command is not None
        and command.get("actor_user_id") == actor_user_id
        and command.get("account_id") == account_id
        and command.get("idempotency_key") == idempotency_key
        and command.get("scenario_version_id") == scenario_revision_id
        and command.get("confirmed") is True
        and evidence.scenario_revision_id == scenario_revision_id
    )


def _stored_report_template(
    *,
    evidence: ScenarioRunEvidence,
    actor_user_id: int,
    account_id: int,
    scenario_revision_id: str,
    idempotency_key: str,
) -> PortfolioRiskReportPayload | None:
    """Verify every saved command identity before exposing its exact report."""

    if evidence.input_snapshot_json is None or evidence.result_snapshot_json is None:
        return None
    input_snapshot = _json_mapping(evidence.input_snapshot_json)
    result_snapshot = _json_mapping(evidence.result_snapshot_json)
    if (
        input_snapshot is None
        or result_snapshot is None
        or input_snapshot.get("schema") != "simulated-account-pressure-input.v1"
        or result_snapshot.get("schema") != "simulated-account-pressure-result.v1"
    ):
        return None
    command = _mapping(input_snapshot.get("command"))
    request = _mapping(input_snapshot.get("request"))
    scenario_context = _mapping(input_snapshot.get("scenario_context"))
    projection = _mapping(input_snapshot.get("account_projection"))
    stored_account = _mapping(projection.get("account_snapshot")) if projection else None
    revision = _mapping(scenario_context.get("revision")) if scenario_context else None
    result_revision = _mapping(result_snapshot.get("scenario_revision"))
    report_json = input_snapshot.get("original_report_json")
    projected_report_json = projection.get("original_report_json") if projection else None
    if (
        command is None
        or request is None
        or scenario_context is None
        or projection is None
        or stored_account is None
        or revision is None
        or result_revision is None
        or type(report_json) is not str
        or report_json != projected_report_json
        or report_json != projection.get("original_report_json")
        or command.get("actor_user_id") != actor_user_id
        or command.get("account_id") != account_id
        or command.get("scenario_version_id") != scenario_revision_id
        or command.get("idempotency_key") != idempotency_key
        or request.get("scenario_revision_id") != scenario_revision_id
        or request.get("portfolio_snapshot_id") != evidence.portfolio_snapshot_id
        or revision.get("revision_id") != scenario_revision_id
        or result_revision.get("revision_id") != scenario_revision_id
        or result_revision.get("content_hash") != revision.get("content_hash")
        or projection.get("scenario_revision_id") != scenario_revision_id
        or projection.get("scenario_revision_hash") != revision.get("content_hash")
        or revision.get("content_hash") is None
        or evidence.scenario_revision_id != scenario_revision_id
        or stored_account.get("account_id") != account_id
        or stored_account.get("owner_user_id") != actor_user_id
        or stored_account.get("snapshot_id") != evidence.portfolio_snapshot_id
        or evidence.portfolio_snapshot_id != projection.get("portfolio_snapshot_id")
        or not _as_of_matches_evidence(evidence, request)
    ):
        return None
    original_report = decode_portfolio_risk_report_json(report_json)
    template = report_payload_from_object(result_snapshot.get("public_report_template"))
    if original_report is None or template is None:
        return None
    if (
        original_report["account_id"] != account_id
        or original_report["as_of"] != _as_of_from_snapshot(request)
        or template["account_id"] != account_id
        or template["as_of"] != _as_of_from_snapshot(request)
        or template["policy_version"] != original_report["policy_version"]
        or template["scope"] != "simulation_only"
        or template["must_not_execute"] is not True
        or evidence.must_not_use_for_decision != template["must_not_use_for_decision"]
    ):
        return None
    checks = tuple(item for item in template["checks"] if item["dimension"] == "exit_pressure")
    if len(checks) != 1:
        return None
    pressure_status = checks[0]["status"]
    expected_must_not_use = original_report["must_not_use_for_decision"] or pressure_status in {
        "unknown",
        "partial",
    }
    if template["must_not_use_for_decision"] != expected_must_not_use:
        return None
    details = checks[0]["details"]
    scenario_details = _mapping(details.get("scenario"))
    assessment = _mapping(result_snapshot.get("assessment"))
    scenario_impact = _mapping(result_snapshot.get("scenario_impact"))
    if (
        details.get("run_evidence_id") != evidence.run_id
        or details.get("run_evidence_result_hash") is not None
        or details.get("portfolio_snapshot_id") != evidence.portfolio_snapshot_id
        or details.get("portfolio_snapshot_hash") != evidence.portfolio_snapshot_hash
        or scenario_details is None
        or scenario_details.get("revision_id") != scenario_revision_id
        or scenario_details.get("content_sha256") != revision.get("content_hash")
        or assessment is None
        or details.get("pressure_result_hash") != assessment.get("result_hash")
        or scenario_impact is None
        or scenario_impact.get("scenario_revision_id") != scenario_revision_id
        or assessment.get("scenario_revision_id") != scenario_revision_id
        or assessment.get("scenario_revision_hash") != revision.get("content_hash")
        or assessment.get("scenario_result_hash") != scenario_impact.get("result_hash")
        or details.get("scenario_result_hash") != scenario_impact.get("result_hash")
        or not _scenario_impact_template_matches(
            report_details=details,
            retained_impact=scenario_impact,
            money_unit=stored_account.get("money_unit"),
        )
        or details.get("run_evidence_persisted") is not True
        or details.get("scope") != "simulation_only"
        or details.get("must_not_execute") is not True
        or details.get("execution_permitted") is not False
        or details.get("source_evidence_ids") != list(evidence.data_evidence_ids)
    ):
        return None
    base_without_pressure = tuple(
        item for item in template["checks"] if item["dimension"] != "exit_pressure"
    )
    if (
        base_without_pressure != tuple(original_report["checks"])
        or template["resource_snapshot_hash"] != original_report["resource_snapshot_hash"]
        or template["sources"] != original_report["sources"]
        or template["freshness"] != original_report["freshness"]
        or template["reliability"] != original_report["reliability"]
        or template["scope"] != original_report["scope"]
        or template["must_not_execute"] != original_report["must_not_execute"]
    ):
        return None
    return template


def _scenario_impact_template_matches(
    *,
    report_details: Mapping[str, object],
    retained_impact: Mapping[str, object],
    money_unit: object,
) -> bool:
    """Accept a truly absent legacy summary, but verify every present one exactly."""

    if "scenario_impact" not in report_details:
        return True
    public_details = _mapping(report_details.get("scenario_impact"))
    if public_details is None:
        return False

    value_known = type(money_unit) is str and bool(money_unit)
    amount_fields = ("initial_value", "final_value", "total_return")
    expected_values = {
        field: retained_impact.get(field) if value_known else None for field in amount_fields
    }
    expected_hash = retained_impact.get("result_hash")
    if (
        type(expected_hash) is not str
        or len(expected_hash) != 64
        or any(character not in "0123456789abcdef" for character in expected_hash)
        or (value_known and any(type(expected_values[field]) is not str for field in amount_fields))
    ):
        return False
    return (
        set(public_details)
        == {
            "scope",
            "scope_label",
            "initial_value",
            "final_value",
            "value_unit",
            "total_return",
            "total_return_unit",
            "scenario_result_hash",
            "hypothetical",
            "market_observation",
        }
        and public_details.get("scope") == "portfolio_snapshot_net_asset_value"
        and public_details.get("scope_label") == "全组合净值（含现金）"
        and public_details.get("initial_value") == expected_values["initial_value"]
        and public_details.get("final_value") == expected_values["final_value"]
        and public_details.get("value_unit") == (money_unit if value_known else None)
        and public_details.get("total_return") == expected_values["total_return"]
        and public_details.get("total_return_unit") == ("fraction" if value_known else None)
        and public_details.get("scenario_result_hash") == expected_hash
        and public_details.get("hypothetical") is True
        and public_details.get("market_observation") is False
    )


def _json_mapping(value: str) -> Mapping[str, object] | None:
    """Decode one canonical snapshot object without accepting untyped JSON roots."""

    try:
        decoded: object = json.loads(value)
    except json.JSONDecodeError:
        return None
    return _mapping(decoded)


def _mapping(value: object) -> Mapping[str, object] | None:
    """Narrow a JSON object to string-keyed entries."""

    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        return None
    return cast(Mapping[str, object], value)


def _as_of_from_snapshot(request: Mapping[str, object]) -> str | None:
    """Read the canonical request cutoff token preserved by the Scenario DTO."""

    value = request.get("as_of_time")
    return value if type(value) is str else None


def _as_of_matches_evidence(
    evidence: ScenarioRunEvidence,
    request: Mapping[str, object],
) -> bool:
    """Compare the stored cutoff as an instant while preserving its source offset."""

    cutoff_text = _as_of_from_snapshot(request)
    if cutoff_text is None:
        return False
    try:
        cutoff = datetime.fromisoformat(cutoff_text)
    except ValueError:
        return False
    if (
        cutoff.tzinfo is None
        or cutoff.utcoffset() is None
        or evidence.as_of_time.tzinfo is None
        or evidence.as_of_time.utcoffset() is None
    ):
        return False
    return cutoff.astimezone(UTC) == evidence.as_of_time.astimezone(UTC)


def _approved_revision(
    *,
    scenario_identifier: str,
    as_of: datetime,
) -> tuple[ScenarioRevision, str]:
    """Resolve one selected revision from the existing active approved catalogue."""

    try:
        summaries = list_scenarios()
    except ScenarioConfigurationError as error:
        raise PortfolioRiskUnavailable(
            code="PORTFOLIO_PRESSURE_SCENARIO_CATALOG_UNAVAILABLE"
        ) from error
    matches = tuple(
        item
        for item in summaries
        if item.revision.revision_id == scenario_identifier
        and item.definition.status is ScenarioDefinitionStatus.ACTIVE
        and item.revision.status in {ScenarioRevisionStatus.APPROVED, ScenarioRevisionStatus.ACTIVE}
        and item.definition.created_at <= as_of
        and item.revision.created_at <= as_of
        and (item.revision.effective_at is None or item.revision.effective_at <= as_of)
    )
    if len(matches) != 1:
        raise InvalidInputError(code="PORTFOLIO_PRESSURE_SCENARIO_NOT_AVAILABLE")
    return matches[0].revision, matches[0].definition.name


def _failure_report(
    *,
    prepared: PreparedPortfolioRisk,
    revision: ScenarioRevision,
    scenario_label: str,
    reason_codes: tuple[str, ...],
) -> PortfolioRiskReportPayload:
    """Return an explicit unknown result without pretending evidence was persisted."""

    reasons = list(_ordered_unique(reason_codes or ("PORTFOLIO_PRESSURE_RESULT_UNKNOWN",)))
    check = _pressure_check(
        status="unknown",
        reason_codes=tuple(reasons),
        summary="退出压力输入尚未形成可复核结果",
        details={
            "scenario": {
                "label": scenario_label,
                "revision_id": revision.revision_id,
                "version": revision.version,
                "content_sha256": revision.content_hash,
            },
            "run_evidence_persisted": False,
            "scope": "simulation_only",
            "must_not_execute": True,
            "execution_permitted": False,
        },
    )
    return _with_pressure_check(
        prepared=prepared,
        check=check,
        must_not_use_for_decision=True,
    )


def _pressure_check(
    *,
    status: PortfolioRiskOutcome,
    reason_codes: tuple[str, ...],
    summary: str,
    details: dict[str, object],
) -> PortfolioRiskCheckPayload:
    """Return the bounded JSON-facing exit-pressure check."""

    return {
        "dimension": "exit_pressure",
        "status": status,
        "reason_codes": list(_ordered_unique(reason_codes)),
        "summary": summary,
        "details": details,
    }


def _with_pressure_check(
    *,
    prepared: PreparedPortfolioRisk,
    check: PortfolioRiskCheckPayload,
    must_not_use_for_decision: bool,
) -> PortfolioRiskReportPayload:
    """Keep the prepared report identity and append one non-executable result."""

    checks = [*prepared.report["checks"], check]
    outcome = _combine_outcomes(
        prepared.report["outcome"],
        check["status"],
    )
    return {
        **prepared.report,
        "checks": checks,
        "outcome": outcome,
        "must_not_use_for_decision": must_not_use_for_decision,
        "scope": "simulation_only",
        "must_not_execute": True,
    }


def _combine_outcomes(
    first: PortfolioRiskOutcome,
    second: PortfolioRiskOutcome,
) -> PortfolioRiskOutcome:
    """Preserve the strongest fail-closed status across the risk and pressure checks."""

    for status in ("blocked", "unknown", "partial"):
        if first == status or second == status:
            return status
    return "allowed"


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    """Preserve stable source/reason ordering while removing duplicates."""

    return tuple(dict.fromkeys(values))


def _reason_code(error: ScenarioRunBlockedError) -> str:
    """Retain a stable Scenario blocker or use a bounded generic code."""

    value = str(error)
    if value and all(character.isalnum() or character in "_:-" for character in value):
        return value
    return "PORTFOLIO_PRESSURE_SCENARIO_RUN_BLOCKED"


def _require_aware(value: datetime, *, code: str) -> None:
    """Reject a missing, naive, or dynamically mistyped server timestamp."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise PortfolioRiskUnavailable(code=code)


__all__ = ["PortfolioRiskPressureRunnerService"]
