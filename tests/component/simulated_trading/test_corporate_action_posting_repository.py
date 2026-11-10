"""SQLite component checks for append-only simulated corporate-action posting."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import connection, models

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
    CorporateActionPostingConflictError,
    PostCorporateActionStageUseCase,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_repository import (
    DjangoCorporateActionPostingRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.support.isolated_schema import isolated_schema

_RECORD_DATE = date(2026, 9, 23)
_EFFECTIVE_DATE = date(2026, 9, 24)
_CAPTURED_AT = datetime(2026, 11, 10, 1, 0, tzinfo=UTC)
_QUALIFIED_AT = datetime(2026, 11, 10, 1, 5, tzinfo=UTC)
_POSTED_AT = datetime(2026, 11, 10, 1, 10, tzinfo=UTC)


class _SyntheticSourceQualifier:
    """Accept only a well-formed synthetic fixture; never access a live provider."""

    def verify_source(self, request: CorporateActionStageRequest) -> bool:
        return (
            request.source_namespace == "exchange_official_disclosure"
            and len(request.source_payload_sha256) == 64
            and len(request.qualification_sha256) == 64
            and request.source_observed_at <= request.qualified_at <= request.posted_at
        )


class _SyntheticOwnershipVerifier:
    """Verify test snapshot identity and record-date scope without current positions."""

    def verify_ownership(self, request: CorporateActionStageRequest) -> bool:
        return (
            request.ownership_snapshot_id
            == f"account-history:{request.account_id}:{request.record_date.isoformat()}"
            and request.ownership_snapshot_as_of_date == request.record_date
            and request.ownership_snapshot_observed_at is not None
            and request.ownership_snapshot_observed_at <= request.qualified_at
            and request.eligible_quantity is not None
        )


class _SyntheticTaxBasisVerifier:
    """Accept a complete synthetic tax-basis record with an explicit exact amount."""

    def verify_tax_basis(self, request: CorporateActionStageRequest) -> bool:
        return (
            request.tax_treatment == "deferred_withholding"
            and request.tax_basis_record_id is not None
            and request.tax_basis_sha256 is not None
            and request.cash_amount is not None
        )


def _repository(*, qualified: bool = True) -> DjangoCorporateActionPostingRepository:
    """Build an isolated repository with synthetic local qualification ports."""

    if not qualified:
        return DjangoCorporateActionPostingRepository(using="default")
    return DjangoCorporateActionPostingRepository(
        source_qualifier=_SyntheticSourceQualifier(),
        ownership_verifier=_SyntheticOwnershipVerifier(),
        tax_basis_verifier=_SyntheticTaxBasisVerifier(),
        using="default",
    )


def _request(
    account: SimulatedAccountModel,
    *,
    event_id: str = "SZSE:002727:synthetic-dividend",
    source_revision_id: str = "sha256:source-v1",
    supersedes_revision_id: str | None = None,
    source_payload_sha256: str = "a" * 64,
    qualification_sha256: str = "b" * 64,
    action_kind: CorporateActionKind = CorporateActionKind.CASH_DIVIDEND,
    stage: CorporateActionStage = CorporateActionStage.CASH_ENTITLEMENT,
    entry_kind: CorporateActionEntryKind = CorporateActionEntryKind.POSTING,
    cash_amount: Decimal | None = Decimal("200.00"),
    share_amount: Decimal | None = None,
    stage_date: date = _EFFECTIVE_DATE,
    payment_date: date | None = None,
    sellable_date: date | None = None,
    tax_treatment: str | None = "deferred_withholding",
    tax_rule_id: str | None = "official-holding-period-tax-v1",
    tax_basis_record_id: str | None = None,
    ownership_snapshot: bool = True,
    eligible_quantity: Decimal = Decimal("1000.000000"),
    odd_lot_policy: str | None = None,
    odd_lot_confirmation_sha256: str | None = None,
    rights_terms_sha256: str | None = None,
    rights_election: str | None = None,
    reversal_of_entry_id: int | None = None,
    tax_basis_sha256: str | None = None,
) -> CorporateActionStageRequest:
    """Build one synthetic stage with explicit source and historical-owner proof."""

    ownership_fields: dict[str, object] = {}
    if ownership_snapshot:
        ownership_fields = {
            "ownership_snapshot_id": (f"account-history:{account.pk}:{_RECORD_DATE.isoformat()}"),
            "ownership_snapshot_sha256": "d" * 64,
            "ownership_snapshot_as_of_date": _RECORD_DATE,
            "ownership_snapshot_observed_at": _CAPTURED_AT,
            "eligible_quantity": eligible_quantity,
            "entitlement_calculation_sha256": "e" * 64,
        }
    return CorporateActionStageRequest(
        account_id=account.pk,
        owner_user_id=account.user_id,
        security_id="002727.SZ",
        asset_code="002727.SZ",
        asset_name="Synthetic security",
        source_namespace="exchange_official_disclosure",
        source_record_id="SZSE:synthetic-disclosure-pdf",
        source_event_id=event_id,
        source_revision_id=source_revision_id,
        source_payload_sha256=source_payload_sha256,
        qualification_sha256=qualification_sha256,
        qualifier_identity="synthetic-qualifier-v1",
        source_observed_at=_CAPTURED_AT,
        qualified_at=_QUALIFIED_AT,
        posted_at=_POSTED_AT,
        action_kind=action_kind,
        stage=stage,
        entry_kind=entry_kind,
        record_date=_RECORD_DATE,
        effective_date=_EFFECTIVE_DATE,
        stage_date=stage_date,
        cash_amount=cash_amount,
        share_amount=share_amount,
        payment_date=payment_date,
        sellable_date=sellable_date,
        tax_treatment=tax_treatment,
        tax_rule_id=tax_rule_id,
        tax_rule_sha256="c" * 64 if tax_rule_id is not None else None,
        tax_basis_record_id=tax_basis_record_id,
        tax_basis_sha256=tax_basis_sha256,
        rights_terms_sha256=rights_terms_sha256,
        rights_election=rights_election,
        odd_lot_policy=odd_lot_policy,
        odd_lot_confirmation_sha256=odd_lot_confirmation_sha256,
        supersedes_revision_id=supersedes_revision_id,
        reversal_of_entry_id=reversal_of_entry_id,
        **ownership_fields,
    )


@pytest.fixture
def action_ledger(
    request: pytest.FixtureRequest,
) -> Iterator[tuple[AbstractBaseUser, SimulatedAccountModel]]:
    """Create only the account, position, trade, reservation, and action tables used here."""

    database_blocker = request.getfixturevalue("django_db_blocker")
    with database_blocker.unblock():
        user_model = get_user_model()
        model_types: tuple[type[models.Model], ...] = (
            user_model,
            AccountProfileModel,
            SimulatedAccountModel,
            PositionModel,
            SimulatedTradeModel,
            SimulatedOrderReservationModel,
            CorporateActionPostingModel,
        )
        original_database_name = connection.settings_dict["NAME"]
        connection.close()
        connection.settings_dict["NAME"] = ":memory:"
        try:
            with isolated_schema(model_types):
                user = user_model.objects.create_user(
                    username="corporate-action-ledger-test",
                    password="unused",
                )
                account = SimulatedAccountModel.objects.create(
                    user=user,
                    account_name="corporate-action-ledger-test",
                    account_type="simulated",
                    initial_capital=Decimal("10000.00"),
                    current_cash=Decimal("10000.00"),
                    current_market_value=Decimal("0.00"),
                    total_value=Decimal("10000.00"),
                    is_active=True,
                )
                yield user, account
        finally:
            connection.close()
            connection.settings_dict["NAME"] = original_database_name


def test_late_cash_entitlement_payment_and_tax_are_idempotent_and_separate(
    action_ledger: tuple[AbstractBaseUser, SimulatedAccountModel],
) -> None:
    """Late input uses historical ownership proof, while cash settles in distinct stages."""

    _, account = action_ledger
    use_case = PostCorporateActionStageUseCase(_repository())
    entitlement = _request(account, stage_date=_RECORD_DATE)
    first = use_case.execute((entitlement,))[0]
    assert not first.replayed
    account.refresh_from_db()
    assert account.current_cash == Decimal("10000.00")

    replay = use_case.execute((entitlement,))[0]
    assert replay.replayed
    assert replay.entry_id == first.entry_id
    with pytest.raises(CorporateActionPostingConflictError):
        use_case.execute((replace(entitlement, cash_amount=Decimal("201.00")),))

    payment = replace(
        entitlement,
        stage=CorporateActionStage.CASH_PAYMENT,
        cash_amount=Decimal("200.00"),
        payment_date=_RECORD_DATE,
        stage_date=_RECORD_DATE,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )
    use_case.execute((payment,))
    account.refresh_from_db()
    assert account.current_cash == Decimal("10200.00")

    withholding = replace(
        payment,
        stage=CorporateActionStage.TAX_WITHHOLDING,
        cash_amount=Decimal("40.00"),
        payment_date=None,
        stage_date=date(2026, 10, 20),
        tax_basis_record_id="qualified-tax-basis:holding-period-bucket",
        tax_basis_sha256="f" * 64,
    )
    use_case.execute((withholding,))
    account.refresh_from_db()
    assert account.current_cash == Decimal("10160.00")
    assert SimulatedTradeModel.objects.count() == 0
    rows = list(CorporateActionPostingModel.objects.filter(account=account))
    assert [row.stage for row in rows] == [
        "cash_entitlement",
        "cash_payment",
        "tax_withholding",
    ]
    assert rows[0].cash_receivable_delta == Decimal("200.00")
    assert rows[1].cash_delta == Decimal("200.00")
    assert rows[2].cash_delta == Decimal("-40.00")
    assert account.total_value == Decimal("10000.00")


def test_correction_is_one_replayable_reversal_and_successor_batch(
    action_ledger: tuple[AbstractBaseUser, SimulatedAccountModel],
) -> None:
    """Correction reverses the prior version before appending its successor stages."""

    _, account = action_ledger
    use_case = PostCorporateActionStageUseCase(_repository())
    entitlement = _request(account)
    entitlement_receipt = use_case.execute((entitlement,))[0]
    payment = replace(
        entitlement,
        stage=CorporateActionStage.CASH_PAYMENT,
        cash_amount=Decimal("200.00"),
        payment_date=date(2026, 9, 25),
        stage_date=date(2026, 9, 25),
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )
    payment_receipt = use_case.execute((payment,))[0]

    correction_common = {
        "source_revision_id": "sha256:source-v2",
        "supersedes_revision_id": "sha256:source-v1",
        "source_payload_sha256": "9" * 64,
        "qualification_sha256": "8" * 64,
        "source_observed_at": datetime(2026, 11, 10, 1, 20, tzinfo=UTC),
        "qualified_at": datetime(2026, 11, 10, 1, 25, tzinfo=UTC),
        "posted_at": datetime(2026, 11, 10, 1, 30, tzinfo=UTC),
    }
    reverse_payment = replace(
        payment,
        **correction_common,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        payment_date=None,
        cash_amount=None,
        tax_treatment=None,
        tax_rule_id=None,
        tax_rule_sha256=None,
        reversal_of_entry_id=payment_receipt.entry_id,
    )
    reverse_entitlement = replace(
        entitlement,
        **correction_common,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        cash_amount=None,
        tax_treatment=None,
        tax_rule_id=None,
        tax_rule_sha256=None,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        reversal_of_entry_id=entitlement_receipt.entry_id,
    )
    corrected_entitlement = replace(
        entitlement,
        **correction_common,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        cash_amount=Decimal("250.00"),
    )
    corrected_payment = replace(
        payment,
        **correction_common,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        cash_amount=Decimal("250.00"),
    )
    correction = (
        reverse_payment,
        reverse_entitlement,
        corrected_entitlement,
        corrected_payment,
    )
    receipts = use_case.execute(correction)
    assert all(not receipt.replayed for receipt in receipts)
    assert tuple(receipt.stage_key for receipt in receipts) == tuple(
        request.stage_key for request in correction
    )
    assert all(receipt.replayed for receipt in use_case.execute(correction))
    account.refresh_from_db()
    assert account.current_cash == Decimal("10250.00")
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 6


def test_historical_snapshot_is_not_current_position_and_share_release_is_t_plus_one(
    action_ledger: tuple[AbstractBaseUser, SimulatedAccountModel],
) -> None:
    """Delivery uses source-final whole shares and waits for its explicit sellable date."""

    _, account = action_ledger
    position = PositionModel.objects.create(
        account=account,
        asset_code="002727.SZ",
        asset_name="Synthetic security",
        asset_type="equity",
        quantity=Decimal("50.000000"),
        available_quantity=Decimal("50.000000"),
        available_quantity_known=True,
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("500.00"),
        cost_basis_known=True,
        current_price=Decimal("12.0000"),
        market_value=Decimal("600.00"),
        valuation_known=True,
        unrealized_pnl=Decimal("100.00"),
        unrealized_pnl_pct=20.0,
        first_buy_date=date(2026, 8, 1),
    )
    use_case = PostCorporateActionStageUseCase(_repository())

    entitlement = _request(
        account,
        event_id="SZSE:002727:synthetic-share-distribution",
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        cash_amount=None,
        share_amount=Decimal("40.000000"),
        tax_treatment="not_applicable",
        tax_rule_id="official-no-tax-treatment",
        ownership_snapshot=True,
        eligible_quantity=Decimal("100.000000"),
        odd_lot_policy="whole_shares",
    )
    use_case.execute((entitlement,))
    delivery = replace(
        entitlement,
        stage=CorporateActionStage.SHARE_DELIVERY,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        sellable_date=date(2026, 9, 25),
        stage_date=date(2026, 9, 24),
    )
    use_case.execute((delivery,))
    position.refresh_from_db()
    assert position.quantity == Decimal("90.000000")
    assert position.available_quantity == Decimal("50.000000")
    assert position.avg_cost == Decimal("5.5556")
    assert position.current_price == Decimal("12.0000")
    assert position.market_value == Decimal("600.00")
    assert not position.valuation_known

    release = replace(
        delivery,
        stage=CorporateActionStage.SHARE_SELLABLE_RELEASE,
        stage_date=date(2026, 9, 25),
    )
    use_case.execute((release,))
    position.refresh_from_db()
    assert position.quantity == Decimal("90.000000")
    assert position.available_quantity == Decimal("90.000000")
    assert SimulatedTradeModel.objects.count() == 0


def test_tax_after_payment_fails_closed_when_basis_exceeds_paid_gross(
    action_ledger: tuple[AbstractBaseUser, SimulatedAccountModel],
) -> None:
    """Tax deductions need verified terms and cannot exceed the event's paid proceeds."""

    _, account = action_ledger
    use_case = PostCorporateActionStageUseCase(_repository())
    entitlement = _request(account)
    use_case.execute((entitlement,))
    payment = replace(
        entitlement,
        stage=CorporateActionStage.CASH_PAYMENT,
        payment_date=date(2026, 9, 25),
        stage_date=date(2026, 9, 25),
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )
    use_case.execute((payment,))
    withholding = replace(
        payment,
        stage=CorporateActionStage.TAX_WITHHOLDING,
        cash_amount=Decimal("201.00"),
        payment_date=None,
        stage_date=date(2026, 10, 20),
        tax_basis_record_id="qualified-tax-basis:excess",
        tax_basis_sha256="f" * 64,
    )
    with pytest.raises(CorporateActionPostingBlockedError) as blocked:
        use_case.execute((withholding,))
    assert blocked.value.code == "CORPORATE_ACTION_TAX_BASIS_INSUFFICIENT"
    account.refresh_from_db()
    assert account.current_cash == Decimal("10200.00")
    assert (
        CorporateActionPostingModel.objects.filter(
            account=account,
            stage="tax_withholding",
        ).count()
        == 0
    )


