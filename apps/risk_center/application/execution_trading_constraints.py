"""Resolve owner-provided evidence before evaluating order tradability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from apps.risk_center.domain.execution_trading_constraints import (
    EXECUTION_CONSTRAINTS_SCHEMA,
    AShareExecutionRule,
    ExecutionMarketEvidence,
    ExecutionOrder,
    ExecutionTradingDecision,
    evaluate_execution_order,
)
from core.exceptions import BusinessLogicError, InvalidInputError


class ExecutionTradingEvidenceUnavailable(BusinessLogicError):
    """Required owner evidence has no usable configured read result."""

    default_code = "EXECUTION_TRADING_EVIDENCE_UNAVAILABLE"
    default_status_code = 503


class ExecutionTradingEvidenceInvalid(BusinessLogicError):
    """An owner read or sealed result violates its typed integrity contract."""

    default_code = "EXECUTION_TRADING_EVIDENCE_INVALID"
    default_status_code = 503


class ExecutionRuleProvider(Protocol):
    """Read an account-scoped effective rule from its trusted owner."""

    def get_rule(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> AShareExecutionRule | None:
        """Return exact rule evidence, or None when no rule is configured."""


class ExecutionMarketEvidenceProvider(Protocol):
    """Read source-bound security, calendar and session evidence."""

    def get_market_evidence(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> ExecutionMarketEvidence | None:
        """Return typed evidence at the same account and knowledge cutoff."""


def _validate_request(order: ExecutionOrder, as_of: datetime) -> None:
    if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise InvalidInputError("Execution evaluation requires an aware knowledge cutoff")
    if type(order) is not ExecutionOrder:
        raise InvalidInputError("Execution evaluation requires an exact typed order")
    try:
        ExecutionOrder.__post_init__(order)
    except (TypeError, ValueError) as exc:
        raise InvalidInputError("Execution order violates its typed contract") from exc


def _evaluate_owner_evidence(
    rule: AShareExecutionRule,
    market: ExecutionMarketEvidence,
    order: ExecutionOrder,
    as_of: datetime,
) -> ExecutionTradingDecision:
    if type(rule) is not AShareExecutionRule or type(market) is not ExecutionMarketEvidence:
        raise ExecutionTradingEvidenceInvalid("Execution owner returned an invalid evidence type")
    try:
        AShareExecutionRule.__post_init__(rule)
        ExecutionMarketEvidence.__post_init__(market)
        return evaluate_execution_order(rule, market, order, as_of)
    except (TypeError, ValueError) as exc:
        raise ExecutionTradingEvidenceInvalid("Execution owner evidence failed validation") from exc


@dataclass(frozen=True, slots=True)
class ExecutionConstraintsEvaluation:
    """An evidence-bound tradability result; execution authorization stays separate."""

    rule: AShareExecutionRule
    market_evidence: ExecutionMarketEvidence
    order: ExecutionOrder
    as_of: datetime
    decision: ExecutionTradingDecision

    def __post_init__(self) -> None:
        """Reject a decision that does not reproduce from these exact inputs."""

        _validate_request(self.order, self.as_of)
        expected = _evaluate_owner_evidence(self.rule, self.market_evidence, self.order, self.as_of)
        if type(self.decision) is not ExecutionTradingDecision or self.decision != expected:
            raise ExecutionTradingEvidenceInvalid("Execution decision differs from owner evidence")

    def to_payload(self) -> dict[str, object]:
        """Return the common wire projection after rechecking immutable inputs."""

        self.__post_init__()
        return {
            "schema": EXECUTION_CONSTRAINTS_SCHEMA,
            "as_of": self.as_of.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "rule": self.rule.to_payload(),
            "market_evidence": self.market_evidence.to_payload(),
            "order": self.order.to_payload(),
            "decision": self.decision.to_payload(),
        }


class EvaluateExecutionTradingConstraintsUseCase:
    """Resolve configured owner evidence and emit a reproducible tradability result."""

    def __init__(
        self,
        *,
        rule_provider: ExecutionRuleProvider,
        market_evidence_provider: ExecutionMarketEvidenceProvider,
    ) -> None:
        """Require explicit trusted providers; no runtime rule fallback exists."""

        self._rules = rule_provider
        self._markets = market_evidence_provider

    def execute(self, *, order: ExecutionOrder, as_of: datetime) -> ExecutionConstraintsEvaluation:
        """Evaluate only typed, owner-read evidence at one explicit cutoff."""

        _validate_request(order, as_of)
        rule = self._rules.get_rule(
            account_id=order.account_id, security_id=order.security_id, as_of=as_of
        )
        if rule is None:
            raise ExecutionTradingEvidenceUnavailable("Execution rule is not configured")
        if type(rule) is not AShareExecutionRule:
            raise ExecutionTradingEvidenceInvalid("Execution rule owner returned an invalid type")
        market = self._markets.get_market_evidence(
            account_id=order.account_id, security_id=order.security_id, as_of=as_of
        )
        if market is None:
            raise ExecutionTradingEvidenceUnavailable("Execution market evidence is unavailable")
        decision = _evaluate_owner_evidence(rule, market, order, as_of)
        return ExecutionConstraintsEvaluation(rule, market, order, as_of, decision)
