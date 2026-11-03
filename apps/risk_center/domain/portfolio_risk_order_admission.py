"""Direction-aware admission for an exact simulated order subject."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PortfolioRiskOrderSide = Literal["buy", "sell", "mixed"]
PortfolioRiskAdmissionStatus = Literal["allowed", "blocked", "unknown", "partial"]
PortfolioRiskOrderAdmissionOutcome = Literal["allowed", "blocked", "unknown"]

PORTFOLIO_RISK_SELL_WAIVABLE_BASELINE_REASON_CODES = frozenset(
    {
        "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT",
        "PORTFOLIO_BASELINE_SINGLE_POSITION_LIMIT",
        "PORTFOLIO_BASELINE_INSUFFICIENT_CASH",
        "PORTFOLIO_BASELINE_CASH_FLOOR",
    }
)


@dataclass(frozen=True, slots=True)
class PortfolioRiskAdmissionCheck:
    """One exact report check consumed by the order-direction decision."""

    dimension: str
    status: PortfolioRiskAdmissionStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require canonical check names and stable, unique reason tokens."""

        if type(self.dimension) is not str or not self.dimension.strip():
            raise ValueError("dimension must be a nonempty string")
        if self.status not in {"allowed", "blocked", "unknown", "partial"}:
            raise ValueError("unsupported portfolio risk check status")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str
            or not code
            or code.strip() != code
            or any(character.isspace() for character in code)
            for code in self.reason_codes
        ):
            raise ValueError("reason_codes must contain canonical reason tokens")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes cannot contain duplicates")


@dataclass(frozen=True, slots=True)
class PortfolioRiskOrderAdmission:
    """Explain whether one proposal set passes direction-specific admission."""

    side: PortfolioRiskOrderSide
    outcome: PortfolioRiskOrderAdmissionOutcome
    reason_codes: tuple[str, ...]
    waived_reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Keep admission results internally consistent and never waive unknowns."""

        if self.side not in {"buy", "sell", "mixed"}:
            raise ValueError("side must be buy, sell, or mixed")
        if self.outcome not in {"allowed", "blocked", "unknown"}:
            raise ValueError("unsupported order admission outcome")
        for name, values in (
            ("reason_codes", self.reason_codes),
            ("waived_reason_codes", self.waived_reason_codes),
        ):
            if type(values) is not tuple or any(
                type(code) is not str
                or not code
                or code.strip() != code
                or any(character.isspace() for character in code)
                for code in values
            ):
                raise ValueError(f"{name} must contain canonical reason tokens")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} cannot contain duplicates")
        if set(self.reason_codes).intersection(self.waived_reason_codes):
            raise ValueError("a reason cannot be both blocking and waived")
        if self.side != "sell" and self.waived_reason_codes:
            raise ValueError("only SELL may waive the existing BUY-limit reasons")
        if self.outcome == "allowed" and self.reason_codes:
            raise ValueError("an allowed result cannot contain blocking reasons")
        if self.outcome != "allowed" and not self.reason_codes:
            raise ValueError("a denied result must explain its blocking reason")


def assess_portfolio_risk_order_admission(
    *,
    side: PortfolioRiskOrderSide,
    checks: tuple[PortfolioRiskAdmissionCheck, ...],
    must_not_use_for_decision: bool,
) -> PortfolioRiskOrderAdmission:
    """Apply legacy BUY-only limits without relaxing source, capacity, or identity gates.

    SELL may proceed past known total-position, single-position, insufficient-cash,
    and minimum-cash breaches. Every unknown/partial result and every other blocked
    dimension remains a blocker; hard exclusions remain bidirectional.
    """

    if side not in {"buy", "sell", "mixed"}:
        raise ValueError("side must be buy, sell, or mixed")
    if type(checks) is not tuple or any(
        type(check) is not PortfolioRiskAdmissionCheck for check in checks
    ):
        raise TypeError("checks must be a tuple of PortfolioRiskAdmissionCheck")
    if type(must_not_use_for_decision) is not bool:
        raise TypeError("must_not_use_for_decision must be an explicit boolean")

    blocking: list[str] = []
    unknown: list[str] = []
    waived: list[str] = []
    if not checks:
        unknown.append("PORTFOLIO_ORDER_ADMISSION_CHECKS_MISSING")
    if must_not_use_for_decision:
        unknown.append("PORTFOLIO_ORDER_ADMISSION_INPUT_NOT_DECISION_GRADE")

    for check in checks:
        if check.status in {"unknown", "partial"}:
            unknown.extend(check.reason_codes or ("PORTFOLIO_ORDER_ADMISSION_CHECK_UNKNOWN",))
            continue
        if check.status == "allowed":
            if check.reason_codes:
                blocking.append("PORTFOLIO_ORDER_ADMISSION_ALLOWED_CHECK_HAS_REASONS")
            continue
        if not must_not_use_for_decision and side == "sell" and check.dimension == "baseline_risk":
            if not check.reason_codes:
                blocking.append("PORTFOLIO_ORDER_ADMISSION_CHECK_BLOCKED")
                continue
            sell_waived = tuple(
                code
                for code in check.reason_codes
                if code in PORTFOLIO_RISK_SELL_WAIVABLE_BASELINE_REASON_CODES
            )
            sell_blocking = tuple(
                code
                for code in check.reason_codes
                if code not in PORTFOLIO_RISK_SELL_WAIVABLE_BASELINE_REASON_CODES
            )
            waived.extend(sell_waived)
            blocking.extend(sell_blocking)
            continue
        blocking.extend(check.reason_codes or ("PORTFOLIO_ORDER_ADMISSION_CHECK_BLOCKED",))

    unique_blocking = tuple(dict.fromkeys(blocking))
    unique_unknown = tuple(dict.fromkeys(unknown))
    unique_reasons = tuple(dict.fromkeys((*unique_blocking, *unique_unknown)))
    unique_waived = tuple(code for code in dict.fromkeys(waived) if code not in unique_reasons)
    if unique_unknown:
        return PortfolioRiskOrderAdmission(
            side=side,
            outcome="unknown",
            reason_codes=unique_reasons,
            waived_reason_codes=unique_waived,
        )
    if unique_blocking:
        return PortfolioRiskOrderAdmission(
            side=side,
            outcome="blocked",
            reason_codes=unique_blocking,
            waived_reason_codes=unique_waived,
        )
    return PortfolioRiskOrderAdmission(
        side=side,
        outcome="allowed",
        reason_codes=(),
        waived_reason_codes=unique_waived,
    )
