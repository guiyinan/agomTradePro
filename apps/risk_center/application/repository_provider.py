"""Repository protocols and composition root for risk center."""

from __future__ import annotations

from typing import Any, Protocol

from apps.risk_center.domain.entities import (
    AccountRiskPolicy,
    RiskException,
    RiskTemplate,
)


class RiskFloorRepository(Protocol):
    def get_active_floor(self) -> Any: ...
    def save_floor(self, payload: dict[str, Any], *, actor: Any | None = None) -> Any: ...


class RiskTemplateRepository(Protocol):
    def list_templates(self) -> list[Any]: ...
    def get_template(self, template_id: int) -> Any | None: ...
    def get_template_domain_by_key(self, key: str) -> RiskTemplate | None: ...
    def get_template_domain_by_profile(self, profile: str) -> RiskTemplate | None: ...
    def save_template(self, payload: dict[str, Any], *, actor: Any | None = None) -> Any: ...
    def update_template(
        self, template_id: int, payload: dict[str, Any], *, actor: Any | None = None
    ) -> Any | None: ...


class RiskPolicyRepository(Protocol):
    def list_policies(self, *, account_ids: list[int] | None = None) -> list[Any]: ...
    def get_policy(self, policy_id: int) -> Any | None: ...
    def get_policy_by_account(self, account_id: int) -> Any | None: ...
    def get_policy_domain_by_account(self, account_id: int) -> AccountRiskPolicy | None: ...
    def upsert_policy(self, payload: dict[str, Any], *, actor: Any | None = None) -> Any: ...
    def apply_template(
        self, policy_id: int, template_id: int, *, actor: Any | None = None
    ) -> Any | None: ...


class RiskExceptionRepository(Protocol):
    def list_exceptions(self, *, account_id: int | None = None) -> list[Any]: ...
    def list_active_domains(self, *, account_id: int) -> list[RiskException]: ...
    def create_exception(self, payload: dict[str, Any], *, actor: Any) -> Any: ...


class RiskAuditRepository(Protocol):
    def list_recent(self, *, limit: int = 50) -> list[Any]: ...


class RiskAccountRepository(Protocol):
    def can_access_account(self, *, user: Any, account_id: int) -> bool: ...
    def list_accessible_account_ids(self, *, user: Any) -> list[int] | None: ...
    def get_account_risk_profile(self, account_id: int) -> str | None: ...


_floor_repository: RiskFloorRepository | None = None
_template_repository: RiskTemplateRepository | None = None
_policy_repository: RiskPolicyRepository | None = None
_exception_repository: RiskExceptionRepository | None = None
_audit_repository: RiskAuditRepository | None = None
_account_repository: RiskAccountRepository | None = None


def configure_risk_center_repositories(
    *,
    floor_repository: RiskFloorRepository,
    template_repository: RiskTemplateRepository,
    policy_repository: RiskPolicyRepository,
    exception_repository: RiskExceptionRepository,
    audit_repository: RiskAuditRepository,
    account_repository: RiskAccountRepository,
) -> None:
    global _floor_repository
    global _template_repository
    global _policy_repository
    global _exception_repository
    global _audit_repository
    global _account_repository
    _floor_repository = floor_repository
    _template_repository = template_repository
    _policy_repository = policy_repository
    _exception_repository = exception_repository
    _audit_repository = audit_repository
    _account_repository = account_repository


def get_risk_floor_repository() -> RiskFloorRepository:
    if _floor_repository is None:
        raise RuntimeError("Risk floor repository is not configured")
    return _floor_repository


def get_risk_template_repository() -> RiskTemplateRepository:
    if _template_repository is None:
        raise RuntimeError("Risk template repository is not configured")
    return _template_repository


def get_risk_policy_repository() -> RiskPolicyRepository:
    if _policy_repository is None:
        raise RuntimeError("Risk policy repository is not configured")
    return _policy_repository


def get_risk_exception_repository() -> RiskExceptionRepository:
    if _exception_repository is None:
        raise RuntimeError("Risk exception repository is not configured")
    return _exception_repository


def get_risk_audit_repository() -> RiskAuditRepository:
    if _audit_repository is None:
        raise RuntimeError("Risk audit repository is not configured")
    return _audit_repository


def get_risk_account_repository() -> RiskAccountRepository:
    if _account_repository is None:
        raise RuntimeError("Risk account repository is not configured")
    return _account_repository
