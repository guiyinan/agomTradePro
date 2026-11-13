"""Reusable real-source synthetic tax qualification and audited cash journey fixtures.

All disclosure and statutory bodies are explicit synthetic fixtures. These helpers
exercise persistence, capture, parser, consent, assessment, posting, and liability
readback paths without claiming official-source acceptance.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.db import connection, transaction
from django.test import override_settings
from django.utils import timezone

import tests.component.simulated_trading.test_execution_settlement_uow as execution_fixtures
import tests.component.simulated_trading.test_local_daily_match_repository as match_fixtures
import tests.component.simulated_trading.test_order_reservation_fill_repository as fill_fixtures
from apps.account import simulated_corporate_action_policy_scope_composition as owner_policy
from apps.account.application.physical_account_row_observation_v2 import (
    CapturePhysicalAccountRowObservationV2Command,
)
from apps.account.canonical_creation_composition import build_canonical_account_creation_stages
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    SimulatedCorporateActionWriteGrant,
)
from apps.account.simulated_corporate_action_consent_composition import (
    read_current_simulated_action_consent_metadata,
    restore_simulated_action_withdrawal_token,
)
from apps.account.simulated_corporate_action_consent_terms import (
    SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
)
from apps.audit.corporate_action_tax_assessment_composition import (
    build_tax_assessment_audit_coordinator,
)
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.data_center.application.security_disclosure_event import (
    AppendSecurityDisclosureEventUseCase,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceSnapshotRecord,
)
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
)
from apps.data_center.infrastructure.official_szse_pdf_capture import (
    CapturedOfficialSzsePdf,
    OfficialSzsePdfBodyStore,
    SzseDistributionTerms,
)
from apps.data_center.infrastructure.security_disclosure_event_repository import (
    DjangoSecurityDisclosureEventRepository,
)
from apps.data_center.security_disclosure_capture_composition import (
    read_verified_szse_distribution,
)
from apps.simulated_trading.account_physical_row_v2_composition import (
    build_account_physical_row_v2_provider,
)
from apps.simulated_trading.account_reobservation_composition import (
    build_existing_account_reobserver,
)
from apps.simulated_trading.application.account_row_reobservation import (
    ReobserveExistingAccountRowCommand,
)
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
    CorporateActionPostingReceipt,
)
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    TaxAssessmentAppendDisposition,
)
from apps.simulated_trading.application.corporate_action_tax_liability import (
    CorporateActionTaxLiabilityUseCase,
    TaxLiabilityAppendDisposition,
    TaxLiabilityEvidenceReference,
    TaxLiabilityWriteReceipt,
)
from apps.simulated_trading.application.corporate_action_tax_payment_basis import (
    SimulatedDividendPaymentBasis,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
)
from apps.simulated_trading.application.fee_policy_v2 import (
    CreateFeePolicyVersionUseCase,
    FeePolicyVersionCommand,
)
from apps.simulated_trading.application.local_daily_match import (
    LocalDailyMatchCommand,
    LocalMatchOutcome,
    RecordLocalDailyMatchUseCase,
    stable_local_daily_observation_id,
)
from apps.simulated_trading.application.order_reservation import ReserveSimulatedOrderUseCase
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    CaptureSimulatedAccountRowSourceV2Command,
)
from apps.simulated_trading.audited_corporate_action_posting_composition import (
    build_audited_cash_entitlement_use_case,
    build_audited_cash_payment_use_case,
)
from apps.simulated_trading.audited_corporate_action_tax_assessment_composition import (
    build_audited_tax_assessment_use_case,
)
from apps.simulated_trading.audited_corporate_action_tax_liability_composition import (
    build_audited_tax_liability_use_case,
)
from apps.simulated_trading.corporate_action_owner_grant_gate import (
    DjangoCorporateActionOwnerGrantGate,
)
from apps.simulated_trading.corporate_action_ownership_history_composition import (
    build_corporate_action_ownership_history_repository,
)
from apps.simulated_trading.corporate_action_tax_date_convention_composition import (
    SIMULATED_TAX_DATE_CONVENTION_KEY,
)
from apps.simulated_trading.corporate_action_tax_liability_owner_scope_composition import (
    DjangoTaxLiabilityOwnerScopeVerifier,
)
from apps.simulated_trading.corporate_action_tax_owner_scope_composition import (
    DjangoTaxAssessmentOwnerScopeVerifier,
)
from apps.simulated_trading.corporate_action_tax_policy_composition import (
    SIMULATED_DIVIDEND_TAX_POLICY_KEY,
)
from apps.simulated_trading.corporate_action_tax_qualification_composition import (
    DjangoCurrentSimulatedTaxQualificationProvider,
)
from apps.simulated_trading.corporate_action_write_scope_composition import (
    DjangoSimulatedCorporateActionWriteScopeLocker,
)
from apps.simulated_trading.creation_composition import build_simulated_account_creation_stages
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
    QualifiedCorporateActionTaxFacts,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import TaxLiabilityCashAction
from apps.simulated_trading.domain.entities import AccountType
from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    ExecutionCurrentReferenceSelectorItemV2,
    ExecutionCurrentReferenceSelectorV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.initial_position_mark import InitialPositionMarkProof
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    build_order_fill_settlement_proof,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentAllocationModel,
    CorporateActionTaxAssessmentHeaderModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_audit import (
    tax_payment_basis_artifact_id,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_payment_basis_reader import (
    read_locked_simulated_dividend_payment_basis,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)
from apps.simulated_trading.infrastructure.local_daily_match_event_reader import (
    DjangoLocalDailyMatchEventReader,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import (
    DjangoLocalDailyMatchRepository,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_row_reader import (
    read_order_reservation_fill_row,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_ownership_anchor_models import (
    SimulatedAccountOwnershipAnchorModel,
)
from apps.simulated_trading.official_disclosure_action_composition import (
    szse_action_qualification_sha256,
)
from core.exceptions import AuthorizationError, BusinessLogicError
from shared.config.secrets import get_secrets
from tests.component.account.test_simulated_corporate_action_consent_capabilities_http import (
    TERMS_SHA256,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
    _intent_for,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash03_auto_calendar_fixture import persist_auto_uow_formal_calendar
from tests.support.ash07_owner_account_authority import (
    OwnerAccountSeed,
    audit_runtime_patch,
    create_owner_account_seed,
    issue_current_owner_audit_selector,
    publish_current_owner_policy,
)
from tests.support.runtime_config import configure_critical_runtime
from tests.support.simulated_tax_model_native_account import create_public_nonstaff_tax_owner_seed
from tests.support.simulated_tax_model_native_sources import (
    append_synthetic_statutory_bundle,
    install_synthetic_document_transport,
    isolated_task_channels,
    retain_synthetic_current_cny_instrument,
    synthetic_szse_distribution_pdf,
)
from tests.unit.simulated_trading.test_creation_composition import _settings as _creation_settings

_SECURITY_ID = "ASH05.SZ.000001"

_ASSET_CODE = "000001.SZ"

_SOURCE_CODE = "000001"

_INSTRUMENT_SOURCE_CODE = "000001.SZ"

_EXCHANGE = "SZ"

_TIMEZONE = "Asia/Shanghai"


@dataclass(frozen=True, slots=True)
class _CurrentTaxQualificationContext:
    """Reusable real-current qualification plus original assessment evidence."""

    owner_seed: OwnerAccountSeed
    action: QualifiedCorporateActionTaxFacts
    action_event: SecurityDisclosureEvent
    assessment: CorporateActionTaxAssessment
    grant: SimulatedCorporateActionWriteGrant
    action_body_store_root: Path
    payment_terms: SzseDistributionTerms
    provider: DjangoCurrentSimulatedTaxQualificationProvider


@dataclass(frozen=True, slots=True)
class _Clock:
    """Provide one explicit clock to the real V4 use cases."""

    value: datetime

    def now(self) -> datetime:
        """Return the supplied aware operation instant."""

        return self.value


@dataclass(frozen=True, slots=True)
class _SZRuleReader:
    """Return the exact controlled V4 bundle for the selected SZ instrument."""

    bundle: object

    def execute(self, *, security_id: str, as_of: datetime) -> object:
        """Validate the exact security and bundle validity before V4 planning."""

        assert security_id == _SECURITY_ID
        assert self.bundle.source_available_at <= as_of < self.bundle.valid_until
        return self.bundle


@dataclass(frozen=True, slots=True)
class _SZIdentityReader:
    """Provide controlled trade identity; current tax identity is read from Data Center."""

    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> object:
        """Return one exact simulated SZ trade identity in the requested scope."""

        source = execution_fixtures._IdentityReader().get_execution_instrument_identity(
            security_id=security_id,
            asset_code=asset_code,
            as_of=as_of,
        )
        return replace(
            source,
            source_code=_SOURCE_CODE,
            source_exchange=_EXCHANGE,
            source_market="ash05-synthetic-main",
            rule_market=_EXCHANGE,
            security_id=security_id,
            asset_code=asset_code,
        )


@dataclass(frozen=True, slots=True)
class _SZCalendarReader:
    """Return the controlled exchange calendar used only by V4 test operations."""

    evidence: object

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> object:
        """Keep the V4 calendar source exact and validate its requested clock."""

        assert exchange == _EXCHANGE
        assert coverage_start is None or self.evidence.snapshot.coverage_start <= coverage_start
        self.evidence.validate_for(as_of)
        return self.evidence


def _sz_bundle(*, as_of: datetime) -> object:
    """Rebind the existing complete V4 test bundle to the explicit SZ rule market."""

    original = execution_fixtures._bundle(as_of=as_of, lag=1)
    v2 = replace(
        original.execution_submission_v2,
        execution_rule_v1=replace(
            original.execution_submission_v2.execution_rule_v1,
            security_id=_SECURITY_ID,
            market=_EXCHANGE,
            content_hash="",
        ),
        price_submission_range=replace(
            original.execution_submission_v2.price_submission_range,
            market=_EXCHANGE,
        ),
        content_hash="",
    )
    policy = replace(
        original.settlement_policy_v1,
        security_id=_SECURITY_ID,
        market=_EXCHANGE,
        bound_execution_rule_v2_hash=v2.content_hash,
        content_hash="",
    )
    return replace(
        original,
        execution_submission_v2=v2,
        settlement_policy_v1=policy,
        content_hash="",
    )


def _seed_sz_fee_policy(*, monkeypatch: pytest.MonkeyPatch, as_of: datetime) -> None:
    """Create an exact V2 fee policy through its immutable version writer."""

    recorded_at = as_of - timedelta(days=1)
    monkeypatch.setattr(timezone, "now", _Clock(recorded_at).now)
    applies = FeeApplicability.APPLIES
    cases = tuple(
        FeeTransactionCase(
            asset_type="equity",
            market=_EXCHANGE,
            board="MAIN",
            side=side,
            commission=applies,
            transfer_fee=applies,
            stamp_duty=(
                applies if side is SimulatedTradeSide.SELL else FeeApplicability.NOT_APPLICABLE
            ),
            slippage=applies,
        )
        for side in (SimulatedTradeSide.BUY, SimulatedTradeSide.SELL)
    )
    command = FeePolicyVersionCommand(
        config_name=f"ash05-sz-fee-config-{uuid4().hex}",
        asset_type="equity",
        commission_rate_buy=0.0003,
        commission_rate_sell=0.0003,
        min_commission=1.0,
        stamp_duty_rate=0.001,
        transfer_fee_rate=0.00002,
        min_transfer_fee=0.0,
        slippage_rate=0.001,
        policy_id=f"ash05-sz-fees-{uuid4().hex}",
        policy_version=1,
        account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        effective_from=recorded_at,
        valid_until=as_of + timedelta(days=30),
        transaction_cases=cases,
        description="explicit synthetic SZ fee policy for the current tax fixture",
    )
    policy = CreateFeePolicyVersionUseCase(
        repository=DjangoFeePolicyV2Repository(using="default")
    ).execute(command)
    assert policy.recorded_at == recorded_at


def _record_v4_fill(
    *,
    monkeypatch: pytest.MonkeyPatch,
    account: SimulatedAccountModel,
    user_id: int,
    key: str,
    side: SimulatedTradeSide,
    quantity: Decimal,
    price: Decimal,
    trade_date: date,
    anchor_date: date,
    complete_through: date,
    open_dates: set[date],
) -> SimulatedTradeModel:
    """Create one real reservation, matched local event, V4 fill and receipt."""

    assert type(account.pk) is int
    operation_at = datetime.combine(trade_date, time(10, 0), tzinfo=ZoneInfo(_TIMEZONE)).astimezone(
        UTC
    )
    monkeypatch.setattr(timezone, "now", _Clock(operation_at).now)
    evidence = execution_fixtures._calendar(
        as_of=operation_at,
        open_dates=open_dates,
        exchange=_EXCHANGE,
        start=anchor_date,
        end=complete_through,
    )
    bundle = _sz_bundle(as_of=operation_at)
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    rule_reader = _SZRuleReader(bundle)
    preparer = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=rule_reader,
        identity_reader=_SZIdentityReader(),
        calendar_reader=_SZCalendarReader(evidence),
        fee_policy_reader=repository,
        repository=repository,
        clock=_Clock(operation_at),
    )
    reservation_repository = DjangoSimulatedOrderReservationRepository(using="default")
    harness = _Harness(
        account=account,
        user_id=user_id,
        repository=reservation_repository,
        preparer=preparer,
        reserve=ReserveSimulatedOrderUseCase(
            preparer=preparer,
            repository=reservation_repository,
            clock=_Clock(operation_at),
        ),
        rule_reader=rule_reader,
    )
    intent = replace(
        _intent_for(
            harness,
            key=key,
            side=side,
            quantity=quantity,
            price=price,
            security_id=_SECURITY_ID,
            asset_code=_ASSET_CODE,
        ),
        market=_EXCHANGE,
        board="MAIN",
        asset_name="ASH05 synthetic listed equity",
    )
    fee_budget = Decimal("30.00") if side is SimulatedTradeSide.BUY else None
    harness.reserve.execute(intent, fee_budget=fee_budget, as_of=operation_at)
    reservation = SimulatedOrderReservationModel.objects.get(
        account_id=account.pk,
        idempotency_key=key,
    )
    match_at = operation_at + timedelta(minutes=5)
    event_at = max(
        reservation.created_at + timedelta(microseconds=1),
        match_at - timedelta(milliseconds=1),
    )
    qualified = match_fixtures._qualified_input(
        security_id=_SECURITY_ID,
        close_price=price,
        as_of=match_at,
    )
    observation = replace(
        qualified.observation,
        session_date=trade_date,
        observation_id=stable_local_daily_observation_id(_SECURITY_ID, trade_date),
        observed_at=event_at,
        available_at=match_at,
        close_price=price,
        traded_volume=Decimal("1000"),
    )
    qualified = replace(
        qualified,
        observation=observation,
        evidence=tuple(replace(row, recorded_at=match_at) for row in qualified.evidence),
    )
    match_command = LocalDailyMatchCommand(
        account_id=account.pk,
        user_id=user_id,
        order_idempotency_key=key,
        operation_key=f"ash05-tax-match-{uuid4().hex}",
        session_date=trade_date,
        qmt_binding_id=str(uuid4()),
    )
    decision = RecordLocalDailyMatchUseCase(
        repository=DjangoLocalDailyMatchRepository(using="default"),
        qualification_reader=match_fixtures._QualificationReader(qualified),
        clock=match_fixtures._FixedClock(match_at),
    ).execute(match_command)
    event = decision.event
    assert decision.result.outcome is LocalMatchOutcome.MATCHED
    assert event is not None and event.event_kind.value in {"fill", "final_fill"}
    fill_at = match_at + timedelta(minutes=2)
    settlement = build_order_fill_settlement_proof(
        calendar_evidence=evidence,
        calendar_read_cutoff=fill_at,
        fill_occurred_at=event.occurred_at,
        settlement_exchange=_EXCHANGE,
        settlement_lag_sessions=1,
    )
    mark_observed_at = fill_at - timedelta(seconds=10)
    mark_freshness_seconds = 600
    mark = InitialPositionMarkProof(
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        asset_type=reservation.asset_type,
        market=_EXCHANGE,
        board="MAIN",
        price=price,
        source_observed_at=mark_observed_at,
        source_available_at=None,
        read_at=fill_at,
        publication_as_of=fill_at - timedelta(seconds=2),
        published_at=fill_at - timedelta(seconds=1),
        valid_until=mark_observed_at + timedelta(seconds=mark_freshness_seconds),
        freshness_window_seconds=mark_freshness_seconds,
        source_identity="ash05-synthetic-unqualified-position-mark",
        source_record_id=f"ash05-mark-{uuid4().hex}",
        source_content_hash="b" * 64,
        publication_id=f"ash05-publication-{uuid4().hex}",
        publication_hash="c" * 64,
        policy_identity="ash05-synthetic-position-mark-policy.v1",
        policy_content_hash="d" * 64,
    )
    result = DjangoSimulatedOrderFillRepository(
        event_reader=DjangoLocalDailyMatchEventReader(using="default"),
        initial_position_mark_reader=fill_fixtures._InitialPositionMarkReader(proof=mark, calls=[]),
        using="default",
    ).apply_fill_event(
        event=event,
        expected_event_payload_hash=event.event_payload_hash,
        settlement_proof=settlement,
        clock=_Clock(fill_at),
    )
    trade = SimulatedTradeModel.objects.get(pk=result.trade_id)
    receipt = SimulatedOrderFillReceiptModel.objects.get(trade=trade)
    reservation.refresh_from_db()
    decoded = read_order_reservation_fill_row(
        reservation_row=reservation,
        receipt_row=receipt,
        trade_row=trade,
    )
    assert decoded.event == event
    assert receipt.source_event_id == event.source_event_id
    return trade


def _synthetic_tax_policy(revision_set_sha256: str) -> dict[str, object]:
    """Return exact explicit model terms matching the retained synthetic clauses."""

    return {
        "schema_version": "simulated_trading.deferred_dividend_tax_policy.v1",
        "policy_id": "ash05-synthetic-deferred-tax-policy",
        "version": "fixture-v1",
        "effective_from": "2015-09-09",
        "effective_through": None,
        "source_identity": f"statutory-revision-set.v1:{revision_set_sha256}",
        "source_sha256": revision_set_sha256,
        "bands": [
            {
                "band_id": "synthetic-short",
                "maximum_holding_months": 1,
                "taxable_dividend_ratio": "1",
                "withholding_rate": "0.2",
            },
            {
                "band_id": "synthetic-middle",
                "maximum_holding_months": 12,
                "taxable_dividend_ratio": "0.5",
                "withholding_rate": "0.2",
            },
            {
                "band_id": "synthetic-long",
                "maximum_holding_months": None,
                "taxable_dividend_ratio": "0",
                "withholding_rate": "0.2",
            },
        ],
        "currency_quantum": "0.01",
        "rounding_mode": "ROUND_HALF_UP",
    }


def _activate_tax_runtime(
    *,
    account: SimulatedAccountModel,
    canonical_account_id: str,
    owner_user_id: int,
    snapshot: InstrumentReferenceSnapshotRecord,
    bundle_id: str,
    revision_set_sha256: str,
    record_date: date,
    convention_start: date,
    convention_end: date,
    now: datetime,
) -> None:
    """Activate fully explicit test-only instrument, tax, and date candidates."""

    mapping = snapshot.mapping_record
    selector = ExecutionCurrentReferenceSelectorV2(
        purpose="normal_simulated_current_reference",
        max_local_reference_age_seconds=600,
        items=(
            ExecutionCurrentReferenceSelectorItemV2(
                security_id=_SECURITY_ID,
                asset_code=_ASSET_CODE,
                source_code=_INSTRUMENT_SOURCE_CODE,
                snapshot_id=snapshot.snapshot_id,
                snapshot_content_hash=snapshot.content_hash,
                snapshot_record_digest=snapshot.record_digest,
                mapping_record_id=mapping.mapping_record_id,
                mapping_id=mapping.content.mapping_id,
                mapping_version=mapping.content.mapping_version,
                mapping_content_hash=mapping.content_hash,
                mapping_record_digest=mapping.record_digest,
                simulated_asset_type="equity",
            ),
        ),
    ).to_payload()
    activate_runtime_profile_patch(
        environment="development",
        patch={
            "config_center.market.simulated_current_reference_selection": selector,
            "config_center.market.exchange_timezone_map": {_EXCHANGE: _TIMEZONE},
            SIMULATED_TAX_DATE_CONVENTION_KEY: {
                "schema_version": "simulated-dividend-tax-date-conventions.v1",
                "enabled": True,
                "policies": [
                    {
                        "convention_id": f"ash05-synthetic-tax-dates-{account.pk}",
                        "version": "fixture-v1",
                        "physical_account_id": account.pk,
                        "canonical_account_id": canonical_account_id,
                        "owner_user_id": owner_user_id,
                        "exchange": _EXCHANGE,
                        "purchase_open_session_offset": 0,
                        "sale_open_session_offset": 1,
                        "trade_window_start": convention_start.isoformat(),
                        "trade_window_end": convention_end.isoformat(),
                        "valid_from": (now - timedelta(minutes=2)).isoformat(),
                        "valid_until": (now + timedelta(hours=1)).isoformat(),
                        "approval_ref": "ash05-explicit-simulation-only-tax-date-test",
                    }
                ],
            },
            SIMULATED_DIVIDEND_TAX_POLICY_KEY: {
                "schema_version": "simulated-dividend-tax-policies.v1",
                "enabled": True,
                "policies": [
                    {
                        "candidate_id": f"ash05-synthetic-tax-candidate-{account.pk}",
                        "candidate_version": "fixture-v1",
                        "account_kind": "simulated",
                        "physical_account_id": account.pk,
                        "canonical_account_id": canonical_account_id,
                        "owner_user_id": owner_user_id,
                        "security_id": _SECURITY_ID,
                        "asset_code": _ASSET_CODE,
                        "exchange": _EXCHANGE,
                        "persona": "domestic_public_market_a_share",
                        "instrument_kind": "listed_equity",
                        "currency": "CNY",
                        "record_date_entitlement_rule": "all_covered_positions",
                        "applicability_ref": "ash05-synthetic-reviewed-model-scope-v1",
                        "record_date_from": "2015-09-09",
                        "record_date_through": record_date.isoformat(),
                        "valid_from": (now - timedelta(minutes=2)).isoformat(),
                        "valid_until": (now + timedelta(hours=1)).isoformat(),
                        "statutory_bundle_id": bundle_id,
                        "statutory_bundle_version": "fixture-v1",
                        "statutory_revision_set_sha256": revision_set_sha256,
                        "tax_policy": _synthetic_tax_policy(revision_set_sha256),
                    }
                ],
            },
        },
        actor="ash05-synthetic-current-tax-qualification",
        reason="explicit unqualified synthetic tax source/model/date fixtures",
    )


def _activate_owner_tax_assess_policy(
    *,
    account_id: str,
    owner_user_id: int,
    now: datetime,
    capabilities: tuple[Capability, ...] = (Capability.TAX_ASSESS,),
    policy_capabilities: tuple[Capability, ...] | None = None,
) -> None:
    """Bind the exact requested V2 capabilities to this ordinary owner and account."""

    allowed_capabilities = capabilities if policy_capabilities is None else policy_capabilities

    activate_runtime_profile_patch(
        environment="development",
        patch={
            owner_policy.SIMULATED_ACTION_WRITE_POLICY_KEY: {
                "schema_version": "simulated-corporate-action-write-policies.v2",
                "enabled": True,
                "policies": [
                    {
                        "policy_id": f"ash05-tax-assess-policy-{owner_user_id}",
                        "policy_version": "fixture-v2",
                        "canonical_account_id": account_id,
                        "owner_user_id": owner_user_id,
                        "tenant_id": f"ash05-tax-tenant-{owner_user_id}",
                        "owner_id": f"ash05-tax-owner-{owner_user_id}",
                        "valid_from": (now - timedelta(minutes=1)).isoformat(),
                        "valid_until": (now + timedelta(hours=1)).isoformat(),
                        "maximum_grant_seconds": 600,
                        "permission": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
                        "service_actor_id": "simulated-trading",
                        "capabilities": [
                            capability.value
                            for capability in sorted(
                                allowed_capabilities, key=lambda item: item.value
                            )
                        ],
                        "terms_version": SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
                        "terms_sha256": TERMS_SHA256,
                    }
                ],
            }
        },
        actor="ash05-explicit-nonstaff-tax-assessment-policy",
        reason="explicit test-only V2 owner cash/tax capability scope for one account",
    )


def _post_consent(
    seed: OwnerAccountSeed, *, path: str, payload: dict[str, object]
) -> dict[str, object]:
    """Post one actual Session/CSRF owner consent API request."""

    response = seed.client.post(
        path,
        payload,
        format="json",
        secure=True,
        HTTP_ORIGIN="https://testserver",
        HTTP_X_CSRFTOKEN=seed.csrf_token,
    )
    assert response.status_code == 200, response.content
    assert response["Content-Type"].startswith("application/json")
    return response.json()


def _request_owner_consent(
    owner_seed: OwnerAccountSeed,
    *,
    canonical_account_id: str,
    capabilities: tuple[Capability, ...],
) -> SimulatedCorporateActionWriteGrant:
    """Obtain one actual session/CSRF consent for the explicitly selected V2 powers."""

    path = f"/api/simulated-trading/accounts/{owner_seed.account.pk}/corporate-action-consent/"
    with override_settings(ROOT_URLCONF="tests.support.ash07_owner_source_test_urls"):
        prepared = _post_consent(
            owner_seed,
            path=path + "prepare/",
            payload={
                "cash_dividend": Capability.CASH_STAGE_WRITE in capabilities,
                "tax_assessment": Capability.TAX_ASSESS in capabilities,
                "tax_withholding": Capability.TAX_WITHHOLD in capabilities,
            },
        )
        token = prepared["continuation"]["input"]["consent_token"]
        assert type(token) is str and token.startswith("v2.")
        consent = _post_consent(
            owner_seed,
            path=path,
            payload={"consent_token": token, "confirmed": True},
        )
    expected = [
        capability.value for capability in sorted(capabilities, key=lambda item: item.value)
    ]
    assert consent["selected_capabilities"] == expected
    grant = read_current_simulated_action_consent_metadata(
        canonical_account_id=canonical_account_id,
        owner_user_id=owner_seed.owner.pk,
        as_of=timezone.now(),
        using="default",
    )
    assert grant is not None
    for capability in Capability:
        assert grant.supports_capability(capability) is (capability in capabilities)
    return grant


def _withdraw_owner_consent(
    owner_seed: OwnerAccountSeed, *, expected_grant: SimulatedCorporateActionWriteGrant
) -> dict[str, object]:
    """Use the same ordinary owner's CSRF-protected HTTP flow to revoke consent."""

    path = f"/api/simulated-trading/accounts/{owner_seed.account.pk}/corporate-action-consent/"
    with override_settings(ROOT_URLCONF="tests.support.ash07_owner_source_test_urls"):
        prepared = _post_consent(owner_seed, path=path + "withdraw/prepare/", payload={})
        token = prepared["continuation"]["input"]["withdrawal_token"]
        assert type(token) is str and token
        selector = restore_simulated_action_withdrawal_token(
            token,
            owner_user_id=owner_seed.owner.pk,
            physical_account_id=owner_seed.account.pk,
        )
        assert selector == expected_grant.selector
        removed = _post_consent(
            owner_seed,
            path=path + "withdraw/",
            payload={"withdrawal_token": token, "confirmed": True},
        )
    assert removed["consent_status"] == "revoked"
    return removed


