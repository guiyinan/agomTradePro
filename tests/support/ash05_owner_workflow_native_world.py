"""Real migrated owner/account setup for ASH-05 workflow acceptance inputs.

The account, canonical binding, V4 fills, source captures, owner consent, and
Audit authority use existing application pipelines.  The exchange and legal
documents supplied by the paired source helper are synthetic and make no claim
of official-event or real-tax qualification.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.db import connection, transaction
from django.utils import timezone

import tests.support.simulated_tax_model_native_context as native_context
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION,
)
from apps.account.infrastructure.owner_tenant_authority_v3_repository import (
    DjangoOwnerTenantAuthorityV3Repository,
)
from apps.account.simulated_corporate_action_consent_terms import (
    SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V3,
)
from apps.account.simulated_corporate_action_policy_scope_composition import (
    SIMULATED_ACTION_WRITE_POLICY_KEY,
    SIMULATED_ACTION_WRITE_POLICY_SCHEMA_V3,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.system_audit_runtime_readiness_composition import (
    read_system_audit_runtime_readiness,
)
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.data_center.application.public import get_asset_repository_port
from apps.data_center.domain.entities import AssetMaster
from apps.data_center.domain.enums import AssetType, MarketExchange
from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    TaxCashCoverageQuery,
    TaxCashCoverageSnapshot,
    TaxCashCoverageStatus,
)
from apps.simulated_trading.corporate_action_share_tax_policy_composition import (
    SHARE_CAPITAL_TAX_MODELS_KEY,
)
from apps.simulated_trading.domain.corporate_action_capital_tax_terms import (
    CapitalTaxSourceOrigin,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
    SimulatedDividendTaxExchange,
    SimulatedDividendTaxInstrumentKind,
    SimulatedDividendTaxPersona,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_classification_reader,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
)
from core.integration.config_center_runtime import get_active_runtime_snapshot_evidence
from core.integration.system_audit_runtime_config import load_system_audit_runtime_config
from shared.config.secrets import get_secrets
from tests.component.simulated_trading import test_execution_settlement_uow as execution_fixtures
from tests.support.ash03_auto_calendar_fixture import persist_auto_uow_formal_calendar
from tests.support.ash05_owner_workflow_native_sources import (
    SyntheticSzseCapture,
    append_owner_workflow_statutory_bundles,
    cash_distribution_capture,
    install_synthetic_szse_capture_transport,
    owner_workflow_statutory_bodies,
    rights_issue_capture,
    share_distribution_capture,
)
from tests.support.ash07_owner_account_authority import (
    OwnerAccountSeed,
    audit_runtime_patch,
    create_owner_account_seed,
    issue_current_owner_audit_selector,
    publish_current_owner_policy,
)
from tests.support.simulated_tax_model_native_account import create_public_nonstaff_tax_owner_seed
from tests.support.simulated_tax_model_native_context import (
    _ASSET_CODE,
    _EXCHANGE,
    _TIMEZONE,
    _activate_tax_runtime,
    _Clock,
    _record_v4_fill,
    _refresh_public_owner_source_after_fills,
    _seed_sz_fee_policy,
)
from tests.support.simulated_tax_model_native_sources import (
    retain_synthetic_current_cny_instrument,
)

TERMS_V3_SHA256 = "b625c087151f8e580ca48cdfa4dac6a2bded6bb8c7413fe6629c4b3ebc6bdbc4"
_DISCLOSURE_COVERAGE_POLICY_KEY = "config_center.market.simulated_disclosure_coverage_policy"
_OWNER_WORKFLOW_RUNTIME_KEY = "config_center.simulated_trading.corporate_action_workflow_runtime"
_TIMEZONE_POLICY = ZoneInfo(_TIMEZONE)
_CAPABILITIES = tuple(
    sorted(
        (
            Capability.CASH_STAGE_WRITE,
            Capability.TAX_ASSESS,
            Capability.TAX_WITHHOLD,
            Capability.SHARE_STAGE_WRITE,
            Capability.RIGHTS_NOT_EXERCISED,
        ),
        key=lambda item: item.value,
    )
)


@dataclass(frozen=True, slots=True)
class OwnerWorkflowNativeWorld:
    """One real owner account and the exact synthetic source/model input scope."""

    owner: OwnerAccountSeed
    audit_authority_seed: OwnerAccountSeed
    canonical_account_id: str
    account_id: int
    asset_code: str
    security_id: str
    anchor_date: date
    record_date: date
    sale_date: date
    settlement_date: date
    decision_date: date
    capture: SyntheticSzseCapture
    action_body_store_root: Path
    statutory_body_store_root: Path
    source_capture_provider_id: int
    source_capture_bundle_id: str
    source_capture_revision_set_sha256: str
    share_tax_bundle_id: str
    share_tax_bundle_sha256: str
    calendar_dataset_key: str
    eligible_quantity: Decimal
    share_delivery_date: date
    share_sellable_date: date


def _local_anchor(actual: datetime) -> tuple[date, datetime]:
    """Choose the explicit recent business-week account-origin clock."""
    anchor_date = actual.astimezone(_TIMEZONE_POLICY).date() - timedelta(days=7)
    while anchor_date.weekday() >= 5:
        anchor_date -= timedelta(days=1)
    anchor_at = datetime.combine(anchor_date, time(9, 0), tzinfo=_TIMEZONE_POLICY).astimezone(UTC)
    return anchor_date, anchor_at


def _activate_v3_policy(
    *, owner: OwnerAccountSeed, canonical_account_id: str, now: datetime
) -> None:
    """Publish the exact pinned V3 document and every separately selectable capability."""
    activate_runtime_profile_patch(
        environment="development",
        patch={
            SIMULATED_ACTION_WRITE_POLICY_KEY: {
                "schema_version": SIMULATED_ACTION_WRITE_POLICY_SCHEMA_V3,
                "enabled": True,
                "policies": [
                    {
                        "policy_id": f"ash05-owner-workflow-v3-{owner.owner.pk}",
                        "policy_version": "synthetic-workflow-v3",
                        "canonical_account_id": canonical_account_id,
                        "owner_user_id": owner.owner.pk,
                        "tenant_id": f"ash05-workflow-tenant-{owner.owner.pk}",
                        "owner_id": f"ash05-workflow-owner-{owner.owner.pk}",
                        "valid_from": (now - timedelta(minutes=2)).isoformat(),
                        "valid_until": (now + timedelta(hours=1)).isoformat(),
                        "maximum_grant_seconds": 600,
                        "permission": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION,
                        "service_actor_id": "simulated-trading",
                        "capabilities": [item.value for item in _CAPABILITIES],
                        "terms_version": SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V3,
                        "terms_sha256": TERMS_V3_SHA256,
                    }
                ],
            }
        },
        actor="ash05-synthetic-owner-workflow-policy",
        reason="explicit isolated V3 owner test policy; synthetic sources only",
    )


def _activate_official_window_policy(*, body_store_root: Path, start_on: date) -> None:
    """Enable one finite current SZSE capture window rooted at this test's origin."""
    activate_runtime_profile_patch(
        environment="development",
        patch={
            _DISCLOSURE_COVERAGE_POLICY_KEY: {
                "schema_version": "simulated-disclosure-coverage-policy.v1",
                "enabled": True,
                "source_id": "szse_official",
                "start_on": start_on.isoformat(),
                "end_on_mode": "decision_on",
                "body_store_root": str(body_store_root.resolve()),
                "policy_version": "synthetic-owner-workflow-window-v1",
                "lease_ttl_seconds": 60,
            }
        },
        actor="ash05-synthetic-owner-workflow-window",
        reason="explicit bounded test source window with synthetic transport",
    )


