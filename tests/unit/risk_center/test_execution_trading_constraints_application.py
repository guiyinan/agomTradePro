"""Trust-boundary behavior for the injected execution-constraint query."""

import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from apps.risk_center.application.execution_trading_constraints import (
    EvaluateExecutionTradingConstraintsUseCase,
    ExecutionTradingEvidenceInvalid,
    ExecutionTradingEvidenceUnavailable,
)
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionDenyCode,
    ExecutionMarketEvidence,
    ExecutionQuantityConstraint,
    ExecutionSide,
    SellOddLotMode,
    SellPositionCompleteness,
    SellPositionEvidence,
)
from core.exceptions import InvalidInputError
from qmt_agent.execution_constraints import (
    ExecutionConstraintViolation,
    validate_effective_constraints,
)
from tests.unit.risk_center.execution_constraints_factories import (
    AS_OF,
)
from tests.unit.risk_center.execution_constraints_factories import execution_market as _market
from tests.unit.risk_center.execution_constraints_factories import execution_order as _order
from tests.unit.risk_center.execution_constraints_factories import execution_rule as _rule


class _RuleProvider:
    def __init__(self, rule: AShareExecutionRule | None) -> None:
        self.rule = rule
        self.calls: list[tuple[int, str, datetime]] = []

    def get_rule(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> AShareExecutionRule | None:
        self.calls.append((account_id, security_id, as_of))
        return self.rule


class _MarketProvider:
    def __init__(self, market: ExecutionMarketEvidence | None) -> None:
        self.market = market
        self.calls: list[tuple[int, str, datetime]] = []

    def get_market_evidence(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> ExecutionMarketEvidence | None:
        self.calls.append((account_id, security_id, as_of))
        return self.market


def test_missing_rule_cannot_fall_back_or_read_market() -> None:
    rules = _RuleProvider(None)
    markets = _MarketProvider(None)
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=rules, market_evidence_provider=markets
    )

    with pytest.raises(ExecutionTradingEvidenceUnavailable, match="rule"):
        use_case.execute(order=_order(), as_of=AS_OF)

    assert rules.calls == [(7, "TEST.SECURITY", AS_OF)]
    assert markets.calls == []


def test_missing_market_cannot_be_replaced_with_rule_defaults() -> None:
    rules = _RuleProvider(_rule())
    markets = _MarketProvider(None)
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=rules, market_evidence_provider=markets
    )

    with pytest.raises(ExecutionTradingEvidenceUnavailable, match="market"):
        use_case.execute(order=_order(), as_of=AS_OF)

    assert markets.calls == [(7, "TEST.SECURITY", AS_OF)]


def test_naive_cutoff_is_rejected_before_any_provider_read() -> None:
    rules = _RuleProvider(None)
    markets = _MarketProvider(None)
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=rules, market_evidence_provider=markets
    )

    with pytest.raises(InvalidInputError):
        use_case.execute(order=_order(), as_of=AS_OF.replace(tzinfo=None))

    assert rules.calls == markets.calls == []


def test_caller_cannot_substitute_a_mapping_for_a_typed_order() -> None:
    rules = _RuleProvider(None)
    markets = _MarketProvider(None)
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=rules, market_evidence_provider=markets
    )

    with pytest.raises(InvalidInputError):
        use_case.execute(order={"account_id": 7}, as_of=AS_OF)

    assert rules.calls == markets.calls == []


def test_output_binds_both_owner_reads_to_the_same_account_and_cutoff() -> None:
    rule = _rule()
    market = _market()
    rules = _RuleProvider(rule)
    markets = _MarketProvider(market)
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=rules, market_evidence_provider=markets
    )

    result = use_case.execute(order=_order(), as_of=AS_OF)
    payload = result.to_payload()

    assert rules.calls == markets.calls == [(7, "TEST.SECURITY", AS_OF)]
    assert result.decision.status == "ALLOWED"
    assert set(payload) == {"schema", "as_of", "rule", "market_evidence", "order", "decision"}
    assert payload["schema"] == "a-share-execution-constraints.v1"
    assert payload["as_of"] == "2026-10-16T02:00:00Z"
    assert payload["rule"] == rule.to_payload()
    assert payload["market_evidence"] == market.to_payload()


