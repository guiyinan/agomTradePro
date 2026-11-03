"""Native PostgreSQL acceptance for locked portfolio-risk order reservations."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Event, Lock
from typing import cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.db import DEFAULT_DB_ALIAS, connection
from django.utils import timezone

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.risk_center.application.portfolio_baseline_risk import (
    PortfolioBaselinePolicyReader,
)
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetsReader,
    PortfolioRiskAssetsReadRequest,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_execution_evidence import (
    PortfolioRiskExecutionEvidence,
    PortfolioRiskExecutionEvidenceWriter,
)
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskPolicyConfigurationError,
    PortfolioRiskPolicyReader,
    PortfolioRiskPolicyReadResult,
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.application.portfolio_risk_runtime import (
    PortfolioPressureApplicationFactory,
    PortfolioRiskRuntime,
)
from apps.risk_center.application.scenario_ports import (
    ScenarioRunEvidenceRepositoryProtocol,
)
from apps.risk_center.domain.portfolio_capacity import CapacityValue
from apps.risk_center.infrastructure.models import RiskPolicyAuditModel
from apps.risk_center.infrastructure.portfolio_risk_execution_evidence_repository import (
    DjangoPortfolioRiskExecutionEvidenceWriter,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
)
from apps.simulated_trading.application.order_reservation import (
    ReserveSimulatedOrderUseCase,
)
from apps.simulated_trading.application.portfolio_risk_calendar import (
    PortfolioRiskCalendarReader,
)
from apps.simulated_trading.application.portfolio_risk_context import (
    PortfolioRiskClock,
    PortfolioRiskPressureRunner,
)
from apps.simulated_trading.application.portfolio_risk_execution_gate import (
    ConfiguredPortfolioRiskLockedOrderGuard,
)
from apps.simulated_trading.application.portfolio_risk_public import (
    PortfolioRiskService,
)
from apps.simulated_trading.application.portfolio_risk_resource_ports import (
    AccountSnapshotReadResult,
    PortfolioRiskAccountScope,
    PortfolioRiskResourceSnapshotReaderProtocol,
)
from apps.simulated_trading.application.portfolio_risk_service import (
    OwnerScopedPortfolioRiskService,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from apps.simulated_trading.infrastructure.performance_repositories import (
    DjangoObserverGrantRepository,
)
from apps.simulated_trading.infrastructure.portfolio_risk_resource_repository import (
    DjangoPortfolioRiskResourceRepository,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    _bundle,
    _calendar,
    _execute_use_case,
    _seed_fee_policy,
)
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _assert_account_parent_lock_wait,
    _submit_worker,
    _wait_for_account_parent_lock,
)
from tests.support.isolated_schema import isolated_schema
from tests.support.native_postgres_database import assert_native_postgres_test_database
from tests.unit.simulated_trading import test_portfolio_risk_service as risk_fixtures

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.account",
        "apps.risk_center",
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)


@pytest.fixture(autouse=True)
def _require_migrated_native_postgres(django_db_use_migrations: bool) -> None:
    """Require the existing isolated, migrated PostgreSQL test database."""

    if not django_db_use_migrations:
        pytest.skip("portfolio-risk row-lock acceptance requires migrated test tables")
    if connection.vendor != "postgresql":
        pytest.skip("portfolio-risk row-lock acceptance requires PostgreSQL")
    assert_native_postgres_test_database()


@dataclass(frozen=True, slots=True)
class _NativeLedger:
    """The exact owner ledger and current planning cutoff for one test."""

    account: SimulatedAccountModel
    account_id: int
    owner_user_id: int
    cutoff: datetime
    session: date


@pytest.fixture
def native_ledger(monkeypatch: pytest.MonkeyPatch) -> Iterator[_NativeLedger]:
    """Create one real account and one current, source-backed FeeV2 row."""

    cutoff = timezone.now().astimezone(UTC)
    session = cutoff.astimezone(ZoneInfo("Asia/Shanghai")).date()
    import tests.component.simulated_trading.test_execution_settlement_uow as uow_fixtures

    monkeypatch.setattr(uow_fixtures, "AS_OF", cutoff)
    user_model = get_user_model()
    model_types = (
        user_model,
        AccountProfileModel,
        SimulatedAccountModel,
        PositionModel,
        SimulatedTradeModel,
        FeeConfigModel,
        SimulatedOrderReservationModel,
        RiskPolicyAuditModel,
    )
    with isolated_schema(model_types):
        user = user_model._default_manager.create_user(
            username=f"risk-native-{uuid4().hex}",
            password="unused",
        )
        account = SimulatedAccountModel._default_manager.create(
            user=user,
            account_name=f"risk-native-account-{uuid4().hex}",
            account_type="simulated",
            initial_capital=Decimal("100000.00"),
            current_cash=Decimal("100000.00"),
            current_market_value=Decimal("0.00"),
            total_value=Decimal("100000.00"),
            is_active=True,
        )
        fee_row = FeeConfigModel._default_manager.create(
            config_name=f"risk-native-fee-{uuid4().hex}",
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
        _seed_fee_policy(fee_row)
        assert type(account.pk) is int
        assert type(user.pk) is int
        yield _NativeLedger(
            account=account,
            account_id=account.pk,
            owner_user_id=user.pk,
            cutoff=cutoff,
            session=session,
        )


class _LiveClock:
    """Use the real server clock so snapshot reads always precede their cutoff."""

    def now(self) -> datetime:
        """Return current aware UTC time without manufacturing a future observation."""

        return timezone.now().astimezone(UTC)


class _StepClock:
    """Advance only the final locked ledger clock for the source-expiry case."""

    def __init__(self, values: tuple[datetime | None, ...]) -> None:
        """Retain real-clock reads and any explicit final transition cutoff."""

        self._values = values
        self.calls = 0

    def now(self) -> datetime:
        """Return the next scripted transition clock, then retain its final value."""

        value = self._values[min(self.calls, len(self._values) - 1)]
        self.calls += 1
        return timezone.now().astimezone(UTC) if value is None else value


class _ReadTrackingResourceReader:
    """Observe active-order counts while delegating every read to the real repository."""

    def __init__(self, delegate: DjangoPortfolioRiskResourceRepository) -> None:
        """Wrap the actual account-scoped ORM reader without replacing its behavior."""

        self._delegate = delegate
        self.active_order_counts: list[int] = []
        self._lock = Lock()

    def read_account_snapshot(
        self,
        *,
        user_id: int,
        account_id: int,
        execution_session: date,
        money_unit: str | None,
    ) -> AccountSnapshotReadResult:
        """Read exact locked values and record the number of real active holds."""

        result = self._delegate.read_account_snapshot(
            user_id=user_id,
            account_id=account_id,
            execution_session=execution_session,
            money_unit=money_unit,
        )
        if result.snapshot is not None:
            with self._lock:
                self.active_order_counts.append(len(result.snapshot.active_orders))
        return result

    def read_account_scope(
        self, *, user_id: int, account_id: int
    ) -> PortfolioRiskAccountScope | None:
        """Preserve the repository's real owner and observer scope result."""

        return self._delegate.read_account_scope(user_id=user_id, account_id=account_id)


