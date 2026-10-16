"""Strict decoding and use-case contracts for operator-owned v2 rules."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest

from apps.risk_center.application.ashare_execution_rule_v2_catalog import (
    ImportAShareExecutionSubmissionRulesUseCase,
    ReadEffectiveAShareExecutionSubmissionRuleUseCase,
)
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionQuantityConstraint,
    SellOddLotMode,
)
from apps.risk_center.domain.price_submission_range import (
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionStage,
)
from apps.risk_center.infrastructure.ashare_execution_rule_v2_codec import (
    ASHARE_EXECUTION_RULES_V2_SCHEMA,
    AShareExecutionRuleV2CodecError,
    parse_a_share_execution_rule_v2_manifest,
)
from apps.risk_center.management.commands import import_a_share_execution_rules as import_command

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)


def _rule_v1() -> AShareExecutionRule:
    return AShareExecutionRule(
        rule_id="v2-catalog-rule",
        rule_version="1",
        security_id="V2.CATALOG.SECURITY",
        market="SH",
        board="MAIN",
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("10000")
        ),
        sell_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("10000")
        ),
        sell_odd_lot_mode=SellOddLotMode.FORBID,
        price_tick=Decimal("0.01"),
        rule_source_id="synthetic-source",
        rule_source_version="fixture-v1",
        rule_source_hash="a" * 64,
        source_observed_at=AS_OF - timedelta(days=1),
        source_available_at=AS_OF - timedelta(hours=1),
        effective_from=AS_OF - timedelta(minutes=30),
        valid_until=AS_OF + timedelta(days=1),
    )


def _rule_v2() -> ExecutionSubmissionRuleV2:
    return ExecutionSubmissionRuleV2(
        execution_rule_v1=_rule_v1(),
        price_submission_range=PriceSubmissionRangeRule(
            market="SH",
            board="MAIN",
            price_tick=Decimal("0.01"),
            buy_deviation_ratio=Decimal("0.02"),
            sell_deviation_ratio=Decimal("0.02"),
            buy_widening_ticks=10,
            sell_widening_ticks=10,
            minimum_distance_ticks=1,
            lower_floor_ticks=1,
            rounding_mode=PriceRoundingMode.HALF_UP,
        ),
        allowed_stages=(PriceSubmissionStage.CONTINUOUS,),
    )


def _manifest_payload(rule: ExecutionSubmissionRuleV2) -> dict[str, object]:
    return {"schema": ASHARE_EXECUTION_RULES_V2_SCHEMA, "rules": [rule.to_payload()]}


def _manifest_text(rule: ExecutionSubmissionRuleV2) -> str:
    return json.dumps(_manifest_payload(rule), ensure_ascii=False, separators=(",", ":"))


def _reseal_rule_payload(payload: dict[str, object]) -> None:
    content = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    payload["content_hash"] = hashlib.sha256(encoded).hexdigest()


def test_v2_manifest_round_trip_preserves_exact_nested_and_outer_hashes() -> None:
    rule = _rule_v2()

    parsed = parse_a_share_execution_rule_v2_manifest(_manifest_text(rule))

    assert parsed == (rule,)
    assert parsed[0].execution_rule_v1.content_hash == rule.execution_rule_v1.content_hash
    assert parsed[0].content_hash == rule.content_hash


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["rules"][0].update(unexpected="value"),
        lambda payload: payload["rules"][0].pop("allowed_stages"),
        lambda payload: payload["rules"][0]["price_submission_range"].update(
            unknown_price_setting="value"
        ),
        lambda payload: payload["rules"][0]["allowed_stages"].append("OPENING_AUCTION"),
    ],
)
def test_v2_manifest_rejects_unknown_missing_or_unsupported_fields(mutate) -> None:
    payload = json.loads(_manifest_text(_rule_v2()))
    mutate(payload)

    with pytest.raises(AShareExecutionRuleV2CodecError):
        parse_a_share_execution_rule_v2_manifest(json.dumps(payload))


def test_v2_manifest_rejects_noncanonical_decimal_even_with_recomputed_outer_hash() -> None:
    payload = json.loads(_manifest_text(_rule_v2()))
    rule_payload = payload["rules"][0]
    rule_payload["price_submission_range"]["price_tick"] = "0.010"
    _reseal_rule_payload(rule_payload)

    with pytest.raises(AShareExecutionRuleV2CodecError):
        parse_a_share_execution_rule_v2_manifest(json.dumps(payload))


def test_v2_manifest_rejects_duplicate_nested_keys_and_nonfinite_json() -> None:
    manifest_text = _manifest_text(_rule_v2())
    duplicate_text = manifest_text.replace('"market":"SH"', '"market":"SH","market":"SH"', 1)

    with pytest.raises(AShareExecutionRuleV2CodecError, match="duplicate"):
        parse_a_share_execution_rule_v2_manifest(duplicate_text)
    with pytest.raises(AShareExecutionRuleV2CodecError):
        parse_a_share_execution_rule_v2_manifest(
            manifest_text.replace('"buy_widening_ticks":10', '"buy_widening_ticks":NaN')
        )


def test_v2_manifest_rejects_a_mixed_v1_and_v2_batch() -> None:
    payload = _manifest_payload(_rule_v2())
    payload["rules"] = [_rule_v1().to_payload()]

    with pytest.raises(AShareExecutionRuleV2CodecError):
        parse_a_share_execution_rule_v2_manifest(json.dumps(payload))


class _Catalog:
    def __init__(self, rule: ExecutionSubmissionRuleV2) -> None:
        self.rule = rule
        self.imported: tuple[ExecutionSubmissionRuleV2, ...] | None = None
        self.read_request: tuple[str, datetime] | None = None

    def import_submission_rules(self, *, rules: tuple[ExecutionSubmissionRuleV2, ...]) -> object:
        self.imported = rules
        return object()

    def get_effective_submission_rule(
        self, *, security_id: str, as_of: datetime
    ) -> ExecutionSubmissionRuleV2:
        self.read_request = (security_id, as_of)
        return self.rule


def test_v2_use_cases_delegate_exact_rules_and_knowledge_cutoff() -> None:
    rule = _rule_v2()
    catalog = _Catalog(rule)

    imported = ImportAShareExecutionSubmissionRulesUseCase(catalog).execute(rules=(rule,))
    read = ReadEffectiveAShareExecutionSubmissionRuleUseCase(catalog).execute(
        security_id=rule.execution_rule_v1.security_id,
        as_of=AS_OF,
    )

    assert imported is not None
    assert catalog.imported == (rule,)
    assert read == rule
    assert catalog.read_request == (rule.execution_rule_v1.security_id, AS_OF)


def test_import_command_dispatches_v2_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule = _rule_v2()
    manifest_path = tmp_path / "rules.json"
    manifest_path.write_text(_manifest_text(rule), encoding="utf-8")
    repository = object()
    captured: dict[str, object] = {}

    class _UseCase:
        def __init__(self, actual_repository: object) -> None:
            captured["repository"] = actual_repository

        def execute(self, *, rules: tuple[ExecutionSubmissionRuleV2, ...]) -> object:
            captured["rules"] = rules
            return type("ImportResult", (), {"inserted_count": 1, "unchanged_count": 0})()

    monkeypatch.setattr(import_command, "DjangoAShareExecutionRuleRepository", lambda: repository)
    monkeypatch.setattr(import_command, "ImportAShareExecutionSubmissionRulesUseCase", _UseCase)
    command = import_command.Command()
    command.stdout = StringIO()

    command.handle(manifest=str(manifest_path))

    assert captured == {"repository": repository, "rules": (rule,)}
    assert "does not authorize trading" in command.stdout.getvalue()


def test_import_command_preserves_v1_schema_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule = _rule_v1()
    manifest_path = tmp_path / "rules-v1.json"
    manifest_path.write_text(
        json.dumps(
            {"schema": "a-share-execution-rules.v1", "rules": [rule.to_payload()]},
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    repository = object()
    captured: dict[str, object] = {}

    class _UseCase:
        def __init__(self, actual_repository: object) -> None:
            captured["repository"] = actual_repository

        def execute(self, *, rules: tuple[AShareExecutionRule, ...]) -> object:
            captured["rules"] = rules
            return type("ImportResult", (), {"inserted_count": 0, "unchanged_count": 1})()

    monkeypatch.setattr(import_command, "DjangoAShareExecutionRuleRepository", lambda: repository)
    monkeypatch.setattr(import_command, "ImportAShareExecutionRulesUseCase", _UseCase)
    command = import_command.Command()
    command.stdout = StringIO()

    command.handle(manifest=str(manifest_path))

    assert captured == {"repository": repository, "rules": (rule,)}
    assert "inserted=0, unchanged=1" in command.stdout.getvalue()
