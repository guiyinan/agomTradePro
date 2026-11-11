"""Price-basis and open-receivable NAV continuity checks."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.infrastructure.models import PriceBarModel
from apps.data_center.infrastructure.price_bar_repository import PriceBarRepository
from apps.simulated_trading.application.corporate_action_posting import (
    PostCorporateActionStageUseCase,
)
from apps.simulated_trading.application.daily_net_value_service import DailyNetValueService
from apps.simulated_trading.application.ports import PositionPriceRefreshInput
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.infrastructure.account_repository import (
    DjangoSimulatedAccountRepository,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_repository import (
    DjangoCorporateActionPostingRepository,
)
from apps.simulated_trading.infrastructure.models import (
    DailyNetValueModel,
    PositionModel,
    SimulatedAccountModel,
)
from apps.simulated_trading.infrastructure.position_repository import DjangoPositionRepository
from core.exceptions import BusinessLogicError

_RECORD_DATE = date(2026, 9, 23)
_EX_DATE = date(2026, 9, 24)
_PAYMENT_DATE = date(2026, 9, 25)
_CAPTURED_AT = datetime(2026, 11, 10, 1, 0, tzinfo=UTC)
_QUALIFIED_AT = datetime(2026, 11, 10, 1, 5, tzinfo=UTC)
_POSTED_AT = datetime(2026, 11, 10, 1, 10, tzinfo=UTC)
_ASSET_CODE = "002727.SZ"


class _SyntheticSourceQualifier:
    """Qualify only complete local test evidence; never call an external source."""

    def verify_source(self, request: CorporateActionStageRequest) -> bool:
        return (
            request.source_namespace == "exchange_official_disclosure"
            and len(request.source_payload_sha256) == 64
            and len(request.qualification_sha256) == 64
            and request.source_observed_at <= request.qualified_at <= request.posted_at
        )


class _SyntheticOwnershipVerifier:
    """Bind entitlement to the request's exact account and record-date snapshot."""

    def verify_ownership(self, request: CorporateActionStageRequest) -> bool:
        return (
            request.ownership_snapshot_id
            == f"account-history:{request.account_id}:{request.record_date.isoformat()}"
            and request.ownership_snapshot_as_of_date == request.record_date
            and request.ownership_snapshot_observed_at is not None
            and request.ownership_snapshot_observed_at <= request.qualified_at
            and request.eligible_quantity is not None
        )


def _posting_use_case() -> PostCorporateActionStageUseCase:
    """Build an isolated local posting use case with explicit test verifiers."""

    repository = DjangoCorporateActionPostingRepository(
        source_qualifier=_SyntheticSourceQualifier(),
        ownership_verifier=_SyntheticOwnershipVerifier(),
        using="default",
    )
    return PostCorporateActionStageUseCase(repository)


def _cash_entitlement_request(
    account: SimulatedAccountModel,
    *,
    cash_amount: Decimal = Decimal("2.00"),
    event_id: str = "SZSE:002727:cash-dividend-sample",
) -> CorporateActionStageRequest:
    """Build an explicit gross entitlement backed by synthetic historical ownership."""

    return CorporateActionStageRequest(
        account_id=account.pk,
        owner_user_id=account.user_id,
        security_id=_ASSET_CODE,
        asset_code=_ASSET_CODE,
        asset_name="Synthetic security",
        source_namespace="exchange_official_disclosure",
        source_record_id="SZSE:sample-corporate-action-record",
        source_event_id=event_id,
        source_revision_id="sha256:sample-action-v1",
        source_payload_sha256="a" * 64,
        qualification_sha256="b" * 64,
        qualifier_identity="synthetic-official-source-v1",
        source_observed_at=_CAPTURED_AT,
        qualified_at=_QUALIFIED_AT,
        posted_at=_POSTED_AT,
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        entry_kind=CorporateActionEntryKind.POSTING,
        record_date=_RECORD_DATE,
        effective_date=_EX_DATE,
        stage_date=_EX_DATE,
        cash_amount=cash_amount,
        tax_treatment="deferred_withholding",
        ownership_snapshot_id=(f"account-history:{account.pk}:{_RECORD_DATE.isoformat()}"),
        ownership_snapshot_sha256="d" * 64,
        ownership_snapshot_as_of_date=_RECORD_DATE,
        ownership_snapshot_observed_at=_CAPTURED_AT,
        eligible_quantity=Decimal("10.000000"),
        entitlement_calculation_sha256="e" * 64,
    )