class _LimitedCapacityAssetsReader(risk_fixtures._AssetsReader):
    """Use the real test DTOs with an explicit 200-share, two-session window."""

    def read_assets(self, request: PortfolioRiskAssetsReadRequest) -> PortfolioRiskAssetsReadResult:
        """Retain source evidence and domain inputs while tightening only volume."""

        result = super().read_assets(request)
        assets = tuple(
            (
                replace(
                    asset,
                    capacity_observation=replace(
                        asset.capacity_observation,
                        volume=CapacityValue(Decimal("200"), "share"),
                    ),
                )
                if asset.capacity_observation is not None
                else asset
            )
            for asset in result.assets
        )
        return replace(result, assets=assets)


class _ObservedAuditWriter(DjangoPortfolioRiskExecutionEvidenceWriter):
    """Write real audit rows, with an optional post-write pause inside the UOW."""

    def __init__(
        self,
        *,
        using: str,
        pause_key: str | None = None,
        audit_written: Event | None = None,
        continue_write: Event | None = None,
    ) -> None:
        """Configure observation after the inherited database insert."""

        super().__init__(using=using)
        self._pause_key = pause_key
        self._audit_written = audit_written
        self._continue_write = continue_write
        self.attempted_keys: list[str] = []

    def record_passed_check(self, evidence: PortfolioRiskExecutionEvidence) -> None:
        """Persist through the real writer, then expose the still-open transaction."""

        super().record_passed_check(evidence)
        self.attempted_keys.append(evidence.idempotency_key)
        if evidence.idempotency_key != self._pause_key:
            return
        if self._audit_written is None or self._continue_write is None:
            raise AssertionError("paused audit writer requires both synchronization events")
        self._audit_written.set()
        if not self._continue_write.wait(timeout=20):
            raise AssertionError("test did not release the locked audit-writing transaction")