def _refresh_public_owner_source_after_fills(owner_seed: OwnerAccountSeed) -> None:
    """Append actual same-owner source successors after financial row updates.

    The fill writer updates the physical account row's ``updated_at``.  Owner
    consent correctly requires a source capture of that exact current row, so
    use the existing re-observation and raw/source/Account-v2 capture pipeline
    rather than weakening the consent freshness check.
    """

    settings_value = _creation_settings()
    initial = owner_seed.binding.creation_root.physical_observation
    account_stages = build_canonical_account_creation_stages(
        using="default",
        settings=settings_value,
        requester=CanonicalAccountCreationRequester(
            actor_id=f"django-user:{owner_seed.owner.pk}",
            user_id=owner_seed.owner.pk,
        ),
        physical_row_provider=build_account_physical_row_v2_provider(using="default"),
    )
    source_stages = build_simulated_account_creation_stages(
        using="default", settings=settings_value
    )
    observer = build_existing_account_reobserver(using="default", settings=settings_value)
    before = SimulatedAccountModel.objects.using("default").get(pk=owner_seed.account.pk)
    version = f"ash05-tax-owner-refresh-{uuid4().hex}"
    with transaction.atomic(using="default"):
        raw = observer.execute(
            ReobserveExistingAccountRowCommand(
                observation_id=initial.raw_observation_id,
                observation_version=version,
                row_pk=owner_seed.account.pk,
                expected_user_id=owner_seed.owner.pk,
                expected_account_type=AccountType.SIMULATED,
                expected_created_at=initial.row_created_at,
                minimum_updated_at=initial.row_updated_at,
            )
        )
        source = source_stages.source_capture.execute(
            CaptureSimulatedAccountRowSourceV2Command(
                source_id=raw.observation_id,
                source_version=raw.observation_version,
                expected_raw_observation_content_hash=raw.content_hash,
                account_namespace=initial.account_namespace,
                account_id=initial.account_id,
                underlying_unified_account_namespace=(initial.underlying_unified_account_namespace),
                underlying_unified_account_id=owner_seed.account.pk,
            )
        )
        physical = account_stages.physical_capture.execute(
            CapturePhysicalAccountRowObservationV2Command(
                observation_id=source.source_id,
                observation_version=source.source_version,
                source_id=source.source_id,
                source_version=source.source_version,
                expected_source_content_hash=source.content_hash,
                account_namespace=source.account_namespace,
                account_id=source.account_id,
                underlying_unified_account_namespace=(source.underlying_unified_account_namespace),
                underlying_unified_account_id=owner_seed.account.pk,
            )
        )
    after = SimulatedAccountModel.objects.using("default").get(pk=owner_seed.account.pk)
    if (
        raw.row_pk != before.pk
        or raw.row_user_id != owner_seed.owner.pk
        or raw.row_created_at != initial.row_created_at
        or raw.row_updated_at != before.updated_at
        or source.account_id != owner_seed.binding.account_id_claim
        or source.row_user_id != owner_seed.owner.pk
        or source.row_updated_at != before.updated_at
        or physical.account_id != source.account_id
        or physical.row_user_id != owner_seed.owner.pk
        or physical.row_updated_at != before.updated_at
        or (
            after.user_id,
            after.created_at,
            after.updated_at,
            after.current_cash,
            after.current_market_value,
            after.total_value,
            after.total_trades,
        )
        != (
            before.user_id,
            before.created_at,
            before.updated_at,
            before.current_cash,
            before.current_market_value,
            before.total_value,
            before.total_trades,
        )
    ):
        raise AssertionError("current owner source re-observation changed or misbound the account")


