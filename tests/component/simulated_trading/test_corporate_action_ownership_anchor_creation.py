"""SQLite component checks for prospective immutable account ownership anchors."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import connection, models, transaction

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.simulated_trading.application.canonical_account_creation_row import (
    CanonicalAccountCreationRowCommand,
    CanonicalAccountCreationRowCorruption,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.order_reservation import ReserveSimulatedOrderUseCase
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount
from apps.simulated_trading.infrastructure import (
    canonical_account_creation_row_writer as canonical_row_writer_module,
)
from apps.simulated_trading.infrastructure.account_gateway import _provision_default_accounts
from apps.simulated_trading.infrastructure.account_repository import (
    DjangoSimulatedAccountRepository,
)
from apps.simulated_trading.infrastructure.canonical_account_creation_row_writer import (
    DjangoCanonicalAccountCreationRowWriter,
)
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    DjangoCorporateActionOwnershipHistoryRepository,
    QualifiedExchangeTimezone,
    _create_zero_origin_anchor_for_inserted_account,
    create_simulated_account_with_zero_origin_anchor,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.models import FeeConfigModel
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_ownership_anchor_models import (
    SimulatedAccountOwnershipAnchorModel,
    simulated_account_ownership_anchor_sha256,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from core.exceptions import BusinessLogicError
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _calendar,
    _Clock,
    _execute_use_case,
    _seed_fee_policy,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _EventReader,
    _FixedClock,
    _initial_position_mark,
    _InitialPositionMarkReader,
    _invoke,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    _reader_rows,
)
from tests.component.simulated_trading.test_order_reservation_repository import _Harness
from tests.support.isolated_schema import isolated_schema

_SCHEMA_MODELS: tuple[type[models.Model], ...] = (
    get_user_model(),
    AccountProfileModel,
    SimulatedAccountModel,
    PositionModel,
    SimulatedTradeModel,
    SimulatedOrderReservationModel,
    SimulatedOrderFillReceiptModel,
    FeeConfigModel,
    CorporateActionPostingModel,
    SimulatedAccountOwnershipAnchorModel,
)


@dataclass(frozen=True, slots=True)
class _ForbiddenTimezonePolicyReader:
    """Prove an unqualified no-fill account never requests a guessed exchange."""

    def read_exchange_timezone_policy(
        self,
        *,
        exchange: str,
        as_of: datetime,
    ) -> QualifiedExchangeTimezone:
        """Fail the test if unsupported account history reaches timezone lookup."""

        del exchange, as_of
        raise AssertionError("exchange must come from a cutoff-known target V4 fill")


@dataclass(frozen=True, slots=True)
class _FixedTimezonePolicyReader:
    """Return one exact test exchange and timezone policy binding."""

    exchange: str

    def read_exchange_timezone_policy(
        self,
        *,
        exchange: str,
        as_of: datetime,
    ) -> QualifiedExchangeTimezone:
        """Return the configured exchange and explicit test policy provenance."""

        assert exchange == self.exchange
        assert as_of.tzinfo is not None
        return QualifiedExchangeTimezone(
            exchange=exchange,
            timezone_name="Asia/Shanghai",
            policy_id="test-exchange-timezone-policy.v1",
            policy_sha256="f" * 64,
        )


@pytest.fixture
def isolated_ownership_ledger(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[AbstractBaseUser]:
    """Create only user and simulated ownership tables in isolated SQLite memory."""

    database_blocker = request.getfixturevalue("django_db_blocker")
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    with database_blocker.unblock():
        original_database_name = connection.settings_dict["NAME"]
        database_path = (
            Path(__file__).resolve().parents[3]
            / "artifacts"
            / "ash05-ownership-20261110"
            / "ownership-component.sqlite3"
        )
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection.close()
        connection.settings_dict["NAME"] = str(database_path)
        try:
            with isolated_schema(_SCHEMA_MODELS):
                user = get_user_model().objects.create_user(
                    username="ownership-anchor-owner",
                    password="unused",
                )
                yield user
        finally:
            connection.close()
            connection.settings_dict["NAME"] = original_database_name


def test_default_account_gateway_creates_one_anchor_and_replays_duplicate_call(
    isolated_ownership_ledger: AbstractBaseUser,
) -> None:
    """Only its fresh simulated default receives one immutable zero-origin row."""

    _provision_default_accounts(isolated_ownership_ledger, Decimal("12000.00"))
    _provision_default_accounts(isolated_ownership_ledger, Decimal("12000.00"))

    simulated_accounts = SimulatedAccountModel._default_manager.filter(
        user_id=isolated_ownership_ledger.pk,
        account_type="simulated",
    )
    real_accounts = SimulatedAccountModel._default_manager.filter(
        user_id=isolated_ownership_ledger.pk,
        account_type="real",
    )
    anchors = SimulatedAccountOwnershipAnchorModel._default_manager.all()

    assert simulated_accounts.count() == 1
    assert real_accounts.count() == 1
    assert anchors.count() == 1
    anchor = anchors.get()
    account = simulated_accounts.get()
    assert anchor.account_id == account.pk
    assert anchor.owner_user_id == isolated_ownership_ledger.pk
    assert anchor.account_created_at == account.created_at
    assert anchor.quantity == Decimal("0.000000")
    assert anchor.evidence_sha256 == simulated_account_ownership_anchor_sha256(
        account_id=account.pk,
        owner_user_id=isolated_ownership_ledger.pk,
        anchor_id=anchor.anchor_id,
        account_created_at=account.created_at,
        observed_at=anchor.created_at,
        anchor_kind=SimulatedAccountOwnershipAnchorModel.ZERO_ORIGIN,
        quantity=Decimal("0.000000"),
    )


def test_account_repository_user_creation_anchors_only_simulated_accounts(
    isolated_ownership_ledger: AbstractBaseUser,
) -> None:
    """The owner-facing creation path anchors its new simulated account only."""

    repository = DjangoSimulatedAccountRepository()
    simulated = repository.create_account_model_for_user(
        user=isolated_ownership_ledger,
        account_name="owner-facing-simulated",
        account_type="simulated",
        initial_capital=Decimal("5000.00"),
    )
    real = repository.create_account_model_for_user(
        user=isolated_ownership_ledger,
        account_name="owner-facing-real",
        account_type="real",
        initial_capital=Decimal("3000.00"),
    )

    assert (
        SimulatedAccountOwnershipAnchorModel._default_manager.filter(
            account_id=simulated.pk
        ).count()
        == 1
    )
    assert not SimulatedAccountOwnershipAnchorModel._default_manager.filter(
        account_id=real.pk
    ).exists()


def _canonical_account_command(
    *, user_id: int, account_type: AccountType
) -> CanonicalAccountCreationRowCommand:
    """Return one unsaved canonical account-row command for component checks."""

    return CanonicalAccountCreationRowCommand(
        requester_user_id=user_id,
        account=SimulatedAccount(
            account_id=0,
            account_name=f"canonical-{account_type.value}",
            account_type=account_type,
            initial_capital=1000.0,
            current_cash=1000.0,
            current_market_value=0.0,
            total_value=1000.0,
            start_date=date(2026, 1, 1),
        ),
        observation_id=f"canonical-create-{account_type.value}",
        mutation_version="v1",
    )


def test_canonical_account_creation_anchors_only_fresh_simulated_rows(
    isolated_ownership_ledger: AbstractBaseUser,
) -> None:
    """The authenticated canonical row writer anchors simulated inserts only."""

    writer = DjangoCanonicalAccountCreationRowWriter(using="default")
    with transaction.atomic():
        simulated = writer.execute(
            _canonical_account_command(
                user_id=isolated_ownership_ledger.pk,
                account_type=AccountType.SIMULATED,
            )
        )
        real = writer.execute(
            _canonical_account_command(
                user_id=isolated_ownership_ledger.pk,
                account_type=AccountType.REAL,
            )
        )

    assert (
        SimulatedAccountOwnershipAnchorModel._default_manager.filter(
            account_id=simulated.account.account_id
        ).count()
        == 1
    )
    assert not SimulatedAccountOwnershipAnchorModel._default_manager.filter(
        account_id=real.account.account_id
    ).exists()


def test_canonical_account_creation_rolls_back_when_anchor_insert_fails(
    isolated_ownership_ledger: AbstractBaseUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An anchor failure rolls back the account row inside the writer savepoint."""

    def fail_anchor_insert(*, account: SimulatedAccountModel, using: str) -> None:
        del account, using
        raise BusinessLogicError(
            "injected anchor failure",
            code="CORPORATE_ACTION_OWNERSHIP_ANCHOR_TEST_FAILURE",
        )

    monkeypatch.setattr(
        canonical_row_writer_module,
        "_create_zero_origin_anchor_for_inserted_account",
        fail_anchor_insert,
    )
    writer = DjangoCanonicalAccountCreationRowWriter(using="default")
    with transaction.atomic():
        with pytest.raises(CanonicalAccountCreationRowCorruption):
            writer.execute(
                _canonical_account_command(
                    user_id=isolated_ownership_ledger.pk,
                    account_type=AccountType.SIMULATED,
                )
            )
        assert not SimulatedAccountModel._default_manager.filter(
            account_name="canonical-simulated"
        ).exists()
        assert SimulatedAccountOwnershipAnchorModel._default_manager.count() == 0


