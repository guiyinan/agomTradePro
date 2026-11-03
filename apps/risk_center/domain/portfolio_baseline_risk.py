"""Exact conservative checks for four existing portfolio risk dimensions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal, TypeAlias

from apps.risk_center.domain.portfolio_exposure_types import (
    PortfolioExposureProjection,
)
from apps.risk_center.domain.portfolio_risk_native_limits import (
    PortfolioRiskNativeAccountLimits,
)
from apps.risk_center.domain.portfolio_risk_serialization import (
    portfolio_risk_content_hash,
)
from apps.risk_center.domain.portfolio_risk_snapshot import (
    AccountSnapshot,
    ProposedOrder,
)

NumericBaselineField: TypeAlias = Literal[
    "max_total_weight",
    "max_single_weight",
    "min_cash_weight",
]
BaselineExceptionField: TypeAlias = Literal[
    "max_total_weight",
    "max_single_weight",
    "min_cash_weight",
    "hard_exclusions",
]
_NUMERIC_FIELDS: tuple[NumericBaselineField, ...] = (
    "max_total_weight",
    "max_single_weight",
    "min_cash_weight",
)


class PortfolioBaselineRiskError(ValueError):
    """One malformed exact value or ambiguous legacy exception binding."""

    def __init__(self, reason_code: str, message: str) -> None:
        """Expose a stable domain reason while retaining the invalid-input detail."""

        self.reason_code = reason_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class BaselineRiskParameters:
    """The four explicitly present values read from one legacy policy row."""

    max_total_weight: Decimal | None
    max_single_weight: Decimal | None
    min_cash_weight: Decimal | None
    hard_exclusions: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate exact unit-interval limits and a typed exclusion list."""

        _validate_weight(self.max_total_weight, "max_total_weight")
        _validate_weight(self.max_single_weight, "max_single_weight")
        _validate_weight(self.min_cash_weight, "min_cash_weight")
        _validate_exclusions(self.hard_exclusions, "hard_exclusions")


@dataclass(frozen=True, slots=True)
class BaselineRiskException:
    """One already scoped and time-qualified existing exception record."""

    field: BaselineExceptionField
    allowed_weight: Decimal | None
    allowed_exclusions: tuple[str, ...] | None

    def __post_init__(self) -> None:
        """Keep numeric and list exceptions disjoint and exact."""

        if self.field not in (*_NUMERIC_FIELDS, "hard_exclusions"):
            raise PortfolioBaselineRiskError(
                "PORTFOLIO_BASELINE_EXCEPTION_FIELD_INVALID",
                "exception field is outside the four baseline dimensions",
            )
        if self.field == "hard_exclusions":
            if self.allowed_weight is not None or self.allowed_exclusions is None:
                raise PortfolioBaselineRiskError(
                    "PORTFOLIO_BASELINE_EXCEPTION_VALUE_INVALID",
                    "hard-exclusion exceptions require only an explicit list",
                )
            _validate_exclusions(self.allowed_exclusions, "allowed_exclusions")
        else:
            if self.allowed_exclusions is not None:
                raise PortfolioBaselineRiskError(
                    "PORTFOLIO_BASELINE_EXCEPTION_VALUE_INVALID",
                    "numeric exceptions cannot carry a hard-exclusion list",
                )
            if self.allowed_weight is None:
                raise PortfolioBaselineRiskError(
                    "PORTFOLIO_BASELINE_EXCEPTION_VALUE_INVALID",
                    "numeric exceptions require one exact limit",
                )
            _validate_weight(self.allowed_weight, "allowed_weight")