def test_wrong_security_from_a_provider_remains_a_denial() -> None:
    rules = _RuleProvider(_rule(security_id="OTHER.SECURITY"))
    markets = _MarketProvider(_market())
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=rules, market_evidence_provider=markets
    )

    result = use_case.execute(order=_order(), as_of=AS_OF)

    assert result.decision.status == "DENIED"
    assert result.decision.reason_codes


def test_mutated_owner_evidence_is_rejected_instead_of_issued() -> None:
    rule = _rule()
    object.__setattr__(rule, "price_tick", Decimal("0.1"))
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=_RuleProvider(rule), market_evidence_provider=_MarketProvider(_market())
    )

    with pytest.raises(ExecutionTradingEvidenceInvalid):
        use_case.execute(order=_order(), as_of=AS_OF)


def test_mutated_order_is_rejected_before_any_owner_read() -> None:
    order = _order()
    object.__setattr__(order, "quantity", Decimal("-1"))
    rules = _RuleProvider(None)
    markets = _MarketProvider(None)
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=rules, market_evidence_provider=markets
    )

    with pytest.raises(InvalidInputError):
        use_case.execute(order=order, as_of=AS_OF)

    assert rules.calls == markets.calls == []


def test_untyped_rule_owner_result_is_rejected_before_market_read() -> None:
    rules = _RuleProvider(cast(AShareExecutionRule, object()))
    markets = _MarketProvider(None)
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=rules, market_evidence_provider=markets
    )

    with pytest.raises(ExecutionTradingEvidenceInvalid):
        use_case.execute(order=_order(), as_of=AS_OF)

    assert markets.calls == []


def test_untyped_market_owner_result_cannot_be_issued() -> None:
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=_RuleProvider(_rule()),
        market_evidence_provider=_MarketProvider(cast(ExecutionMarketEvidence, object())),
    )

    with pytest.raises(ExecutionTradingEvidenceInvalid):
        use_case.execute(order=_order(), as_of=AS_OF)


def test_result_cannot_substitute_a_different_evidence_hash() -> None:
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=_RuleProvider(_rule()), market_evidence_provider=_MarketProvider(_market())
    )
    result = use_case.execute(order=_order(), as_of=AS_OF)
    forged = replace(result.decision, rule_content_hash="f" * 64)

    with pytest.raises(ExecutionTradingEvidenceInvalid):
        replace(result, decision=forged)


def test_serialization_revalidates_evidence_changed_after_evaluation() -> None:
    rule = _rule()
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=_RuleProvider(rule), market_evidence_provider=_MarketProvider(_market())
    )
    result = use_case.execute(order=_order(), as_of=AS_OF)
    object.__setattr__(rule, "content_hash", "f" * 64)

    with pytest.raises(ExecutionTradingEvidenceInvalid):
        result.to_payload()


@pytest.mark.parametrize(
    ("minimum", "step", "quantity"),
    [("100", "100", "200"), ("200", "1", "201")],
)
def test_domain_projection_is_accepted_by_the_independent_agent(
    minimum: str, step: str, quantity: str
) -> None:
    rule = replace(
        _rule(),
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal(minimum), step=Decimal(step), maximum=Decimal("10000")
        ),
        content_hash="",
    )
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=_RuleProvider(rule), market_evidence_provider=_MarketProvider(_market())
    )
    result = use_case.execute(order=replace(_order(), quantity=Decimal(quantity)), as_of=AS_OF)

    assert result.decision.status == "ALLOWED"
    validate_effective_constraints(result.to_payload(), submitted_at=AS_OF)


def test_agent_rechecks_expiry_after_a_valid_server_evaluation() -> None:
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=_RuleProvider(_rule()), market_evidence_provider=_MarketProvider(_market())
    )
    result = use_case.execute(order=_order(), as_of=AS_OF)

    assert result.decision.status == "ALLOWED"
    with pytest.raises(ExecutionConstraintViolation):
        validate_effective_constraints(
            result.to_payload(), submitted_at=AS_OF + timedelta(seconds=31)
        )


def test_agent_rejects_a_genuine_domain_denial() -> None:
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=_RuleProvider(_rule()), market_evidence_provider=_MarketProvider(_market())
    )
    result = use_case.execute(order=replace(_order(), quantity=Decimal("150")), as_of=AS_OF)

    assert result.decision.status == "DENIED"
    with pytest.raises(ExecutionConstraintViolation):
        validate_effective_constraints(result.to_payload(), submitted_at=AS_OF)