def _build_current_tax_qualification_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    preserve_account_authority_generation: None,
    *,
    capabilities: tuple[Capability, ...] = (Capability.TAX_ASSESS,),
    policy_capabilities: tuple[Capability, ...] | None = None,
    payment_date: date | None = None,
    security_id: str = _SECURITY_ID,
) -> _CurrentTaxQualificationContext:
    """Build current qualification, assessment, and exact V2 owner authority."""

    del preserve_account_authority_generation
    assert connection.vendor == "postgresql"
    # The cash source adapter supports the canonical code identity; the original
    # assessment-only scenario keeps its independent internal identifier.
    monkeypatch.setattr(
        "tests.support.simulated_tax_model_native_context._SECURITY_ID", security_id
    )
    actual_now = timezone.now
    actual = actual_now().astimezone(UTC)
    monkeypatch.setenv(
        "AGOMTRADEPRO_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(b"t" * 32).decode("ascii"),
    )
    get_secrets.cache_clear()
    try:
        with isolated_task_channels():
            anchor_date = actual.astimezone(ZoneInfo(_TIMEZONE)).date() - timedelta(days=7)
            while anchor_date.weekday() >= 5:
                anchor_date -= timedelta(days=1)
            anchor_at = datetime.combine(
                anchor_date, time(9, 0), tzinfo=ZoneInfo(_TIMEZONE)
            ).astimezone(UTC)
            monkeypatch.setattr(timezone, "now", _Clock(anchor_at).now)
            configure_critical_runtime()
            with override_settings(ROOT_URLCONF="tests.support.ash07_owner_source_test_urls"):
                owner_seed = create_public_nonstaff_tax_owner_seed(as_of=anchor_at)
            assert owner_seed.owner.is_staff is False
            assert owner_seed.owner.is_superuser is False
            assert owner_seed.account.user_id == owner_seed.owner.pk
            assert owner_seed.binding.underlying_unified_account_id_claim == owner_seed.account.pk
            assert owner_seed.binding.account_id_claim
            anchor = SimulatedAccountOwnershipAnchorModel.objects.get(
                account_id=owner_seed.account.pk
            )
            assert anchor.owner_user_id == owner_seed.owner.pk
            assert anchor.quantity == Decimal("0.000000")
            canonical_account_id = owner_seed.binding.account_id_claim
            account = owner_seed.account

            monkeypatch.setattr(timezone, "now", actual_now)
            install_synthetic_document_transport(monkeypatch)
            instrument = retain_synthetic_current_cny_instrument(monkeypatch=monkeypatch)
            publisher, statutory_bundle, revision_set_sha = append_synthetic_statutory_bundle(
                body_store_root=tmp_path / "statutory"
            )
            calendar = persist_auto_uow_formal_calendar(
                as_of=actual_now().astimezone(UTC),
                exchange=_EXCHANGE,
                timezone_name=_TIMEZONE,
                live_clock=True,
                require_current_open_session=False,
            )
            open_dates = tuple(row.calendar_date for row in calendar.snapshot.days if row.is_open)
            assert len(open_dates) >= 5
            assert calendar.snapshot.coverage_start == anchor_date
            trade_dates = tuple(day for day in open_dates if day > anchor_date)
            buy_date = anchor_date
            release_date = trade_dates[0]
            record_date = trade_dates[1]
            sale_date = trade_dates[2]
            complete_through = trade_dates[3]
            assert complete_through < actual.astimezone(ZoneInfo(_TIMEZONE)).date()

            _seed_sz_fee_policy(
                monkeypatch=monkeypatch,
                as_of=datetime.combine(
                    buy_date, time(10, 0), tzinfo=ZoneInfo(_TIMEZONE)
                ).astimezone(UTC),
            )
            all_open = {
                row.calendar_date
                for row in calendar.snapshot.days
                if row.is_open and anchor_date <= row.calendar_date <= complete_through
            }
            buy = _record_v4_fill(
                monkeypatch=monkeypatch,
                account=account,
                user_id=owner_seed.owner.pk,
                key=f"ash05-tax-buy-{uuid4().hex}",
                side=SimulatedTradeSide.BUY,
                quantity=Decimal("100"),
                price=Decimal("10.00"),
                trade_date=buy_date,
                anchor_date=anchor_date,
                complete_through=complete_through,
                open_dates=all_open,
            )
            assert buy.settlement_release_date == release_date
            release_at = datetime.combine(
                release_date, time(10, 0), tzinfo=ZoneInfo(_TIMEZONE)
            ).astimezone(UTC)
            monkeypatch.setattr(timezone, "now", _Clock(release_at).now)
            release_evidence = execution_fixtures._calendar(
                as_of=release_at,
                open_dates=all_open,
                exchange=_EXCHANGE,
                start=anchor_date,
                end=complete_through,
            )
            released = DjangoSimulatedTradeExecutionRepository(
                using="default"
            ).release_due_settlements(
                account_id=account.pk,
                user_id=owner_seed.owner.pk,
                asset_code=_ASSET_CODE,
                calendar_evidence=release_evidence,
                clock=_Clock(release_at),
            )
            assert released == 1
            sell = _record_v4_fill(
                monkeypatch=monkeypatch,
                account=account,
                user_id=owner_seed.owner.pk,
                key=f"ash05-tax-sale-{uuid4().hex}",
                side=SimulatedTradeSide.SELL,
                quantity=Decimal("30"),
                price=Decimal("10.25"),
                trade_date=sale_date,
                anchor_date=anchor_date,
                complete_through=complete_through,
                open_dates=all_open,
            )
            position = PositionModel.objects.get(account_id=account.pk, asset_code=_ASSET_CODE)
            assert position.quantity == Decimal("70.000000")
            assert position.available_quantity == Decimal("70.000000")
            assert SimulatedTradeModel.objects.filter(account_id=account.pk).count() == 2
            assert (
                SimulatedOrderFillReceiptModel.objects.filter(trade__account_id=account.pk).count()
                == 2
            )
            assert SimulatedOrderReservationModel.objects.filter(account_id=account.pk).count() == 2
            assert (
                buy.settlement_release_date != release_date
                or buy.settlement_release_date < sale_date
            )
            assert sell.settlement_release_date is None

            monkeypatch.setattr(timezone, "now", actual_now)
            now = timezone.now().astimezone(UTC)
            _refresh_public_owner_source_after_fills(owner_seed)
            _activate_tax_runtime(
                account=account,
                canonical_account_id=canonical_account_id,
                owner_user_id=owner_seed.owner.pk,
                snapshot=instrument,
                bundle_id=statutory_bundle.bundle_id,
                revision_set_sha256=revision_set_sha,
                record_date=record_date,
                convention_start=anchor_date,
                convention_end=complete_through,
                now=now,
            )
            source_payment_date = payment_date or date(2026, 11, 30)
            action_body = synthetic_szse_distribution_pdf(
                security_code=_SOURCE_CODE,
                lines=(
                    "平安银行：2026年度权益分派实施公告",
                    f"股权登记日为：{record_date.year}年{record_date.month}月{record_date.day}日",
                    f"除权日（除息日）为：{complete_through.year}年{complete_through.month}月{complete_through.day}日",
                    "每10股派发现金红利2.00元",
                    f"现金红利将于{source_payment_date.year}年"
                    f"{source_payment_date.month}月{source_payment_date.day}日发放",
                    "暂不扣缴个人所得税，待个人转让股票时计算。",
                ),
            )
            first_seen_at = now - timedelta(seconds=5)
            action_event_id = str(uuid4())
            action_url = (
                "https://disc.static.szse.cn/disc/disk03/finalpage/"
                f"{record_date.isoformat()}/{action_event_id}.PDF"
            )
            action_event = SecurityDisclosureEvent.from_source_document(
                source=SecurityDisclosureSource.SZSE_OFFICIAL,
                exchange=SecurityDisclosureExchange.SZSE,
                asset_code=_ASSET_CODE,
                source_security_code=_SOURCE_CODE,
                source_event_id=action_event_id,
                source_revision_id=f"sha256:{sha256(action_body).hexdigest()}",
                raw_event_type="现金分红实施公告",
                event_type=SecurityDisclosureEventType.CASH_DIVIDEND,
                source_url=action_url,
                source_document_body=action_body,
                first_seen_at=first_seen_at,
                effective_at=complete_through,
            )
            AppendSecurityDisclosureEventUseCase(DjangoSecurityDisclosureEventRepository()).execute(
                action_event, action_body
            )
            OfficialSzsePdfBodyStore(tmp_path / "action").retain(
                CapturedOfficialSzsePdf(
                    source_url=action_event.source_url,
                    source_document_id=action_event.source_event_id,
                    first_seen_at=first_seen_at,
                    body_sha256=action_event.source_body_sha256,
                    body=action_body,
                )
            )
            payment_terms = read_verified_szse_distribution(
                action_event,
                body_store_root=tmp_path / "action",
            )
            assert payment_terms is not None
            action = QualifiedCorporateActionTaxFacts(
                account_id=account.pk,
                owner_user_id=owner_seed.owner.pk,
                security_id=_SECURITY_ID,
                asset_code=_ASSET_CODE,
                corporate_action_id=action_event.source_event_id,
                source_namespace="exchange_official_disclosure",
                source_record_id=action_event.source_event_id,
                source_event_id=action_event.source_event_id,
                source_revision_id=action_event.source_revision_id,
                source_revision_sha256=action_event.content_hash,
                source_payload_sha256=action_event.source_body_sha256,
                record_date=record_date,
                effective_date=complete_through,
                dividend_per_share=Decimal("0.2"),
            )

            with override_settings(ROOT_URLCONF="tests.support.ash07_owner_source_test_urls"):
                audit_seed = create_owner_account_seed()
                publish_current_owner_policy(audit_seed)
                audit_selector = issue_current_owner_audit_selector(audit_seed)
            activate_runtime_profile_patch(
                environment="development",
                patch=audit_runtime_patch(audit_selector),
                actor="ash05-independent-audit-service",
                reason="require actual Audit and Outbox for the owner tax assessment write",
            )
            _activate_owner_tax_assess_policy(
                account_id=canonical_account_id,
                owner_user_id=owner_seed.owner.pk,
                now=now,
                capabilities=capabilities,
                policy_capabilities=policy_capabilities,
            )
            grant_metadata = _request_owner_consent(
                owner_seed,
                canonical_account_id=canonical_account_id,
                capabilities=capabilities,
            )

            provider = DjangoCurrentSimulatedTaxQualificationProvider(
                runtime_environment="development",
                calendar_dataset_key=calendar.dataset_key,
                statutory_provider_id=publisher.pk,
                statutory_body_store_root=tmp_path / "statutory",
                action_body_store_root=tmp_path / "action",
                deployment_region="ash05-native-qa",
                using="default",
            )
            target_date = complete_through
            before_financial = (
                SimulatedAccountModel.objects.get(pk=account.pk).current_cash,
                SimulatedAccountModel.objects.get(pk=account.pk).total_value,
                PositionModel.objects.filter(account_id=account.pk).count(),
                SimulatedTradeModel.objects.filter(account_id=account.pk).count(),
                SimulatedOrderFillReceiptModel.objects.filter(trade__account_id=account.pk).count(),
                CorporateActionTaxAssessmentHeaderModel.objects.count(),
                CorporateActionTaxAssessmentAllocationModel.objects.count(),
                SystemAuditEventModel.objects.count(),
                SystemAuditOutboxModel.objects.count(),
            )
            preview = provider.prepare_current(
                action=action,
                canonical_account_id=canonical_account_id,
                target_settlement_date=target_date,
                assessment_revision_id=f"ash05-tax-assessment-{uuid4().hex}",
                supersedes_assessment_revision_id=None,
            )
            repeated_preview = provider.prepare_current(
                action=action,
                canonical_account_id=canonical_account_id,
                target_settlement_date=target_date,
                assessment_revision_id=preview.assessment_revision_id,
                supersedes_assessment_revision_id=None,
            )
            assert repeated_preview.semantic_sha256 == preview.semantic_sha256
            assert preview.history.record_date_ownership_proof.eligible_quantity == Decimal(
                "100.000000"
            )
            assert preview.simulated_tax_date_observation is not None
            assert preview.history.settlement_date_rule_id.startswith("ash05-synthetic-tax-dates-")
            assert (
                preview.simulated_tax_date_observation.date_rule.definition_key
                == SIMULATED_TAX_DATE_CONVENTION_KEY
            )
            assert (
                preview.history.settlement_date_rule_sha256
                == preview.simulated_tax_date_observation.date_rule.convention_sha256
            )
            assert preview.history.settlement_days
            assert (
                tuple(day.settlement_date for day in preview.history.settlement_days)
                == preview.history.covered_session_dates
            )
            assert any(
                day.net_quantity_change == Decimal("0.000000")
                for day in preview.history.settlement_days
            )
            assert len(preview.bridge.request.lots) == 1
            tax_lot = preview.bridge.request.lots[0]
            assert tax_lot.record_date_quantity == Decimal("100.000000")
            assert tax_lot.acquired_on != buy.settlement_release_date
            assert len(preview.bridge.request.dispositions) == 1
            assert preview.bridge.request.dispositions[0].quantity == Decimal("30.000000")
            assert (
                preview.bridge.request.dispositions[0].transfer_settlement_date == complete_through
            )
            after_preview = (
                SimulatedAccountModel.objects.get(pk=account.pk).current_cash,
                SimulatedAccountModel.objects.get(pk=account.pk).total_value,
                PositionModel.objects.filter(account_id=account.pk).count(),
                SimulatedTradeModel.objects.filter(account_id=account.pk).count(),
                SimulatedOrderFillReceiptModel.objects.filter(trade__account_id=account.pk).count(),
                CorporateActionTaxAssessmentHeaderModel.objects.count(),
                CorporateActionTaxAssessmentAllocationModel.objects.count(),
                SystemAuditEventModel.objects.count(),
                SystemAuditOutboxModel.objects.count(),
            )
            assert after_preview == before_financial

            verifier = DjangoTaxAssessmentOwnerScopeVerifier(
                selector=grant_metadata.selector,
                scope_locker=DjangoSimulatedCorporateActionWriteScopeLocker(
                    database_alias="default", runtime_environment="development"
                ),
                qualification_provider=provider,
                using="default",
                environment="development",
            )
            use_case = build_audited_tax_assessment_use_case(
                scope_verifier=verifier,
                using="default",
            )
            receipt = use_case.execute(preview, actor_user_id=owner_seed.owner.pk)
            assert receipt.disposition is TaxAssessmentAppendDisposition.STORED
            header = CorporateActionTaxAssessmentHeaderModel.objects.get(
                assessment_revision_id=preview.assessment_revision_id
            )
            assert header.authority_grant_id == grant_metadata.grant_id
            assert header.authority_grant_version == grant_metadata.grant_version
            assert header.authority_grant_sha256 == grant_metadata.content_hash
            assert not owner_seed.owner.is_staff and not owner_seed.owner.is_superuser
            assert (
                CorporateActionTaxAssessmentHeaderModel.objects.filter(
                    assessment_revision_id=preview.assessment_revision_id
                ).count()
                == 1
            )
            written = (
                SimulatedAccountModel.objects.get(pk=account.pk).current_cash,
                SimulatedAccountModel.objects.get(pk=account.pk).total_value,
                PositionModel.objects.filter(account_id=account.pk).count(),
                SimulatedTradeModel.objects.filter(account_id=account.pk).count(),
                SimulatedOrderFillReceiptModel.objects.filter(trade__account_id=account.pk).count(),
            )
            assert written == before_financial[:5]
            assert CorporateActionTaxAssessmentHeaderModel.objects.count() == (
                before_financial[5] + 1
            )
            assert CorporateActionTaxAssessmentAllocationModel.objects.count() == (
                before_financial[6] + len(preview.calculation.allocations)
            )
            assert SystemAuditEventModel.objects.count() == before_financial[7] + 1
            assert SystemAuditOutboxModel.objects.count() == before_financial[8] + 1
            return _CurrentTaxQualificationContext(
                owner_seed=owner_seed,
                action=action,
                action_event=action_event,
                assessment=preview,
                grant=grant_metadata,
                action_body_store_root=tmp_path / "action",
                payment_terms=payment_terms,
                provider=provider,
            )
    finally:
        get_secrets.cache_clear()