def resolve_portfolio_baseline_parameters(
    *,
    template: BaselineRiskParameters,
    overrides: BaselineRiskParameters,
    floor: BaselineRiskParameters,
    exceptions: tuple[BaselineRiskException, ...],
) -> BaselineRiskParameters:
    """Preserve existing override/floor/exception semantics with exact Decimals.

    Empty account exclusions retain the template, matching the legacy resolver.
    A missing template value stays missing when the floor cannot be applied to
    that dimension. Active exceptions may relax only the matching floor value.
    """

    for name, parameters in (
        ("template", template),
        ("overrides", overrides),
        ("floor", floor),
    ):
        if type(parameters) is not BaselineRiskParameters:
            raise PortfolioBaselineRiskError(
                "PORTFOLIO_BASELINE_PARAMETERS_INVALID",
                f"{name} must be BaselineRiskParameters",
            )
    if type(exceptions) is not tuple or any(
        type(item) is not BaselineRiskException for item in exceptions
    ):
        raise PortfolioBaselineRiskError(
            "PORTFOLIO_BASELINE_EXCEPTIONS_INVALID",
            "exceptions must be a tuple of BaselineRiskException values",
        )
    by_field = {item.field: item for item in exceptions}
    if len(by_field) != len(exceptions):
        raise PortfolioBaselineRiskError(
            "PORTFOLIO_BASELINE_EXCEPTION_AMBIGUOUS",
            "multiple active baseline exceptions target one dimension",
        )

    max_total = _resolve_upper_limit(
        overrides.max_total_weight,
        template.max_total_weight,
        floor.max_total_weight,
        by_field.get("max_total_weight"),
    )
    max_single = _resolve_upper_limit(
        overrides.max_single_weight,
        template.max_single_weight,
        floor.max_single_weight,
        by_field.get("max_single_weight"),
    )
    min_cash = _resolve_lower_limit(
        overrides.min_cash_weight,
        template.min_cash_weight,
        floor.min_cash_weight,
        by_field.get("min_cash_weight"),
    )

    exclusions = overrides.hard_exclusions or template.hard_exclusions
    if floor.hard_exclusions:
        exclusion_exception = by_field.get("hard_exclusions")
        if exclusion_exception is not None:
            if exclusion_exception.allowed_exclusions is None:
                raise PortfolioBaselineRiskError(
                    "PORTFOLIO_BASELINE_EXCEPTION_VALUE_INVALID",
                    "hard-exclusion exception list is missing",
                )
            exclusions = exclusion_exception.allowed_exclusions
        else:
            exclusions = tuple(sorted(set(exclusions) | set(floor.hard_exclusions)))
    return BaselineRiskParameters(
        max_total_weight=max_total,
        max_single_weight=max_single,
        min_cash_weight=min_cash,
        hard_exclusions=exclusions,
    )


