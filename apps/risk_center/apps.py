from django.apps import AppConfig


class RiskCenterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.risk_center"
    verbose_name = "风控中心"

    def ready(self) -> None:
        from apps.risk_center.application.repository_provider import (
            configure_risk_center_repositories,
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

        configure_risk_center_repositories(
            floor_repository=DjangoRiskFloorRepository(),
            template_repository=DjangoRiskTemplateRepository(),
            policy_repository=DjangoRiskPolicyRepository(),
            exception_repository=DjangoRiskExceptionRepository(),
            audit_repository=DjangoRiskAuditRepository(),
            daily_report_repository=DjangoRiskDailyReportRepository(),
            account_repository=DjangoRiskAccountRepository(),
        )
