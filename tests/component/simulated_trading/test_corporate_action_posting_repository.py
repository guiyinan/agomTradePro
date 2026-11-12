"""SQLite component checks for append-only simulated corporate-action posting."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser

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
from apps.simulated_trading.infrastructure import corporate_action_posting_repository
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_repository import (
    DjangoCorporateActionPostingRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)

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
    source_record_id: str = "SZSE:synthetic-disclosure-pdf",
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
    tax_rule_id: str | None = None,
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
        source_record_id=source_record_id,
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


def _unsaved_posting_row(
    request: CorporateActionStageRequest,
    *,
    entry_id: int,
    account_revision: int,
) -> CorporateActionPostingModel:
    """Build a real model instance for replay checks without opening a database."""

    return CorporateActionPostingModel(
        id=entry_id,
        account_id=request.account_id,
        account_revision=account_revision,
        source_namespace=request.source_namespace,
        source_record_id=request.source_record_id,
        source_event_id=request.source_event_id,
        source_revision_id=request.source_revision_id,
        asset_code=request.asset_code,
        security_id=request.security_id,
        action_kind=request.action_kind.value,
        entry_kind=request.entry_kind.value,
        stage=request.stage.value,
        stage_key=request.stage_key,
        request_payload_sha256=request.payload_sha256,
        supersedes_revision_id=request.supersedes_revision_id,
    )


@pytest.fixture
def action_ledger(
    transactional_db: None,
) -> Iterator[tuple[AbstractBaseUser, SimulatedAccountModel]]:
    """Use pytest's migrated disposable database for the actual account signal."""

    del transactional_db
    user = get_user_model().objects.create_user(
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
        tax_rule_id="synthetic-statutory-rule-v1",
        tax_rule_sha256="c" * 64,
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


@pytest.mark.parametrize(
    ("server_now", "should_block"),
    (
        (datetime(2026, 9, 23, 15, 59, 59, tzinfo=UTC), True),
        (datetime(2026, 9, 23, 16, 0, 0, tzinfo=UTC), False),
    ),
)
def test_cash_payment_uses_szse_calendar_date(
    action_ledger: tuple[AbstractBaseUser, SimulatedAccountModel],
    monkeypatch: pytest.MonkeyPatch,
    server_now: datetime,
    should_block: bool,
) -> None:
    """A UTC date before the SZSE payment date cannot trigger simulated payment."""

    _, account = action_ledger
    use_case = PostCorporateActionStageUseCase(_repository())
    entitlement = _request(account, stage_date=_RECORD_DATE)
    payment = replace(
        entitlement,
        stage=CorporateActionStage.CASH_PAYMENT,
        cash_amount=Decimal("200.00"),
        payment_date=date(2026, 9, 24),
        stage_date=date(2026, 9, 24),
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )
    monkeypatch.setattr(
        corporate_action_posting_repository.timezone,
        "now",
        lambda: server_now,
    )

    if should_block:
        with pytest.raises(CorporateActionPostingBlockedError) as error:
            use_case.execute((entitlement, payment))
        assert error.value.code == "CORPORATE_ACTION_PAYMENT_DATE_NOT_REACHED"
        assert CorporateActionPostingModel.objects.filter(account=account).count() == 0
        account.refresh_from_db()
        assert account.current_cash == Decimal("10000.00")
        return

    receipts = use_case.execute((entitlement, payment))
    assert all(not receipt.replayed for receipt in receipts)
    account.refresh_from_db()
    assert account.current_cash == Decimal("10200.00")
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 2
    monkeypatch.setattr(
        corporate_action_posting_repository.timezone,
        "now",
        lambda: datetime(2026, 9, 23, 15, 59, 59, tzinfo=UTC),
    )
    assert all(receipt.replayed for receipt in use_case.execute((entitlement, payment)))


@pytest.mark.parametrize("amount", (Decimal("199.99"), Decimal("200.01")))
def test_cash_payment_must_settle_exact_outstanding_event_receivable(
    action_ledger: tuple[AbstractBaseUser, SimulatedAccountModel],
    amount: Decimal,
) -> None:
    """Partial payment and overpayment both leave the append-only ledger untouched."""

    _, account = action_ledger
    use_case = PostCorporateActionStageUseCase(_repository())
    entitlement = _request(account, stage_date=_RECORD_DATE)
    payment = replace(
        entitlement,
        stage=CorporateActionStage.CASH_PAYMENT,
        cash_amount=amount,
        payment_date=date(2026, 9, 24),
        stage_date=date(2026, 9, 24),
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )

    with pytest.raises(CorporateActionPostingBlockedError) as error:
        use_case.execute((entitlement, payment))

    assert error.value.code == "CORPORATE_ACTION_RECEIVABLE_NOT_FULLY_SETTLED"
    account.refresh_from_db()
    assert account.current_cash == Decimal("10000.00")
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 0


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
        "source_record_id": "SZSE:synthetic-corrected-disclosure-pdf",
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

    second_correction_common = {
        "source_record_id": "SZSE:synthetic-second-correction-pdf",
        "source_revision_id": "sha256:source-v3",
        "supersedes_revision_id": "sha256:source-v2",
        "source_payload_sha256": "7" * 64,
        "qualification_sha256": "6" * 64,
        "source_observed_at": datetime(2026, 11, 10, 1, 40, tzinfo=UTC),
        "qualified_at": datetime(2026, 11, 10, 1, 45, tzinfo=UTC),
        "posted_at": datetime(2026, 11, 10, 1, 50, tzinfo=UTC),
    }
    reverse_second_payment = replace(
        corrected_payment,
        **second_correction_common,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        payment_date=None,
        cash_amount=None,
        tax_treatment=None,
        tax_rule_id=None,
        tax_rule_sha256=None,
        reversal_of_entry_id=receipts[3].entry_id,
    )
    reverse_second_entitlement = replace(
        corrected_entitlement,
        **second_correction_common,
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
        reversal_of_entry_id=receipts[2].entry_id,
    )
    second_successor_entitlement = replace(
        corrected_entitlement,
        **second_correction_common,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        cash_amount=Decimal("275.00"),
    )
    second_successor_payment = replace(
        corrected_payment,
        **second_correction_common,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        cash_amount=Decimal("275.00"),
    )
    second_correction = (
        reverse_second_payment,
        reverse_second_entitlement,
        second_successor_entitlement,
        second_successor_payment,
    )
    second_receipts = use_case.execute(second_correction)
    assert all(not receipt.replayed for receipt in second_receipts)
    assert all(receipt.replayed for receipt in use_case.execute(second_correction))
    account.refresh_from_db()
    assert account.current_cash == Decimal("10275.00")
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 10


def test_correction_replay_requires_complete_set_and_survives_later_payment(
    action_ledger: tuple[AbstractBaseUser, SimulatedAccountModel],
) -> None:
    """A correction is complete, while its later payment remains a separate posting."""

    _, account = action_ledger
    use_case = PostCorporateActionStageUseCase(_repository())
    entitlement = _request(account)
    original_receipt = use_case.execute((entitlement,))[0]
    correction_common = {
        "source_revision_id": "sha256:source-v2",
        "supersedes_revision_id": "sha256:source-v1",
        "source_payload_sha256": "9" * 64,
        "qualification_sha256": "8" * 64,
        "source_observed_at": datetime(2026, 11, 10, 1, 20, tzinfo=UTC),
        "qualified_at": datetime(2026, 11, 10, 1, 25, tzinfo=UTC),
        "posted_at": datetime(2026, 11, 10, 1, 30, tzinfo=UTC),
    }
    reversal = replace(
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
        reversal_of_entry_id=original_receipt.entry_id,
    )
    successor = replace(
        entitlement,
        **correction_common,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        cash_amount=Decimal("250.00"),
    )
    correction = (reversal, successor)

    with pytest.raises(CorporateActionPostingBlockedError) as mismatched_predecessor:
        use_case.execute((reversal, replace(successor, supersedes_revision_id="sha256:source-v0")))
    assert mismatched_predecessor.value.code == "CORPORATE_ACTION_BATCH_IDENTITY_INVALID"

    receipts = use_case.execute(correction)
    assert all(not receipt.replayed for receipt in receipts)

    with pytest.raises(CorporateActionPostingConflictError) as partial_replay:
        use_case.execute((reversal,))
    assert partial_replay.value.code == "CORPORATE_ACTION_REVISION_REPLAY_CONFLICT"

    duplicate_entitlement = replace(
        successor,
        entry_kind=CorporateActionEntryKind.POSTING,
        supersedes_revision_id=None,
    )
    with pytest.raises(CorporateActionPostingConflictError) as duplicate_stage:
        use_case.execute((duplicate_entitlement,))
    assert duplicate_stage.value.code == "CORPORATE_ACTION_STAGE_ALREADY_APPLIED"

    later_payment = replace(
        successor,
        stage=CorporateActionStage.CASH_PAYMENT,
        entry_kind=CorporateActionEntryKind.POSTING,
        stage_date=date(2026, 9, 25),
        payment_date=date(2026, 9, 25),
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        supersedes_revision_id=None,
    )
    with pytest.raises(CorporateActionPostingConflictError) as changed_record:
        use_case.execute(
            (replace(later_payment, source_record_id="SZSE:other-corrected-document"),)
        )
    assert changed_record.value.code == "CORPORATE_ACTION_SOURCE_RECORD_IDENTITY_CONFLICT"
    payment_receipt = use_case.execute((later_payment,))[0]
    assert not payment_receipt.replayed

    replay = use_case.execute(correction)
    assert all(receipt.replayed for receipt in replay)
    assert tuple(receipt.entry_id for receipt in replay) == tuple(
        receipt.entry_id for receipt in receipts
    )
    account.refresh_from_db()
    assert account.current_cash == Decimal("10250.00")
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 4


def test_replay_resolution_requires_complete_correction_but_allows_later_posting() -> None:
    """Replay membership uses correction kinds and preserves ordinary stage retries."""

    account = SimulatedAccountModel(pk=101, user_id=202)
    original = _request(account)
    correction_common = {
        "source_revision_id": "sha256:source-v2",
        "supersedes_revision_id": "sha256:source-v1",
        "source_payload_sha256": "9" * 64,
        "qualification_sha256": "8" * 64,
        "source_observed_at": datetime(2026, 11, 10, 1, 20, tzinfo=UTC),
        "qualified_at": datetime(2026, 11, 10, 1, 25, tzinfo=UTC),
        "posted_at": datetime(2026, 11, 10, 1, 30, tzinfo=UTC),
    }
    reversal = replace(
        original,
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
        reversal_of_entry_id=11,
    )
    successor = replace(
        original,
        **correction_common,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        cash_amount=Decimal("250.00"),
    )
    later_payment = replace(
        successor,
        stage=CorporateActionStage.CASH_PAYMENT,
        entry_kind=CorporateActionEntryKind.POSTING,
        stage_date=date(2026, 9, 25),
        payment_date=date(2026, 9, 25),
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        supersedes_revision_id=None,
    )
    rows = [
        _unsaved_posting_row(original, entry_id=11, account_revision=1),
        _unsaved_posting_row(reversal, entry_id=12, account_revision=2),
        _unsaved_posting_row(successor, entry_id=13, account_revision=3),
        _unsaved_posting_row(later_payment, entry_id=14, account_revision=4),
    ]
    repository = DjangoCorporateActionPostingRepository()
    mismatched_successor = replace(successor, supersedes_revision_id="sha256:source-v0")
    with pytest.raises(CorporateActionPostingBlockedError) as mixed_predecessors:
        repository._validate_batch_identity((reversal, mismatched_successor), reversal)
    assert mixed_predecessors.value.code == "CORPORATE_ACTION_BATCH_IDENTITY_INVALID"

    prior_row = _unsaved_posting_row(original, entry_id=11, account_revision=1)
    prior_row.cash_receivable_delta = Decimal("200.00")
    with pytest.raises(CorporateActionPostingConflictError) as stale_predecessor:
        repository._validate_revision_transition(
            (reversal, mismatched_successor),
            [prior_row],
        )
    assert stale_predecessor.value.code == "CORPORATE_ACTION_REVISION_CONFLICT"

    assert all(
        receipt.replayed for receipt in repository._resolve_exact_replay((original,), rows) or ()
    )
    correction_replay = repository._resolve_exact_replay((reversal, successor), rows)
    assert correction_replay is not None
    assert all(receipt.replayed for receipt in correction_replay)
    assert tuple(receipt.entry_id for receipt in correction_replay) == (12, 13)
    with pytest.raises(CorporateActionPostingConflictError) as partial_replay:
        repository._resolve_exact_replay((reversal,), rows)
    assert partial_replay.value.code == "CORPORATE_ACTION_REVISION_REPLAY_CONFLICT"
    payment_replay = repository._resolve_exact_replay((later_payment,), rows)
    assert payment_replay is not None and payment_replay[0].entry_id == 14
    assert payment_replay[0].replayed


def test_source_record_identity_may_change_only_between_source_revisions() -> None:
    """Logical event identity spans corrections, but one revision pins one disclosure ID."""

    account = SimulatedAccountModel(pk=101, user_id=202)
    original = _request(account)
    successor = replace(
        original,
        source_record_id="SZSE:synthetic-corrected-disclosure-pdf",
        source_revision_id="sha256:source-v2",
        source_payload_sha256="9" * 64,
        qualification_sha256="8" * 64,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        supersedes_revision_id=original.source_revision_id,
    )
    old_row = _unsaved_posting_row(original, entry_id=11, account_revision=1)
    corrected_row = _unsaved_posting_row(successor, entry_id=12, account_revision=2)
    corrected_row.source_record_id = "SZSE:other-disclosure-pdf"

    assert corporate_action_posting_repository._same_event_identity(successor, [old_row])
    assert corporate_action_posting_repository._same_revision_source_record(successor, [old_row])
    assert not corporate_action_posting_repository._same_revision_source_record(
        successor, [old_row, corrected_row]
    )


def test_corrected_revision_blocks_duplicate_posting_but_allows_payment_and_full_replay() -> None:
    """One source head cannot credit an entitlement twice or lose correction retries."""

    account = SimulatedAccountModel(pk=101, user_id=202)
    original = _request(account)
    correction_common = {
        "source_record_id": "SZSE:synthetic-corrected-disclosure-pdf",
        "source_revision_id": "sha256:source-v2",
        "supersedes_revision_id": original.source_revision_id,
        "source_payload_sha256": "9" * 64,
        "qualification_sha256": "8" * 64,
        "source_observed_at": datetime(2026, 11, 10, 1, 20, tzinfo=UTC),
        "qualified_at": datetime(2026, 11, 10, 1, 25, tzinfo=UTC),
        "posted_at": datetime(2026, 11, 10, 1, 30, tzinfo=UTC),
    }
    reversal = replace(
        original,
        **correction_common,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        cash_amount=None,
        tax_treatment=None,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        reversal_of_entry_id=11,
    )
    successor = replace(
        original,
        **correction_common,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        cash_amount=Decimal("250.00"),
    )
    later_payment = replace(
        successor,
        stage=CorporateActionStage.CASH_PAYMENT,
        entry_kind=CorporateActionEntryKind.POSTING,
        stage_date=date(2026, 9, 25),
        payment_date=date(2026, 9, 25),
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        supersedes_revision_id=None,
    )
    duplicate_entitlement = replace(
        successor,
        entry_kind=CorporateActionEntryKind.POSTING,
        supersedes_revision_id=None,
    )
    rows = [
        _unsaved_posting_row(original, entry_id=11, account_revision=1),
        _unsaved_posting_row(reversal, entry_id=12, account_revision=2),
        _unsaved_posting_row(successor, entry_id=13, account_revision=3),
        _unsaved_posting_row(later_payment, entry_id=14, account_revision=4),
    ]
    repository = DjangoCorporateActionPostingRepository()

    with pytest.raises(CorporateActionPostingConflictError) as duplicate:
        repository._validate_revision_transition((duplicate_entitlement,), rows)
    assert duplicate.value.code == "CORPORATE_ACTION_STAGE_ALREADY_APPLIED"

    repository._validate_revision_transition((later_payment,), rows[:-1])
    replay = repository._resolve_exact_replay((reversal, successor), rows)
    assert replay is not None and all(receipt.replayed for receipt in replay)
    with pytest.raises(CorporateActionPostingConflictError) as partial:
        repository._resolve_exact_replay((reversal,), rows)
    assert partial.value.code == "CORPORATE_ACTION_REVISION_REPLAY_CONFLICT"


def test_current_source_head_does_not_repeat_an_existing_rights_no_effect_stage() -> None:
    """A no-effect stage is still a unique immutable source-revision decision."""

    account = SimulatedAccountModel(pk=101, user_id=202)
    no_effect = _request(
        account,
        action_kind=CorporateActionKind.RIGHTS_ISSUE,
        stage=CorporateActionStage.RIGHTS_NOT_EXERCISED,
        entry_kind=CorporateActionEntryKind.NO_EFFECT,
        cash_amount=None,
        tax_treatment=None,
        rights_terms_sha256="f" * 64,
        rights_election="not_exercised",
    )
    row = _unsaved_posting_row(no_effect, entry_id=11, account_revision=1)

    with pytest.raises(CorporateActionPostingConflictError) as duplicate:
        DjangoCorporateActionPostingRepository._validate_revision_transition((no_effect,), [row])

    assert duplicate.value.code == "CORPORATE_ACTION_STAGE_ALREADY_APPLIED"


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
        tax_rule_id=None,
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
        tax_rule_id="synthetic-statutory-rule-v1",
        tax_rule_sha256="c" * 64,
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


def test_tax_withholding_without_a_legal_rule_verifier_fails_closed(
    action_ledger: tuple[AbstractBaseUser, SimulatedAccountModel],
) -> None:
    """A typed basis ID and hash cannot bypass the absent statutory tax verifier."""

    _, account = action_ledger
    repository = DjangoCorporateActionPostingRepository(
        source_qualifier=_SyntheticSourceQualifier(),
        ownership_verifier=_SyntheticOwnershipVerifier(),
        using="default",
    )
    request = _request(
        account,
        stage=CorporateActionStage.TAX_WITHHOLDING,
        stage_date=date(2026, 10, 20),
        ownership_snapshot=False,
        tax_rule_id="synthetic-statutory-rule-v1",
        tax_basis_record_id="assessment:disposition-1",
        tax_basis_sha256="f" * 64,
        cash_amount=Decimal("1.00"),
    )

    with pytest.raises(CorporateActionPostingBlockedError) as blocked:
        PostCorporateActionStageUseCase(repository).execute((request,))

    assert blocked.value.code == "CORPORATE_ACTION_TAX_VERIFIER_UNAVAILABLE"
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 0
    account.refresh_from_db()
    assert account.current_cash == Decimal("10000.00")


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
