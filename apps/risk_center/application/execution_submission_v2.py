"""Resolve owner-provided v2 rules and market evidence for one exact order."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from apps.risk_center.application.execution_trading_constraints import (
    ExecutionTradingEvidenceInvalid,
    ExecutionTradingEvidenceUnavailable,
)
from apps.risk_center.domain.execution_submission_v2 import (
    ExecutionSubmissionDecisionV2,
    ExecutionSubmissionMarketV2,
    ExecutionSubmissionRuleV2,
    evaluate_execution_submission,
)
from apps.risk_center.domain.execution_trading_constraints import (
    ExecutionOrder,
    ExecutionSide,
    SellPositionEvidence,
)
from core.exceptions import InvalidInputError

EXECUTION_SUBMISSION_V2_SCHEMA: str = "a-share-execution-constraints.v2"


class ExecutionSubmissionRuleProvider(Protocol):
    """Read the source-bound, configured v2 rule for an exact account and cutoff."""

    def get_submission_rule(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> ExecutionSubmissionRuleV2 | None:
        """Return the owner's exact v2 configuration, or None if unavailable."""


class ExecutionSubmissionMarketProvider(Protocol):
    """Read a single source-bound market snapshot including stage and book states."""

    def get_submission_market(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> ExecutionSubmissionMarketV2 | None:
        """Return current owner evidence without substituting caller-supplied facts."""


class ExecutionSellPositionProvider(Protocol):
    """Read complete sell-balance evidence from the trusted account owner."""

    def get_sell_position(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> SellPositionEvidence | None:
        """Return exact account/security evidence at the shared knowledge cutoff."""


def _validate_request(order: ExecutionOrder, as_of: datetime) -> None:
    if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise InvalidInputError("Execution submission requires an aware knowledge cutoff")
    if type(order) is not ExecutionOrder:
        raise InvalidInputError("Execution submission requires an exact typed order")
    try:
        ExecutionOrder.__post_init__(order)
    except (TypeError, ValueError) as error:
        raise InvalidInputError("Execution order violates its typed contract") from error


def _validate_rule(rule: ExecutionSubmissionRuleV2) -> None:
    if type(rule) is not ExecutionSubmissionRuleV2:
        raise ExecutionTradingEvidenceInvalid("Execution rule owner did not return v2 evidence")
    try:
        ExecutionSubmissionRuleV2.__post_init__(rule)
    except (TypeError, ValueError) as error:
        raise ExecutionTradingEvidenceInvalid(
            "Execution v2 rule failed integrity checks"
        ) from error


def _evaluate(
    rule: ExecutionSubmissionRuleV2,
    market: ExecutionSubmissionMarketV2,
    order: ExecutionOrder,
    as_of: datetime,
) -> ExecutionSubmissionDecisionV2:
    _validate_rule(rule)
    if type(market) is not ExecutionSubmissionMarketV2:
        raise ExecutionTradingEvidenceInvalid("Execution market owner did not return v2 evidence")
    try:
        return evaluate_execution_submission(rule, market, order, as_of)
    except (TypeError, ValueError) as error:
        raise ExecutionTradingEvidenceInvalid("Execution v2 evidence failed validation") from error


@dataclass(frozen=True, slots=True)
class ExecutionSubmissionV2Evaluation:
    """A reproducible v2 tradability result with no execution authority attached."""

    rule: ExecutionSubmissionRuleV2
    market_evidence: ExecutionSubmissionMarketV2
    order: ExecutionOrder
    as_of: datetime
    decision: ExecutionSubmissionDecisionV2

    def __post_init__(self) -> None:
        """Require the decision to reproduce from these exact owner-read inputs."""

        _validate_request(self.order, self.as_of)
        expected = _evaluate(self.rule, self.market_evidence, self.order, self.as_of)
        if type(self.decision) is not ExecutionSubmissionDecisionV2 or self.decision != expected:
            raise ExecutionTradingEvidenceInvalid(
                "Execution v2 decision differs from owner evidence"
            )

    def to_payload(self) -> dict[str, object]:
        """Revalidate and project the complete explicit v2 envelope."""

        self.__post_init__()
        return {
            "schema": EXECUTION_SUBMISSION_V2_SCHEMA,
            "as_of": self.as_of.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "rule": self.rule.to_payload(),
            "market_evidence": self.market_evidence.to_payload(),
            "order": self.order.to_payload(),
            "decision": self.decision.to_payload(),
        }


class EvaluateExecutionSubmissionV2UseCase:
    """Query configured v2 owner ports and calculate a bound tradability response."""

    def __init__(
        self,
        *,
        rule_provider: ExecutionSubmissionRuleProvider,
        market_provider: ExecutionSubmissionMarketProvider,
        position_provider: ExecutionSellPositionProvider | None = None,
    ) -> None:
        """Inject owner readers; sell orders require an explicit position reader."""

        self._rules = rule_provider
        self._markets = market_provider
        self._positions = position_provider

    def execute(self, *, order: ExecutionOrder, as_of: datetime) -> ExecutionSubmissionV2Evaluation:
        """Read owner facts for the intent without trusting caller position evidence.

        The low-level Domain accepts assembled evidence. This use-case boundary
        accepts an intent whose sell_position_evidence is None; SELL evidence
        must instead come from its injected owner port at the same cutoff.
        """

        _validate_request(order, as_of)
        if order.sell_position_evidence is not None:
            raise InvalidInputError("Execution position evidence must be read from its owner")
        rule = self._rules.get_submission_rule(
            account_id=order.account_id, security_id=order.security_id, as_of=as_of
        )
        if rule is None:
            raise ExecutionTradingEvidenceUnavailable("Execution v2 rule is not configured")
        _validate_rule(rule)
        if order.side is ExecutionSide.SELL:
            order = replace(order, sell_position_evidence=self._read_sell_position(order, as_of))
        market = self._markets.get_submission_market(
            account_id=order.account_id, security_id=order.security_id, as_of=as_of
        )
        if market is None:
            raise ExecutionTradingEvidenceUnavailable("Execution v2 market evidence is unavailable")
        decision = _evaluate(rule, market, order, as_of)
        return ExecutionSubmissionV2Evaluation(rule, market, order, as_of, decision)

    def _read_sell_position(self, order: ExecutionOrder, as_of: datetime) -> SellPositionEvidence:
        if self._positions is None:
            raise ExecutionTradingEvidenceUnavailable(
                "Execution sell position owner is unavailable"
            )
        position = self._positions.get_sell_position(
            account_id=order.account_id, security_id=order.security_id, as_of=as_of
        )
        if position is None:
            raise ExecutionTradingEvidenceUnavailable("Execution sell position is unavailable")
        if type(position) is not SellPositionEvidence:
            raise ExecutionTradingEvidenceInvalid(
                "Execution position owner returned an invalid type"
            )
        try:
            SellPositionEvidence.__post_init__(position)
        except (TypeError, ValueError) as error:
            raise ExecutionTradingEvidenceInvalid(
                "Execution position owner returned invalid evidence"
            ) from error
        if position.account_id != order.account_id or position.security_id != order.security_id:
            raise ExecutionTradingEvidenceInvalid(
                "Execution position owner returned a different account or security"
            )
        return position