@dataclass(frozen=True, slots=True)
class _ReservationAttempt:
    """Keep the actual reservation result or risk rejection from one worker."""

    result: object | None
    blocked_code: str | None
    reason_codes: tuple[str, ...]


def _reservation_attempt(
    reserve: ReserveSimulatedOrderUseCase,
    intent: SimulatedTradeIntent,
    *,
    as_of: datetime,
) -> _ReservationAttempt:
    """Run the actual reservation use case and retain typed risk-block evidence."""

    try:
        return _ReservationAttempt(
            result=reserve.execute(intent, fee_budget=Decimal("5.00"), as_of=as_of),
            blocked_code=None,
            reason_codes=(),
        )
    except SimulatedTradeExecutionBlocked as error:
        raw_reasons = error.details.get("reason_codes")
        reasons = (
            tuple(item for item in raw_reasons if type(item) is str)
            if type(raw_reasons) is list
            else ()
        )
        return _ReservationAttempt(
            result=None,
            blocked_code=error.code,
            reason_codes=reasons,
        )


class _NativePolicyReader:
    """Reparse one immutable runtime profile against each actual service cutoff."""

    def __init__(self, ledger: _NativeLedger) -> None:
        """Keep persisted profile clocks fixed and prepare this account's test value."""

        self._value = risk_fixtures._configuration()
        self._account_id = ledger.account_id
        self._profile_id = f"native-risk-profile-{ledger.account_id}"
        self._profile_key = f"native-risk-profile-key-{ledger.account_id}"
        self._snapshot_id = f"native-risk-snapshot-{ledger.account_id}"
        self._created_at = ledger.cutoff - timedelta(minutes=3)
        self._effective_at = ledger.cutoff - timedelta(minutes=2)
        self._snapshot_generated_at = ledger.cutoff - timedelta(minutes=1)
        self.reads: list[tuple[int, datetime, date]] = []

    def read_policy(
        self,
        *,
        as_of: datetime,
        business_date: date,
        account_id: int,
    ) -> PortfolioRiskPolicyReadResult:
        """Bind identical immutable profile content to the exact requested cutoff."""

        self.reads.append((account_id, as_of, business_date))
        evidence = ActiveRuntimeValueEvidence(
            environment="test",
            definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
            value=self._value,
            profile_id=self._profile_id,
            profile_key=self._profile_key,
            profile_version=12,
            profile_content_hash="e" * 64,
            snapshot_id=self._snapshot_id,
            snapshot_hash="f" * 64,
            created_at=self._created_at,
            known_at=self._created_at,
            activated_at=self._effective_at,
            snapshot_generated_at=self._snapshot_generated_at,
            effective_at=self._effective_at,
            as_of=as_of,
        )
        try:
            policy = parse_portfolio_risk_policy_bundle(
                evidence,
                business_date=business_date,
                as_of=as_of,
            )
        except PortfolioRiskPolicyConfigurationError as error:
            return PortfolioRiskPolicyReadResult(
                policy=None,
                reason_codes=(error.reason_code,),
            )
        if account_id != self._account_id:
            return PortfolioRiskPolicyReadResult(
                policy=None,
                reason_codes=("SIMULATED_PORTFOLIO_RISK_ACCOUNT_SCOPE_INVALID",),
            )
        return PortfolioRiskPolicyReadResult(policy=policy, reason_codes=())