def _activate_share_capital_tax_model(
    *,
    owner: OwnerAccountSeed,
    canonical_account_id: str,
    bundle_id: str,
    bundle_sha256: str,
    record_date: date,
    now: datetime,
) -> None:
    """Configure one explicit retained-source simulation model for this owner.

    The scenario is synthetic and does not identify a real investor or make a
    real tax-eligibility determination. Its instrument class comes from the
    actual current reference reader, not from a fixture-side default.
    """
    classification = build_current_reference_classification_reader(
        runtime_environment="development"
    ).resolve_simulated_instrument_classification(
        security_id=_ASSET_CODE, asset_code=_ASSET_CODE, as_of=now
    )
    if classification is None:
        raise AssertionError("the actual retained synthetic instrument did not classify")
    activate_runtime_profile_patch(
        environment="development",
        patch={
            SHARE_CAPITAL_TAX_MODELS_KEY: {
                "schema": "simulated.corporate_action.share_capital_tax_models.v1",
                "models": [
                    {
                        "enabled": True,
                        "simulation_only": True,
                        "must_not_use_for_real_tax_decision": True,
                        "model_kind": "stock_issue_premium_transfer_no_withholding_simulation",
                        "model_rule_id": f"ash05-synthetic-share-capital-model-{owner.owner.pk}",
                        "simulated_asset_type": classification.simulated_asset_type,
                        "scope": {
                            "account_kind": "simulated",
                            "physical_account_id": owner.account.pk,
                            "canonical_account_id": canonical_account_id,
                            "owner_user_id": owner.owner.pk,
                            "security_id": _ASSET_CODE,
                            "asset_code": _ASSET_CODE,
                            "exchange": SimulatedDividendTaxExchange.SZ.value,
                            "persona": SimulatedDividendTaxPersona.DOMESTIC_PUBLIC_MARKET_A_SHARE.value,
                            "instrument_kind": SimulatedDividendTaxInstrumentKind.LISTED_EQUITY.value,
                            "currency": SimulatedDividendTaxCurrency.CNY.value,
                            "capital_source": CapitalTaxSourceOrigin.STOCK_ISSUE_PREMIUM_CAPITAL_RESERVE.value,
                        },
                        "valid_from": (now - timedelta(minutes=2)).isoformat(),
                        "valid_until": (now + timedelta(hours=1)).isoformat(),
                        "record_date_start": record_date.isoformat(),
                        "record_date_end": record_date.isoformat(),
                        "statutory_bundle_id": bundle_id,
                        "statutory_bundle_version": "fixture-v1",
                        "statutory_source_bundle_sha256": bundle_sha256,
                        "document_1997_id": "sat-1997-198-synthetic-test",
                        "document_1998_id": "sat-1998-289-synthetic-test",
                    }
                ],
            }
        },
        actor="ash05-synthetic-share-capital-tax-model",
        reason="explicit simulation-only model and retained synthetic statute pair",
    )


