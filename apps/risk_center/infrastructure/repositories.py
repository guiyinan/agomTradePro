"""Django repository implementations for risk center."""

from __future__ import annotations

from typing import Any

from django.apps import apps as django_apps
from django.db import transaction
from django.utils import timezone

from apps.risk_center.domain.entities import (
    AccountRiskPolicy,
    RiskException,
    RiskParameters,
    RiskProfile,
    RiskTemplate,
)
from apps.risk_center.domain.services import fallback_template_for_profile
from apps.risk_center.infrastructure.models import (
    AccountRiskPolicyModel,
    GlobalRiskFloorModel,
    RiskDailyReportModel,
    RiskExceptionModel,
    RiskPolicyAuditModel,
    RiskTemplateModel,
)

PARAMETER_MODEL_FIELDS = {
    "max_total_position_pct",
    "max_single_position_pct",
    "max_daily_loss_pct",
    "max_drawdown_pct",
    "max_stop_loss_pct",
    "take_profit_pct",
    "min_cash_pct",
    "force_stop_loss",
    "hard_exclusions",
}


DEFAULT_FLOOR = {
    "name": "Global Risk Floor",
    "max_total_position_pct": 0.95,
    "max_single_position_pct": 0.3,
    "max_daily_loss_pct": 0.06,
    "max_drawdown_pct": 0.25,
    "max_stop_loss_pct": 0.2,
    "min_cash_pct": 0.03,
    "force_stop_loss": True,
    "hard_exclusions": [],
    "is_active": True,
}


class SnapshotMixin:
    @staticmethod
    def _snapshot(model: Any | None) -> dict[str, Any]:
        if model is None:
            return {}
        payload: dict[str, Any] = {
            "id": getattr(model, "id", None),
            "created_at": getattr(model, "created_at", None),
            "updated_at": getattr(model, "updated_at", None),
        }
        for field_name in model._meta.fields:
            value = getattr(model, field_name.name)
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            elif hasattr(value, "pk"):
                value = value.pk
            payload[field_name.name] = value
        return payload

    @staticmethod
    def _audit(
        *,
        target_type: str,
        target_id: str | int,
        action: str,
        actor: Any | None,
        before: dict[str, Any],
        after: dict[str, Any],
        reason: str = "",
    ) -> None:
        RiskPolicyAuditModel._default_manager.create(
            target_type=target_type,
            target_id=str(target_id),
            action=action,
            actor=actor if getattr(actor, "is_authenticated", False) else None,
            before=before,
            after=after,
            reason=reason,
        )


def _apply_payload(model: Any, payload: dict[str, Any]) -> None:
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)


def _params_from_model(model: Any) -> RiskParameters:
    return RiskParameters.from_mapping(model.to_parameter_dict())


def _template_to_domain(model: RiskTemplateModel) -> RiskTemplate:
    return RiskTemplate(
        key=model.key,
        name=model.name,
        risk_profile=RiskProfile(model.risk_profile),
        parameters=_params_from_model(model),
        is_active=model.is_active,
    )


def _policy_to_domain(model: AccountRiskPolicyModel) -> AccountRiskPolicy:
    return AccountRiskPolicy(
        account_id=model.account_id,
        template_key=model.template.key if model.template else None,
        risk_profile=RiskProfile(model.risk_profile) if model.risk_profile else None,
        overrides=_params_from_model(model),
        is_active=model.is_active,
    )


class DjangoRiskFloorRepository(SnapshotMixin):
    def get_active_floor(self) -> GlobalRiskFloorModel:
        floor = (
            GlobalRiskFloorModel._default_manager.filter(is_active=True)
            .order_by("-updated_at", "-id")
            .first()
        )
        if floor:
            return floor
        return GlobalRiskFloorModel._default_manager.create(**DEFAULT_FLOOR)

    def save_floor(
        self, payload: dict[str, Any], *, actor: Any | None = None
    ) -> GlobalRiskFloorModel:
        with transaction.atomic():
            floor = self.get_active_floor()
            before = self._snapshot(floor)
            _apply_payload(floor, payload)
            floor.save()
            self._audit(
                target_type=RiskPolicyAuditModel.TARGET_FLOOR,
                target_id=floor.id,
                action="update",
                actor=actor,
                before=before,
                after=self._snapshot(floor),
                reason=str(payload.get("reason", "")),
            )
            return floor