def _cash_entitlement_request(
    context: _CurrentTaxQualificationContext,
) -> CorporateActionStageRequest:
    """Build a cash entitlement from parsed source terms and the real history replay."""

    owner_seed = context.owner_seed
    action_event = context.action_event
    terms = context.payment_terms
    if terms.cash_per_ten is None or terms.tax_treatment is None:
        raise AssertionError("retained synthetic source lacks explicit cash/tax terms")
    qualified_at = timezone.now().astimezone(UTC)
    proof = build_corporate_action_ownership_history_repository(
        runtime_environment="development",
        using="default",
    ).read_record_date_ownership_proof(
        account_id=owner_seed.account.pk,
        owner_user_id=owner_seed.owner.pk,
        security_id=context.action.security_id,
        asset_code=context.action.asset_code,
        record_date=terms.record_date,
        evidence_cutoff_at=qualified_at,
    )
    cash_amount = (proof.eligible_quantity * terms.cash_per_ten / Decimal("10")).quantize(
        Decimal("0.01")
    )
    entitlement_calculation = sha256(
        (
            "ash05-synthetic-cash-entitlement-v1\0"
            f"{proof.ownership_snapshot_sha256}\0"
            f"{terms.cash_per_ten}\0{proof.eligible_quantity}\0{cash_amount}"
        ).encode()
    ).hexdigest()
    posted_at = timezone.now().astimezone(UTC)
    return CorporateActionStageRequest(
        account_id=owner_seed.account.pk,
        owner_user_id=owner_seed.owner.pk,
        security_id=context.action.security_id,
        asset_code=context.action.asset_code,
        asset_name="ASH05 synthetic cash dividend",
        source_namespace="exchange_official_disclosure",
        source_record_id=action_event.source_event_id,
        source_event_id=action_event.source_event_id,
        source_revision_id=action_event.source_revision_id,
        source_payload_sha256=action_event.source_body_sha256,
        qualification_sha256=szse_action_qualification_sha256(action_event, terms),
        qualifier_identity="szse_official_pdf.v1",
        source_observed_at=action_event.first_seen_at,
        qualified_at=qualified_at,
        posted_at=posted_at,
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        entry_kind=CorporateActionEntryKind.POSTING,
        record_date=terms.record_date,
        effective_date=terms.ex_date,
        stage_date=terms.record_date,
        cash_amount=cash_amount,
        tax_treatment=terms.tax_treatment,
        ownership_snapshot_id=proof.ownership_snapshot_id,
        ownership_snapshot_sha256=proof.ownership_snapshot_sha256,
        ownership_snapshot_as_of_date=proof.ownership_snapshot_as_of_date,
        ownership_snapshot_observed_at=proof.ownership_snapshot_observed_at,
        eligible_quantity=proof.eligible_quantity,
        entitlement_calculation_sha256=entitlement_calculation,
    )