def _activate_workflow_runtime(
    *,
    calendar_dataset_key: str,
    provider_id: int,
    statutory_body_store_root: Path,
) -> None:
    """Bind the owner workflow to the exact persisted calendar and retained-source store."""
    activate_runtime_profile_patch(
        environment="development",
        patch={
            _OWNER_WORKFLOW_RUNTIME_KEY: {
                "schema": "simulated.corporate_action.owner_workflow_runtime.v1",
                "calendar_dataset_key": calendar_dataset_key,
                "statutory_provider_id": provider_id,
                "statutory_body_store_root": str(statutory_body_store_root.resolve()),
                "deployment_region": "ash05-native-qa",
            },
            "config_center.market.exchange_timezone_map": {
                _EXCHANGE: _TIMEZONE,
                "SZSE": _TIMEZONE,
            },
        },
        actor="ash05-synthetic-owner-workflow-runtime",
        reason="explicit calendar and retained statutory-source routing for native test",
    )


def _activate_audit_authority() -> OwnerAccountSeed:
    """Publish a separate actual Account-backed Audit/Outbox authority bundle."""
    audit_seed = create_owner_account_seed()
    publish_current_owner_policy(audit_seed)
    selector = issue_current_owner_audit_selector(audit_seed)
    activate_runtime_profile_patch(
        environment="development",
        patch=audit_runtime_patch(selector),
        actor="ash05-owner-workflow-audit-authority",
        reason="actual isolated SystemAudit/Outbox authority for synthetic workflow sources",
    )
    return audit_seed