def _compose_risk_service(
    *,
    ledger: _NativeLedger,
    monkeypatch: pytest.MonkeyPatch,
    writer: _ObservedAuditWriter,
) -> tuple[OwnerScopedPortfolioRiskService, _ReadTrackingResourceReader]:
    """Compose the real service/repository/writer with explicit typed source ports."""

    monkeypatch.setattr(risk_fixtures, "_AS_OF", ledger.cutoff)
    monkeypatch.setattr(risk_fixtures, "_BUSINESS_DATE", ledger.session)
    monkeypatch.setattr(risk_fixtures, "_SESSION", ledger.session)
    monkeypatch.setattr(risk_fixtures, "_ACCOUNT_ID", ledger.account_id)
    monkeypatch.setattr(risk_fixtures, "_OWNER_ID", ledger.owner_user_id)
    monkeypatch.setattr(risk_fixtures, "_ASSET_CODE", "600000.SH")
    monkeypatch.setattr(risk_fixtures, "_SECURITY_ID", "SH.UOW.SECURITY")
    policy_reader = _NativePolicyReader(ledger)
    resource_repository = DjangoPortfolioRiskResourceRepository(
        using=DEFAULT_DB_ALIAS,
        observer_grant_repository=DjangoObserverGrantRepository(using=DEFAULT_DB_ALIAS),
    )
    resources = _ReadTrackingResourceReader(resource_repository)
    runtime = PortfolioRiskRuntime(
        policy_reader=cast(PortfolioRiskPolicyReader, policy_reader),
        assets_reader=cast(PortfolioRiskAssetsReader, _LimitedCapacityAssetsReader()),
        baseline_reader=cast(
            PortfolioBaselinePolicyReader,
            risk_fixtures._BaselineReader(risk_fixtures._baseline_policy()),
        ),
        execution_evidence_writer=cast(PortfolioRiskExecutionEvidenceWriter, writer),
        pressure_factory=cast(PortfolioPressureApplicationFactory, object()),
        pressure_evidence_repository=cast(
            ScenarioRunEvidenceRepositoryProtocol,
            object(),
        ),
    )
    service = OwnerScopedPortfolioRiskService(
        resources=cast(PortfolioRiskResourceSnapshotReaderProtocol, resources),
        runtime=runtime,
        clock=cast(PortfolioRiskClock, _LiveClock()),
        business_timezone=ZoneInfo("Asia/Shanghai"),
        code_version="portfolio-risk-native-postgres-test",
        using=DEFAULT_DB_ALIAS,
        pressure_runner=cast(PortfolioRiskPressureRunner, object()),
        calendar_reader=cast(PortfolioRiskCalendarReader, risk_fixtures._CalendarReader()),
    )
    import apps.simulated_trading.application.portfolio_risk_public as public_risk

    monkeypatch.setattr(
        public_risk,
        "_service_factory",
        lambda using: cast(PortfolioRiskService, service),
    )
    return service, resources


