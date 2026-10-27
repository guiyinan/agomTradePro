"""Owner-scoped read-only fee correction head repository acceptance."""

from __future__ import annotations

import os
import tempfile
from copy import copy
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.account.infrastructure.account_authority_generation_models import (
    AccountAuthorityGenerationModel,
)
from apps.simulated_trading.application.fee_correction import (
    ApplySimulatedFeeCorrectionUseCase,
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
    FeeCorrectionRequest,
)
from apps.simulated_trading.application.fee_correction_evidence import (
    FeeCorrectionEvidenceUploadCommand,
    FeeCorrectionEvidenceUploadUseCase,
)
from apps.simulated_trading.domain.entities import OrderStatus
from apps.simulated_trading.infrastructure import fee_correction_head_repository
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidenceBindingModel,
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.fee_correction_head_repository import (
    DjangoFeeCorrectionHeadRepository,
)
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel
from tests.component.simulated_trading.test_fee_correction_repository import (
    _CountingClock,
    _csv_bytes,
    _LedgerFixture,
    _run_apply,
    _seed_ledger,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _seed_authority_generation_without_migrations(django_db_use_migrations: bool) -> None:
    """Seed only the missing 0065 row in an isolated SQLite no-migrations test DB."""

    if django_db_use_migrations or connection.vendor != "sqlite":
        return
    active_name = str(connection.settings_dict["NAME"])
    memory_database = active_name == ":memory:" or (
        active_name.startswith("file:memorydb_") and "mode=memory" in active_name
    )
    if not memory_database:
        test_name = connection.settings_dict["TEST"].get("NAME")
        if not isinstance(test_name, str) or not test_name:
            raise AssertionError("The SQLite no-migrations test database is not identified.")
        active_path = Path(active_name).resolve()
        if (
            active_path != Path(test_name).resolve()
            or active_path.parent
            != (Path(tempfile.gettempdir()) / "agomtradepro-test-databases").resolve()
            or active_path.name != f"test_db_{os.getpid()}.sqlite3"
        ):
            raise AssertionError("Refusing to seed authority generation outside isolated SQLite.")
    AccountAuthorityGenerationModel.objects.get_or_create(
        singleton=1,
        defaults={"generation": 0},
    )
    rows = list(AccountAuthorityGenerationModel.objects.values_list("singleton", "generation"))
    if len(rows) != 1 or rows[0][0] != 1 or type(rows[0][1]) is not int or rows[0][1] < 0:
        raise AssertionError("The Account authority singleton is absent or malformed.")


def _head_repository() -> DjangoFeeCorrectionHeadRepository:
    """Build the production head repository for component acceptance."""

    return DjangoFeeCorrectionHeadRepository()


def _after_latest_event(monkeypatch: pytest.MonkeyPatch, ledger: _LedgerFixture) -> datetime:
    """Fix the repository clock just after the persisted latest event."""

    latest = (
        SimulatedFeeCorrectionEventModel.objects.filter(
            account_id=ledger.account.pk,
            trade_id=ledger.trade.pk,
        )
        .order_by("-revision", "-pk")
        .first()
    )
    assert latest is not None
    as_of = latest.posted_at + timedelta(microseconds=1)
    monkeypatch.setattr(fee_correction_head_repository.timezone, "now", lambda: as_of)
    return as_of


def _append_second_correction(ledger: _LedgerFixture) -> SimulatedFeeCorrectionEventModel:
    """Append a second real correction with a new source binding and predecessor."""

    previous = SimulatedFeeCorrectionEventModel.objects.get(
        account_id=ledger.account.pk,
        trade_id=ledger.trade.pk,
        revision=1,
    )
    idempotency_key = f"fee-correction-head-{uuid4().hex}"
    observed_at = timezone.now() - timedelta(seconds=1)
    content = _csv_bytes(
        account_id=ledger.account.pk,
        trade=ledger.trade,
        source_observed_at=observed_at,
        commission=Decimal("10.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    )
    uploaded = FeeCorrectionEvidenceUploadUseCase(ledger.evidence_repository).execute(
        FeeCorrectionEvidenceUploadCommand(
            account_id=ledger.account.pk,
            trade_id=ledger.trade.pk,
            expected_revision=1,
            expected_predecessor_id=previous.pk,
            idempotency_key=idempotency_key,
            original_filename="fee-correction-head-second.csv",
            content=content,
            attestation_acknowledged=True,
        ),
        principal=ledger.owner,
    )
    request = FeeCorrectionRequest(
        account_id=ledger.account.pk,
        trade_id=ledger.trade.pk,
        idempotency_key=idempotency_key,
        expected_revision=1,
        source_locator=uploaded.source_locator,
    )
    clock = _CountingClock(previous.posted_at + timedelta(minutes=1))
    receipt = ApplySimulatedFeeCorrectionUseCase(
        repository=ledger.repository,
        evidence_verifier=ledger.evidence_repository,
        authority=ledger.evidence_repository,
        clock=clock,
    ).execute(request, principal=ledger.owner)
    return SimulatedFeeCorrectionEventModel.objects.get(pk=receipt.event_id)


def _append_correction_for_another_trade(
    ledger: _LedgerFixture,
) -> SimulatedFeeCorrectionEventModel:
    """Create a second reconciled BUY and retain a correction under its own key."""

    now = timezone.now()
    execution_time = now - timedelta(minutes=20)
    amount = Decimal("100.00")
    quantity = Decimal("10.000000")
    commission = Decimal("2.00")
    slippage = Decimal("0.02")
    total_cost = amount + commission + slippage
    second_trade = SimulatedTradeModel.objects.create(
        account=ledger.account,
        asset_code=ledger.trade.asset_code,
        asset_name="Second fee correction fixture",
        asset_type="equity",
        action="buy",
        quantity=quantity,
        price=Decimal("10.0000"),
        amount=amount,
        commission=commission,
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
        slippage=slippage,
        total_cost=total_cost,
        fee_amounts_known=True,
        cost_basis_known=True,
        realized_pnl=None,
        realized_pnl_pct=None,
        order_date=execution_time.date(),
        execution_date=execution_time.date(),
        execution_time=execution_time,
        status="executed",
    )
    new_position_quantity = ledger.position.quantity + quantity
    new_position_total_cost = ledger.position.total_cost + total_cost
    ledger.position.quantity = new_position_quantity
    ledger.position.available_quantity += quantity
    ledger.position.total_cost = new_position_total_cost
    ledger.position.avg_cost = (new_position_total_cost / new_position_quantity).quantize(
        Decimal("0.0001")
    )
    ledger.position.market_value += amount
    ledger.position.unrealized_pnl = ledger.position.market_value - new_position_total_cost
    ledger.position.save(
        update_fields=(
            "quantity",
            "available_quantity",
            "total_cost",
            "avg_cost",
            "market_value",
            "unrealized_pnl",
            "last_update_date",
        )
    )
    ledger.account.current_cash -= total_cost
    ledger.account.current_market_value += amount
    ledger.account.total_value = ledger.account.current_cash + ledger.account.current_market_value
    ledger.account.save(
        update_fields=("current_cash", "current_market_value", "total_value", "updated_at")
    )

    idempotency_key = f"fee-correction-head-other-{uuid4().hex}"
    content = _csv_bytes(
        account_id=ledger.account.pk,
        trade=second_trade,
        source_observed_at=now - timedelta(minutes=5),
        commission=Decimal("3.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    )
    uploaded = FeeCorrectionEvidenceUploadUseCase(ledger.evidence_repository).execute(
        FeeCorrectionEvidenceUploadCommand(
            account_id=ledger.account.pk,
            trade_id=second_trade.pk,
            expected_revision=0,
            expected_predecessor_id=None,
            idempotency_key=idempotency_key,
            original_filename="fee-correction-head-other-trade.csv",
            content=content,
            attestation_acknowledged=True,
        ),
        principal=ledger.owner,
    )
    receipt = ApplySimulatedFeeCorrectionUseCase(
        repository=ledger.repository,
        evidence_verifier=ledger.evidence_repository,
        authority=ledger.evidence_repository,
        clock=_CountingClock(now + timedelta(minutes=1)),
    ).execute(
        FeeCorrectionRequest(
            account_id=ledger.account.pk,
            trade_id=second_trade.pk,
            idempotency_key=idempotency_key,
            expected_revision=0,
            source_locator=uploaded.source_locator,
        ),
        principal=ledger.owner,
    )
    return SimulatedFeeCorrectionEventModel.objects.get(pk=receipt.event_id)


def _assert_authority_denied(
    ledger: _LedgerFixture,
    principal: AuthenticatedFeeCorrectionPrincipalProtocol,
) -> None:
    """Require the same non-disclosing denial for an unauthorized principal."""

    with pytest.raises(FeeCorrectionBlockedError) as denied:
        _head_repository().get_head(
            account_id=ledger.account.pk,
            trade_id=ledger.trade.pk,
            principal=principal,
        )
    assert denied.value.code == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"
    with pytest.raises(FeeCorrectionBlockedError) as locator_denied:
        _head_repository().get_head(
            account_id=ledger.account.pk,
            trade_id=ledger.trade.pk,
            principal=principal,
            source_locator=ledger.request.source_locator,
        )
    assert locator_denied.value.code == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"


def test_head_without_corrections_is_zero_and_read_only() -> None:
    """An empty validated chain returns revision zero without creating ledger rows."""

    ledger = _seed_ledger(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    event_count = SimulatedFeeCorrectionEventModel.objects.filter(
        account_id=ledger.account.pk
    ).count()
    policy = FeeCorrectionEvidencePolicyModel.objects.get(account_id=ledger.account.pk)
    policy_version = policy.version

    head = _head_repository().get_head(
        account_id=ledger.account.pk,
        trade_id=ledger.trade.pk,
        principal=ledger.owner,
    )

    assert head.account_id == ledger.account.pk
    assert head.trade_id == ledger.trade.pk
    assert head.revision == 0
    assert head.expected_predecessor_id is None
    assert head.request_receipt is None
    assert head.trade.status is OrderStatus.EXECUTED
    assert head.trade.current_commission == 7.0
    assert (
        SimulatedFeeCorrectionEventModel.objects.filter(account_id=ledger.account.pk).count()
        == event_count
    )
    policy.refresh_from_db()
    assert policy.version == policy_version


def test_head_uses_latest_id_from_the_validated_multi_event_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The next predecessor is the final validated event, not the first event."""

    ledger = _seed_ledger(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    first_receipt = _run_apply(
        ledger,
        _CountingClock(timezone.now() + timedelta(minutes=1)),
    ).execute(ledger.request, principal=ledger.owner)
    latest = _append_second_correction(ledger)
    as_of = _after_latest_event(monkeypatch, ledger)

    head = _head_repository().get_head(
        account_id=ledger.account.pk,
        trade_id=ledger.trade.pk,
        principal=ledger.owner,
    )

    assert latest.pk != first_receipt.event_id
    assert head.as_of == as_of
    assert head.revision == 2
    assert head.expected_predecessor_id == latest.pk
    assert head.trade.fee_correction_revision == 2
    assert head.trade.current_commission == 10.0


def test_head_returns_original_request_receipt_after_a_later_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An old idempotency key reads its exact event after the chain advances."""

    ledger = _seed_ledger(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    original = _run_apply(
        ledger,
        _CountingClock(timezone.now() + timedelta(minutes=1)),
    ).execute(ledger.request, principal=ledger.owner)
    latest = _append_second_correction(ledger)
    _after_latest_event(monkeypatch, ledger)

    head = _head_repository().get_head(
        account_id=ledger.account.pk,
        trade_id=ledger.trade.pk,
        principal=ledger.owner,
        request_key=ledger.request.idempotency_key,
    )

    assert head.revision == 2
    assert head.expected_predecessor_id == latest.pk
    assert head.request_receipt is not None
    assert head.request_receipt.event_id == original.event_id
    assert head.request_receipt.revision == 1
    assert head.request_receipt.replayed is True


def test_head_resolves_evidence_locator_for_its_exact_request_and_trade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persisted evidence locator resolves only its bound trade's original event."""

    ledger = _seed_ledger(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    original = _run_apply(
        ledger,
        _CountingClock(timezone.now() + timedelta(minutes=1)),
    ).execute(ledger.request, principal=ledger.owner)
    _after_latest_event(monkeypatch, ledger)

    recovered = _head_repository().get_head(
        account_id=ledger.account.pk,
        trade_id=ledger.trade.pk,
        principal=ledger.owner,
        source_locator=ledger.request.source_locator,
    )

    assert recovered.request_receipt is not None
    assert recovered.request_receipt.event_id == original.event_id
    assert SimulatedFeeCorrectionEventModel.objects.get(pk=original.event_id).source_record_id == (
        ledger.request.source_locator
    )


def test_head_locator_rejects_event_bound_to_different_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The binding check rejects a mismatched event copy without mutating stored history."""

    ledger = _seed_ledger(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    receipt = _run_apply(
        ledger,
        _CountingClock(timezone.now() + timedelta(minutes=1)),
    ).execute(ledger.request, principal=ledger.owner)
    _after_latest_event(monkeypatch, ledger)

    ledger.account.refresh_from_db()
    cash_before = ledger.account.current_cash
    event_count_before = SimulatedFeeCorrectionEventModel.objects.filter(
        account_id=ledger.account.pk
    ).count()
    stored_event = SimulatedFeeCorrectionEventModel.objects.get(pk=receipt.event_id)
    original_validator = fee_correction_head_repository._validate_event_source_binding

    def validate_mismatched_event_copy(
        *,
        event: SimulatedFeeCorrectionEventModel,
        binding: FeeCorrectionEvidenceBindingModel,
    ) -> None:
        """Alter only the in-memory event passed to the actual validator."""

        mismatched_event = copy(event)
        mismatched_event.source_record_id = "00000000-0000-0000-0000-000000000001"
        original_validator(event=mismatched_event, binding=binding)

    monkeypatch.setattr(
        fee_correction_head_repository,
        "_validate_event_source_binding",
        validate_mismatched_event_copy,
    )
    with pytest.raises(FeeCorrectionBlockedError) as blocked:
        _head_repository().get_head(
            account_id=ledger.account.pk,
            trade_id=ledger.trade.pk,
            principal=ledger.owner,
            source_locator=ledger.request.source_locator,
        )
    assert blocked.value.code == "FEE_CORRECTION_HISTORY_INVALID"
    stored_event.refresh_from_db()
    assert stored_event.source_record_id == ledger.request.source_locator
    ledger.account.refresh_from_db()
    assert ledger.account.current_cash == cash_before
    assert (
        SimulatedFeeCorrectionEventModel.objects.filter(account_id=ledger.account.pk).count()
        == event_count_before
    )


def test_head_rejects_idempotency_key_owned_by_another_trade() -> None:
    """An account-local key bound to another Trade is a conflict, not a miss."""

    ledger = _seed_ledger(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    other_trade_event = _append_correction_for_another_trade(ledger)

    with pytest.raises(FeeCorrectionBlockedError) as conflict:
        _head_repository().get_head(
            account_id=ledger.account.pk,
            trade_id=ledger.trade.pk,
            principal=ledger.owner,
            request_key=other_trade_event.idempotency_key,
        )

    assert conflict.value.code == "FEE_CORRECTION_IDEMPOTENCY_CONFLICT"
    with pytest.raises(FeeCorrectionBlockedError) as locator_denied:
        _head_repository().get_head(
            account_id=ledger.account.pk,
            trade_id=ledger.trade.pk,
            principal=ledger.owner,
            source_locator=other_trade_event.source_record_id,
        )
    assert locator_denied.value.code == "FEE_CORRECTION_EVIDENCE_NOT_FOUND"


def test_head_reads_validated_history_when_current_policy_is_disabled_and_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Historical visibility does not depend on whether new corrections remain enabled."""

    ledger = _seed_ledger(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    receipt = _run_apply(
        ledger,
        _CountingClock(timezone.now() + timedelta(minutes=1)),
    ).execute(ledger.request, principal=ledger.owner)
    event = SimulatedFeeCorrectionEventModel.objects.get(pk=receipt.event_id)
    policy = FeeCorrectionEvidencePolicyModel.objects.get(account_id=ledger.account.pk)
    policy.enabled = False
    policy.allow_operator_attested_upload = False
    policy.valid_until = event.posted_at - timedelta(seconds=1)
    policy.save(update_fields=("enabled", "allow_operator_attested_upload", "valid_until"))
    _after_latest_event(monkeypatch, ledger)

    head = _head_repository().get_head(
        account_id=ledger.account.pk,
        trade_id=ledger.trade.pk,
        principal=ledger.owner,
        request_key=ledger.request.idempotency_key,
    )

    assert head.revision == 1
    assert head.expected_predecessor_id == receipt.event_id
    assert head.trade.current_commission == 9.0
    assert head.request_receipt is not None
    assert head.request_receipt.event_id == receipt.event_id
    assert head.request_receipt.replayed is True

    locator_head = _head_repository().get_head(
        account_id=ledger.account.pk,
        trade_id=ledger.trade.pk,
        principal=ledger.owner,
        source_locator=ledger.request.source_locator,
    )
    assert locator_head.request_receipt is not None
    assert locator_head.request_receipt.event_id == receipt.event_id


def test_head_rejects_foreign_superuser_and_inactive_owner() -> None:
    """Staff privilege cannot bypass current account ownership or actor activity."""

    ledger = _seed_ledger(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    user_model = get_user_model()
    suffix = uuid4().hex
    foreign_superuser = user_model.objects.create_superuser(
        username=f"foreign-head-{suffix}",
        email=f"foreign-head-{suffix}@example.test",
        password="unused",
    )
    _assert_authority_denied(ledger, foreign_superuser)

    ledger.owner.is_active = False
    ledger.owner.save(update_fields=("is_active",))
    _assert_authority_denied(ledger, ledger.owner)


def test_head_rejects_inactive_and_real_accounts() -> None:
    """The head is available only for an active simulated account."""

    inactive = _seed_ledger(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    inactive.account.is_active = False
    inactive.account.save(update_fields=("is_active",))
    _assert_authority_denied(inactive, inactive.owner)

    real = _seed_ledger(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    real.account.account_type = "real"
    real.account.save(update_fields=("account_type",))
    _assert_authority_denied(real, real.owner)


def test_head_blocks_a_future_correction_instead_of_reporting_zero() -> None:
    """A validated but not-yet-visible event cannot be mistaken for an empty head."""

    ledger = _seed_ledger(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    _run_apply(
        ledger,
        _CountingClock(timezone.now() + timedelta(hours=1)),
    ).execute(ledger.request, principal=ledger.owner)

    with pytest.raises(FeeCorrectionBlockedError) as blocked:
        _head_repository().get_head(
            account_id=ledger.account.pk,
            trade_id=ledger.trade.pk,
            principal=ledger.owner,
        )
    assert blocked.value.code == "FEE_CORRECTION_HISTORY_INVALID"


def test_head_propagates_corrupt_history_instead_of_falling_back_to_zero() -> None:
    """A broken persisted event digest remains blocked by the full history validator."""

    ledger = _seed_ledger(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    receipt = _run_apply(
        ledger,
        _CountingClock(timezone.now() + timedelta(minutes=1)),
    ).execute(ledger.request, principal=ledger.owner)
    table = connection.ops.quote_name(SimulatedFeeCorrectionEventModel._meta.db_table)
    column = connection.ops.quote_name("request_payload_hash")
    primary_key = connection.ops.quote_name(SimulatedFeeCorrectionEventModel._meta.pk.column)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET {column} = %s WHERE {primary_key} = %s",
            ["f" * 64, receipt.event_id],
        )

    with pytest.raises(FeeCorrectionBlockedError):
        _head_repository().get_head(
            account_id=ledger.account.pk,
            trade_id=ledger.trade.pk,
            principal=ledger.owner,
        )


def test_head_blocks_when_target_trade_fee_or_basis_is_unknown() -> None:
    """Unknown legacy financial facts are not exposed as a valid correction head."""

    ledger = _seed_ledger(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    SimulatedTradeModel._base_manager.filter(pk=ledger.trade.pk).update(
        fee_amounts_known=None,
        cost_basis_known=None,
    )

    with pytest.raises(FeeCorrectionBlockedError) as blocked:
        _head_repository().get_head(
            account_id=ledger.account.pk,
            trade_id=ledger.trade.pk,
            principal=ledger.owner,
        )
    assert blocked.value.code == "FEE_CORRECTION_ASSET_HISTORY_UNKNOWN"
