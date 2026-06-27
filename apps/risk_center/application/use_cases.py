"""Risk center application use cases."""

from __future__ import annotations

from typing import Any

from apps.risk_center.application.repository_provider import (
    get_risk_account_repository,
    get_risk_audit_repository,
    get_risk_exception_repository,
    get_risk_floor_repository,
    get_risk_policy_repository,
    get_risk_template_repository,
)
from apps.risk_center.domain.entities import GlobalRiskFloor, RiskParameters, RiskProfile
from apps.risk_center.domain.services import RiskPolicyResolver, fallback_template_for_profile


class RiskCenterAccessDeniedError(Exception):
    """Raised when a user cannot access a risk-center operation."""


class RiskCenterNotFoundError(Exception):
    """Raised when a requested risk-center object does not exist."""


class RiskCenterValidationError(Exception):
    """Raised when risk-center input is invalid."""


def _require_staff(actor: Any) -> None:
    if not getattr(actor, "is_staff", False):
        raise RiskCenterAccessDeniedError("Only staff users can modify global risk settings.")


def _require_account_access(actor: Any, account_id: int) -> None:
    if getattr(actor, "is_staff", False):
        return
    if not get_risk_account_repository().can_access_account(user=actor, account_id=account_id):
        raise RiskCenterAccessDeniedError("No permission to access this account risk policy.")


class GetRiskFloorUseCase:
    def execute(self, *, actor: Any) -> Any:
        if not getattr(actor, "is_authenticated", False):
            raise RiskCenterAccessDeniedError("Authentication required.")
        return get_risk_floor_repository().get_active_floor()


class UpdateRiskFloorUseCase:
    def execute(self, *, actor: Any, payload: dict[str, Any]) -> Any:
        _require_staff(actor)
        return get_risk_floor_repository().save_floor(payload, actor=actor)


class ListRiskTemplatesUseCase:
    def execute(self, *, actor: Any) -> list[Any]:
        if not getattr(actor, "is_authenticated", False):
            raise RiskCenterAccessDeniedError("Authentication required.")
        return get_risk_template_repository().list_templates()


class CreateRiskTemplateUseCase:
    def execute(self, *, actor: Any, payload: dict[str, Any]) -> Any:
        _require_staff(actor)
        return get_risk_template_repository().save_template(payload, actor=actor)


class UpdateRiskTemplateUseCase:
    def execute(self, *, actor: Any, template_id: int, payload: dict[str, Any]) -> Any:
        _require_staff(actor)
        result = get_risk_template_repository().update_template(template_id, payload, actor=actor)
        if result is None:
            raise RiskCenterNotFoundError("Risk template not found.")
        return result


class ListAccountRiskPoliciesUseCase:
    def execute(self, *, actor: Any) -> list[Any]:
        if not getattr(actor, "is_authenticated", False):
            raise RiskCenterAccessDeniedError("Authentication required.")
        account_ids = get_risk_account_repository().list_accessible_account_ids(user=actor)
        return get_risk_policy_repository().list_policies(account_ids=account_ids)


class UpsertAccountRiskPolicyUseCase:
    def execute(self, *, actor: Any, payload: dict[str, Any]) -> Any:
        account_id = int(payload["account_id"])
        _require_account_access(actor, account_id)
        return get_risk_policy_repository().upsert_policy(payload, actor=actor)


class GetAccountRiskPolicyUseCase:
    def execute(self, *, actor: Any, account_id: int) -> Any | None:
        _require_account_access(actor, account_id)
        return get_risk_policy_repository().get_policy_by_account(account_id)


class ApplyRiskTemplateToPolicyUseCase:
    def execute(self, *, actor: Any, policy_id: int, template_id: int) -> Any:
        policy = get_risk_policy_repository().get_policy(policy_id)
        if policy is None:
            raise RiskCenterNotFoundError("Account risk policy not found.")
        _require_account_access(actor, int(policy.account_id))
        result = get_risk_policy_repository().apply_template(
            policy_id,
            template_id,
            actor=actor,
        )
        if result is None:
            raise RiskCenterNotFoundError("Risk template not found.")
        return result


class ListRiskExceptionsUseCase:
    def execute(self, *, actor: Any, account_id: int | None = None) -> list[Any]:
        if not getattr(actor, "is_authenticated", False):
            raise RiskCenterAccessDeniedError("Authentication required.")
        if account_id is not None:
            _require_account_access(actor, account_id)
        elif not getattr(actor, "is_staff", False):
            account_ids = get_risk_account_repository().list_accessible_account_ids(user=actor)
            if not account_ids:
                return []
            return [
                item
                for checked_account_id in account_ids
                for item in get_risk_exception_repository().list_exceptions(
                    account_id=checked_account_id
                )
            ]
        return get_risk_exception_repository().list_exceptions(account_id=account_id)


class CreateRiskExceptionUseCase:
    def execute(self, *, actor: Any, payload: dict[str, Any]) -> Any:
        _require_staff(actor)
        if not payload.get("reason"):
            raise RiskCenterValidationError("Risk exception reason is required.")
        if not payload.get("expires_at"):
            raise RiskCenterValidationError("Risk exception expires_at is required.")
        return get_risk_exception_repository().create_exception(payload, actor=actor)


class GetEffectiveRiskPolicyUseCase:
    def execute(self, *, actor: Any, account_id: int) -> dict[str, Any]:
        _require_account_access(actor, account_id)
        return _resolve_effective_policy(account_id)


class ResolveEffectiveRiskPolicyForAccountUseCase:
    """Internal entrypoint for scheduled tasks and execution engines."""

    def execute(self, *, account_id: int) -> dict[str, Any]:
        return _resolve_effective_policy(account_id)


def _resolve_effective_policy(account_id: int) -> dict[str, Any]:
    floor_model = get_risk_floor_repository().get_active_floor()
    policy = get_risk_policy_repository().get_policy_domain_by_account(account_id)
    profile = (
        policy.risk_profile.value
        if policy and policy.risk_profile
        else get_risk_account_repository().get_account_risk_profile(account_id)
    )
    profile = profile or RiskProfile.MODERATE.value
    template = None
    if policy and policy.template_key:
        template = get_risk_template_repository().get_template_domain_by_key(policy.template_key)
    if template is None:
        template = get_risk_template_repository().get_template_domain_by_profile(profile)
    if template is None:
        template = fallback_template_for_profile(profile)

    floor = GlobalRiskFloor(
        parameters=RiskParameters.from_mapping(floor_model.to_parameter_dict()),
        is_active=bool(floor_model.is_active),
    )
    exceptions = get_risk_exception_repository().list_active_domains(account_id=account_id)
    resolved = RiskPolicyResolver().resolve(
        account_id=account_id,
        floor=floor,
        template=template,
        account_policy=policy,
        exceptions=exceptions,
    )
    return resolved.to_dict()


class GetRiskCenterConsoleContextUseCase:
    def execute(self, *, actor: Any) -> dict[str, Any]:
        _require_staff(actor)
        return {
            "floor": get_risk_floor_repository().get_active_floor(),
            "templates": get_risk_template_repository().list_templates(),
            "policies": get_risk_policy_repository().list_policies(account_ids=None),
            "exceptions": get_risk_exception_repository().list_exceptions(account_id=None),
            "audits": get_risk_audit_repository().list_recent(limit=30),
        }
