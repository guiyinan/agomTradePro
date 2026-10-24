"""Contract tests for the read-only ASH-03 historical sellability report."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, localcontext
from io import StringIO
from typing import Protocol, cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.utils import timezone

from apps.account.application.historical_position_source import ReadLegacyPortfolioPositions
from apps.account.infrastructure.historical_position_source_repository import (
    DjangoLegacyPortfolioPositionRepository,
)
from apps.account.infrastructure.portfolio_models import PortfolioModel, PositionModel
from apps.simulated_trading.historical_sellable_difference_composition import (
    build_historical_sellable_difference_service,
)
from apps.simulated_trading.infrastructure import models as simulated_models
from apps.simulated_trading.infrastructure.models import (
    LedgerMigrationMapModel,
    SimulatedAccountModel,
)
from core.exceptions import InvalidInputError

pytestmark = pytest.mark.django_db

REPORT_COMMAND = "report_historical_sellable_differences"


class _SqlExecutor(Protocol):
    """The Django cursor executor signature consumed by an execute wrapper."""

    def __call__(
        self,
        sql: str,
        params: object,
        many: bool,
        context: dict[str, object],
    ) -> object:
        """Execute the supplied SQL and return the driver's result."""


class _SqlExecuteWrapper(Protocol):
    """The callable contract accepted by Django's connection wrapper API."""

    def __call__(
        self,
        execute: _SqlExecutor,
        sql: str,
        params: object,
        many: bool,
        context: dict[str, object],
    ) -> object:
        """Observe SQL before forwarding it to Django's actual executor."""


class _SeededPosition:
    """Concrete private fixture values without exposing ORM to the report API."""

    def __init__(
        self,
        *,
        owner: User,
        portfolio: PortfolioModel,
        source_position: PositionModel,
        account: SimulatedAccountModel,
        target_position: simulated_models.PositionModel,
        portfolio_map: LedgerMigrationMapModel,
        position_map: LedgerMigrationMapModel,
    ) -> None:
        self.owner = owner
        self.portfolio = portfolio
        self.source_position = source_position
        self.account = account
        self.target_position = target_position
        self.portfolio_map = portfolio_map
        self.position_map = position_map


def _new_user(label: str) -> User:
    """Create an isolated authenticated identity for the ORM fixture."""

    return User._default_manager.create_user(username=f"ash03-g5-{label}-{uuid4().hex}")