def _payment_request(entitlement: CorporateActionStageRequest) -> CorporateActionStageRequest:
    """Move an existing gross receivable to cash without creating another entitlement."""

    return replace(
        entitlement,
        stage=CorporateActionStage.CASH_PAYMENT,
        stage_date=_PAYMENT_DATE,
        payment_date=_PAYMENT_DATE,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )


def _price_input(
    price: float,
    *,
    as_of: date,
    adjustment: str | None = "none",
) -> PositionPriceRefreshInput:
    """Build one source-attributed daily close for the account refresh seam."""

    return PositionPriceRefreshInput(
        asset_code=_ASSET_CODE,
        asset_type="equity",
        price=price,
        source="synthetic-data-center-close",
        freshness="close_fallback",
        as_of=as_of,
        observed_at=None,
        price_adjustment=adjustment,
    )


def _create_account_with_position(*, username: str) -> SimulatedAccountModel:
    """Create one disposable simulated account with ten raw-priced shares."""

    user = get_user_model().objects.create_user(username=username, password="unused")
    account = SimulatedAccountModel.objects.create(
        user=user,
        account_name=username,
        account_type="simulated",
        initial_capital=Decimal("10100.00"),
        current_cash=Decimal("10000.00"),
        current_market_value=Decimal("100.00"),
        total_value=Decimal("10100.00"),
        is_active=True,
    )
    PositionModel.objects.create(
        account=account,
        asset_code=_ASSET_CODE,
        asset_name="Synthetic security",
        asset_type="equity",
        quantity=Decimal("10.000000"),
        available_quantity=Decimal("10.000000"),
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("100.00"),
        current_price=Decimal("10.0000"),
        market_value=Decimal("100.00"),
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        first_buy_date=_RECORD_DATE,
    )
    return account


@pytest.mark.django_db(transaction=True)
def test_price_bar_repository_prefers_none_basis_on_same_observation() -> None:
    """A same-date adjusted row cannot win the canonical one-row price lookup."""

    PriceBarModel.objects.create(
        asset_code=_ASSET_CODE,
        bar_date=_EX_DATE,
        freq="1d",
        adjustment=PriceAdjustment.NONE.value,
        open=9.7,
        high=10.0,
        low=9.5,
        close=9.8,
        source="synthetic-raw",
    )
    PriceBarModel.objects.create(
        asset_code=_ASSET_CODE,
        bar_date=_EX_DATE,
        freq="1d",
        adjustment=PriceAdjustment.FORWARD.value,
        open=9.7,
        high=10.0,
        low=9.5,
        close=9.8,
        source="synthetic-forward",
    )

    rows = PriceBarRepository().get_bars(
        _ASSET_CODE,
        start=_EX_DATE,
        end=_EX_DATE,
        limit=1,
    )

    assert len(rows) == 1
    assert rows[0].adjustment is PriceAdjustment.NONE


