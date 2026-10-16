"""Owner-read and integrity boundaries for the v2 execution submission query."""

import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from apps.risk_center.application.execution_submission_v2 import (
    EvaluateExecutionSubmissionV2UseCase,
)
from apps.risk_center.application.execution_trading_constraints import (
    ExecutionTradingEvidenceInvalid,
    ExecutionTradingEvidenceUnavailable,
)
from apps.risk_center.domain.execution_submission_v2 import (
    ExecutionSubmissionMarketV2,
    ExecutionSubmissionRuleV2,
    SubmissionV2DenyCode,
)
from apps.risk_center.domain.execution_trading_constraints import (
    ExecutionDenyCode,
    ExecutionSide,
    SellPositionCompleteness,
    SellPositionEvidence,
)
from apps.risk_center.domain.price_submission_range import (
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionStage,
    QuoteValue,
    QuoteValueState,
)
from core.exceptions import InvalidInputError
from tests.unit.risk_center.execution_constraints_factories import (
    AS_OF,
    execution_market,
    execution_order,
    execution_rule,
)


def _rule() -> ExecutionSubmissionRuleV2:
    base = execution_rule()
    return ExecutionSubmissionRuleV2(
        execution_rule_v1=base,
        price_submission_range=PriceSubmissionRangeRule(
            market=base.market,
            board=base.board,
            price_tick=base.price_tick,
            buy_deviation_ratio=Decimal("0.02"),
            sell_deviation_ratio=Decimal("0.02"),
            buy_widening_ticks=0,
            sell_widening_ticks=0,
            minimum_distance_ticks=1,
            lower_floor_ticks=1,
            rounding_mode=PriceRoundingMode.HALF_UP,
        ),
        allowed_stages=(PriceSubmissionStage.CONTINUOUS,),
    )


def _market() -> ExecutionSubmissionMarketV2:
    quote = QuoteValue(state=QuoteValueState.PRESENT, value=Decimal("10"))
    return ExecutionSubmissionMarketV2(
        market_evidence_v1=execution_market(),
        stage=PriceSubmissionStage.CONTINUOUS,
        ask=quote,
        bid=quote,
        latest=quote,
        previous_close=quote,
    )


