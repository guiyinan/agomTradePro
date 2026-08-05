from uuid import UUID

from django.apps import AppConfig
from django.core.exceptions import ValidationError


def _is_scenario_forecast_reference_valid(
    scenario_revision_id: str,
    scenario_set_revision_id: str | None,
) -> bool:
    """Confirm an approved/active revision and optional exact set membership."""

    from apps.risk_center.infrastructure.models import (
        ScenarioSetMemberModel,
        StressScenarioRevisionModel,
    )

    eligible_statuses = ("approved", "active")
    try:
        revision_uuid = UUID(scenario_revision_id)
        set_revision_uuid = (
            UUID(scenario_set_revision_id) if scenario_set_revision_id is not None else None
        )
        if scenario_set_revision_id is None:
            return StressScenarioRevisionModel._default_manager.filter(
                revision_id=revision_uuid,
                status__in=eligible_statuses,
            ).exists()
        assert set_revision_uuid is not None
        return ScenarioSetMemberModel._default_manager.filter(
            scenario_revision_id=revision_uuid,
            scenario_revision__status__in=eligible_statuses,
            scenario_set_revision_id=set_revision_uuid,
            scenario_set_revision__status__in=eligible_statuses,
        ).exists()
    except (ValidationError, ValueError):
        return False


class RiskCenterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.risk_center"
    verbose_name = "风控中心"

    def ready(self) -> None:
        from apps.risk_center.application.repository_provider import (
            configure_risk_center_repositories,
        )
        from apps.risk_center.application.scenario_governance import (
            configure_scenario_governance_repository,
        )
        from apps.risk_center.application.scenario_repository_provider import (
            configure_scenario_repositories,
        )
        from apps.risk_center.infrastructure.repositories import (
            DjangoRiskAccountRepository,
            DjangoRiskAuditRepository,
            DjangoRiskDailyReportRepository,
            DjangoRiskExceptionRepository,
            DjangoRiskFloorRepository,
            DjangoRiskPolicyRepository,
            DjangoRiskTemplateRepository,
        )
        from apps.risk_center.infrastructure.scenario_governance_repository import (
            DjangoScenarioGovernanceRepository,
        )
        from apps.risk_center.infrastructure.scenario_repositories import (
            DjangoScenarioRepository,
        )
        from core.integration.research_integrity_registry import (
            configure_scenario_forecast_reference_checker,
        )

        configure_risk_center_repositories(
            floor_repository=DjangoRiskFloorRepository(),
            template_repository=DjangoRiskTemplateRepository(),
            policy_repository=DjangoRiskPolicyRepository(),
            exception_repository=DjangoRiskExceptionRepository(),
            audit_repository=DjangoRiskAuditRepository(),
            daily_report_repository=DjangoRiskDailyReportRepository(),
            account_repository=DjangoRiskAccountRepository(),
        )
        scenario_repository = DjangoScenarioRepository()
        configure_scenario_repositories(
            query_repository=scenario_repository,
            revision_repository=scenario_repository,
            activation_repository=scenario_repository,
            evidence_repository=scenario_repository,
        )
        configure_scenario_governance_repository(DjangoScenarioGovernanceRepository())
        configure_scenario_forecast_reference_checker(_is_scenario_forecast_reference_valid)