def recover_owner_workflow_operator_authority(world: OwnerWorkflowNativeWorld) -> None:
    """Explicitly reapprove the test operator through fresh V5 lineage and profile CAS.

    This is independent test-operator setup between user operations. It never
    renews the ordinary owner's grant or changes an original source deadline.
    """
    started_at = timezone.now()
    environment = world.audit_authority_seed.environment
    before_lease = read_system_audit_runtime_readiness(environment=environment, using="default")
    events = tuple(
        SystemAuditEventModel.objects.order_by("pk").values_list(
            "pk", "content_hash", "canonical_payload"
        )
    )
    outbox = tuple(
        SystemAuditOutboxModel.objects.order_by("pk").values_list("pk", "payload_hash", "payload")
    )
    with transaction.atomic(using="default"):
        bundle = get_active_runtime_snapshot_evidence(
            environment=environment,
            definition_keys=(
                "audit.system_event.authority_selector",
                "audit.system_event.mode",
                "audit.system_event.outbox_enabled",
            ),
            as_of=timezone.now(),
        )
        binding = load_system_audit_runtime_config(environment=environment)
        if (
            bundle is None
            or binding.authority_selector is None
            or (bundle.profile.profile_id, bundle.profile.version, bundle.snapshot.snapshot_hash)
            != (binding.profile_id, binding.profile_version, binding.snapshot_hash)
        ):
            raise AssertionError("operator recovery requires one exact current runtime bundle")
        selector = binding.authority_selector
        repository = DjangoOwnerTenantAuthorityV3Repository(using="default")
        previous = repository.get_provisional_winner(
            authority_id=selector.scope_source_id,
            authority_version=selector.scope_source_version,
            expected_content_hash=selector.scope_content_hash,
            as_of=timezone.now(),
        )
        if (
            previous is None
            or previous.authority.actor_user_id != world.audit_authority_seed.owner.pk
        ):
            raise AssertionError("operator recovery predecessor belongs to another operator")
        selected = issue_current_owner_audit_selector(
            world.audit_authority_seed,
            previous_assignment=previous.authority.assignment,
        )
        successor = repository.get_provisional_winner(
            authority_id=selected.scope_source_id,
            authority_version=selected.scope_source_version,
            expected_content_hash=selected.scope_content_hash,
            as_of=timezone.now(),
        )
        assert successor is not None
        assert (
            successor.authority.tenant_id,
            successor.authority.owner_id,
            successor.authority.account_namespace,
            successor.authority.account_id,
            successor.authority.actor_user_id,
        ) == (
            previous.authority.tenant_id,
            previous.authority.owner_id,
            previous.authority.account_namespace,
            previous.authority.account_id,
            previous.authority.actor_user_id,
        ), "operator recovery must preserve the original Audit scope"
        activate_runtime_profile_patch(
            environment=environment,
            patch=audit_runtime_patch(selected),
            actor="ash05-explicit-test-operator-reapproval",
            reason="fresh physical observation and exact V5 receipt/evidence successor for a long synthetic journey",
            expected_active_profile_id=bundle.profile.profile_id,
            expected_active_profile_version=bundle.profile.version,
            expected_active_profile_hash=bundle.profile.content_hash,
            expected_active_snapshot_hash=bundle.snapshot.snapshot_hash,
        )
        retained = repository.get_provisional_winner(
            authority_id=selector.scope_source_id,
            authority_version=selector.scope_source_version,
            expected_content_hash=selector.scope_content_hash,
            as_of=timezone.now(),
        )
        assert retained == previous, "operator recovery must not edit original authority or lease"
        assert events == tuple(
            SystemAuditEventModel.objects.order_by("pk").values_list(
                "pk", "content_hash", "canonical_payload"
            )
        )
        assert outbox == tuple(
            SystemAuditOutboxModel.objects.order_by("pk").values_list(
                "pk", "payload_hash", "payload"
            )
        )
    after_lease = read_system_audit_runtime_readiness(environment=environment, using="default")
    checked_at = timezone.now()
    assert after_lease.valid_until is not None and checked_at < after_lease.valid_until
    output = os.environ.get("ASH05_SQL_BUDGET_DIR")
    if output:
        directory = Path(output) / "operator-reapproval"
        directory.mkdir(parents=True, exist_ok=True)
        report = {
            "started_at": started_at.isoformat(),
            "checked_at": checked_at.isoformat(),
            "old_original_valid_until": previous.authority.valid_until.isoformat(),
            "old_lease_valid_until": (
                before_lease.valid_until.isoformat() if before_lease.valid_until else None
            ),
            "new_lease_valid_until": after_lease.valid_until.isoformat(),
            "old_authority_unchanged": True,
            "original_event_outbox_unchanged": True,
            "profile_predecessor_cas": True,
            "new_v5_lineage": True,
            "original_scope_unchanged": True,
        }
        (directory / f"{uuid4().hex}.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )


def _record_owner_history(
    *,
    owner: OwnerAccountSeed,
    monkeypatch: pytest.MonkeyPatch,
    anchor_date: date,
    open_dates: tuple[date, ...],
) -> tuple[date, date, date, date]:
    """Record one actual V4 BUY, settlement release and later partial SELL."""
    release_date, record_date, sale_date, settlement_date = open_dates[0:4]
    eligible_open_dates = {
        anchor_date,
        *open_dates[0:4],
    }
    _seed_sz_fee_policy(
        monkeypatch=monkeypatch,
        as_of=datetime.combine(anchor_date, time(10, 0), tzinfo=_TIMEZONE_POLICY).astimezone(UTC),
    )
    buy = _record_v4_fill(
        monkeypatch=monkeypatch,
        account=owner.account,
        user_id=owner.owner.pk,
        key=f"ash05-workflow-buy-{uuid4().hex}",
        side=SimulatedTradeSide.BUY,
        quantity=Decimal("100"),
        price=Decimal("10.00"),
        trade_date=anchor_date,
        anchor_date=anchor_date,
        complete_through=settlement_date,
        open_dates=eligible_open_dates,
    )
    if buy.settlement_release_date != release_date:
        raise AssertionError("synthetic BUY settlement is not the next verified open session")
    release_at = datetime.combine(release_date, time(10, 0), tzinfo=_TIMEZONE_POLICY).astimezone(
        UTC
    )
    monkeypatch.setattr(timezone, "now", _Clock(release_at).now)
    release_evidence = execution_fixtures._calendar(
        as_of=release_at,
        open_dates=eligible_open_dates,
        exchange=_EXCHANGE,
        start=anchor_date,
        end=settlement_date,
    )
    from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
        DjangoSimulatedTradeExecutionRepository,
    )

    released = DjangoSimulatedTradeExecutionRepository(using="default").release_due_settlements(
        account_id=owner.account.pk,
        user_id=owner.owner.pk,
        asset_code=_ASSET_CODE,
        calendar_evidence=release_evidence,
        clock=_Clock(release_at),
    )
    if released != 1:
        raise AssertionError("the real V4 settlement release did not release the BUY")
    sale = _record_v4_fill(
        monkeypatch=monkeypatch,
        account=owner.account,
        user_id=owner.owner.pk,
        key=f"ash05-workflow-sale-{uuid4().hex}",
        side=SimulatedTradeSide.SELL,
        quantity=Decimal("30"),
        price=Decimal("10.25"),
        trade_date=sale_date,
        anchor_date=anchor_date,
        complete_through=settlement_date,
        open_dates=eligible_open_dates,
    )
    position = PositionModel.objects.using("default").get(
        account_id=owner.account.pk, asset_code=_ASSET_CODE
    )
    if position.quantity != Decimal("70.000000") or position.available_quantity != Decimal(
        "70.000000"
    ):
        raise AssertionError("the real V4 account does not retain the source-date quantity")
    if sale.settlement_release_date is not None:
        raise AssertionError("the later sale should retain its normal settlement state")
    return release_date, record_date, sale_date, settlement_date


