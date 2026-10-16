"""Application and wire-contract tests for Risk-owned A-share rules."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.risk_center.application.ashare_execution_rule_catalog import (
    ExecutionRuleInputError,
    ImportAShareExecutionRulesUseCase,
    ReadEffectiveAShareExecutionRuleUseCase,
)
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionQuantityConstraint,
    SellOddLotMode,
)
from apps.risk_center.infrastructure.ashare_execution_rule_codec import (
    ASHARE_EXECUTION_RULES_SCHEMA,
    AShareExecutionRuleCodecError,
    parse_a_share_execution_rule_manifest,
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)


def _rule() -> AShareExecutionRule:
    return AShareExecutionRule(
        rule_id="unit-rule",
        rule_version="v1",
        security_id="UNIT.SECURITY",
        market="fixture-market",
        board="fixture-board",
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("10000")
        ),
        sell_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("10000")
        ),
        sell_odd_lot_mode=SellOddLotMode.FORBID,
        price_tick=Decimal("0.01"),
        rule_source_id="unit-source",
        rule_source_version="v1",
        rule_source_hash="a" * 64,
        source_observed_at=AS_OF - timedelta(days=1),
        source_available_at=AS_OF - timedelta(days=1),
        effective_from=AS_OF - timedelta(hours=1),
        valid_until=AS_OF + timedelta(days=1),
    )


class _Repository:
    def __init__(self, value: AShareExecutionRule) -> None:
        self.value = value
        self.imported: tuple[AShareExecutionRule, ...] | None = None
        self.read_request: tuple[str, datetime] | None = None

    def import_rules(self, *, rules: tuple[AShareExecutionRule, ...]):
        self.imported = rules
        return object()

    def get_effective_rule(self, *, security_id: str, as_of: datetime) -> AShareExecutionRule:
        self.read_request = (security_id, as_of)
        return self.value


def _manifest_text(rule: AShareExecutionRule) -> str:
    return json.dumps(
        {"schema": ASHARE_EXECUTION_RULES_SCHEMA, "rules": [rule.to_payload()]},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def test_manifest_round_trip_preserves_exact_typed_rule() -> None:
    rule = _rule()

    parsed = parse_a_share_execution_rule_manifest(_manifest_text(rule))

    assert parsed == (rule,)


def test_manifest_rejects_duplicate_json_keys() -> None:
    text = _manifest_text(_rule()).replace(
        '"schema":"a-share-execution-rules.v1"',
        '"schema":"a-share-execution-rules.v1","schema":"a-share-execution-rules.v1"',
    )

    with pytest.raises(AShareExecutionRuleCodecError, match="duplicate"):
        parse_a_share_execution_rule_manifest(text)


def test_manifest_rejects_payload_changed_without_resealing_hash() -> None:
    payload = json.loads(_manifest_text(_rule()))
    payload["rules"][0]["board"] = "tampered-board"

    with pytest.raises(AShareExecutionRuleCodecError):
        parse_a_share_execution_rule_manifest(json.dumps(payload))


def test_manifest_rejects_oversized_decimal_before_decimal_construction() -> None:
    payload = json.loads(_manifest_text(_rule()))
    payload["rules"][0]["price_tick"] = "1" * 258

    with pytest.raises(AShareExecutionRuleCodecError, match="text bound"):
        parse_a_share_execution_rule_manifest(json.dumps(payload))


def test_use_cases_pass_exact_typed_rules_and_knowledge_cutoff() -> None:
    rule = _rule()
    repository = _Repository(rule)

    imported = ImportAShareExecutionRulesUseCase(repository).execute(rules=(rule,))
    read = ReadEffectiveAShareExecutionRuleUseCase(repository).execute(
        security_id=rule.security_id,
        as_of=AS_OF,
    )

    assert imported is not None
    assert repository.imported == (rule,)
    assert read == rule
    assert repository.read_request == (rule.security_id, AS_OF)


def test_import_use_case_rejects_empty_batch_before_repository_call() -> None:
    repository = _Repository(_rule())

    with pytest.raises(ExecutionRuleInputError):
        ImportAShareExecutionRulesUseCase(repository).execute(rules=())

    assert repository.imported is None