class DjangoRiskTemplateRepository(SnapshotMixin):
    def _ensure_defaults(self) -> None:
        for profile in (
            RiskProfile.CONSERVATIVE,
            RiskProfile.MODERATE,
            RiskProfile.AGGRESSIVE,
        ):
            template = fallback_template_for_profile(profile)
            values = template.parameters.to_dict()
            RiskTemplateModel._default_manager.get_or_create(
                key=template.key,
                defaults={
                    "name": template.name,
                    "risk_profile": template.risk_profile.value,
                    "description": f"Default {template.risk_profile.value} risk template",
                    **values,
                },
            )

    def list_templates(self) -> list[RiskTemplateModel]:
        self._ensure_defaults()
        return list(RiskTemplateModel._default_manager.all())

    def get_template(self, template_id: int) -> RiskTemplateModel | None:
        self._ensure_defaults()
        return RiskTemplateModel._default_manager.filter(id=template_id).first()

    def get_template_domain_by_key(self, key: str) -> RiskTemplate | None:
        self._ensure_defaults()
        model = RiskTemplateModel._default_manager.filter(key=key, is_active=True).first()
        return _template_to_domain(model) if model else None

    def get_template_domain_by_profile(self, profile: str) -> RiskTemplate | None:
        self._ensure_defaults()
        model = (
            RiskTemplateModel._default_manager.filter(risk_profile=profile, is_active=True)
            .order_by("key")
            .first()
        )
        return _template_to_domain(model) if model else None

    def save_template(
        self, payload: dict[str, Any], *, actor: Any | None = None
    ) -> RiskTemplateModel:
        with transaction.atomic():
            template = RiskTemplateModel(**payload)
            template.save()
            self._audit(
                target_type=RiskPolicyAuditModel.TARGET_TEMPLATE,
                target_id=template.id,
                action="create",
                actor=actor,
                before={},
                after=self._snapshot(template),
                reason=str(payload.get("reason", "")),
            )
            return template

    def update_template(
        self, template_id: int, payload: dict[str, Any], *, actor: Any | None = None
    ) -> RiskTemplateModel | None:
        with transaction.atomic():
            template = self.get_template(template_id)
            if template is None:
                return None
            before = self._snapshot(template)
            _apply_payload(template, payload)
            template.save()
            self._audit(
                target_type=RiskPolicyAuditModel.TARGET_TEMPLATE,
                target_id=template.id,
                action="update",
                actor=actor,
                before=before,
                after=self._snapshot(template),
                reason=str(payload.get("reason", "")),
            )
            return template


class DjangoRiskPolicyRepository(SnapshotMixin):
    def list_policies(
        self, *, account_ids: list[int] | None = None
    ) -> list[AccountRiskPolicyModel]:
        qs = AccountRiskPolicyModel._default_manager.select_related("template").all()
        if account_ids is not None:
            qs = qs.filter(account_id__in=account_ids)
        return list(qs)

    def get_policy(self, policy_id: int) -> AccountRiskPolicyModel | None:
        return (
            AccountRiskPolicyModel._default_manager.select_related("template")
            .filter(id=policy_id)
            .first()
        )

    def get_policy_by_account(self, account_id: int) -> AccountRiskPolicyModel | None:
        return (
            AccountRiskPolicyModel._default_manager.select_related("template")
            .filter(account_id=account_id)
            .first()
        )

    def get_policy_domain_by_account(self, account_id: int) -> AccountRiskPolicy | None:
        model = self.get_policy_by_account(account_id)
        return _policy_to_domain(model) if model else None

    def upsert_policy(
        self, payload: dict[str, Any], *, actor: Any | None = None
    ) -> AccountRiskPolicyModel:
        account_id = int(payload["account_id"])
        template_id = payload.pop("template_id", None)
        with transaction.atomic():
            policy = self.get_policy_by_account(account_id)
            created = policy is None
            if policy is None:
                policy = AccountRiskPolicyModel(account_id=account_id)
            before = self._snapshot(policy) if not created else {}
            if template_id:
                policy.template = RiskTemplateModel._default_manager.filter(id=template_id).first()
            _apply_payload(policy, payload)
            policy.save()
            self._audit(
                target_type=RiskPolicyAuditModel.TARGET_POLICY,
                target_id=policy.id,
                action="create" if created else "update",
                actor=actor,
                before=before,
                after=self._snapshot(policy),
                reason=str(payload.get("reason", "")),
            )
            return policy

    def apply_template(
        self, policy_id: int, template_id: int, *, actor: Any | None = None
    ) -> AccountRiskPolicyModel | None:
        with transaction.atomic():
            policy = self.get_policy(policy_id)
            template = RiskTemplateModel._default_manager.filter(id=template_id).first()
            if policy is None or template is None:
                return None
            before = self._snapshot(policy)
            policy.template = template
            policy.risk_profile = template.risk_profile
            policy.save()
            self._audit(
                target_type=RiskPolicyAuditModel.TARGET_POLICY,
                target_id=policy.id,
                action="apply_template",
                actor=actor,
                before=before,
                after=self._snapshot(policy),
            )
            return policy