class _HistoricalSeedTaxCashCoverage:
    """Provide an explicit synthetic coverage lease only for pre-workflow V4 seeding.

    The ordinary owner HTTP operations use the production current-coverage
    reader. This fixture-only port prevents historical V4 setup from treating
    the intentionally not-yet-created corporate-action source as a zero-debt
    production result.
    """

    database_alias = "default"

    def __init__(self, *, canonical_account_id: str, owner_user_id: int, account_id: int) -> None:
        """Bind this test-only source to one exact physical and canonical owner scope."""
        self._canonical_account_id = canonical_account_id
        self._owner_user_id = owner_user_id
        self._account_id = account_id
        self._witnesses: set[str] = set()

    def read_locked(
        self, *, physical_account_id: int, owner_user_id: int, using: str
    ) -> TaxCashCoverageSnapshot:
        """Return only a finite synthetic seed lease for the exact one-account fixture."""
        if (
            using != self.database_alias
            or physical_account_id != self._account_id
            or owner_user_id != self._owner_user_id
        ):
            raise AssertionError("historical seed coverage crossed its synthetic owner scope")
        checked_at = timezone.now().astimezone(UTC)
        query = TaxCashCoverageQuery(
            physical_account_id,
            owner_user_id,
            self._canonical_account_id,
            "development",
        )
        snapshot = TaxCashCoverageSnapshot(
            query=query,
            currency_quantum=Decimal("0.01"),
            accepted_unpaid_tax=Decimal("0.00"),
            modeled_unapplied_tax_reserve=Decimal("0.00"),
            coverage_status=TaxCashCoverageStatus.COMPLETE,
            reason_codes=(),
            checked_at=checked_at,
            coverage_known_at=checked_at - timedelta(microseconds=1),
            valid_until=checked_at + timedelta(hours=1),
            coverage_sha256=("a" * 64),
            must_not_use_for_decision=True,
        )
        self._witnesses.add(snapshot.coverage_sha256 or "")
        return snapshot

    def assert_still_current(
        self,
        snapshot: TaxCashCoverageSnapshot,
        *,
        using: str,
        expected_account_updated_at: datetime | None = None,
    ) -> None:
        """Keep the seed-only proof within the same original time lease and alias."""
        if using != self.database_alias or snapshot.coverage_sha256 not in self._witnesses:
            raise AssertionError("historical seed coverage proof was not issued here")
        snapshot.verify_for(snapshot.query, as_of=timezone.now())
        if expected_account_updated_at is not None and expected_account_updated_at > timezone.now():
            raise AssertionError("historical fixture write clock is in the future")