@pytest.mark.parametrize(
    ("available", "quantity", "allowed"),
    [
        ("150", "50", True),
        ("150", "150", True),
        ("150", "25", False),
        ("299", "99", True),
        ("299", "100", True),
        ("299", "199", True),
        ("299", "200", True),
        ("299", "299", True),
        ("299", "1", False),
        ("299", "101", False),
        ("299", "198", False),
        ("299", "298", False),
        ("500", "201", False),
    ],
)
def test_explicit_odd_remainder_rule_has_the_same_server_and_agent_result(
    available: str, quantity: str, allowed: bool
) -> None:
    rule = replace(
        _rule(),
        sell_odd_lot_mode=SellOddLotMode.SELL_ODD_REMAINDER_ONCE,
        content_hash="",
    )
    position = SellPositionEvidence(
        account_id=7,
        security_id="TEST.SECURITY",
        available_to_sell_quantity=Decimal(available),
        restricted_quantity=Decimal("0"),
        completeness=SellPositionCompleteness.COMPLETE,
        source_id="fixture-position",
        source_version="fixture-only",
        source_hash="d" * 64,
        observed_at=AS_OF - timedelta(seconds=1),
        available_at=AS_OF,
        valid_until=AS_OF + timedelta(seconds=30),
    )
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=_RuleProvider(rule), market_evidence_provider=_MarketProvider(_market())
    )
    result = use_case.execute(
        order=replace(
            _order(),
            side=ExecutionSide.SELL,
            quantity=Decimal(quantity),
            sell_position_evidence=position,
        ),
        as_of=AS_OF,
    )

    assert (result.decision.status == "ALLOWED") is allowed
    if allowed:
        validate_effective_constraints(result.to_payload(), submitted_at=AS_OF)
    else:
        with pytest.raises(ExecutionConstraintViolation):
            validate_effective_constraints(result.to_payload(), submitted_at=AS_OF)
        claimed_allowed = result.to_payload()
        decision_payload = cast(dict[str, object], claimed_allowed["decision"])
        decision_payload["status"] = "ALLOWED"
        decision_payload["reason_codes"] = []
        with pytest.raises(ExecutionConstraintViolation):
            validate_effective_constraints(claimed_allowed, submitted_at=AS_OF)


def test_published_wire_schema_covers_the_actual_nested_projection() -> None:
    position = SellPositionEvidence(
        account_id=7,
        security_id="TEST.SECURITY",
        available_to_sell_quantity=Decimal("300"),
        restricted_quantity=Decimal("0"),
        completeness=SellPositionCompleteness.COMPLETE,
        source_id="fixture-position",
        source_version="fixture-only",
        source_hash="d" * 64,
        observed_at=AS_OF - timedelta(seconds=1),
        available_at=AS_OF,
        valid_until=AS_OF + timedelta(seconds=30),
    )
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=_RuleProvider(_rule()), market_evidence_provider=_MarketProvider(_market())
    )
    payload = use_case.execute(
        order=replace(_order(), side=ExecutionSide.SELL, sell_position_evidence=position),
        as_of=AS_OF,
    ).to_payload()
    schema_path = (
        Path(__file__).resolve().parents[3]
        / "docs/api/a-share-execution-constraints-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    definitions = schema["$defs"]
    objects = (
        (schema, payload),
        (definitions["rule"], payload["rule"]),
        (definitions["marketEvidence"], payload["market_evidence"]),
        (definitions["order"], payload["order"]),
        (definitions["sellPositionEvidence"], position.to_payload()),
        (definitions["decision"], payload["decision"]),
        (definitions["quantityConstraint"], _rule().buy_quantity.to_payload()),
    )
    for contract, projection in objects:
        assert set(contract["properties"]) == set(contract["required"]) == set(projection)
        assert contract["additionalProperties"] is False
    assert set(definitions["decision"]["properties"]["reason_codes"]["items"]["enum"]) == {
        item.value for item in ExecutionDenyCode
    }
    assert set(definitions["rule"]["properties"]["sell_odd_lot_mode"]["enum"]) == {
        item.value for item in SellOddLotMode
    }
