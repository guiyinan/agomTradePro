"""Explicit serializers for the owner-published M1 risk policy API."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from rest_framework import serializers

from apps.risk_center.application.m1_rebalance_risk_policy import M1RiskPolicyRevision
from apps.risk_center.domain.m1_rebalance_risk_policy import (
    M1RiskCondition,
    RiskApplicability,
)
from apps.simulated_trading.application.m1_rebalance_risk_policy import (
    OwnerM1RiskPolicyPublishRequest,
)

_EXPLICIT_TIMEZONE_SUFFIX = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")


class ExplicitAwareDateTimeField(serializers.DateTimeField):
    """Require an explicit UTC marker or numeric offset in owner input."""

    def to_internal_value(self, value: object) -> datetime:
        """Reject naive ISO input before DRF can attach the server timezone."""

        if type(value) is not str or _EXPLICIT_TIMEZONE_SUFFIX.search(value) is None:
            raise serializers.ValidationError("an explicit timezone offset is required")
        return super().to_internal_value(value)


class M1RiskConditionInputSerializer(serializers.Serializer[dict[str, Any]]):
    """Require an explicit applicability state and exact percentage semantics."""

    applicability = serializers.ChoiceField(choices=tuple(item.value for item in RiskApplicability))
    limit_pct = serializers.DecimalField(
        max_digits=6,
        decimal_places=3,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        required=False,
        allow_null=True,
    )
    not_applicable_reason = serializers.CharField(required=False, allow_blank=False, max_length=500)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Prevent a missing limit from being silently treated as disabled."""

        state = attrs.get("applicability")
        limit = attrs.get("limit_pct")
        reason = attrs.get("not_applicable_reason")
        if state == RiskApplicability.APPLICABLE.value:
            if type(limit) is not Decimal or reason is not None:
                raise serializers.ValidationError(
                    "applicable condition requires limit_pct and forbids not_applicable_reason"
                )
        elif state == RiskApplicability.NOT_APPLICABLE.value:
            if limit is not None or type(reason) is not str or not reason.strip():
                raise serializers.ValidationError(
                    "not_applicable requires an owner reason and no numeric limit"
                )
        elif state == RiskApplicability.UNKNOWN.value:
            if limit is not None or reason is not None:
                raise serializers.ValidationError(
                    "unknown condition cannot carry an inferred limit or N/A claim"
                )
        return attrs


class OwnerM1RiskPolicyPublishSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate an explicit policy window and the three applicability states."""

    strategy_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    effective_from = ExplicitAwareDateTimeField()
    effective_until = ExplicitAwareDateTimeField()
    reason = serializers.CharField(allow_blank=False, max_length=2000)
    max_single_position = M1RiskConditionInputSerializer()
    max_total_position = M1RiskConditionInputSerializer()
    max_stop_loss = M1RiskConditionInputSerializer()

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Require a positive aware interval without deriving it from request time."""

        effective_from = attrs.get("effective_from")
        effective_until = attrs.get("effective_until")
        if (
            type(effective_from) is not datetime
            or type(effective_until) is not datetime
            or effective_from.tzinfo is None
            or effective_until.tzinfo is None
            or effective_from.utcoffset() is None
            or effective_until.utcoffset() is None
            or effective_from >= effective_until
        ):
            raise serializers.ValidationError("effective window must be aware and increasing")
        reason = attrs.get("reason")
        if type(reason) is not str or not reason.strip():
            raise serializers.ValidationError("owner reason is required")
        return attrs

    def to_application_request(self) -> OwnerM1RiskPolicyPublishRequest:
        """Convert validated request data into typed Application conditions."""

        if not self.is_valid():
            raise AssertionError("serializer must be valid before conversion")
        data = self.validated_data
        return OwnerM1RiskPolicyPublishRequest(
            strategy_id=cast(int | None, data.get("strategy_id")),
            effective_from=cast(datetime, data["effective_from"]),
            effective_until=cast(datetime, data["effective_until"]),
            reason=cast(str, data["reason"]).strip(),
            max_single_position=_condition(data["max_single_position"]),
            max_total_position=_condition(data["max_total_position"]),
            max_stop_loss=_condition(data["max_stop_loss"]),
        )


