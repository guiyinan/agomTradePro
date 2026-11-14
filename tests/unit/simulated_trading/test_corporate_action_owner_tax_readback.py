"""Tax display receipts preserve original operation clocks and actual cash deltas."""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from apps.simulated_trading.corporate_action_owner_tax_readback import owner_tax_operation_row
from tests.unit.simulated_trading.test_corporate_action_current_official_window import _NOW


def test_tax_receipt_uses_original_material_clock_and_cash_delta_without_inventing_balance():
    receipt = SimpleNamespace(cash_delta=Decimal("-3.20"), collected_delta=Decimal("3.20"))
    operation = SimpleNamespace(
        material=SimpleNamespace(recorded_at=_NOW - timedelta(days=2)),
        receipt=receipt,
        event=SimpleNamespace(event_id="original-tax-audit"),
        row=SimpleNamespace(asset_code="ignored-untyped-column"),
    )
    row = owner_tax_operation_row(operation, asset_code="000001.SZ")
    assert row["recorded_at"] == (_NOW - timedelta(days=2)).isoformat()
    assert row["cash_delta"] == "-3.20"
    assert row["share_delta"] == "0"
    assert row["receipt_id"] == "original-tax-audit"
    assert row["asset_code"] == "000001.SZ"
    assert not {"tax_payable", "outstanding_after", "spendable_cash"}.intersection(row)


def test_recognition_receipt_does_not_claim_to_have_collected_tax():
    operation = SimpleNamespace(
        material=SimpleNamespace(recorded_at=_NOW),
        receipt=SimpleNamespace(cash_delta=Decimal("0.00"), collected_delta=Decimal("0.00")),
        event=SimpleNamespace(event_id="recognize-only"),
    )
    row = owner_tax_operation_row(operation, asset_code="000001.SZ")
    assert row["cash_delta"] == "0.00"
    assert "没有扣款" in row["summary"]
