"""Human confirmation must contain concrete source dates and modeled amounts."""

from apps.simulated_trading.corporate_action_owner_workflow_composition import _preparation_summary
from tests.unit.simulated_trading.test_corporate_action_owner_intent_codec import _intent


def test_tax_preview_shows_exact_amount_and_record_date_before_any_confirmation():
    intent = _intent(tax=True)
    summary = _preparation_summary(intent, False)
    assert intent.assessment is not None
    assert format(intent.assessment.calculation.withholding_amount, "f") in summary
    assert intent.assessment.action.record_date.isoformat() in summary
    assert "本步骤不扣款" in summary


def test_cash_preview_shows_distinct_record_ex_and_payout_dates():
    intent = _intent()
    summary = _preparation_summary(intent, False)
    reference = intent.source_reference
    assert reference.record_date.isoformat() in summary
    assert reference.effective_date.isoformat() in summary
    assert "登记日" in summary
    assert "除权息日" in summary
    assert "到账日" in summary