def _cash_payment_request(
    entitlement: CorporateActionStageRequest,
    *,
    payment_date: date,
) -> CorporateActionStageRequest:
    """Build the same exact source/action payment stage without owner-proof terms."""

    qualified_at = timezone.now().astimezone(UTC)
    posted_at = timezone.now().astimezone(UTC)
    if posted_at < qualified_at:
        posted_at = qualified_at
    return replace(
        entitlement,
        qualified_at=qualified_at,
        posted_at=posted_at,
        stage=CorporateActionStage.CASH_PAYMENT,
        stage_date=payment_date,
        payment_date=payment_date,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )


def _assert_receipt_has_exact_audit_outbox_pair(
    request: CorporateActionStageRequest,
    *,
    entry_id: int,
    account_revision: int,
    stage_key: str,
    request_payload_sha256: str,
) -> None:
    """Read one ledger receipt and verify its canonical Audit and exact Outbox pair."""

    ledger_row = CorporateActionPostingModel.objects.using("default").get(pk=entry_id)
    assert ledger_row.account_id == request.account_id
    assert ledger_row.account_revision == account_revision
    assert ledger_row.stage_key == stage_key == request.stage_key
    assert ledger_row.request_payload_sha256 == request_payload_sha256 == request.payload_sha256
    assert ledger_row.source_event_id == request.source_event_id
    assert ledger_row.source_revision_id == request.source_revision_id
    assert ledger_row.stage == request.stage.value

    with transaction.atomic(using="default"):
        audit_row = SystemAuditEventModel.objects.using("default").get(
            event_type="simulated.corporate_action.stage_posted",
            source_component="corporate_action_posting",
            detail__entry_id=entry_id,
        )
        coordinator = DjangoSystemAuditEventOutboxCoordinator(using="default")
        with coordinator.caller_owned_readonly():
            event = coordinator.get_winner(
                event_id=audit_row.event_id,
                event_version=audit_row.event_version,
                as_of=timezone.now(),
            )
            assert event is not None
            assert event.content_hash == audit_row.content_hash
            assert event.detail["account_id"] == request.account_id
            assert event.detail["source_event_id"] == request.source_event_id
            assert event.detail["source_revision_id"] == request.source_revision_id
            assert event.detail["stage"] == request.stage.value
            assert event.detail["entry_id"] == entry_id
            assert event.detail["stage_key"] == request.stage_key
            assert event.detail["request_payload_sha256"] == request.payload_sha256
            outbox = coordinator.get_exact_outbox_winner_targeted(event)
            assert outbox is not None
            assert outbox.event == event
            assert outbox.event_id == event.event_id
            assert outbox.payload_hash == event.content_hash