def test_repository_without_source_and_ownership_verifiers_remains_blocked(
    action_ledger: tuple[AbstractBaseUser, SimulatedAccountModel],
) -> None:
    """Unsigned caller-supplied hashes are not accepted as production qualification."""

    _, account = action_ledger
    use_case = PostCorporateActionStageUseCase(_repository(qualified=False))
    with pytest.raises(CorporateActionPostingBlockedError) as blocked:
        use_case.execute((_request(account),))
    assert blocked.value.code == "CORPORATE_ACTION_SOURCE_VERIFIER_UNAVAILABLE"
    assert CorporateActionPostingModel.objects.count() == 0


def test_same_event_identity_is_account_scoped(
    action_ledger: tuple[AbstractBaseUser, SimulatedAccountModel],
) -> None:
    """The natural key separates owners' accounts while retaining one source event ID."""

    user, first_account = action_ledger
    second_account = SimulatedAccountModel.objects.create(
        user=user,
        account_name="corporate-action-second-account",
        account_type="simulated",
        initial_capital=Decimal("5000.00"),
        current_cash=Decimal("5000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("5000.00"),
        is_active=True,
    )
    use_case = PostCorporateActionStageUseCase(_repository())
    first_receipt = use_case.execute((_request(first_account),))[0]
    second_request = replace(
        _request(second_account),
        cash_amount=Decimal("100.00"),
        eligible_quantity=Decimal("500.000000"),
    )
    second_receipt = use_case.execute((second_request,))[0]
    first_account.refresh_from_db()
    second_account.refresh_from_db()
    assert first_receipt.entry_id != second_receipt.entry_id
    assert first_account.current_cash == Decimal("10000.00")
    assert second_account.current_cash == Decimal("5000.00")
    assert (
        CorporateActionPostingModel.objects.filter(
            source_event_id=second_request.source_event_id
        ).count()
        == 2
    )