def _record_seeded_owner_history(
    *,
    owner: OwnerAccountSeed,
    monkeypatch: pytest.MonkeyPatch,
    anchor_date: date,
    open_dates: tuple[date, ...],
    canonical_account_id: str,
) -> tuple[date, date, date, date]:
    """Use an isolated synthetic coverage port for historical V4 fixture setup only."""
    import apps.simulated_trading.infrastructure.execution_settlement_uow_repository as trade_module
    from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
        DjangoSimulatedTradeExecutionRepository as TradeRepository,
    )
    from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
        DjangoSimulatedOrderFillRepository as FillRepository,
    )
    from apps.simulated_trading.infrastructure.order_reservation_repository import (
        DjangoSimulatedOrderReservationRepository as ReservationRepository,
    )

    coverage = _HistoricalSeedTaxCashCoverage(
        canonical_account_id=canonical_account_id,
        owner_user_id=owner.owner.pk,
        account_id=owner.account.pk,
    )
    trade_factory = partial(TradeRepository, tax_cash_coverage_reader=coverage)
    reservation_factory = partial(ReservationRepository, tax_cash_coverage_reader=coverage)
    fill_factory = partial(FillRepository, tax_cash_coverage_reader=coverage)
    with monkeypatch.context() as seed_patch:
        seed_patch.setattr(native_context, "DjangoSimulatedTradeExecutionRepository", trade_factory)
        seed_patch.setattr(trade_module, "DjangoSimulatedTradeExecutionRepository", trade_factory)
        seed_patch.setattr(
            native_context, "DjangoSimulatedOrderReservationRepository", reservation_factory
        )
        seed_patch.setattr(native_context, "DjangoSimulatedOrderFillRepository", fill_factory)
        return _record_owner_history(
            owner=owner,
            monkeypatch=monkeypatch,
            anchor_date=anchor_date,
            open_dates=open_dates,
        )