def _post_audited_cash_entitlement(
    context: _CurrentTaxQualificationContext,
) -> tuple[CorporateActionStageRequest, CorporateActionPostingReceipt]:
    """Post one current-source cash entitlement through the actual owner gate."""

    if not context.grant.supports_capability(Capability.CASH_STAGE_WRITE):
        raise AssertionError("current consent lacks the explicit cash-stage capability")
    gate = DjangoCorporateActionOwnerGrantGate(
        selector=context.grant.selector,
        scope_locker=DjangoSimulatedCorporateActionWriteScopeLocker(
            database_alias="default",
            runtime_environment="development",
        ),
        using="default",
        environment="development",
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    )
    use_case = build_audited_cash_entitlement_use_case(
        body_store_root=context.action_body_store_root,
        runtime_environment="development",
        owner_grant_gate=gate,
        using="default",
    )
    request = _cash_entitlement_request(context)
    return request, use_case.execute(request)[0]


def _post_audited_cash_payment(
    context: _CurrentTaxQualificationContext,
    entitlement: CorporateActionStageRequest,
    *,
    payment_date: date,
) -> tuple[CorporateActionStageRequest, CorporateActionPostingReceipt]:
    """Post one payment stage through the same original cash-stage grant."""

    if not context.grant.supports_capability(Capability.CASH_STAGE_WRITE):
        raise AssertionError("current consent lacks the explicit cash-stage capability")
    gate = DjangoCorporateActionOwnerGrantGate(
        selector=context.grant.selector,
        scope_locker=DjangoSimulatedCorporateActionWriteScopeLocker(
            database_alias="default",
            runtime_environment="development",
        ),
        using="default",
        environment="development",
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    )
    use_case = build_audited_cash_payment_use_case(
        body_store_root=context.action_body_store_root,
        runtime_environment="development",
        owner_grant_gate=gate,
        using="default",
    )
    request = _cash_payment_request(entitlement, payment_date=payment_date)
    return request, use_case.execute(request)[0]


