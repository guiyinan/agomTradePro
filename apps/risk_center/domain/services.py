"""Pure risk policy resolution rules."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from apps.risk_center.domain.entities import (
    FLOOR_LIMIT_FIELDS,
    PARAMETER_FIELDS,
    AccountRiskPolicy,
    GlobalRiskFloor,
    ResolvedRiskPolicy,
    RiskException,
    RiskParameters,
    RiskProfile,
    RiskTemplate,
)


class RiskPolicyResolver:
    """Resolve effective account risk controls from template, overrides, and floor."""

    def resolve(
        self,
        *,
        account_id: int,
        floor: GlobalRiskFloor | None,
        template: RiskTemplate,
        account_policy: AccountRiskPolicy | None = None,
        exceptions: list[RiskException] | None = None,
        resolved_at: datetime | None = None,
    ) -> ResolvedRiskPolicy:
        checked_at = resolved_at or datetime.now(UTC)
        active_exceptions = {
            item.field_name: item
            for item in exceptions or []
            if item.field_name in PARAMETER_FIELDS and item.is_valid_at(checked_at)
        }

        values = template.parameters.to_dict()
        sources = {
            field_name: f"template:{template.key}"
            for field_name, value in values.items()
            if value not in (None, [], ())
        }

        if account_policy and account_policy.is_active:
            override_values = account_policy.overrides.to_dict()
            for field_name, value in override_values.items():
                if value not in (None, [], ()):
                    values[field_name] = value
                    sources[field_name] = "account_policy"

        floor_applied: list[dict[str, Any]] = []
        exceptions_applied: list[dict[str, Any]] = []
        if floor and floor.is_active:
            values = self._apply_floor(
                values=values,
                floor=floor,
                sources=sources,
                active_exceptions=active_exceptions,
                floor_applied=floor_applied,
                exceptions_applied=exceptions_applied,
            )

        return ResolvedRiskPolicy(
            account_id=account_id,
            parameters=RiskParameters.from_mapping(values),
            template_key=template.key,
            risk_profile=(
                account_policy.risk_profile
                if account_policy and account_policy.risk_profile
                else template.risk_profile
            ),
            sources=sources,
            floor_applied=floor_applied,
            exceptions_applied=exceptions_applied,
        )

    def _apply_floor(
        self,
        *,
        values: dict[str, Any],
        floor: GlobalRiskFloor,
        sources: dict[str, str],
        active_exceptions: dict[str, RiskException],
        floor_applied: list[dict[str, Any]],
        exceptions_applied: list[dict[str, Any]],
    ) -> dict[str, Any]:
        floor_values = floor.parameters.to_dict()
        result = dict(values)

        for field_name in FLOOR_LIMIT_FIELDS:
            floor_value = floor_values.get(field_name)
            current_value = result.get(field_name)
            if floor_value is None or current_value is None or current_value <= floor_value:
                continue
            if field_name in active_exceptions:
                result[field_name] = self._max_allowed_value(
                    requested=current_value,
                    allowed=active_exceptions[field_name].allowed_value,
                )
                self._record_exception(
                    field_name,
                    current_value,
                    result[field_name],
                    active_exceptions[field_name],
                    exceptions_applied,
                )
                sources[field_name] = "exception"
                continue
            result[field_name] = floor_value
            sources[field_name] = "global_floor"
            floor_applied.append(
                {"field": field_name, "requested": current_value, "applied": floor_value}
            )

        min_cash_floor = floor_values.get("min_cash_pct")
        min_cash_current = result.get("min_cash_pct")
        if (
            min_cash_floor is not None
            and min_cash_current is not None
            and min_cash_current < min_cash_floor
        ):
            if "min_cash_pct" in active_exceptions:
                exception = active_exceptions["min_cash_pct"]
                result["min_cash_pct"] = self._min_allowed_value(
                    requested=min_cash_current,
                    allowed=exception.allowed_value,
                )
                self._record_exception(
                    "min_cash_pct",
                    min_cash_current,
                    result["min_cash_pct"],
                    exception,
                    exceptions_applied,
                )
                sources["min_cash_pct"] = "exception"
            else:
                result["min_cash_pct"] = min_cash_floor
                sources["min_cash_pct"] = "global_floor"
                floor_applied.append(
                    {
                        "field": "min_cash_pct",
                        "requested": min_cash_current,
                        "applied": min_cash_floor,
                    }
                )

        if floor_values.get("force_stop_loss") is True and result.get("force_stop_loss") is False:
            if "force_stop_loss" in active_exceptions:
                exception = active_exceptions["force_stop_loss"]
                result["force_stop_loss"] = bool(exception.allowed_value)
                self._record_exception(
                    "force_stop_loss",
                    False,
                    result["force_stop_loss"],
                    exception,
                    exceptions_applied,
                )
                sources["force_stop_loss"] = "exception"
            else:
                result["force_stop_loss"] = True
                sources["force_stop_loss"] = "global_floor"
                floor_applied.append(
                    {"field": "force_stop_loss", "requested": False, "applied": True}
                )

        floor_exclusions = set(floor_values.get("hard_exclusions") or [])
        current_exclusions = set(result.get("hard_exclusions") or [])
        if floor_exclusions:
            if "hard_exclusions" in active_exceptions:
                exception = active_exceptions["hard_exclusions"]
                result["hard_exclusions"] = list(exception.allowed_value or [])
                self._record_exception(
                    "hard_exclusions",
                    sorted(current_exclusions | floor_exclusions),
                    result["hard_exclusions"],
                    exception,
                    exceptions_applied,
                )
                sources["hard_exclusions"] = "exception"
            else:
                merged = sorted(current_exclusions | floor_exclusions)
                if merged != sorted(current_exclusions):
                    floor_applied.append(
                        {
                            "field": "hard_exclusions",
                            "requested": sorted(current_exclusions),
                            "applied": merged,
                        }
                    )
                result["hard_exclusions"] = merged
                sources["hard_exclusions"] = "global_floor"

        return result

    @staticmethod
    def _max_allowed_value(*, requested: Any, allowed: Any) -> Any:
        try:
            return min(float(requested), float(allowed))
        except (TypeError, ValueError):
            return requested

    @staticmethod
    def _min_allowed_value(*, requested: Any, allowed: Any) -> Any:
        try:
            return max(float(requested), float(allowed))
        except (TypeError, ValueError):
            return requested

    @staticmethod
    def _record_exception(
        field_name: str,
        requested: Any,
        applied: Any,
        exception: RiskException,
        exceptions_applied: list[dict[str, Any]],
    ) -> None:
        exceptions_applied.append(
            {
                "field": field_name,
                "requested": requested,
                "applied": applied,
                "reason": exception.reason,
                "expires_at": exception.expires_at.isoformat(),
            }
        )


def fallback_template_for_profile(profile: RiskProfile | str | None) -> RiskTemplate:
    profile_value = profile.value if isinstance(profile, RiskProfile) else profile
    if profile_value == RiskProfile.CONSERVATIVE.value:
        return RiskTemplate(
            key="conservative",
            name="Conservative",
            risk_profile=RiskProfile.CONSERVATIVE,
            parameters=RiskParameters(
                max_total_position_pct=0.65,
                max_single_position_pct=0.12,
                max_daily_loss_pct=0.02,
                max_drawdown_pct=0.08,
                max_stop_loss_pct=0.08,
                take_profit_pct=0.18,
                min_cash_pct=0.25,
                force_stop_loss=True,
            ),
        )
    if profile_value == RiskProfile.AGGRESSIVE.value:
        return RiskTemplate(
            key="aggressive",
            name="Aggressive",
            risk_profile=RiskProfile.AGGRESSIVE,
            parameters=RiskParameters(
                max_total_position_pct=0.9,
                max_single_position_pct=0.25,
                max_daily_loss_pct=0.05,
                max_drawdown_pct=0.2,
                max_stop_loss_pct=0.15,
                take_profit_pct=0.35,
                min_cash_pct=0.05,
                force_stop_loss=True,
            ),
        )
    return RiskTemplate(
        key="moderate",
        name="Moderate",
        risk_profile=RiskProfile.MODERATE,
        parameters=RiskParameters(
            max_total_position_pct=0.8,
            max_single_position_pct=0.18,
            max_daily_loss_pct=0.035,
            max_drawdown_pct=0.12,
            max_stop_loss_pct=0.1,
            take_profit_pct=0.25,
            min_cash_pct=0.15,
            force_stop_loss=True,
        ),
    )


def with_template_key(template: RiskTemplate, key: str | None) -> RiskTemplate:
    if not key:
        return template
    return replace(template, key=key)
