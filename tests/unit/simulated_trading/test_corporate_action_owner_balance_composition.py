"""Independent mark identity and exact currency projection boundaries."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.simulated_trading import corporate_action_owner_balance_composition as composition
from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    TaxCashCoverageQuery,
    TaxCashCoverageSnapshot,
    TaxCashCoverageStatus,
)
from apps.simulated_trading.corporate_action_current_entitlement_coverage import (
    CurrentAssetEntitlementCoverage,
)
from apps.simulated_trading.corporate_action_owner_balance_composition import (
    _exact_amount,
    _mark_selection,
)
from apps.simulated_trading.corporate_action_owner_ledger_composition import (
    OwnerCorporateActionPostingState,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_nav_mark_reader import _query, _reader


def _proof():
    reader, _ = _reader()
    proof = reader.read_current_mark(_query())
    assert proof is not None
    return proof


def test_mark_reread_clock_alone_does_not_change_original_valuation_identity():
    original = _proof()
    checked = original.checked_at + timedelta(seconds=1)
    classification = replace(
        original.classification,
        read_at=checked,
        identity_evidence=replace(
            original.classification.identity_evidence,
            selection=replace(
                original.classification.identity_evidence.selection, selected_at=checked
            ),
        ),
    )
    current = replace(
        original,
        classification=classification,
        checked_at=checked,
        policy_binding=replace(original.policy_binding, checked_at=checked),
        source_evidence=replace(original.source_evidence, knowledge_cutoff=checked),
    )
    assert _mark_selection(current, original=original) == _mark_selection(
        original, original=original
    )
    assert current.source_observed_at is None


def test_mark_same_value_profile_version_swap_changes_valuation_identity():
    original = _proof()
    version = original.policy_binding.profile_version + 1
    classification = replace(
        original.classification,
        identity_evidence=replace(
            original.classification.identity_evidence,
            selection=replace(
                original.classification.identity_evidence.selection, profile_version=version
            ),
        ),
    )
    current = replace(
        original,
        classification=classification,
        policy_binding=replace(original.policy_binding, profile_version=version),
    )
    assert _mark_selection(current, original=original) != _mark_selection(
        original, original=original
    )


def test_exact_valuation_does_not_choose_an_unconfigured_sub_cent_rounding_rule():
    assert _exact_amount(Decimal("103.20"), quantum=Decimal("0.01")) == Decimal("103.20")
    with pytest.raises(BusinessLogicError):
        _exact_amount(Decimal("103.205"), quantum=Decimal("0.01"))


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-1")])
def test_invalid_marked_assets_never_become_zero(value):
    with pytest.raises(BusinessLogicError):
        _exact_amount(value, quantum=Decimal("0.01"))


def _scoped_balance_proof():
    original = _proof()
    code = original.query.asset_code
    selector = replace(
        original.classification.selector,
        items=tuple(
            replace(item, security_id=code) for item in original.classification.selector.items
        ),
    )
    identity = replace(
        original.classification.identity_evidence,
        source_evidence=replace(
            original.classification.identity_evidence.source_evidence, security_id=code
        ),
        selection=replace(
            original.classification.identity_evidence.selection,
            selector_content_hash=selector.content_hash,
        ),
    )
    return replace(
        original,
        query=replace(original.query, security_id=code),
        classification=replace(
            original.classification, selector=selector, identity_evidence=identity
        ),
    )


def _read_balance(monkeypatch, *, cash_complete=True, shares_complete=True, floor=None):
    original = _scoped_balance_proof()
    query = original.query
    now = original.checked_at
    account = composition.SimulatedAccountModel(
        pk=query.physical_account_id,
        user_id=query.owner_user_id,
        account_type="simulated",
        is_active=True,
        updated_at=now,
        current_cash=Decimal("1000.00"),
        cash_known=True,
        cash_reconciliation_status="simulated_ledger",
    )
    account._state.db = "default"

    class Chain:
        def using(self, *args):
            return self

        def select_for_update(self):
            return self

        def filter(self, **kwargs):
            return self

        def order_by(self, *args):
            return self

        def get(self, **kwargs):
            return account

        def __getitem__(self, key):
            return (
                SimpleNamespace(
                    asset_code=query.asset_code,
                    asset_type=query.asset_type,
                    quantity=Decimal("100"),
                ),
            )

    field_metadata = composition.SimulatedAccountModel._meta
    monkeypatch.setattr(
        composition,
        "SimulatedAccountModel",
        SimpleNamespace(_meta=field_metadata, _base_manager=Chain()),
    )
    monkeypatch.setattr(composition, "PositionModel", SimpleNamespace(_base_manager=Chain()))
    monkeypatch.setattr(
        composition,
        "connections",
        {"default": SimpleNamespace(in_atomic_block=True, get_autocommit=lambda: False)},
    )
    monkeypatch.setattr(composition, "lock_active_order_reservations", lambda **kwargs: ())
    monkeypatch.setattr(composition.timezone, "now", lambda: now)
    tax_query = TaxCashCoverageQuery(
        query.physical_account_id, query.owner_user_id, query.canonical_account_id, "test"
    )
    tax = TaxCashCoverageSnapshot(
        tax_query,
        Decimal("0.01"),
        Decimal("0"),
        Decimal("0"),
        TaxCashCoverageStatus.COMPLETE,
        (),
        now,
        now - timedelta(seconds=1),
        now + timedelta(seconds=30),
        "a" * 64,
    )
    entitlements = (
        CurrentAssetEntitlementCoverage(
            query.asset_code, cash_complete, shares_complete, floor, "b" * 64
        ),
    )

    class TaxReader:
        def __init__(self, **kwargs):
            pass

        def read_locked(self, **kwargs):
            return tax

        def read_current_entitlement_coverage(self, snapshot, **kwargs):
            assert snapshot == tax
            return entitlements

        def assert_still_current(self, *args, **kwargs):
            pass

    monkeypatch.setattr(composition, "DjangoCorporateActionTaxCashCoverageReader", TaxReader)
    monkeypatch.setattr(
        composition,
        "read_owner_corporate_action_workflow_runtime",
        lambda **kwargs: SimpleNamespace(calendar_dataset_key="synthetic-calendar"),
    )
    monkeypatch.setattr(
        composition,
        "build_corporate_action_nav_raw_mark_reader",
        lambda **kwargs: SimpleNamespace(read_current_mark=lambda query: original),
    )
    monkeypatch.setattr(
        composition,
        "build_current_reference_classification_reader",
        lambda **kwargs: SimpleNamespace(
            resolve_simulated_instrument_classification=lambda **kwargs: original.classification
        ),
    )
    return (
        composition.read_locked_owner_corporate_action_balance(
            account=account,
            canonical_account_id=query.canonical_account_id,
            ledger=OwnerCorporateActionPostingState(Decimal("0"), (), ()),
            environment="test",
        ),
        original,
    )


def test_complete_tax_coverage_does_not_invent_zero_missing_cash_rights(monkeypatch):
    result, _ = _read_balance(monkeypatch, cash_complete=False)
    assert result.balance.dividend_receivable is None
    assert result.balance.net_asset_value is None
    assert result.balance.spendable_cash == Decimal("1000.00")


def test_raw_cum_dividend_mark_cannot_value_recognized_ex_date_rights(monkeypatch):
    original = _proof()
    result, _ = _read_balance(monkeypatch, floor=original.trade_date + timedelta(days=1))
    assert result.balance.marked_assets is None
    assert result.balance.net_asset_value is None
    assert result.balance.spendable_cash == Decimal("1000.00")


def test_known_rights_and_reached_ex_date_allow_exact_raw_mark_nav(monkeypatch):
    original = _proof()
    result, _ = _read_balance(monkeypatch, floor=original.trade_date)
    assert result.balance.net_asset_value == Decimal("1000.00") + original.price * 100