def _refresh_owner_source_and_requalify_original_assessment(
    context: _CurrentTaxQualificationContext,
    *,
    capabilities: tuple[Capability, ...],
) -> tuple[SimulatedCorporateActionWriteGrant, CorporateActionTaxAssessment]:
    """Refresh SourceV2 and consent, then requalify the exact stored assessment revision."""

    owner_seed = context.owner_seed
    _refresh_public_owner_source_after_fills(owner_seed)
    grant = _request_owner_consent(
        owner_seed,
        canonical_account_id=owner_seed.binding.account_id_claim,
        capabilities=capabilities,
    )
    assert grant.supports_capability(Capability.TAX_ASSESS)
    assert grant.supports_capability(Capability.TAX_WITHHOLD) is (
        Capability.TAX_WITHHOLD in capabilities
    )
    assert grant.supports_capability(Capability.CASH_STAGE_WRITE) is (
        Capability.CASH_STAGE_WRITE in capabilities
    )
    current_assessment = context.provider.prepare_current(
        action=context.action,
        canonical_account_id=owner_seed.binding.account_id_claim,
        target_settlement_date=context.assessment.target_settlement_date,
        assessment_revision_id=context.assessment.assessment_revision_id,
        supersedes_assessment_revision_id=context.assessment.supersedes_assessment_revision_id,
    )
    if current_assessment.semantic_sha256 != context.assessment.semantic_sha256:
        raise AssertionError(
            "post-payment source reobservation changed tax semantics; "
            f"stored={context.assessment.semantic_sha256} "
            f"requalified={current_assessment.semantic_sha256}"
        )
    assert current_assessment.assessment_revision_id == context.assessment.assessment_revision_id
    assert (
        current_assessment.supersedes_assessment_revision_id
        == context.assessment.supersedes_assessment_revision_id
    )
    assert context.assessment.calculation.withholding_amount > Decimal("0.00")
    return grant, context.assessment


def _read_paid_payment_basis(
    assessment: CorporateActionTaxAssessment,
    grant: SimulatedCorporateActionWriteGrant,
) -> SimulatedDividendPaymentBasis:
    """Read the independently verified full paid basis within a caller UOW."""

    binding = grant.selector.binding
    with transaction.atomic(using="default"):
        return read_locked_simulated_dividend_payment_basis(
            assessment,
            using="default",
            canonical_account_namespace=binding.account_namespace,
            canonical_account_id=binding.account_id,
            audit_scope=AuditScopeRef(binding.tenant_id, binding.owner_id),
            as_of=timezone.now(),
        )


def _build_actual_tax_collection_use_case(
    context: _CurrentTaxQualificationContext,
    grant: SimulatedCorporateActionWriteGrant,
) -> CorporateActionTaxLiabilityUseCase:
    """Compose the actual locked owner, current qualification, and Audit financial use case."""

    audit = build_tax_assessment_audit_coordinator(using="default")
    verifier = DjangoTaxLiabilityOwnerScopeVerifier(
        selector=grant.selector,
        scope_locker=DjangoSimulatedCorporateActionWriteScopeLocker(
            database_alias="default",
            runtime_environment="development",
        ),
        qualification_provider=context.provider,
        audit=audit,
        using="default",
        environment="development",
    )
    return build_audited_tax_liability_use_case(
        scope_verifier=verifier,
        using="default",
        audit=audit,
    )


def _assert_payment_basis_reference(
    receipt: TaxLiabilityWriteReceipt,
    basis: SimulatedDividendPaymentBasis,
) -> None:
    """Bind the retained operation's complete basis reference to the verified source pair."""

    basis_id = tax_payment_basis_artifact_id(basis)
    expected = TaxLiabilityEvidenceReference(basis_id, "v1", basis.content_sha256)
    assert receipt.payment_basis_reference == expected


def _capture_financial_effects(
    account: SimulatedAccountModel,
) -> tuple[Decimal, Decimal, datetime, int, int, int, int]:
    """Capture cash, legacy summary value, update clock, rows, and Audit counts."""

    account.refresh_from_db(using="default")
    return (
        account.current_cash,
        account.total_value,
        account.updated_at,
        CorporateActionTaxLiabilityOperationModel.objects.using("default")
        .filter(account_id=account.pk)
        .count(),
        CorporateActionPostingModel.objects.using("default").filter(account_id=account.pk).count(),
        SystemAuditEventModel.objects.using("default").count(),
        SystemAuditOutboxModel.objects.using("default").count(),
    )