def _compose_reserver(
    *,
    ledger: _NativeLedger,
    clock: SimulatedTradeExecutionClock,
    valid_until: datetime | None = None,
) -> ReserveSimulatedOrderUseCase:
    """Reuse the complete execution, fee and published-calendar test plan."""

    bundle = _bundle(as_of=ledger.cutoff, valid_until=valid_until)
    evidence = _calendar(
        as_of=ledger.cutoff,
        open_dates={
            ledger.session,
            ledger.session + timedelta(days=1),
            ledger.session + timedelta(days=2),
        },
        exchange="SH",
        start=ledger.session,
        end=ledger.session + timedelta(days=2),
    )
    preparer, _, _ = _execute_use_case(
        account_id=ledger.account_id,
        user_id=ledger.owner_user_id,
        as_of=ledger.cutoff,
        evidence=evidence,
        rule_bundle=bundle,
    )
    repository = DjangoSimulatedOrderReservationRepository(
        using=DEFAULT_DB_ALIAS,
        portfolio_risk_guard=ConfiguredPortfolioRiskLockedOrderGuard(using=DEFAULT_DB_ALIAS),
    )
    return ReserveSimulatedOrderUseCase(
        preparer=preparer,
        repository=repository,
        clock=clock,
    )


def _intent(ledger: _NativeLedger, *, key: str) -> SimulatedTradeIntent:
    """Create one exact 45-share BUY using the existing full order contract."""

    return SimulatedTradeIntent(
        account_id=ledger.account_id,
        user_id=ledger.owner_user_id,
        idempotency_key=key,
        side=SimulatedTradeSide.BUY,
        security_id="SH.UOW.SECURITY",
        asset_code="600000.SH",
        asset_name="Test security",
        asset_type="equity",
        market="SH",
        board="MAIN",
        quantity=Decimal("45"),
        price=Decimal("10.00"),
        reason="native portfolio-risk reservation acceptance",
        signal_id=None,
    )