@dataclass(frozen=True, slots=True)
class PortfolioBaselinePolicy:
    """A qualified read of existing floor/template/account/exception rows."""

    account_id: int
    account_policy_id: int
    content_sha256: str
    known_at: datetime
    effective_until: datetime | None
    max_total_weight: Decimal | None
    max_single_weight: Decimal | None
    min_cash_weight: Decimal | None
    hard_exclusions: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require stable row identity, actual aware clocks, and exact limits."""

        if type(self.account_id) is not int or self.account_id < 1:
            raise ValueError("account_id must be a positive integer")
        if type(self.account_policy_id) is not int or self.account_policy_id < 1:
            raise ValueError("account_policy_id must be a positive integer")
        if (
            type(self.content_sha256) is not str
            or len(self.content_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.content_sha256)
        ):
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
        _require_aware(self.known_at, "known_at")
        if self.effective_until is not None:
            _require_aware(self.effective_until, "effective_until")
        _validate_weight(self.max_total_weight, "max_total_weight")
        _validate_weight(self.max_single_weight, "max_single_weight")
        _validate_weight(self.min_cash_weight, "min_cash_weight")
        _validate_exclusions(self.hard_exclusions, "hard_exclusions")


def intersect_native_account_limits(
    policy: PortfolioBaselinePolicy | None,
    native: PortfolioRiskNativeAccountLimits | None,
    snapshot_read_at: datetime,
) -> PortfolioBaselinePolicy | None:
    """Intersect known native account caps without changing the source policy.

    A dimension stays unknown unless both persisted baseline and native account
    values are known. Zero is retained as the strictest cap. The returned policy
    carries the latest real baseline/snapshot clock and a lossless digest of the
    source baseline hash plus the native values and basis.
    """

    if (
        type(policy) is not PortfolioBaselinePolicy
        or type(native) is not PortfolioRiskNativeAccountLimits
        or type(snapshot_read_at) is not datetime
        or not _is_aware(snapshot_read_at)
    ):
        return None
    return replace(
        policy,
        max_total_weight=_minimum_known_limit(
            policy.max_total_weight,
            native.max_total_weight,
        ),
        max_single_weight=_minimum_known_limit(
            policy.max_single_weight,
            native.max_single_weight,
        ),
        known_at=max(policy.known_at, snapshot_read_at),
        content_sha256=portfolio_risk_content_hash(
            {
                "baseline_source_sha256": policy.content_sha256,
                "native_account_limits": native,
            }
        ),
    )


@dataclass(frozen=True, slots=True)
class PortfolioBaselineAssessment:
    """The original limits applied without anticipating any unfilled sale."""

    outcome: Literal["allowed", "blocked", "unknown"]
    reason_codes: tuple[str, ...]
    projected_total_value: Decimal | None
    cash_after_committed_demands: Decimal | None

    def __post_init__(self) -> None:
        """Keep result status and exact values consistent."""

        if self.outcome not in ("allowed", "blocked", "unknown"):
            raise ValueError("outcome must be allowed, blocked, or unknown")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str or not code or code.strip() != code for code in self.reason_codes
        ):
            raise ValueError("reason_codes must be a tuple of stable nonempty tokens")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes cannot contain duplicates")
        if (self.outcome == "allowed") != (not self.reason_codes):
            raise ValueError("only allowed assessments may have no reasons")
        _validate_result_decimal(self.projected_total_value, "projected_total_value")
        _validate_result_decimal(
            self.cash_after_committed_demands,
            "cash_after_committed_demands",
            allow_negative=True,
        )


def assess_portfolio_baseline(
    *,
    policy: PortfolioBaselinePolicy | None,
    snapshot: AccountSnapshot,
    projection: PortfolioExposureProjection | None,
    proposals: tuple[ProposedOrder, ...],
    as_of: datetime,
) -> PortfolioBaselineAssessment:
    """Retain total, direct-position, cash-floor and exclusion constraints.

    The denominator is current pre-trade gross NAV. Active remaining cash holds
    and proposed fee budgets reduce spendable cash. BUY proposals also reserve
    their exact limit notional. Unfilled SELLs never reduce exposure or release
    sale proceeds. All comparisons use rational arithmetic over exact Decimals.
    """

    if type(snapshot) is not AccountSnapshot:
        return _unknown("PORTFOLIO_BASELINE_SNAPSHOT_INVALID")
    if type(proposals) is not tuple or any(type(order) is not ProposedOrder for order in proposals):
        return _unknown("PORTFOLIO_BASELINE_PROPOSALS_INVALID")
    if type(as_of) is not datetime or not _is_aware(as_of):
        return _unknown("PORTFOLIO_BASELINE_CUTOFF_INVALID")
    if policy is None:
        return _unknown("PORTFOLIO_BASELINE_POLICY_UNAVAILABLE")
    if type(policy) is not PortfolioBaselinePolicy:
        return _unknown("PORTFOLIO_BASELINE_POLICY_INVALID")
    if policy.account_id != snapshot.account_id or policy.known_at > as_of:
        return _unknown("PORTFOLIO_BASELINE_POLICY_SCOPE_OR_CLOCK_INVALID")
    if policy.effective_until is not None and as_of >= policy.effective_until:
        return _unknown("PORTFOLIO_BASELINE_POLICY_EXPIRED")
    if snapshot.read_at > as_of:
        return _unknown("PORTFOLIO_BASELINE_ACCOUNT_SNAPSHOT_AFTER_CUTOFF")
    if projection is None:
        return _unknown("PORTFOLIO_BASELINE_PROJECTION_UNAVAILABLE")
    if type(projection) is not PortfolioExposureProjection:
        return _unknown("PORTFOLIO_BASELINE_PROJECTION_INVALID")
    if projection.portfolio_snapshot_id != snapshot.snapshot_id or projection.as_of != as_of:
        return _unknown("PORTFOLIO_BASELINE_SNAPSHOT_OR_CUTOFF_MISMATCH")
    if projection.portfolio_market_value is None:
        return _unknown("PORTFOLIO_BASELINE_NAV_UNKNOWN")
    nav = Fraction(projection.portfolio_market_value)
    if nav <= 0:
        return _unknown("PORTFOLIO_BASELINE_NAV_INVALID")

    unknown: list[str] = []
    blocked: list[str] = []
    limits = (
        policy.max_total_weight,
        policy.max_single_weight,
        policy.min_cash_weight,
    )
    if any(value is None for value in limits):
        unknown.append("PORTFOLIO_BASELINE_LIMIT_UNKNOWN")

    if any(
        portfolio_risk_subject_is_excluded(
            asset_code=order.asset_code, hard_exclusions=policy.hard_exclusions
        )
        for order in proposals
    ):
        blocked.append("PORTFOLIO_BASELINE_HARD_EXCLUSION")
    proposal_ids = tuple(order.order_id for order in proposals)
    if len(set(proposal_ids)) != len(proposal_ids):
        blocked.append("PORTFOLIO_BASELINE_PROPOSAL_ID_DUPLICATE")

    projected = Fraction(0)
    projected_values_known = True
    for asset in projection.assets:
        value = asset.projected_market_value
        if value is None:
            projected_values_known = False
            continue
        exact_value = Fraction(value)
        projected += exact_value
        if policy.max_single_weight is not None and exact_value > nav * Fraction(
            policy.max_single_weight
        ):
            blocked.append("PORTFOLIO_BASELINE_SINGLE_POSITION_LIMIT")
    if not projected_values_known:
        unknown.append("PORTFOLIO_BASELINE_PROJECTED_VALUE_UNKNOWN")
    elif policy.max_total_weight is not None and projected > nav * Fraction(
        policy.max_total_weight
    ):
        blocked.append("PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT")

    free_cash: Fraction | None = None
    cash_complete = True
    if snapshot.money_unit is None:
        unknown.append("PORTFOLIO_BASELINE_MONEY_UNIT_UNKNOWN")
        cash_complete = False
    if snapshot.cash is None:
        unknown.append("PORTFOLIO_BASELINE_CASH_UNKNOWN")
        cash_complete = False
    elif snapshot.cash is not None and snapshot.money_unit is not None:
        free_cash = Fraction(snapshot.cash)
        if not snapshot.active_orders_complete:
            unknown.append("PORTFOLIO_BASELINE_CASH_HOLDS_INCOMPLETE")
            cash_complete = False
        for order in snapshot.active_orders:
            if order.remaining_cash is None:
                unknown.append("PORTFOLIO_BASELINE_CASH_HOLD_UNKNOWN")
                cash_complete = False
            else:
                free_cash -= Fraction(order.remaining_cash)
        for proposed_order in proposals:
            if proposed_order.side == "buy":
                free_cash -= Fraction(proposed_order.quantity) * Fraction(proposed_order.price)
            if proposed_order.fee_cap is None:
                unknown.append("PORTFOLIO_BASELINE_FEE_BUDGET_UNKNOWN")
                cash_complete = False
            else:
                free_cash -= Fraction(proposed_order.fee_cap)
        if free_cash < 0:
            blocked.append("PORTFOLIO_BASELINE_INSUFFICIENT_CASH")
        if (
            snapshot.money_unit is not None
            and policy.min_cash_weight is not None
            and free_cash < nav * Fraction(policy.min_cash_weight)
        ):
            blocked.append("PORTFOLIO_BASELINE_CASH_FLOOR")

    reasons = tuple(dict.fromkeys((*blocked, *unknown)))
    return PortfolioBaselineAssessment(
        outcome="blocked" if blocked else "unknown" if unknown else "allowed",
        reason_codes=reasons,
        projected_total_value=(_fraction_to_decimal(projected) if projected_values_known else None),
        cash_after_committed_demands=(
            _fraction_to_decimal(free_cash) if free_cash is not None and cash_complete else None
        ),
    )


def _resolve_upper_limit(
    override: Decimal | None,
    template: Decimal | None,
    floor: Decimal | None,
    exception: BaselineRiskException | None,
) -> Decimal | None:
    value = template if override is None else override
    if value is not None and floor is not None and value > floor:
        if exception is None:
            return floor
        if exception.allowed_weight is None:
            raise PortfolioBaselineRiskError(
                "PORTFOLIO_BASELINE_EXCEPTION_VALUE_INVALID",
                "upper-limit exception has no exact limit",
            )
        return min(value, exception.allowed_weight)
    return value


def _minimum_known_limit(
    baseline_limit: Decimal | None,
    native_limit: Decimal | None,
) -> Decimal | None:
    if baseline_limit is None or native_limit is None:
        return None
    return min(baseline_limit, native_limit)


def _resolve_lower_limit(
    override: Decimal | None,
    template: Decimal | None,
    floor: Decimal | None,
    exception: BaselineRiskException | None,
) -> Decimal | None:
    value = template if override is None else override
    if value is not None and floor is not None and value < floor:
        if exception is None:
            return floor
        if exception.allowed_weight is None:
            raise PortfolioBaselineRiskError(
                "PORTFOLIO_BASELINE_EXCEPTION_VALUE_INVALID",
                "minimum-cash exception has no exact limit",
            )
        return max(value, exception.allowed_weight)
    return value


def _validate_weight(value: Decimal | None, field_name: str) -> None:
    if value is None:
        return
    if type(value) is not Decimal or not value.is_finite() or not 0 <= value <= 1:
        raise PortfolioBaselineRiskError(
            "PORTFOLIO_BASELINE_LIMIT_INVALID",
            f"{field_name} must be an exact Decimal within [0, 1]",
        )


def _validate_exclusions(values: tuple[str, ...], field_name: str) -> None:
    if type(values) is not tuple or any(
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
        for value in values
    ):
        raise PortfolioBaselineRiskError(
            "PORTFOLIO_BASELINE_EXCLUSIONS_INVALID",
            f"{field_name} must be a tuple of canonical asset codes",
        )
    if len({value.upper() for value in values}) != len(values):
        raise PortfolioBaselineRiskError(
            "PORTFOLIO_BASELINE_EXCLUSIONS_DUPLICATE",
            f"{field_name} cannot repeat an asset code",
        )


def _validate_result_decimal(
    value: Decimal | None,
    field_name: str,
    *,
    allow_negative: bool = False,
) -> None:
    if value is None:
        return
    if type(value) is not Decimal or not value.is_finite():
        raise TypeError(f"{field_name} must be a finite Decimal or None")
    if not allow_negative and value < 0:
        raise ValueError(f"{field_name} must be nonnegative")


def _require_aware(value: datetime, field_name: str) -> None:
    if type(value) is not datetime or not _is_aware(value):
        raise ValueError(f"{field_name} must be timezone-aware")


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _unknown(reason: str) -> PortfolioBaselineAssessment:
    return PortfolioBaselineAssessment("unknown", (reason,), None, None)


def _fraction_to_decimal(value: Fraction) -> Decimal:
    denominator = value.denominator
    twos = 0
    fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise PortfolioBaselineRiskError(
            "PORTFOLIO_BASELINE_NONTERMINATING_DECIMAL",
            "baseline exact arithmetic cannot be represented as a finite Decimal",
        )
    scale = max(twos, fives)
    coefficient = value.numerator * (2 ** (scale - twos)) * (5 ** (scale - fives))
    sign = 1 if coefficient < 0 else 0
    digits = tuple(int(character) for character in str(abs(coefficient)))
    return Decimal((sign, digits, -scale))


__all__ = (
    "BaselineExceptionField",
    "BaselineRiskException",
    "BaselineRiskParameters",
    "NumericBaselineField",
    "PortfolioBaselineAssessment",
    "PortfolioBaselinePolicy",
    "PortfolioBaselineRiskError",
    "assess_portfolio_baseline",
    "intersect_native_account_limits",
    "resolve_portfolio_baseline_parameters",
)


def portfolio_risk_subject_is_excluded(
    *, asset_code: str, hard_exclusions: tuple[str, ...]
) -> bool:
    """Apply the same declared exclusion semantics to an executing accepted order."""

    return asset_code.upper() in {code.upper() for code in hard_exclusions}