def run_paid_cash_tax_collection_journey(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    preserve_account_tax_authority_generation: None,
) -> None:
    """Exercise audited synthetic dividend payment, fresh consent, withholding and replay."""

    current_payment_date = timezone.now().astimezone(ZoneInfo(_TIMEZONE)).date()
    initial_capabilities = (Capability.CASH_STAGE_WRITE, Capability.TAX_ASSESS)
    full_policy_capabilities = (
        Capability.CASH_STAGE_WRITE,
        Capability.TAX_ASSESS,
        Capability.TAX_WITHHOLD,
    )
    context = _build_current_tax_qualification_context(
        monkeypatch,
        tmp_path,
        preserve_account_tax_authority_generation,
        capabilities=initial_capabilities,
        policy_capabilities=full_policy_capabilities,
        payment_date=current_payment_date,
        security_id=_ASSET_CODE,
    )
    assert not context.owner_seed.owner.is_staff and not context.owner_seed.owner.is_superuser
    assert context.grant.supports_capability(Capability.CASH_STAGE_WRITE)
    assert context.grant.supports_capability(Capability.TAX_ASSESS)
    assert not context.grant.supports_capability(Capability.TAX_WITHHOLD)

    account = context.owner_seed.account
    account.refresh_from_db(using="default")
    before_payment_cash = account.current_cash
    before_payment_legacy_summary = account.total_value
    before_payment_updated_at = account.updated_at
    before_audit_count = SystemAuditEventModel.objects.using("default").count()
    before_outbox_count = SystemAuditOutboxModel.objects.using("default").count()
    before_posting_count = (
        CorporateActionPostingModel.objects.using("default").filter(account_id=account.pk).count()
    )
    entitlement_request, entitlement_receipt = _post_audited_cash_entitlement(context)
    account.refresh_from_db(using="default")
    after_entitlement = account.current_cash, account.total_value
    assert after_entitlement == (before_payment_cash, before_payment_legacy_summary)
    assert account.updated_at == before_payment_updated_at
    payment_request, payment_receipt = _post_audited_cash_payment(
        context,
        entitlement_request,
        payment_date=current_payment_date,
    )
    account.refresh_from_db(using="default")
    paid_cash = account.current_cash
    assert paid_cash == before_payment_cash + entitlement_request.cash_amount
    assert account.total_value == before_payment_legacy_summary
    rows = tuple(
        CorporateActionPostingModel.objects.using("default")
        .filter(account_id=account.pk)
        .order_by("account_revision")
    )
    assert len(rows) == before_posting_count + 2
    entitlement_row, payment_row = rows[-2:]
    assert entitlement_row.stage == CorporateActionStage.CASH_ENTITLEMENT.value
    assert payment_row.stage == CorporateActionStage.CASH_PAYMENT.value
    assert entitlement_row.cash_receivable_delta == entitlement_request.cash_amount
    assert entitlement_row.cash_delta == Decimal("0.00")
    assert payment_row.cash_delta == entitlement_request.cash_amount
    assert payment_row.cash_receivable_delta == -entitlement_request.cash_amount
    assert SystemAuditEventModel.objects.using("default").count() == before_audit_count + 2
    assert SystemAuditOutboxModel.objects.using("default").count() == before_outbox_count + 2
    _assert_receipt_has_exact_audit_outbox_pair(
        entitlement_request,
        entry_id=entitlement_receipt.entry_id,
        account_revision=entitlement_receipt.account_revision,
        stage_key=entitlement_receipt.stage_key,
        request_payload_sha256=entitlement_receipt.request_payload_sha256,
    )
    _assert_receipt_has_exact_audit_outbox_pair(
        payment_request,
        entry_id=payment_receipt.entry_id,
        account_revision=payment_receipt.account_revision,
        stage_key=payment_receipt.stage_key,
        request_payload_sha256=payment_receipt.request_payload_sha256,
    )

    fresh_capabilities = (Capability.TAX_ASSESS, Capability.TAX_WITHHOLD)
    grant, assessment = _refresh_owner_source_and_requalify_original_assessment(
        context,
        capabilities=fresh_capabilities,
    )
    assert grant.grant_id == context.grant.grant_id
    assert grant.grant_version != context.grant.grant_version
    assert grant.content_hash != context.grant.content_hash
    assert grant.supersedes_content_hash == context.grant.content_hash
    assert grant.capabilities is not None
    assert set(grant.capabilities) == set(fresh_capabilities)
    assert grant.supports_capability(Capability.CASH_STAGE_WRITE) is False
    updated_context = replace(context, grant=grant, assessment=assessment)
    basis = _read_paid_payment_basis(assessment, grant)
    assert basis.payment_date == current_payment_date
    assert basis.entitlement_entry_id == entitlement_receipt.entry_id
    assert basis.payment_entry_id == payment_receipt.entry_id
    assert basis.entitlement_audit_event_id
    assert basis.entitlement_outbox_record_id
    assert basis.payment_audit_event_id
    assert basis.payment_outbox_record_id
    assert basis.entitlement_grant_id == context.grant.grant_id
    assert basis.payment_grant_id == context.grant.grant_id
    assert basis.gross_entitlement_amount == entitlement_request.cash_amount

    use_case = _build_actual_tax_collection_use_case(updated_context, grant)
    before_collection = _capture_financial_effects(account)
    first = use_case.execute(
        assessment,
        actor_user_id=context.owner_seed.owner.pk,
        operation_id=f"ash05-paid-tax-collection-{uuid4().hex}",
        cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
    )
    assert first.disposition is TaxLiabilityAppendDisposition.STORED
    assert first.collected_delta == assessment.calculation.withholding_amount
    assert first.cash_delta == -first.collected_delta
    assert first.outstanding_delta == Decimal("0.00")
    _assert_payment_basis_reference(first, basis)
    after_collection = _capture_financial_effects(account)
    assert after_collection[0] == before_collection[0] - first.collected_delta
    assert after_collection[1] == before_collection[1]
    assert after_collection[2] > before_collection[2]
    assert after_collection[3] == before_collection[3] + 1
    assert after_collection[4] == before_collection[4]
    assert after_collection[5] == before_collection[5] + 1
    assert after_collection[6] == before_collection[6] + 1

    retry = use_case.execute(
        assessment,
        actor_user_id=context.owner_seed.owner.pk,
        operation_id=first.operation_id,
        cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
    )
    assert retry == replace(first, disposition=TaxLiabilityAppendDisposition.EXACT_RETRY)
    _assert_payment_basis_reference(retry, basis)
    assert _capture_financial_effects(account) == after_collection

    removed = _withdraw_owner_consent(context.owner_seed, expected_grant=grant)
    assert removed["grant_id"] == grant.grant_id
    after_withdrawal = _capture_financial_effects(account)
    assert after_withdrawal[:5] == after_collection[:5]
    with pytest.raises((AuthorizationError, BusinessLogicError)):
        use_case.execute(
            assessment,
            actor_user_id=context.owner_seed.owner.pk,
            operation_id=first.operation_id,
            cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
        )
    assert _capture_financial_effects(account) == after_withdrawal


def run_blocked_payment_tax_collection_journey(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    preserve_account_tax_authority_generation: None,
    payment_state: str,
) -> None:
    """Prove absent and future simulated payments cannot create tax financial effects."""

    if payment_state not in ("missing", "unreached"):
        raise ValueError("unsupported payment fixture state")
    current_date = timezone.now().astimezone(ZoneInfo(_TIMEZONE)).date()
    payment_date = current_date if payment_state == "missing" else current_date + timedelta(days=7)
    capabilities = (
        Capability.CASH_STAGE_WRITE,
        Capability.TAX_ASSESS,
        Capability.TAX_WITHHOLD,
    )
    context = _build_current_tax_qualification_context(
        monkeypatch,
        tmp_path,
        preserve_account_tax_authority_generation,
        capabilities=capabilities,
        payment_date=payment_date,
        security_id=_ASSET_CODE,
    )
    account = context.owner_seed.account
    account.refresh_from_db(using="default")
    entitlement_request, _ = _post_audited_cash_entitlement(context)
    if payment_state == "unreached":
        before_unreached_post = _capture_financial_effects(account)
        with pytest.raises(CorporateActionPostingBlockedError) as payment_blocked:
            _post_audited_cash_payment(
                context,
                entitlement_request,
                payment_date=payment_date,
            )
        assert payment_blocked.value.code == "CORPORATE_ACTION_PAYMENT_DATE_NOT_REACHED"
        assert _capture_financial_effects(account) == before_unreached_post

    before_attempt = _capture_financial_effects(account)
    use_case = _build_actual_tax_collection_use_case(context, context.grant)
    with pytest.raises(BusinessLogicError) as blocked:
        use_case.execute(
            context.assessment,
            actor_user_id=context.owner_seed.owner.pk,
            operation_id=f"ash05-blocked-tax-collection-{uuid4().hex}",
            cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
        )
    assert blocked.value.code == "SIMULATED_DIVIDEND_PAYMENT_BASIS_BLOCKED"
    assert _capture_financial_effects(account) == before_attempt