class M1RiskPolicyRevisionResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize the new policy source separately from any legacy rule version."""

    risk_policy_version = serializers.UUIDField()
    account_id = serializers.IntegerField(min_value=1)
    effective_from = serializers.DateTimeField()
    effective_until = serializers.DateTimeField()
    known_at = serializers.DateTimeField()
    legacy_rule_version = serializers.CharField(allow_null=True)
    publication_status = serializers.ChoiceField(choices=("published",))
    source_binding = serializers.JSONField()
    risk_falsification = serializers.JSONField()


class OwnerM1RiskPolicyRevokeSerializer(serializers.Serializer[dict[str, Any]]):
    """Require a human-readable reason; the actor always comes from request auth."""

    reason = serializers.CharField(allow_blank=False, max_length=2000)

    def validate_reason(self, value: str) -> str:
        """Reject whitespace-only revocation reasons."""

        if not value.strip():
            raise serializers.ValidationError("revocation reason is required")
        return value.strip()


class M1RiskPolicyRevocationResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Return the audit-backed revocation event without mutating the revision."""

    risk_policy_version = serializers.UUIDField()
    account_id = serializers.IntegerField(min_value=1)
    revoked_at = serializers.DateTimeField()
    revoked_by_user_id = serializers.IntegerField(min_value=1)
    revocation_reason = serializers.CharField()
    revocation_status = serializers.ChoiceField(choices=("revoked",))


class M1RiskPolicyErrorResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Describe stable owner API failures and optional business blocker codes."""

    code = serializers.CharField()
    reason_codes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
    )


def revision_response(revision: M1RiskPolicyRevision) -> dict[str, object]:
    """Return version identity, actual validity, and owner-submitted predicates."""

    conditions = (
        (
            "max_single_position",
            revision.max_single_position,
            "target_single_position_pct <= limit_pct",
        ),
        (
            "max_total_position",
            revision.max_total_position,
            "projected_total_position_pct <= limit_pct",
        ),
        ("max_stop_loss", revision.max_stop_loss, "observed_loss_pct < stop_loss_limit_pct"),
    )
    return {
        "risk_policy_version": revision.risk_policy_version,
        "account_id": revision.account_id,
        "effective_from": revision.effective_from,
        "effective_until": revision.effective_until,
        "known_at": revision.known_at,
        "legacy_rule_version": None,
        "publication_status": "published",
        "source_binding": {
            "strategy_selection_state": revision.source_snapshot.strategy_selection_state,
            "strategy_id": revision.source_snapshot.strategy_id,
            "strategy_version": revision.source_snapshot.strategy_version,
            "position_rule_id": revision.source_snapshot.position_rule_id,
        },
        "risk_falsification": {
            "schema_version": "m1-risk-falsification.v1",
            "status": "not_evaluated",
            "conditions": [
                {
                    "dimension": name,
                    "applicability": condition.applicability.value,
                    "predicate": predicate,
                    "threshold_pct": (
                        str(condition.limit_pct) if condition.limit_pct is not None else None
                    ),
                    "owner_reason": condition.not_applicable_reason,
                }
                for name, condition, predicate in conditions
            ],
        },
    }


def revocation_response(revision: M1RiskPolicyRevision) -> dict[str, object]:
    """Serialize the immutable audit event returned by the repository."""

    if (
        revision.revocation_state != "revoked"
        or revision.revoked_at is None
        or revision.revoked_by_user_id is None
        or revision.revocation_reason is None
    ):
        raise ValueError("revocation audit source is incomplete")
    return {
        "risk_policy_version": revision.risk_policy_version,
        "account_id": revision.account_id,
        "revoked_at": revision.revoked_at,
        "revoked_by_user_id": revision.revoked_by_user_id,
        "revocation_reason": revision.revocation_reason,
        "revocation_status": "revoked",
    }


def _condition(value: object) -> M1RiskCondition:
    """Narrow validated nested serializer data into a Domain value object."""

    if not isinstance(value, dict):
        raise ValueError("risk condition payload must be an object")
    raw_state = value.get("applicability")
    try:
        state = RiskApplicability(cast(str, raw_state))
    except ValueError as exc:
        raise ValueError("risk condition applicability is invalid") from exc
    limit_value = value.get("limit_pct")
    if limit_value is not None and type(limit_value) is not Decimal:
        raise ValueError("risk condition limit must be Decimal or None")
    reason_value = value.get("not_applicable_reason")
    if reason_value is not None and type(reason_value) is not str:
        raise ValueError("risk condition reason must be str or None")
    return M1RiskCondition(
        applicability=state,
        limit_pct=limit_value,
        not_applicable_reason=reason_value,
    )


__all__: tuple[str, ...] = (
    "ExplicitAwareDateTimeField",
    "M1RiskConditionInputSerializer",
    "M1RiskPolicyRevisionResponseSerializer",
    "M1RiskPolicyRevocationResponseSerializer",
    "M1RiskPolicyErrorResponseSerializer",
    "OwnerM1RiskPolicyPublishSerializer",
    "OwnerM1RiskPolicyRevokeSerializer",
    "revision_response",
    "revocation_response",
)