def test_native_postgres_serializes_risk_qualified_reservations_and_counts_first_hold(
    native_ledger: _NativeLedger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second BUY reads the committed first hold and exceeds the exact capacity."""

    audit_written = Event()
    continue_write = Event()
    first_key = "pg-risk-first-buy"
    writer = _ObservedAuditWriter(
        using=DEFAULT_DB_ALIAS,
        pause_key=first_key,
        audit_written=audit_written,
        continue_write=continue_write,
    )
    _, resources = _compose_risk_service(
        ledger=native_ledger,
        monkeypatch=monkeypatch,
        writer=writer,
    )
    reserve = _compose_reserver(ledger=native_ledger, clock=_LiveClock())
    first_intent = _intent(native_ledger, key=first_key)
    second_intent = _intent(native_ledger, key="pg-risk-second-buy")

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="portfolio-risk-reserve") as pool:
        first_worker = _submit_worker(
            pool,
            lambda: _reservation_attempt(reserve, first_intent, as_of=native_ledger.cutoff),
        )
        if not audit_written.wait(timeout=15):
            if first_worker.future.done():
                worker_outcome = first_worker.future.result(timeout=0)
                attempt = worker_outcome.value
                if isinstance(attempt, _ReservationAttempt):
                    pytest.fail(
                        "first risk audit was not written inside its UOW: "
                        f"blocked_code={attempt.blocked_code!r}, "
                        f"reason_codes={attempt.reason_codes!r}"
                    )
                pytest.fail(
                    "first risk audit was not written inside its UOW: "
                    f"worker_value={attempt!r}, "
                    f"worker_blocked_code={worker_outcome.blocked_code!r}, "
                    f"backend_pids={first_worker.backend_pids!r}"
                )
            pytest.fail(
                "first risk audit was not written inside its UOW and worker is still pending: "
                f"backend_pids={first_worker.backend_pids!r}"
            )
        second_worker = None
        try:
            second_worker = _submit_worker(
                pool,
                lambda: _reservation_attempt(reserve, second_intent, as_of=native_ledger.cutoff),
            )
            wait = _wait_for_account_parent_lock(
                waiter_pid=second_worker.backend_pids[0],
                allowed_blocker_pids=(first_worker.backend_pids[0],),
                future=second_worker.future,
            )
            _assert_account_parent_lock_wait(wait)
            assert first_worker.backend_pids[0] in wait.blocker_pids
        finally:
            continue_write.set()
        first_outcome = first_worker.future.result(timeout=25)
        assert second_worker is not None
        second_outcome = second_worker.future.result(timeout=25)

    first_attempt = cast(_ReservationAttempt, first_outcome.value)
    second_attempt = cast(_ReservationAttempt, second_outcome.value)
    assert first_attempt.blocked_code is None
    assert first_attempt.result is not None
    assert second_attempt.result is None
    assert second_attempt.blocked_code == "PORTFOLIO_RISK_NOT_QUALIFIED"
    assert any(code.startswith("CAPACITY_") for code in second_attempt.reason_codes)
    assert resources.active_order_counts == [0, 1]

    active_rows = list(
        SimulatedOrderReservationModel._default_manager.using(DEFAULT_DB_ALIAS).filter(
            account_id=native_ledger.account_id,
            status=SimulatedOrderReservationModel.STATUS_ACTIVE,
        )
    )
    assert len(active_rows) == 1
    assert active_rows[0].idempotency_key == first_key
    audits = list(
        RiskPolicyAuditModel._default_manager.using(DEFAULT_DB_ALIAS)
        .filter(actor_id=native_ledger.owner_user_id, action="portfolio_preexecution")
        .values_list("after", flat=True)
    )
    assert len(audits) == 1
    assert audits[0]["idempotency_key"] == first_key
    assert (
        SimulatedTradeModel._default_manager.using(DEFAULT_DB_ALIAS)
        .filter(account_id=native_ledger.account_id)
        .count()
        == 0
    )


def test_native_postgres_rolls_back_risk_audit_when_locked_source_expires(
    native_ledger: _NativeLedger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A passed risk audit is rolled back when the original execution source expires."""

    key = "pg-risk-source-expiry-buy"
    writer = _ObservedAuditWriter(using=DEFAULT_DB_ALIAS)
    _compose_risk_service(ledger=native_ledger, monkeypatch=monkeypatch, writer=writer)
    clock_start = timezone.now().astimezone(UTC)
    final_clock = clock_start + timedelta(minutes=10)
    if final_clock.astimezone(ZoneInfo("Asia/Shanghai")).date() != native_ledger.session:
        pytest.skip("source-expiry rollback needs a second clock in the same exchange session")
    source_expiry = clock_start + timedelta(minutes=3)
    clock = _StepClock((None, final_clock))
    reserve = _compose_reserver(
        ledger=native_ledger,
        clock=clock,
        valid_until=source_expiry,
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        reserve.execute(
            _intent(native_ledger, key=key),
            fee_budget=Decimal("5.00"),
            as_of=native_ledger.cutoff,
        )

    assert blocked.value.code == "ORDER_RESERVATION_PLAN_STALE", (
        f"actual code={blocked.value.code!r}; "
        f"risk reason_codes={blocked.value.details.get('reason_codes')!r}; "
        f"details={blocked.value.details!r}"
    )
    assert clock.calls == 2
    assert writer.attempted_keys == [key]
    assert (
        not RiskPolicyAuditModel._default_manager.using(DEFAULT_DB_ALIAS)
        .filter(
            actor_id=native_ledger.owner_user_id,
            action="portfolio_preexecution",
        )
        .exists()
    )
    assert (
        not SimulatedOrderReservationModel._default_manager.using(DEFAULT_DB_ALIAS)
        .filter(
            account_id=native_ledger.account_id,
        )
        .exists()
    )
    assert (
        not SimulatedTradeModel._default_manager.using(DEFAULT_DB_ALIAS)
        .filter(
            account_id=native_ledger.account_id,
        )
        .exists()
    )
    native_ledger.account.refresh_from_db(using=DEFAULT_DB_ALIAS)
    assert native_ledger.account.current_cash == Decimal("100000.00")