@pytest.mark.django_db(transaction=True)
def test_cash_receivable_and_payment_keep_account_net_value_continuous() -> None:
    """Ex-date repricing adds the open receivable once; payment only transfers it to cash."""

    account = _create_account_with_position(username="ash05-price-continuity-owner")
    other_user = get_user_model().objects.create_user(
        username="ash05-price-continuity-other-owner",
        password="unused",
    )
    other_account = SimulatedAccountModel.objects.create(
        user=other_user,
        account_name="ash05-price-continuity-other-account",
        account_type="simulated",
        initial_capital=Decimal("100.00"),
        current_cash=Decimal("100.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100.00"),
        is_active=True,
    )
    position_repository = DjangoPositionRepository()
    net_value_service = DailyNetValueService()
    position_repository.update_position_prices_for_account(
        account.pk,
        {_ASSET_CODE: _price_input(10.0, as_of=_RECORD_DATE)},
    )
    account.refresh_from_db()
    assert account.total_value == Decimal("10100.00")
    first_result = net_value_service.record_and_update_performance(
        account_id=account.pk,
        record_date=_RECORD_DATE,
    )
    assert first_result["outcome"] == "success"

    posting = _posting_use_case()
    entitlement = _cash_entitlement_request(account)
    posting.execute((entitlement,))
    replay = posting.execute((entitlement,))[0]
    assert replay.replayed
    posting.execute(
        (
            _cash_entitlement_request(
                other_account,
                cash_amount=Decimal("50.00"),
                event_id="SZSE:002727:other-account-sample",
            ),
        )
    )

    position_repository.update_position_prices_for_account(
        account.pk,
        {_ASSET_CODE: _price_input(9.8, as_of=_EX_DATE)},
    )
    account.refresh_from_db()
    assert account.total_value == Decimal("10100.00")
    assert DjangoSimulatedAccountRepository().get_cash_receivable(account.pk) == Decimal("2.00")
    ex_date_result = net_value_service.record_and_update_performance(
        account_id=account.pk,
        record_date=_EX_DATE,
    )
    assert ex_date_result["outcome"] == "success"

    payment = _payment_request(entitlement)
    posting.execute((payment,))
    payment_replay = posting.execute((payment,))[0]
    assert payment_replay.replayed
    position_repository.update_position_prices_for_account(
        account.pk,
        {_ASSET_CODE: _price_input(9.8, as_of=_PAYMENT_DATE)},
    )
    account.refresh_from_db()
    assert account.current_cash == Decimal("10002.00")
    assert account.current_market_value == Decimal("98.00")
    assert account.total_value == Decimal("10100.00")
    assert DjangoSimulatedAccountRepository().get_cash_receivable(account.pk) == Decimal("0.00")

    payment_result = net_value_service.record_and_update_performance(
        account_id=account.pk,
        record_date=_PAYMENT_DATE,
    )
    assert payment_result["outcome"] == "success"
    records = list(DailyNetValueModel.objects.filter(account_id=account.pk).order_by("record_date"))
    assert [row.net_value for row in records] == [
        Decimal("10100.00"),
        Decimal("10100.00"),
        Decimal("10100.00"),
    ]
    assert [row.daily_return for row in records] == [0.0, 0.0, 0.0]
    ledger_receivables = sum(
        CorporateActionPostingModel.objects.filter(account=account).values_list(
            "cash_receivable_delta",
            flat=True,
        ),
        start=Decimal("0.00"),
    )
    assert ledger_receivables == Decimal("0.00")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "adjustment",
    ["forward", "backward", None],
    ids=["forward-adjusted", "backward-adjusted", "basis-missing"],
)
def test_position_refresh_rejects_price_without_none_basis_before_writing(
    adjustment: str | None,
) -> None:
    """Adjusted or unknown-basis values never alter stored holding or account totals."""

    account = _create_account_with_position(username=f"ash05-price-basis-{adjustment}")
    with pytest.raises(BusinessLogicError) as error:
        DjangoPositionRepository().update_position_prices_for_account(
            account.pk,
            {
                _ASSET_CODE: _price_input(
                    9.8,
                    as_of=_EX_DATE,
                    adjustment=adjustment,
                )
            },
        )

    assert error.value.code == "POSITION_PRICE_BASIS_UNVERIFIED"
    account.refresh_from_db()
    position = PositionModel.objects.get(account=account, asset_code=_ASSET_CODE)
    assert position.current_price == Decimal("10.0000")
    assert account.total_value == Decimal("10100.00")


@pytest.mark.django_db
def test_legacy_numeric_refresh_blocks_account_with_corporate_action_history() -> None:
    """Bare numeric prices cannot revalue a dividend-bearing account."""

    account = _create_account_with_position(username="ash05-legacy-price-basis")
    _posting_use_case().execute((_cash_entitlement_request(account),))

    with pytest.raises(BusinessLogicError) as error:
        DjangoPositionRepository().update_position_prices({_ASSET_CODE: 9.8})

    assert error.value.code == "POSITION_PRICE_BASIS_UNVERIFIED"
    account.refresh_from_db()
    position = PositionModel.objects.get(account=account, asset_code=_ASSET_CODE)
    assert position.current_price == Decimal("10.0000")
    assert account.total_value == Decimal("10100.00")