@pytest.mark.parametrize("failure_point", ["uow", "claim"])
def test_canonical_account_creation_maps_anchor_uow_failures_and_rolls_back(
    isolated_ownership_ledger: AbstractBaseUser,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    """Setup or claim failures are typed and never leave a simulated account row."""

    @contextmanager
    def fail_uow(*, using: str) -> Iterator[object]:
        del using
        raise BusinessLogicError(
            "injected ownership UOW failure",
            code="CORPORATE_ACTION_OWNERSHIP_ANCHOR_TEST_FAILURE",
        )
        yield object()

    @contextmanager
    def fail_claim(*, token: object, account: SimulatedAccountModel, using: str) -> Iterator[None]:
        del token, account, using
        raise BusinessLogicError(
            "injected ownership claim failure",
            code="CORPORATE_ACTION_OWNERSHIP_ANCHOR_TEST_FAILURE",
        )
        yield

    if failure_point == "uow":
        monkeypatch.setattr(
            canonical_row_writer_module,
            "_activate_new_account_creation_uow",
            fail_uow,
        )
    else:
        monkeypatch.setattr(
            canonical_row_writer_module,
            "_claim_new_account_for_anchor",
            fail_claim,
        )

    writer = DjangoCanonicalAccountCreationRowWriter(using="default")
    with transaction.atomic():
        with pytest.raises(CanonicalAccountCreationRowCorruption):
            writer.execute(
                _canonical_account_command(
                    user_id=isolated_ownership_ledger.pk,
                    account_type=AccountType.SIMULATED,
                )
            )
        assert not SimulatedAccountModel._default_manager.filter(
            account_name="canonical-simulated"
        ).exists()
        assert SimulatedAccountOwnershipAnchorModel._default_manager.count() == 0


def test_anchor_create_fails_closed_for_direct_insert_and_old_account_backfill(
    isolated_ownership_ledger: AbstractBaseUser,
) -> None:
    """No generic writer can attach a forged or retroactive zero-origin row."""

    old_account = SimulatedAccountModel._default_manager.create(
        user=isolated_ownership_ledger,
        account_name="old-unanchored-account",
        account_type="simulated",
        initial_capital=Decimal("1000.00"),
        current_cash=Decimal("1000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("1000.00"),
    )

    with pytest.raises(BusinessLogicError) as backfill:
        _create_zero_origin_anchor_for_inserted_account(account=old_account, using="default")
    assert backfill.value.code == "CORPORATE_ACTION_OWNERSHIP_ANCHOR_BACKFILL_BLOCKED"

    anchor_id = f"simulated-account-zero-origin.v1:{old_account.pk}"
    observed_at = old_account.created_at
    forged = SimulatedAccountOwnershipAnchorModel(
        account_id=old_account.pk,
        owner_user_id=isolated_ownership_ledger.pk,
        anchor_id=anchor_id,
        anchor_kind=SimulatedAccountOwnershipAnchorModel.ZERO_ORIGIN,
        quantity=Decimal("0.000000"),
        account_created_at=old_account.created_at,
        evidence_sha256=simulated_account_ownership_anchor_sha256(
            account_id=old_account.pk,
            owner_user_id=isolated_ownership_ledger.pk,
            anchor_id=anchor_id,
            account_created_at=old_account.created_at,
            observed_at=observed_at,
            anchor_kind=SimulatedAccountOwnershipAnchorModel.ZERO_ORIGIN,
            quantity=Decimal("0.000000"),
        ),
        created_at=observed_at,
    )
    with pytest.raises(ValidationError, match="精确的账户创建声明"):
        forged.save(using="default")

    assert not SimulatedAccountOwnershipAnchorModel._default_manager.filter(
        account_id=old_account.pk
    ).exists()


def test_anchor_failure_rolls_back_fresh_account_insert(
    isolated_ownership_ledger: AbstractBaseUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The account row cannot commit without its required anchor row."""

    def fail_anchor_save(
        self: SimulatedAccountOwnershipAnchorModel, *args: Any, **kwargs: Any
    ) -> None:
        del self, args, kwargs
        raise ValidationError("synthetic anchor storage failure")

    monkeypatch.setattr(SimulatedAccountOwnershipAnchorModel, "save", fail_anchor_save)
    with pytest.raises(ValidationError, match="synthetic anchor storage failure"):
        create_simulated_account_with_zero_origin_anchor(
            user=isolated_ownership_ledger,
            account_name="rollback-account",
            initial_capital=Decimal("2000.00"),
            using="default",
        )

    assert not SimulatedAccountModel._default_manager.filter(
        user_id=isolated_ownership_ledger.pk,
        account_name="rollback-account",
    ).exists()
    assert not SimulatedAccountOwnershipAnchorModel._default_manager.exists()


def test_anchored_accounts_block_delete_and_destructive_reset(
    isolated_ownership_ledger: AbstractBaseUser,
) -> None:
    """Physical deletion and ledger reset would destroy the immutable replay base."""

    account = create_simulated_account_with_zero_origin_anchor(
        user=isolated_ownership_ledger,
        account_name="retained-history-account",
        initial_capital=Decimal("2000.00"),
        using="default",
    )
    repository = DjangoSimulatedAccountRepository()

    for operation in (
        lambda: repository.delete(account.pk),
        lambda: repository.delete_account_with_summary(account.pk),
        lambda: repository.reset_account_with_summary(account.pk),
    ):
        with pytest.raises(BusinessLogicError) as blocked:
            operation()
        assert blocked.value.code == "SIMULATED_ACCOUNT_OWNERSHIP_HISTORY_RETAINED"

    assert SimulatedAccountModel._default_manager.filter(pk=account.pk).exists()
    assert SimulatedAccountOwnershipAnchorModel._default_manager.filter(
        account_id=account.pk
    ).exists()


def test_read_only_verifier_blocks_without_a_cutoff_known_target_exchange_fill(
    isolated_ownership_ledger: AbstractBaseUser,
) -> None:
    """A zero anchor alone cannot invent exchange identity or caller evidence."""

    account = create_simulated_account_with_zero_origin_anchor(
        user=isolated_ownership_ledger,
        account_name="no-fill-proof-account",
        initial_capital=Decimal("2000.00"),
        using="default",
    )
    repository = DjangoCorporateActionOwnershipHistoryRepository(
        exchange_timezone_policy_reader=_ForbiddenTimezonePolicyReader(),
        using="default",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        repository.read_record_date_ownership_proof(
            account_id=account.pk,
            owner_user_id=isolated_ownership_ledger.pk,
            security_id="SZ.SECURITY.NO-FILL",
            asset_code="600001.SH",
            record_date=date(2026, 11, 11),
            evidence_cutoff_at=datetime(2026, 11, 12, tzinfo=UTC),
        )

    assert blocked.value.code == "CORPORATE_ACTION_OWNERSHIP_EXCHANGE_UNAVAILABLE"


def test_read_only_verifier_blocks_legacy_trade_without_v4_receipt(
    isolated_ownership_ledger: AbstractBaseUser,
) -> None:
    """A mutable legacy Trade row cannot be mistaken for immutable ownership proof."""

    account = create_simulated_account_with_zero_origin_anchor(
        user=isolated_ownership_ledger,
        account_name="legacy-trade-proof-account",
        initial_capital=Decimal("2000.00"),
        using="default",
    )
    SimulatedTradeModel._default_manager.create(
        account=account,
        asset_code="600001.SH",
        asset_name="Legacy row",
        asset_type="equity",
        action="buy",
        quantity=Decimal("10.000000"),
        price=Decimal("10.0000"),
        amount=Decimal("100.00"),
        total_cost=Decimal("100.00"),
        order_date=date(2026, 11, 10),
        execution_date=date(2026, 11, 10),
        status="executed",
    )
    repository = DjangoCorporateActionOwnershipHistoryRepository(
        exchange_timezone_policy_reader=_ForbiddenTimezonePolicyReader(),
        using="default",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        repository.read_record_date_ownership_proof(
            account_id=account.pk,
            owner_user_id=isolated_ownership_ledger.pk,
            security_id="SZ.SECURITY.LEGACY",
            asset_code="600001.SH",
            record_date=date(2026, 11, 11),
            evidence_cutoff_at=datetime(2026, 11, 12, tzinfo=UTC),
        )

    assert blocked.value.code == "CORPORATE_ACTION_OWNERSHIP_RECEIPT_UNSUPPORTED"


def test_read_only_verifier_replays_a_persisted_v4_fill(
    isolated_ownership_ledger: AbstractBaseUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticate zero-origin, complete V4 receipt, exchange policy, and replay."""

    fee_config = FeeConfigModel._default_manager.create(
        config_name="ownership-test-fees",
        asset_type="equity",
        commission_rate_buy=0.0003,
        commission_rate_sell=0.0003,
        min_commission=1.0,
        stamp_duty_rate=0.001,
        transfer_fee_rate=0.00002,
        min_transfer_fee=0.0,
        slippage_rate=0.001,
        is_default=False,
        is_active=False,
    )
    _seed_fee_policy(fee_config)
    anchor_clock = AS_OF - timedelta(days=1)
    monkeypatch.setattr("django.utils.timezone.now", lambda: anchor_clock)
    account = create_simulated_account_with_zero_origin_anchor(
        user=isolated_ownership_ledger,
        account_name="ownership-v4-proof-account",
        initial_capital=Decimal("100000.00"),
        using="default",
    )

    fill_clock = AS_OF + timedelta(minutes=3)
    monkeypatch.setattr("django.utils.timezone.now", lambda: fill_clock)
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
        exchange="SH",
    )
    preparer, rule_reader, _ = _execute_use_case(
        account_id=account.pk,
        user_id=isolated_ownership_ledger.pk,
        as_of=AS_OF,
        evidence=evidence,
    )
    reservation_repository = DjangoSimulatedOrderReservationRepository(using="default")
    harness = _Harness(
        account=account,
        user_id=isolated_ownership_ledger.pk,
        repository=reservation_repository,
        preparer=preparer,
        reserve=ReserveSimulatedOrderUseCase(
            preparer=preparer,
            repository=reservation_repository,
            clock=_Clock(AS_OF),
        ),
        rule_reader=rule_reader,
    )
    rows = _reader_rows(harness)
    rows.reservation.refresh_from_db()
    fill_repository = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(rows.event, []),
        initial_position_mark_reader=_InitialPositionMarkReader(
            _initial_position_mark(rows),
            [],
        ),
        using="default",
    )
    _invoke(
        fill_repository,
        rows.event,
        rows.proof,
        clock=_FixedClock(fill_clock),
    )

    ownership_repository = DjangoCorporateActionOwnershipHistoryRepository(
        exchange_timezone_policy_reader=_FixedTimezonePolicyReader("SH"),
        using="default",
    )
    proof = ownership_repository.read_record_date_ownership_proof(
        account_id=account.pk,
        owner_user_id=isolated_ownership_ledger.pk,
        security_id=rows.event.security_id,
        asset_code=rows.event.asset_code,
        record_date=date(2026, 10, 17),
        evidence_cutoff_at=datetime(2026, 10, 18, 0, 0, tzinfo=UTC),
    )

    assert proof.eligible_quantity == Decimal("10.000000")
    assert proof.exchange == "SH"
    assert proof.ownership_snapshot_as_of_date == date(2026, 10, 17)
    assert len(proof.ownership_snapshot_sha256) == 64