class DjangoRiskExceptionRepository(SnapshotMixin):
    def list_exceptions(self, *, account_id: int | None = None) -> list[RiskExceptionModel]:
        qs = RiskExceptionModel._default_manager.select_related("created_by").all()
        if account_id is not None:
            qs = qs.filter(account_id=account_id)
        return list(qs)

    def list_active_domains(self, *, account_id: int) -> list[RiskException]:
        now = timezone.now()
        qs = RiskExceptionModel._default_manager.select_related("created_by").filter(
            is_active=True,
            expires_at__gt=now,
        )
        qs = qs.filter(account_id__in=[account_id, None])
        return [
            RiskException(
                account_id=item.account_id,
                field_name=item.field_name,
                allowed_value=item.allowed_value,
                reason=item.reason,
                created_by=getattr(item.created_by, "username", ""),
                expires_at=item.expires_at,
                is_active=item.is_active,
            )
            for item in qs
        ]

    def create_exception(self, payload: dict[str, Any], *, actor: Any) -> RiskExceptionModel:
        with transaction.atomic():
            exception = RiskExceptionModel._default_manager.create(
                account_id=payload.get("account_id"),
                field_name=payload["field_name"],
                allowed_value=payload["allowed_value"],
                reason=payload["reason"],
                expires_at=payload["expires_at"],
                is_active=payload.get("is_active", True),
                created_by=actor,
            )
            self._audit(
                target_type=RiskPolicyAuditModel.TARGET_EXCEPTION,
                target_id=exception.id,
                action="create",
                actor=actor,
                before={},
                after=self._snapshot(exception),
                reason=exception.reason,
            )
            return exception


class DjangoRiskAuditRepository:
    def list_recent(self, *, limit: int = 50) -> list[RiskPolicyAuditModel]:
        return list(
            RiskPolicyAuditModel._default_manager.select_related("actor").order_by("-created_at")[
                :limit
            ]
        )


class DjangoRiskDailyReportRepository:
    def upsert_report(
        self, payload: dict[str, Any], *, actor: Any | None = None
    ) -> RiskDailyReportModel:
        values = dict(payload)
        account_id = int(values.pop("account_id"))
        report_date = values.pop("report_date")
        values["generated_by"] = actor if getattr(actor, "is_authenticated", False) else None
        report, _ = RiskDailyReportModel._default_manager.update_or_create(
            account_id=account_id,
            report_date=report_date,
            defaults=values,
        )
        return report

    def get_report(self, *, account_id: int, report_date: Any) -> RiskDailyReportModel | None:
        return (
            RiskDailyReportModel._default_manager.select_related("generated_by")
            .filter(account_id=account_id, report_date=report_date)
            .first()
        )

    def list_reports(
        self,
        *,
        account_id: int | None = None,
        account_ids: list[int] | None = None,
        start_date: Any | None = None,
        end_date: Any | None = None,
        limit: int = 90,
    ) -> list[RiskDailyReportModel]:
        qs = RiskDailyReportModel._default_manager.select_related("generated_by").all()
        if account_id is not None:
            qs = qs.filter(account_id=account_id)
        elif account_ids is not None:
            qs = qs.filter(account_id__in=account_ids)
        if start_date is not None:
            qs = qs.filter(report_date__gte=start_date)
        if end_date is not None:
            qs = qs.filter(report_date__lte=end_date)
        return list(qs.order_by("-report_date", "-updated_at")[: max(int(limit), 0)])


class DjangoRiskAccountRepository:
    def _account_model(self):
        return django_apps.get_model("simulated_trading", "SimulatedAccountModel")

    def can_access_account(self, *, user: Any, account_id: int) -> bool:
        if not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return self._account_model()._default_manager.filter(id=account_id).exists()
        return (
            self._account_model()._default_manager.filter(id=account_id, user_id=user.id).exists()
        )

    def list_accessible_account_ids(self, *, user: Any) -> list[int] | None:
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return None
        if not getattr(user, "is_authenticated", False):
            return []
        return list(
            self._account_model()
            ._default_manager.filter(user_id=user.id)
            .values_list("id", flat=True)
        )

    def get_account_risk_profile(self, account_id: int) -> str | None:
        account = self._account_model()._default_manager.filter(id=account_id).first()
        value = getattr(account, "risk_profile", None) or getattr(account, "risk_tolerance", None)
        if value in {RiskProfile.CONSERVATIVE.value, "low", "LOW"}:
            return RiskProfile.CONSERVATIVE.value
        if value in {RiskProfile.AGGRESSIVE.value, "high", "HIGH"}:
            return RiskProfile.AGGRESSIVE.value
        if value in {RiskProfile.MODERATE.value, "medium", "MEDIUM", "balanced", "BALANCED"}:
            return RiskProfile.MODERATE.value
        return None
