"""Django repositories for Data Center egress rules and audit evidence."""

from __future__ import annotations

import logging
from uuid import UUID

from django.db import DatabaseError, transaction

from apps.data_center.domain.egress_routing import (
    EgressRouteRule,
    EgressRoutingError,
    EgressStrategy,
    validate_rule_set,
)

from .egress_models import EgressRequestAuditModel, EgressRoutingRuleModel
from .models import ProviderConfigModel

logger = logging.getLogger(__name__)


class EgressRoutingRuleRepository:
    """Persist and project routing rules without importing them into domain code."""

    def list(self, *, include_disabled: bool = True) -> tuple[EgressRouteRule, ...]:
        """Return rules ordered by priority and persistent identifier."""

        queryset = EgressRoutingRuleModel._default_manager.all()
        if not include_disabled:
            queryset = queryset.filter(enabled=True)
        return tuple(self._to_domain(model) for model in queryset)

    def get(self, rule_id: int) -> EgressRouteRule | None:
        """Read one persisted rule."""

        model = EgressRoutingRuleModel._default_manager.filter(pk=rule_id).first()
        return self._to_domain(model) if model is not None else None

    @transaction.atomic
    def create(self, rule: EgressRouteRule) -> EgressRouteRule:
        """Serialize conflict checks and insertion on the existing provider row."""

        self._lock_providers((rule.provider_id,))
        validate_rule_set(self.list() + (rule,))

        model = EgressRoutingRuleModel._default_manager.create(
            provider_id=rule.provider_id,
            dataset_key=rule.dataset_key,
            domain_pattern=rule.domain_pattern,
            deployment_region=rule.deployment_region,
            strategy=rule.strategy.value,
            fixed_egress_id=rule.fixed_egress_id,
            priority=rule.priority,
            enabled=rule.enabled,
        )
        return self._to_domain(model)

    @transaction.atomic
    def update(self, rule_id: int, rule: EgressRouteRule) -> EgressRouteRule | None:
        """Replace one route rule while retaining its identifier."""

        model = (
            EgressRoutingRuleModel._default_manager.select_for_update().filter(pk=rule_id).first()
        )
        if model is None:
            return None
        self._lock_providers((model.provider_id, rule.provider_id))
        validate_rule_set(tuple(item for item in self.list() if item.rule_id != rule_id) + (rule,))
        model.provider_id = rule.provider_id
        model.dataset_key = rule.dataset_key
        model.domain_pattern = rule.domain_pattern
        model.deployment_region = rule.deployment_region
        model.strategy = rule.strategy.value
        model.fixed_egress_id = rule.fixed_egress_id
        model.priority = rule.priority
        model.enabled = rule.enabled
        model.save(
            update_fields=[
                "provider_id",
                "dataset_key",
                "domain_pattern",
                "deployment_region",
                "strategy",
                "fixed_egress_id",
                "priority",
                "enabled",
                "updated_at",
            ]
        )
        return self._to_domain(model)

    @staticmethod
    def _lock_providers(provider_ids: tuple[int, ...]) -> None:
        """Use stable provider locks, including when no routing rule exists yet."""
        expected = set(provider_ids)
        existing = set(
            ProviderConfigModel._default_manager.select_for_update()
            .filter(pk__in=expected)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        if existing != expected:
            raise EgressRoutingError("provider does not exist", code="EGRESS_PROVIDER_NOT_FOUND")

    @staticmethod
    def _to_domain(model: EgressRoutingRuleModel) -> EgressRouteRule:
        """Convert a model row into the pure rule value object."""

        return EgressRouteRule(
            rule_id=int(model.pk),
            provider_id=int(model.provider_id),
            dataset_key=model.dataset_key,
            domain_pattern=model.domain_pattern,
            deployment_region=model.deployment_region,
            strategy=EgressStrategy(model.strategy),
            fixed_egress_id=(
                int(model.fixed_egress_id) if model.fixed_egress_id is not None else None
            ),
            priority=int(model.priority),
            enabled=bool(model.enabled),
        )


class EgressAuditRepository:
    """Write bounded request-attempt evidence without persisting URLs or secrets."""

    def record(
        self,
        *,
        request_id: UUID,
        provider_id: int | None,
        dataset_key: str,
        target_host: str,
        deployment_region: str,
        rule_id: int | None,
        egress_id: int | None,
        attempt: int,
        outcome: str,
        error_code: str = "",
        latency_ms: float | None = None,
    ) -> None:
        """Persist one redacted attempt record, failing closed on invalid values."""

        if isinstance(attempt, bool) or attempt < 1:
            raise ValueError("invalid_egress_attempt")
        try:
            with transaction.atomic():
                EgressRequestAuditModel._default_manager.create(
                    request_id=request_id,
                    provider_id=provider_id,
                    dataset_key=str(dataset_key)[:120],
                    target_host=str(target_host)[:253],
                    deployment_region=str(deployment_region)[:40],
                    rule_id=rule_id,
                    egress_id=egress_id,
                    attempt=attempt,
                    outcome=str(outcome)[:24],
                    error_code=str(error_code)[:80],
                    latency_ms=latency_ms,
                )
        except DatabaseError as exc:
            logger.error(
                "EGRESS_AUDIT_WRITE_FAILED request_id=%s error=%s", request_id, type(exc).__name__
            )


__all__ = ["EgressAuditRepository", "EgressRoutingRuleRepository"]