class _Rules:
    def __init__(self, rule: ExecutionSubmissionRuleV2 | None) -> None:
        self.rule = rule
        self.calls: list[tuple[int, str, datetime]] = []

    def get_submission_rule(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> ExecutionSubmissionRuleV2 | None:
        self.calls.append((account_id, security_id, as_of))
        return self.rule


class _Markets:
    def __init__(self, market: ExecutionSubmissionMarketV2 | None) -> None:
        self.market = market
        self.calls: list[tuple[int, str, datetime]] = []

    def get_submission_market(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> ExecutionSubmissionMarketV2 | None:
        self.calls.append((account_id, security_id, as_of))
        return self.market


def test_v2_query_binds_both_owner_reads_and_preserves_nested_v1_hashes() -> None:
    rule, market = _rule(), _market()
    rules, markets = _Rules(rule), _Markets(market)
    result = EvaluateExecutionSubmissionV2UseCase(
        rule_provider=rules, market_provider=markets
    ).execute(order=execution_order(), as_of=AS_OF)
    payload = result.to_payload()

    assert rules.calls == markets.calls == [(7, "TEST.SECURITY", AS_OF)]
    assert payload["schema"] == "a-share-execution-constraints.v2"
    assert payload["as_of"] == "2026-10-16T02:00:00Z"
    assert set(payload) == {"schema", "as_of", "rule", "market_evidence", "order", "decision"}
    assert payload["rule"] == rule.to_payload()
    assert payload["market_evidence"] == market.to_payload()
    assert result.decision.status == "ALLOWED"
    assert result.decision.rule_content_hash == rule.content_hash
    assert result.decision.market_evidence_content_hash == market.content_hash
    assert rule.execution_rule_v1.content_hash == execution_rule().content_hash


def test_missing_v2_rule_does_not_read_market_or_fall_back_to_v1() -> None:
    rules, markets = _Rules(None), _Markets(_market())

    with pytest.raises(ExecutionTradingEvidenceUnavailable, match="rule"):
        EvaluateExecutionSubmissionV2UseCase(rule_provider=rules, market_provider=markets).execute(
            order=execution_order(), as_of=AS_OF
        )

    assert markets.calls == []


def test_v1_rule_cannot_impersonate_the_v2_owner_result() -> None:
    rules = _Rules(cast(ExecutionSubmissionRuleV2, execution_rule()))
    markets = _Markets(_market())

    with pytest.raises(ExecutionTradingEvidenceInvalid):
        EvaluateExecutionSubmissionV2UseCase(rule_provider=rules, market_provider=markets).execute(
            order=execution_order(), as_of=AS_OF
        )

    assert markets.calls == []


def test_missing_v2_market_has_a_stable_unavailable_error() -> None:
    with pytest.raises(ExecutionTradingEvidenceUnavailable, match="market"):
        EvaluateExecutionSubmissionV2UseCase(
            rule_provider=_Rules(_rule()), market_provider=_Markets(None)
        ).execute(order=execution_order(), as_of=AS_OF)


def test_v1_market_cannot_impersonate_the_v2_owner_result() -> None:
    with pytest.raises(ExecutionTradingEvidenceInvalid):
        EvaluateExecutionSubmissionV2UseCase(
            rule_provider=_Rules(_rule()),
            market_provider=_Markets(cast(ExecutionSubmissionMarketV2, execution_market())),
        ).execute(order=execution_order(), as_of=AS_OF)


def test_naive_cutoff_is_rejected_before_any_v2_owner_read() -> None:
    rules, markets = _Rules(None), _Markets(None)

    with pytest.raises(InvalidInputError):
        EvaluateExecutionSubmissionV2UseCase(rule_provider=rules, market_provider=markets).execute(
            order=execution_order(), as_of=AS_OF.replace(tzinfo=None)
        )

    assert rules.calls == markets.calls == []


def test_expired_v2_source_is_denied_without_retimestamping_it() -> None:
    market = _market()
    observed_at = market.market_evidence_v1.market_observed_at
    result = EvaluateExecutionSubmissionV2UseCase(
        rule_provider=_Rules(_rule()), market_provider=_Markets(market)
    ).execute(order=execution_order(), as_of=AS_OF + timedelta(seconds=31))

    assert result.decision.status == "DENIED"
    assert market.market_evidence_v1.market_observed_at == observed_at


def test_v2_cage_denial_is_not_masked_by_a_valid_daily_band() -> None:
    result = EvaluateExecutionSubmissionV2UseCase(
        rule_provider=_Rules(_rule()), market_provider=_Markets(_market())
    ).execute(order=replace(execution_order(), limit_price=Decimal("10.5")), as_of=AS_OF)

    assert result.decision.status == "DENIED"
    assert any(
        item.value == "LIMIT_PRICE_OUTSIDE_SUBMISSION_RANGE"
        for item in result.decision.reason_codes
    )


def test_v2_result_cannot_be_rebound_to_a_different_hash() -> None:
    result = EvaluateExecutionSubmissionV2UseCase(
        rule_provider=_Rules(_rule()), market_provider=_Markets(_market())
    ).execute(order=execution_order(), as_of=AS_OF)

    with pytest.raises(ExecutionTradingEvidenceInvalid):
        replace(result, decision=replace(result.decision, rule_content_hash="f" * 64))


def test_v2_serialization_revalidates_inputs_after_evaluation() -> None:
    market = _market()
    result = EvaluateExecutionSubmissionV2UseCase(
        rule_provider=_Rules(_rule()), market_provider=_Markets(market)
    ).execute(order=execution_order(), as_of=AS_OF)
    object.__setattr__(market, "content_hash", "f" * 64)

    with pytest.raises(ExecutionTradingEvidenceInvalid):
        result.to_payload()


def test_v2_schema_preserves_the_strict_nested_projection_and_reason_vocabulary() -> None:
    rule, market = _rule(), _market()
    payload = (
        EvaluateExecutionSubmissionV2UseCase(
            rule_provider=_Rules(rule), market_provider=_Markets(market)
        )
        .execute(order=execution_order(), as_of=AS_OF)
        .to_payload()
    )
    path = (
        Path(__file__).resolve().parents[3]
        / "docs/api/a-share-execution-constraints-v2.schema.json"
    )
    schema = json.loads(path.read_text(encoding="utf-8"))
    definitions = schema["$defs"]
    for definition, projection in (
        (schema, payload),
        (definitions["rule"], rule.to_payload()),
        (definitions["ruleV1"], rule.execution_rule_v1.to_payload()),
        (definitions["priceSubmissionRange"], rule.price_submission_range.to_payload()),
        (definitions["marketEvidence"], market.to_payload()),
        (definitions["marketEvidenceV1"], market.market_evidence_v1.to_payload()),
        (definitions["quoteValue"], market.ask.to_payload()),
        (definitions["order"], execution_order().to_payload()),
    ):
        assert set(definition["properties"]) == set(definition["required"]) == set(projection)
        assert definition["additionalProperties"] is False
    assert set(definitions["decision"]["properties"]["reason_codes"]["items"]["enum"]) == {
        item.value for item in (*ExecutionDenyCode, *SubmissionV2DenyCode)
    }
    assert set(definitions["marketEvidence"]["properties"]["stage"]["enum"]) == {
        item.value for item in PriceSubmissionStage
    }


def _position() -> SellPositionEvidence:
    return SellPositionEvidence(
        security_id="TEST.SECURITY",
        account_id=7,
        available_to_sell_quantity=Decimal("300"),
        restricted_quantity=Decimal("0"),
        completeness=SellPositionCompleteness.COMPLETE,
        source_id="synthetic-position-owner",
        source_version="fixture-only",
        source_hash="d" * 64,
        observed_at=AS_OF - timedelta(seconds=1),
        available_at=AS_OF,
        valid_until=AS_OF + timedelta(seconds=30),
    )


class _Positions:
    def __init__(self, position: SellPositionEvidence | None) -> None:
        self.position = position
        self.calls: list[tuple[int, str, datetime]] = []

    def get_sell_position(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> SellPositionEvidence | None:
        self.calls.append((account_id, security_id, as_of))
        return self.position


@pytest.mark.parametrize("side", [ExecutionSide.BUY, ExecutionSide.SELL])
def test_v2_caller_position_evidence_cannot_impersonate_the_position_owner(
    side: ExecutionSide,
) -> None:
    rules, markets = _Rules(_rule()), _Markets(_market())
    order = replace(execution_order(), side=side, sell_position_evidence=_position())

    with pytest.raises(InvalidInputError, match="position"):
        EvaluateExecutionSubmissionV2UseCase(rule_provider=rules, market_provider=markets).execute(
            order=order, as_of=AS_OF
        )

    assert rules.calls == markets.calls == []


def test_v2_sell_without_a_position_owner_has_no_caller_or_zero_balance_fallback() -> None:
    markets = _Markets(_market())
    with pytest.raises(ExecutionTradingEvidenceUnavailable, match="position"):
        EvaluateExecutionSubmissionV2UseCase(
            rule_provider=_Rules(_rule()), market_provider=markets
        ).execute(order=replace(execution_order(), side=ExecutionSide.SELL), as_of=AS_OF)
    assert markets.calls == []


def test_v2_sell_binds_all_owner_reads_and_preserves_original_position_source() -> None:
    rules, markets, positions = _Rules(_rule()), _Markets(_market()), _Positions(_position())
    intent = replace(execution_order(), side=ExecutionSide.SELL)
    result = EvaluateExecutionSubmissionV2UseCase(
        rule_provider=rules, market_provider=markets, position_provider=positions
    ).execute(order=intent, as_of=AS_OF)

    assert rules.calls == markets.calls == positions.calls == [(7, "TEST.SECURITY", AS_OF)]
    assert result.decision.status == "ALLOWED"
    assert intent.sell_position_evidence is None
    assert result.order.sell_position_evidence == positions.position
    assert result.to_payload()["order"]["sell_position_evidence"] == _position().to_payload()


def test_v2_buy_does_not_read_sell_positions() -> None:
    positions = _Positions(None)
    result = EvaluateExecutionSubmissionV2UseCase(
        rule_provider=_Rules(_rule()),
        market_provider=_Markets(_market()),
        position_provider=positions,
    ).execute(order=execution_order(), as_of=AS_OF)
    assert result.decision.status == "ALLOWED"
    assert result.order.sell_position_evidence is None
    assert positions.calls == []


@pytest.mark.parametrize(
    "position",
    [
        None,
        replace(_position(), account_id=8),
        replace(_position(), security_id="OTHER.SECURITY"),
        cast(SellPositionEvidence, {"available_to_sell_quantity": "300"}),
    ],
)
def test_v2_position_owner_requires_exact_account_and_security(
    position: SellPositionEvidence | None,
) -> None:
    markets = _Markets(_market())
    error = (
        ExecutionTradingEvidenceUnavailable if position is None else ExecutionTradingEvidenceInvalid
    )
    with pytest.raises(error, match="position"):
        EvaluateExecutionSubmissionV2UseCase(
            rule_provider=_Rules(_rule()),
            market_provider=markets,
            position_provider=_Positions(position),
        ).execute(order=replace(execution_order(), side=ExecutionSide.SELL), as_of=AS_OF)
    assert markets.calls == []


def test_v2_missing_rule_does_not_read_position_owner() -> None:
    positions, markets = _Positions(_position()), _Markets(_market())
    with pytest.raises(ExecutionTradingEvidenceUnavailable, match="rule"):
        EvaluateExecutionSubmissionV2UseCase(
            rule_provider=_Rules(None), market_provider=markets, position_provider=positions
        ).execute(order=replace(execution_order(), side=ExecutionSide.SELL), as_of=AS_OF)
    assert positions.calls == markets.calls == []


@pytest.mark.parametrize(
    ("position", "reason"),
    [
        (
            replace(
                _position(),
                observed_at=AS_OF - timedelta(seconds=3),
                available_at=AS_OF - timedelta(seconds=2),
                valid_until=AS_OF,
            ),
            "POSITION_EVIDENCE_EXPIRED",
        ),
        (
            replace(
                _position(),
                observed_at=AS_OF + timedelta(seconds=1),
                available_at=AS_OF + timedelta(seconds=1),
            ),
            "POSITION_EVIDENCE_NOT_YET_AVAILABLE",
        ),
        (
            replace(_position(), available_to_sell_quantity=Decimal("100")),
            "SELLABLE_BALANCE_INSUFFICIENT",
        ),
        (
            replace(_position(), completeness=SellPositionCompleteness.INCOMPLETE),
            "POSITION_EVIDENCE_INCOMPLETE",
        ),
    ],
)
def test_v2_position_owner_cannot_bypass_existing_domain_constraints(
    position: SellPositionEvidence, reason: str
) -> None:
    result = EvaluateExecutionSubmissionV2UseCase(
        rule_provider=_Rules(_rule()),
        market_provider=_Markets(_market()),
        position_provider=_Positions(position),
    ).execute(order=replace(execution_order(), side=ExecutionSide.SELL), as_of=AS_OF)
    assert result.decision.status == "DENIED"
    assert reason in {item.value for item in result.decision.reason_codes}
    assert result.order.sell_position_evidence == position


def test_v2_position_owner_revalidates_an_object_mutated_after_construction() -> None:
    position = _position()
    object.__setattr__(position, "available_to_sell_quantity", Decimal("NaN"))
    markets = _Markets(_market())
    with pytest.raises(ExecutionTradingEvidenceInvalid, match="position"):
        EvaluateExecutionSubmissionV2UseCase(
            rule_provider=_Rules(_rule()),
            market_provider=markets,
            position_provider=_Positions(position),
        ).execute(order=replace(execution_order(), side=ExecutionSide.SELL), as_of=AS_OF)
    assert markets.calls == []