def build_owner_workflow_native_world(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capture_kind: Literal["cash", "share", "rights"] = "cash",
    payment_date_override: date | None = None,
) -> OwnerWorkflowNativeWorld:
    """Create one actual nonstaff owner and V4 history before HTTP workflow calls.

    This returns only fixture identities.  It never inserts corporate-action
    ledger rows or Audit events directly; the public refresh and workflow APIs
    do that through the production compositions.
    """
    if connection.vendor != "postgresql":
        pytest.skip("ordinary owner workflow needs the assigned migrated PostgreSQL database")
    actual_clock = timezone.now
    actual = actual_clock().astimezone(UTC)
    anchor_date, anchor_at = _local_anchor(actual)
    monkeypatch.setenv(
        "AGOMTRADEPRO_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(b"w" * 32).decode("ascii"),
    )
    get_secrets.cache_clear()
    monkeypatch.setattr(
        "tests.support.simulated_tax_model_native_context._SECURITY_ID", _ASSET_CODE
    )
    from tests.support.runtime_config import configure_critical_runtime

    monkeypatch.setattr(timezone, "now", _Clock(anchor_at).now)
    configure_critical_runtime()
    owner = create_public_nonstaff_tax_owner_seed(as_of=anchor_at)
    if owner.owner.is_staff or owner.owner.is_superuser or owner.account.user_id != owner.owner.pk:
        raise AssertionError("fixture account is not an ordinary user's public-created account")
    canonical_account_id = owner.binding.account_id_claim
    if not canonical_account_id:
        raise AssertionError("public Account binding has no canonical identity")
    monkeypatch.setattr(timezone, "now", actual_clock)

    # All source responses below are explicitly synthetic; parser, retention,
    # current-window, Audit, and Outbox components remain production code.
    instrument = retain_synthetic_current_cny_instrument(monkeypatch=monkeypatch)
    get_asset_repository_port().upsert(
        AssetMaster(
            code=_ASSET_CODE,
            name="ASH05 synthetic listed equity",
            short_name="ASH05 synthetic equity",
            asset_type=AssetType.STOCK,
            exchange=MarketExchange.SZSE,
            currency="CNY",
            extra={"synthetic_fixture": True},
        )
    )

    calendar = persist_auto_uow_formal_calendar(
        as_of=actual_clock().astimezone(UTC),
        exchange=_EXCHANGE,
        timezone_name=_TIMEZONE,
        live_clock=True,
        require_current_open_session=False,
    )
    open_dates = tuple(
        row.calendar_date
        for row in calendar.snapshot.days
        if row.is_open and row.calendar_date > anchor_date
    )
    if len(open_dates) < 5 or calendar.snapshot.coverage_start != anchor_date:
        raise AssertionError("formal exchange calendar does not cover the actual account origin")
    release_date, record_date, sale_date, settlement_date = _record_seeded_owner_history(
        owner=owner,
        monkeypatch=monkeypatch,
        anchor_date=anchor_date,
        open_dates=open_dates,
        canonical_account_id=canonical_account_id,
    )
    monkeypatch.setattr(timezone, "now", actual_clock)
    now = actual_clock().astimezone(UTC)
    _refresh_public_owner_source_after_fills(owner)
    decision_date = calendar.market_session
    payment_date = payment_date_override or decision_date
    share_delivery_date = open_dates[3]
    share_sellable_date = open_dates[4]
    if capture_kind == "cash":
        capture = cash_distribution_capture(
            asset_code=_ASSET_CODE,
            published_on=anchor_date,
            record_date=record_date,
            ex_date=settlement_date,
            payment_date=payment_date,
        )
    elif capture_kind == "share":
        capture = share_distribution_capture(
            asset_code=_ASSET_CODE,
            published_on=anchor_date,
            record_date=record_date,
            ex_date=settlement_date,
            delivery_date=share_delivery_date,
            sellable_date=share_sellable_date,
        )
    else:
        capture = rights_issue_capture(
            asset_code=_ASSET_CODE,
            published_on=settlement_date,
            record_date=record_date,
            subscription_start_date=record_date + timedelta(days=1),
            subscription_end_date=sale_date,
            actual_ex_rights_date=settlement_date,
        )
    statutory_bodies = owner_workflow_statutory_bodies()
    install_synthetic_szse_capture_transport(
        monkeypatch, capture, statutory_documents=statutory_bodies
    )
    statutory_root = (tmp_path / "statutory").resolve()
    action_root = (tmp_path / "action-window").resolve()
    (
        publisher,
        statutory_bundle,
        revision_set_sha256,
        share_tax_bundle,
    ) = append_owner_workflow_statutory_bundles(body_store_root=statutory_root)
    _activate_tax_runtime(
        account=owner.account,
        canonical_account_id=canonical_account_id,
        owner_user_id=owner.owner.pk,
        snapshot=instrument,
        bundle_id=statutory_bundle.bundle_id,
        revision_set_sha256=revision_set_sha256,
        record_date=record_date,
        convention_start=anchor_date,
        convention_end=settlement_date,
        now=now,
    )
    _activate_share_capital_tax_model(
        owner=owner,
        canonical_account_id=canonical_account_id,
        bundle_id=share_tax_bundle.bundle_id,
        bundle_sha256=share_tax_bundle.source_bundle_sha256,
        record_date=record_date,
        now=timezone.now().astimezone(UTC),
    )
    _activate_official_window_policy(body_store_root=action_root, start_on=anchor_date)
    _activate_workflow_runtime(
        calendar_dataset_key=calendar.dataset_key,
        provider_id=publisher.pk,
        statutory_body_store_root=statutory_root,
    )
    _activate_v3_policy(owner=owner, canonical_account_id=canonical_account_id, now=now)
    audit_seed = _activate_audit_authority()
    return OwnerWorkflowNativeWorld(
        owner=owner,
        audit_authority_seed=audit_seed,
        canonical_account_id=canonical_account_id,
        account_id=owner.account.pk,
        asset_code=_ASSET_CODE,
        security_id=_ASSET_CODE,
        anchor_date=anchor_date,
        record_date=record_date,
        sale_date=sale_date,
        settlement_date=settlement_date,
        decision_date=decision_date,
        capture=capture,
        action_body_store_root=action_root,
        statutory_body_store_root=statutory_root,
        source_capture_provider_id=publisher.pk,
        source_capture_bundle_id=statutory_bundle.bundle_id,
        source_capture_revision_set_sha256=revision_set_sha256,
        share_tax_bundle_id=share_tax_bundle.bundle_id,
        share_tax_bundle_sha256=share_tax_bundle.source_bundle_sha256,
        calendar_dataset_key=calendar.dataset_key,
        eligible_quantity=Decimal("100.000000"),
        share_delivery_date=share_delivery_date,
        share_sellable_date=share_sellable_date,
    )


__all__ = ("OwnerWorkflowNativeWorld", "build_owner_workflow_native_world")