def _new_account(owner: User, label: str) -> SimulatedAccountModel:
    """Create a quantity-only target account with no certified cash balance."""

    return SimulatedAccountModel._default_manager.create(
        user=owner,
        account_name=f"ASH03 G5 {label}",
        account_type="real",
        initial_capital=Decimal("0.00"),
        current_cash=Decimal("0.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("0.00"),
        cash_reconciliation_status="quantity_only",
        auto_trading_enabled=False,
    )


def _new_source_position(
    portfolio: PortfolioModel,
    *,
    asset_code: str = "600000.SH",
    shares: float = 300.0,
) -> PositionModel:
    """Create one legacy quantity row; it has no source sellable field."""

    return PositionModel._default_manager.create(
        portfolio=portfolio,
        asset_code=asset_code,
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=shares,
        avg_cost=Decimal("10.0000"),
        current_price=Decimal("10.0000"),
        market_value=Decimal("3000.00"),
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        source="manual",
        is_closed=False,
    )


def _new_target_position(
    account: SimulatedAccountModel,
    *,
    asset_code: str = "600000.SH",
    quantity: Decimal = Decimal("300.000000"),
    available_quantity: Decimal = Decimal("100.000000"),
    available_quantity_known: bool = True,
) -> simulated_models.PositionModel:
    """Create a mapped unified position with independently stored sellable data."""

    return simulated_models.PositionModel._default_manager.create(
        account=account,
        asset_code=asset_code,
        asset_name="Fixture security",
        asset_type="equity",
        quantity=quantity,
        available_quantity=available_quantity,
        available_quantity_known=available_quantity_known,
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("3000.00"),
        current_price=Decimal("10.0000"),
        market_value=Decimal("3000.00"),
        first_buy_date=date(2026, 9, 29),
        first_buy_date_known=False,
    )


def _seed_position_case(
    *,
    label: str = "base",
    source_shares: float = 300.0,
    target_quantity: Decimal = Decimal("300.000000"),
    available_quantity: Decimal = Decimal("100.000000"),
    available_quantity_known: bool = True,
    asset_code: str = "600000.SH",
) -> _SeededPosition:
    """Create a source portfolio and exact forward account/position mappings."""

    owner = _new_user(label)
    portfolio = PortfolioModel._default_manager.create(
        user=owner,
        name=f"ASH03 G5 source {label}",
    )
    source_position = _new_source_position(
        portfolio,
        asset_code=asset_code,
        shares=source_shares,
    )
    account = _new_account(owner, label)
    target_position = _new_target_position(
        account,
        asset_code=asset_code,
        quantity=target_quantity,
        available_quantity=available_quantity,
        available_quantity_known=available_quantity_known,
    )
    portfolio_map = LedgerMigrationMapModel._default_manager.create(
        source_app="account",
        source_table="portfolio",
        source_id=portfolio.pk,
        target_table="simulated_account",
        target_id=account.pk,
    )
    position_map = LedgerMigrationMapModel._default_manager.create(
        source_app="account",
        source_table="position",
        source_id=source_position.pk,
        target_table="simulated_position",
        target_id=target_position.pk,
    )
    return _SeededPosition(
        owner=owner,
        portfolio=portfolio,
        source_position=source_position,
        account=account,
        target_position=target_position,
        portfolio_map=portfolio_map,
        position_map=position_map,
    )


def _run_report(*, user_id: int, account_id: int) -> dict[str, object]:
    """Call the documented read-only command and parse its only stdout value."""

    stdout = StringIO()
    call_command(
        REPORT_COMMAND,
        user_id=user_id,
        account_id=account_id,
        stdout=stdout,
    )
    value: object = json.loads(stdout.getvalue())
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _rows(report: dict[str, object]) -> list[dict[str, object]]:
    """Return the report rows after validating the public JSON container shape."""

    value = report.get("rows")
    assert isinstance(value, list)
    assert all(isinstance(row, dict) for row in value)
    return [cast(dict[str, object], row) for row in value]


def _row_for_source(report: dict[str, object], source_position_id: int) -> dict[str, object]:
    """Select one report row by the requested owner's exact legacy position ID."""

    matches = [row for row in _rows(report) if row.get("source_position_id") == source_position_id]
    assert len(matches) == 1
    return matches[0]


def _assert_read_only_report(report: dict[str, object], *, owner_id: int, account_id: int) -> None:
    """Require a machine-only report that explicitly denies execution authority."""

    assert report["report_kind"] == "ash03.historical_sellable_difference.v1"
    assert report["read_only"] is True
    assert report["must_not_execute"] is True
    assert report["must_not_use_for_decision"] is True
    assert report["repair_ready"] is False
    assert report["settled"] is False
    assert report["consistent_snapshot"] is False
    assert report["source_database_alias"] == "default"
    assert report["target_database_alias"] == "default"
    assert isinstance(report["reported_at"], str)
    assert report["owner_user_id"] == owner_id
    assert report["account_id"] == account_id


@pytest.mark.parametrize(
    "available_quantity_known",
    [pytest.param(True, id="known-is-not-proof"), pytest.param(False, id="unknown-retained")],
)
def test_stored_sellable_quantity_never_substitutes_for_public_settlement_proof(
    available_quantity_known: bool,
) -> None:
    """A stored 100 or known flag cannot turn 300 total shares into supported evidence."""

    case = _seed_position_case(
        available_quantity_known=available_quantity_known,
        label="stored-available",
    )

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    _assert_read_only_report(report, owner_id=case.owner.pk, account_id=case.account.pk)
    row = _row_for_source(report, case.source_position.pk)
    assert row["asset_code"] == "600000.SH"
    assert row["source_asset_code"] == "600000.SH"
    assert row["source_total_quantity"] == "300.000000"
    assert row["target_total_quantity"] == "300.000000"
    assert row["stored_available_quantity"] == "100.000000"
    assert row["stored_available_quantity_known"] is available_quantity_known
    assert row["supported_sellable_quantity"] is None
    assert row["requires_reconciliation"] is True
    assert row["source_observed_at"] is None
    assert row["legacy_record_updated_at"] is not None
    reason_codes = row.get("reason_codes")
    assert isinstance(reason_codes, list)
    assert "SETTLEMENT_EVIDENCE_UNAVAILABLE" in reason_codes


def test_report_uses_exact_decimal_strings_and_preserves_difference_at_low_context() -> None:
    """Share comparison must not round through float or inherit a low Decimal context."""

    case = _seed_position_case(
        source_shares=300.123456,
        target_quantity=Decimal("100.000001"),
        label="decimal-delta",
    )

    with localcontext() as decimal_context:
        decimal_context.prec = 2
        report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    row = _row_for_source(report, case.source_position.pk)
    assert row["source_total_quantity"] == "300.123456"
    assert row["target_total_quantity"] == "100.000001"
    assert row["total_quantity_difference"] == "200.123455"
    assert isinstance(row["source_total_quantity"], str)
    assert isinstance(row["target_total_quantity"], str)
    assert row["supported_sellable_quantity"] is None


def test_unrepresentable_legacy_float_quantity_stays_unknown_instead_of_rounding() -> None:
    """A legacy FloatField value beyond six decimal places must remain unresolved."""

    case = _seed_position_case(
        source_shares=300.0000004,
        label="unrepresentable-quantity",
    )

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    row = _row_for_source(report, case.source_position.pk)
    assert row["source_total_quantity"] is None
    assert row["source_quantity_known"] is False
    assert row["supported_sellable_quantity"] is None
    assert row["requires_reconciliation"] is True
    reason_codes = row.get("reason_codes")
    assert isinstance(reason_codes, list)
    assert "SOURCE_QUANTITY_PRECISION_UNSUPPORTED" in reason_codes


def test_closed_legacy_position_is_retained_but_never_claimed_currently_sellable() -> None:
    """A closed source row is visible as history, not dropped or treated as current."""

    case = _seed_position_case(label="closed-source-row")
    case.source_position.is_closed = True
    case.source_position.save(update_fields=["is_closed"])

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    row = _row_for_source(report, case.source_position.pk)
    assert row["source_position_closed"] is True
    assert "SOURCE_POSITION_CLOSED" in row["reason_codes"]
    assert row["source_total_quantity"] == "300.000000"
    assert row["supported_sellable_quantity"] is None


def test_database_router_mismatch_fails_closed_before_orm_queries() -> None:
    """Both App repositories refuse a configured route outside the requested alias."""

    source_reader = ReadLegacyPortfolioPositions(DjangoLegacyPortfolioPositionRepository())
    with patch(
        "apps.account.infrastructure.historical_position_source_repository.router.db_for_read",
        return_value="archive",
    ):
        source_read = source_reader.read(
            user_id=1,
            portfolio_id=1,
            database_alias="default",
        )
    assert source_read.status == "database_route_mismatch"

    service = build_historical_sellable_difference_service()
    with patch(
        "apps.simulated_trading.infrastructure.historical_sellable_difference_repository.router.db_for_read",
        return_value="archive",
    ):
        report = service.build_report(
            user_id=1,
            account_id=1,
            database_alias="default",
            reported_at=timezone.now(),
        )
    assert report.scope_status == "blocked"
    assert report.reason_codes == ("DATABASE_ROUTER_ALIAS_MISMATCH",)
    assert report.rows == ()


def test_application_rejects_boolean_identifiers_and_naive_report_time() -> None:
    """The Application contract is strict even when callers bypass CLI parsing."""

    service = build_historical_sellable_difference_service()
    with pytest.raises(InvalidInputError):
        service.build_report(
            user_id=True,
            account_id=1,
            database_alias="default",
            reported_at=timezone.now(),
        )
    with pytest.raises(InvalidInputError):
        service.build_report(
            user_id=1,
            account_id=1,
            database_alias="default",
            reported_at=datetime(2026, 10, 25),
        )
    source_reader = ReadLegacyPortfolioPositions(DjangoLegacyPortfolioPositionRepository())
    with pytest.raises(InvalidInputError):
        source_reader.read(user_id=True, portfolio_id=1, database_alias="default")


@pytest.mark.parametrize(
    ("map_field", "map_value", "reason_code"),
    [
        pytest.param(
            "target_table",
            "simulated_trade",
            "POSITION_MAP_TARGET_TABLE_MISMATCH",
            id="wrong-target-table",
        ),
        pytest.param(
            "target_id",
            2_000_000_001,
            "POSITION_MAP_TARGET_MISSING",
            id="orphan-target-id",
        ),
    ],
)
def test_invalid_forward_position_map_has_a_stable_reason(
    map_field: str,
    map_value: object,
    reason_code: str,
) -> None:
    """A source row never inherits a same-numbered or wrong-table target by guess."""

    case = _seed_position_case(label="invalid-forward-map")
    setattr(case.position_map, map_field, map_value)
    case.position_map.save(update_fields=[map_field])

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    row = _row_for_source(report, case.source_position.pk)
    reason_codes = row.get("reason_codes")
    assert isinstance(reason_codes, list)
    assert reason_code in reason_codes
    assert row["supported_sellable_quantity"] is None
    assert row["requires_reconciliation"] is True


def test_missing_forward_position_map_is_reported_without_guessing_by_asset() -> None:
    """A matching asset code is not enough to bind a missing source map."""

    case = _seed_position_case(label="missing-forward-map")
    case.position_map.delete()

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    row = _row_for_source(report, case.source_position.pk)
    reason_codes = row.get("reason_codes")
    assert isinstance(reason_codes, list)
    assert "POSITION_MAP_MISSING" in reason_codes
    assert row["target_position_id"] is None
    assert row["supported_sellable_quantity"] is None


def test_reverse_many_to_one_position_map_is_ambiguous() -> None:
    """Two source positions mapped to one target cannot each claim its quantity."""

    case = _seed_position_case(label="reverse-map-ambiguous")
    second_source = _new_source_position(
        case.portfolio,
        asset_code="600000.SH",
        shares=25.0,
    )
    LedgerMigrationMapModel._default_manager.create(
        source_app="account",
        source_table="position",
        source_id=second_source.pk,
        target_table="simulated_position",
        target_id=case.target_position.pk,
    )

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    for source_id in (case.source_position.pk, second_source.pk):
        row = _row_for_source(report, source_id)
        reason_codes = row.get("reason_codes")
        assert isinstance(reason_codes, list)
        assert "POSITION_MAP_REVERSE_AMBIGUOUS" in reason_codes
        assert row["supported_sellable_quantity"] is None


def test_mapped_target_must_match_exact_source_security() -> None:
    """A map cannot bind one legacy security to a different unified security."""

    case = _seed_position_case(
        label="security-mismatch",
    )
    case.target_position.asset_code = "000001.SZ"
    case.target_position.save(update_fields=["asset_code"])

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    row = _row_for_source(report, case.source_position.pk)
    reason_codes = row.get("reason_codes")
    assert isinstance(reason_codes, list)
    assert "POSITION_MAP_ASSET_MISMATCH" in reason_codes
    assert row["source_asset_code"] == "600000.SH"
    assert row["target_asset_code"] == "000001.SZ"
    assert row["supported_sellable_quantity"] is None


def test_exactly_mapped_total_quantity_difference_has_its_own_reason() -> None:
    """A correct identity map still exposes source-to-target quantity drift."""

    case = _seed_position_case(
        label="total-quantity-mismatch",
        target_quantity=Decimal("250.000000"),
    )

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    row = _row_for_source(report, case.source_position.pk)
    reason_codes = row.get("reason_codes")
    assert isinstance(reason_codes, list)
    assert "TOTAL_QUANTITY_MISMATCH" in reason_codes
    assert "POSITION_MAP_ASSET_MISMATCH" not in reason_codes
    assert row["total_quantity_difference"] == "50.000000"
    assert row["supported_sellable_quantity"] is None


def test_unmapped_target_is_reported_as_orphan_without_supported_quantity() -> None:
    """A target row with no exact source mapping is not paired by matching asset code."""

    case = _seed_position_case(label="orphan-target")
    orphan = _new_target_position(
        case.account,
        asset_code="000001.SZ",
        quantity=Decimal("20.000000"),
    )

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    orphan_rows = [row for row in _rows(report) if row.get("target_position_id") == orphan.pk]
    assert len(orphan_rows) == 1
    row = orphan_rows[0]
    assert row["source_position_id"] is None
    assert row["asset_code"] == "000001.SZ"
    reason_codes = row.get("reason_codes")
    assert isinstance(reason_codes, list)
    assert "POSITION_SOURCE_MISSING" in reason_codes
    assert row["supported_sellable_quantity"] is None


def test_same_owner_mapping_to_another_account_is_not_mixed_into_requested_scope() -> None:
    """A same-owner account is still a different ledger scope for position mappings."""

    case = _seed_position_case(label="same-owner-other-account")
    other_account = _new_account(case.owner, "same-owner-other-target")
    other_target = _new_target_position(other_account)
    case.position_map.target_id = other_target.pk
    case.position_map.save(update_fields=["target_id"])

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    assert report["scope_status"] == "ok"
    reason_codes = report.get("reason_codes")
    assert isinstance(reason_codes, list)
    row = _row_for_source(report, case.source_position.pk)
    assert "POSITION_MAP_ACCOUNT_MISMATCH" in row["reason_codes"]
    assert row["target_position_id"] is None
    assert row["target_asset_code"] is None
    assert row["target_total_quantity"] is None
    assert "PORTFOLIO_ACCOUNT_MAPPING_MISMATCH" not in reason_codes


def test_missing_portfolio_account_map_blocks_the_selected_scope() -> None:
    """A target account is never inferred from the owner or a matching asset."""

    case = _seed_position_case(label="missing-portfolio-map")
    case.portfolio_map.delete()

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    assert report["scope_status"] == "blocked"
    reason_codes = report.get("reason_codes")
    assert isinstance(reason_codes, list)
    assert "PORTFOLIO_ACCOUNT_MAP_MISSING" in reason_codes
    assert _rows(report) == []


def test_foreign_owner_scope_failure_does_not_leak_foreign_position_fields() -> None:
    """Owner mismatch returns a generic JSON refusal without foreign row details."""

    case = _seed_position_case(label="owner-scope-request")
    foreign_owner = _new_user("foreign-owner")
    foreign_portfolio = PortfolioModel._default_manager.create(
        user=foreign_owner,
        name="private portfolio must not be serialized",
    )
    _new_source_position(
        foreign_portfolio,
        asset_code="SECRET-OWNER-ASSET",
        shares=987.0,
    )
    foreign_account = _new_account(foreign_owner, "private-target")
    _new_target_position(
        foreign_account,
        asset_code="SECRET-OWNER-ASSET",
        quantity=Decimal("987.000000"),
    )

    report = _run_report(user_id=case.owner.pk, account_id=foreign_account.pk)

    assert report["scope_status"] == "blocked"
    reason_codes = report.get("reason_codes")
    assert isinstance(reason_codes, list)
    assert reason_codes == ["SCOPE_UNAVAILABLE"]
    assert _rows(report) == []
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert "SECRET-OWNER-ASSET" not in serialized
    assert "private portfolio must not be serialized" not in serialized
    assert "987.000000" not in serialized
    assert "source_position_id" not in serialized
    assert "target_position_id" not in serialized


def test_selected_portfolio_map_must_not_cross_owner_scope() -> None:
    """A map to a foreign legacy portfolio blocks without disclosing its rows."""

    case = _seed_position_case(label="foreign-source-map")
    foreign_owner = _new_user("foreign-source-map-owner")
    foreign_portfolio = PortfolioModel._default_manager.create(
        user=foreign_owner,
        name="foreign source scope secret",
    )
    _new_source_position(
        foreign_portfolio,
        asset_code="SECRET-SOURCE-CODE",
        shares=987.0,
    )
    case.portfolio_map.source_id = foreign_portfolio.pk
    case.portfolio_map.save(update_fields=["source_id"])

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    assert report["scope_status"] == "blocked"
    assert report["reason_codes"] == ["SCOPE_UNAVAILABLE"]
    assert _rows(report) == []
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert "foreign source scope secret" not in serialized
    assert "SECRET-SOURCE-CODE" not in serialized
    assert "987.000000" not in serialized


def test_portfolio_map_with_wrong_target_table_blocks_selected_scope() -> None:
    """A numeric target ID cannot override the portfolio map's declared table."""

    case = _seed_position_case(label="portfolio-map-wrong-table")
    case.portfolio_map.target_table = "simulated_position"
    case.portfolio_map.save(update_fields=["target_table"])

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    assert report["scope_status"] == "blocked"
    assert report["reason_codes"] == ["PORTFOLIO_ACCOUNT_MAP_TARGET_TABLE_MISMATCH"]
    assert _rows(report) == []


def test_dangling_source_map_is_reported_without_inventing_source_position() -> None:
    """A map whose source row vanished is distinct from a target-only orphan."""

    case = _seed_position_case(label="dangling-source-map")
    case.source_position.delete()
    case.position_map.source_id = 2_000_000_002
    case.position_map.save(update_fields=["source_id"])

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    matching = [
        row for row in _rows(report) if row.get("position_mapping_id") == case.position_map.pk
    ]
    assert len(matching) == 1
    row = matching[0]
    assert row["source_position_id"] is None
    assert row["target_position_id"] == case.target_position.pk
    assert "POSITION_MAP_SOURCE_MISSING_OR_OUTSIDE_SCOPE" in row["reason_codes"]
    assert "mapping_source_id" not in row
    assert row["supported_sellable_quantity"] is None


def test_empty_mapped_scope_is_not_claimed_reconciled_or_repair_ready() -> None:
    """An empty, correctly mapped scope remains an empty diagnostic result."""

    case = _seed_position_case(label="empty-source-target-scope")
    case.position_map.delete()
    case.source_position.delete()
    case.target_position.delete()

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    _assert_read_only_report(report, owner_id=case.owner.pk, account_id=case.account.pk)
    assert report["scope_status"] == "ok"
    assert _rows(report) == []


def test_negative_legacy_quantity_is_unknown_not_a_valid_difference() -> None:
    """Invalid negative source quantities are not rounded or treated as evidence."""

    case = _seed_position_case(
        label="negative-source-quantity",
        source_shares=-1.0,
    )

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    row = _row_for_source(report, case.source_position.pk)
    assert row["source_total_quantity"] is None
    assert row["source_quantity_known"] is False
    assert "SOURCE_QUANTITY_INVALID" in row["reason_codes"]
    assert row["supported_sellable_quantity"] is None


def test_wrong_account_target_mapping_does_not_disclose_target_position() -> None:
    """A same or foreign account target is never shown outside the requested scope."""

    case = _seed_position_case(label="cross-owner-target-map")
    foreign_owner = _new_user("foreign-target-owner")
    foreign_account = _new_account(foreign_owner, "foreign-target")
    foreign_target = _new_target_position(
        foreign_account,
        asset_code="SECRET-TARGET-ASSET",
        quantity=Decimal("987.000000"),
    )
    case.position_map.target_id = foreign_target.pk
    case.position_map.save(update_fields=["target_id"])

    report = _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    row = _row_for_source(report, case.source_position.pk)
    assert "POSITION_MAP_ACCOUNT_MISMATCH" in row["reason_codes"]
    assert row["target_position_id"] is None
    assert row["target_asset_code"] is None
    assert row["target_total_quantity"] is None
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert "SECRET-TARGET-ASSET" not in serialized
    assert "987.000000" not in serialized


def test_both_scope_identifiers_are_required() -> None:
    """The operator must select an explicit owner and exact account together."""

    case = _seed_position_case(label="required-scope")
    with pytest.raises(CommandError, match="account-id"):
        call_command(REPORT_COMMAND, user_id=case.owner.pk, stdout=StringIO())
    with pytest.raises(CommandError, match="user-id"):
        call_command(REPORT_COMMAND, account_id=case.account.pk, stdout=StringIO())


def test_command_rejects_apply_option() -> None:
    """The diagnostic command exposes no write or repair switch."""

    case = _seed_position_case(label="reject-apply")
    with pytest.raises(TypeError, match="apply"):
        call_command(
            REPORT_COMMAND,
            user_id=case.owner.pk,
            account_id=case.account.pk,
            apply=True,
            stdout=StringIO(),
        )


@pytest.mark.parametrize(
    "database_alias",
    ["missing_alias", " default"],
    ids=["unconfigured-database", "surrounding-whitespace"],
)
def test_command_rejects_unconfigured_or_malformed_database_alias(database_alias: str) -> None:
    """A typo cannot fall through to another database or fail as a raw connection error."""

    case = _seed_position_case(label="invalid-database-alias")
    with pytest.raises(CommandError, match="--database"):
        call_command(
            REPORT_COMMAND,
            user_id=case.owner.pk,
            account_id=case.account.pk,
            database=database_alias,
            stdout=StringIO(),
        )


@contextmanager
def _capture_write_sql() -> Iterator[list[str]]:
    """Record SQL mutation statements sent over the default report database."""

    mutations: list[str] = []

    def observe(
        execute: _SqlExecutor,
        sql: str,
        params: object,
        many: bool,
        context: dict[str, object],
    ) -> object:
        command = sql.lstrip().split(maxsplit=1)
        if command and command[0].upper() in {
            "INSERT",
            "UPDATE",
            "DELETE",
            "REPLACE",
            "TRUNCATE",
            "ALTER",
            "DROP",
            "CREATE",
        }:
            mutations.append(sql)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(cast(_SqlExecuteWrapper, observe)):
        yield mutations


def test_read_only_report_executes_no_database_mutation() -> None:
    """No insert/update/delete is allowed, even if final model values look unchanged."""

    case = _seed_position_case(label="mutation-observer")
    initial_available = case.target_position.available_quantity
    with _capture_write_sql() as mutations:
        _run_report(user_id=case.owner.pk, account_id=case.account.pk)

    case.target_position.refresh_from_db()
    assert mutations == []
    assert case.target_position.available_quantity == initial_available
    assert case.target_position.available_quantity_known is True
