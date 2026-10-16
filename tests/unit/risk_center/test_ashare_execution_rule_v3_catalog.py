"""Application and command contracts for operator-supplied v3 bundles."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest
from django.core.management.base import CommandError

from apps.risk_center.application.ashare_execution_rule_catalog import (
    ExecutionRuleImportResult,
    ExecutionRuleInputError,
)
from apps.risk_center.application.ashare_execution_rule_v3_catalog import (
    ImportAShareExecutionSettlementRulesV3UseCase,
)
from apps.risk_center.application.execution_settlement_v3 import (
    ExecutionSettlementV3ReadRecord,
)
from apps.risk_center.domain.execution_settlement_v3 import (
    ExecutionSettlementBundleV3,
    SettlementBasis,
    SettlementPolicyV1,
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
from apps.risk_center.infrastructure.ashare_execution_rule_v3_codec import (
    ASHARE_EXECUTION_RULES_V3_SCHEMA,
)
from apps.risk_center.management.commands import import_a_share_execution_rules as import_command

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)


def _bundle() -> ExecutionSettlementBundleV3:
    base = AShareExecutionRule(
        rule_id="catalog-v3-nested-rule",
        rule_version="1",
        security_id="V3.CATALOG.SECURITY",
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
        rule_source_id="catalog-source",
        rule_source_version="2026-10",
        rule_source_hash="a" * 64,
        source_observed_at=AS_OF - timedelta(days=1),
        source_available_at=AS_OF - timedelta(hours=2),
        effective_from=AS_OF - timedelta(hours=1),
        valid_until=AS_OF + timedelta(hours=1),
    )
    nested = ExecutionSubmissionRuleV2(
        execution_rule_v1=base,
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
    policy = SettlementPolicyV1(
        policy_id="catalog-policy",
        policy_version="1",
        security_id=base.security_id,
        market=base.market,
        board=base.board,
        settlement_basis=SettlementBasis.CN_OPEN_MARKET_SESSIONS,
        settlement_lag_sessions=1,
        bound_execution_rule_v2_hash=nested.content_hash,
        source_id="settlement-source",
        source_version="2026-10",
        source_hash="b" * 64,
        source_observed_at=AS_OF - timedelta(days=1),
        source_available_at=AS_OF - timedelta(hours=1),
        effective_from=base.effective_from,
        valid_until=base.valid_until,
    )
    return ExecutionSettlementBundleV3(
        bundle_id="catalog-package",
        bundle_version="1",
        execution_submission_v2=nested,
        settlement_policy_v1=policy,
    )


class _Catalog:
    def __init__(self) -> None:
        self.imported: tuple[ExecutionSettlementBundleV3, ...] | None = None

    def import_settlement_bundles(
        self, *, bundles: tuple[ExecutionSettlementBundleV3, ...]
    ) -> ExecutionRuleImportResult:
        self.imported = bundles
        return ExecutionRuleImportResult(inserted_count=len(bundles), unchanged_count=0)

    def get_effective_settlement_bundle(
        self, *, security_id: str, as_of: datetime
    ) -> ExecutionSettlementV3ReadRecord | None:
        return None


def test_v3_import_use_case_delegates_exact_immutable_bundle_batch() -> None:
    bundle = _bundle()
    catalog = _Catalog()

    result = ImportAShareExecutionSettlementRulesV3UseCase(catalog).execute(bundles=(bundle,))

    assert result == ExecutionRuleImportResult(inserted_count=1, unchanged_count=0)
    assert catalog.imported == (bundle,)


def test_v3_import_use_case_rejects_an_empty_batch() -> None:
    with pytest.raises(ExecutionRuleInputError):
        ImportAShareExecutionSettlementRulesV3UseCase(_Catalog()).execute(bundles=())


def test_command_dispatches_explicit_v3_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle()
    path = tmp_path / "rules-v3.json"
    path.write_text(
        json.dumps(
            {"schema": ASHARE_EXECUTION_RULES_V3_SCHEMA, "rules": [bundle.to_payload()]},
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    repository = object()
    captured: dict[str, object] = {}

    class _UseCase:
        def __init__(self, actual_repository: object) -> None:
            captured["repository"] = actual_repository

        def execute(
            self, *, bundles: tuple[ExecutionSettlementBundleV3, ...]
        ) -> ExecutionRuleImportResult:
            captured["bundles"] = bundles
            return ExecutionRuleImportResult(inserted_count=1, unchanged_count=0)

    monkeypatch.setattr(import_command, "DjangoAShareExecutionRuleRepository", lambda: repository)
    monkeypatch.setattr(import_command, "ImportAShareExecutionSettlementRulesV3UseCase", _UseCase)
    command = import_command.Command()
    command.stdout = StringIO()

    command.handle(manifest=str(path))

    assert captured == {"repository": repository, "bundles": (bundle,)}
    assert "inserted=1, unchanged=0" in command.stdout.getvalue()
    assert "does not authorize trading" in command.stdout.getvalue()


def test_command_rejects_v2_payload_under_v3_manifest_without_downgrade(
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    path = tmp_path / "mixed-v3.json"
    path.write_text(
        json.dumps(
            {
                "schema": ASHARE_EXECUTION_RULES_V3_SCHEMA,
                "rules": [bundle.execution_submission_v2.to_payload()],
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    with pytest.raises(CommandError):
        import_command.Command().handle(manifest=str(path))
