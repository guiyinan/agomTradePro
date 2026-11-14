from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID

import pytest

from apps.simulated_trading.domain import corporate_action_tax_assessment as assessment_domain
from apps.simulated_trading.domain import simulated_tax_settlement_history as tax_history_domain
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxPolicy,
    DeferredDividendTaxValidationError,
    HoldingPeriodTaxBand,
    TaxLotOrigin,
    TaxRoundingMode,
    calculate_deferred_dividend_tax,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    OwnershipAnchorKind,
    OwnershipOpeningAnchor,
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
    QualifiedCorporateActionTaxFacts,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_evidence import (
    QualifiedTaxSettlementHistory,
    RecordDateTaxEntitlementEvidence,
    RecordDateTaxEntitlementRuleKind,
    TaxSettlementDayEvidence,
)
from apps.simulated_trading.domain.corporate_action_tax_source_evidence import (
    TaxAssessmentSourceCaptureObservation,
    TaxAssessmentSourceDateEvidence,
    TaxAssessmentSourceDatePrecision,
    TaxAssessmentStatutorySourceBundle,
    TaxAssessmentStatutorySourceRevision,
)
from apps.simulated_trading.domain.simulated_tax_settlement_history import (
    SimulatedTaxDateRuleRuntimeProvenance,
    SimulatedTaxSettlementHistoryObservation,
)

_ACCOUNT_ID = 7
_OWNER_ID = 11
_RECORD_DATE = date(2025, 2, 28)
_TARGET_DATE = date(2025, 3, 3)
_BODY = b"synthetic tax policy fixture; not a legal source"


def _source_bundle(
    *,
    capture_id: UUID = UUID("11111111-1111-4111-8111-111111111111"),
    captured_at: datetime | None = None,
    bundle_id: str = "synthetic-tax-fixture",
    bundle_version: str = "fixture-v1",
    source_version: str = "fixture-r1",
) -> TaxAssessmentStatutorySourceBundle:
    """Build a synthetic body capture with stable native revision facts."""

    revision = TaxAssessmentStatutorySourceRevision(
        document_id="synthetic-tax-policy-fixture",
        source_version=source_version,
        canonical_url="https://example.invalid/synthetic-tax-policy",
        issuer="Synthetic test fixture",
        title="Synthetic policy fixture; not a legal document",
        legal_number="SYNTHETIC-NOT-LEGAL",
        publication_date=TaxAssessmentSourceDateEvidence(
            TaxAssessmentSourceDatePrecision.UNKNOWN, None, None
        ),
        effective_date=TaxAssessmentSourceDateEvidence(
            TaxAssessmentSourceDatePrecision.UNKNOWN, None, None
        ),
        body_sha256=hashlib.sha256(_BODY).hexdigest(),
        body_size_bytes=len(_BODY),
    )
    selected_capture_id = capture_id
    capture = TaxAssessmentSourceCaptureObservation(
        capture_id=selected_capture_id,
        revision=revision,
        captured_at=(datetime(2026, 11, 12, tzinfo=UTC) if captured_at is None else captured_at),
        content_type="text/html; charset=utf-8",
        body_reference=f"statutory-source-body:///v1/{selected_capture_id}.body",
        body_sha256=revision.body_sha256,
        body_size_bytes=len(_BODY),
    )
    return TaxAssessmentStatutorySourceBundle(bundle_id, bundle_version, (capture,))


def _policy(bundle: TaxAssessmentStatutorySourceBundle) -> DeferredDividendTaxPolicy:
    """Build an explicit synthetic policy whose body is present in the bundle."""

    return DeferredDividendTaxPolicy(
        policy_id="synthetic-tax-policy",
        version="fixture-v1",
        effective_from=date(2024, 1, 1),
        effective_through=None,
        source_identity=bundle.source_revision_set_identity,
        source_sha256=bundle.source_revision_set_sha256,
        bands=(
            HoldingPeriodTaxBand(
                band_id="synthetic-short",
                maximum_holding_months=12,
                taxable_dividend_ratio=Decimal("1"),
                withholding_rate=Decimal("0.2"),
            ),
            HoldingPeriodTaxBand(
                band_id="synthetic-long",
                maximum_holding_months=None,
                taxable_dividend_ratio=Decimal("0"),
                withholding_rate=Decimal("0"),
            ),
        ),
        currency_quantum=Decimal("0.01"),
        rounding_mode=TaxRoundingMode.HALF_UP,
    )


def _history(
    *,
    proof_id: str = "synthetic-ownership-proof-1",
    proof_sha256: str = "a" * 64,
    proof_observed_at: datetime = datetime(2025, 3, 1, 16, tzinfo=UTC),
    changed_source_revision: bool = False,
) -> QualifiedTaxSettlementHistory:
    """Build one complete synthetic EOD prefix through a partial sale."""

    proof = RecordDateOwnershipProof(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id="600000.SH",
        asset_code="equity-cn",
        record_date=_RECORD_DATE,
        ownership_snapshot_as_of_date=_RECORD_DATE,
        record_date_end_exclusive=datetime(2025, 3, 1, tzinfo=UTC),
        exchange="SYNTHETIC",
        exchange_timezone_name="Asia/Shanghai",
        cutoff_policy_id="synthetic-cutoff-v1",
        cutoff_policy_sha256="b" * 64,
        eligible_quantity=Decimal("70.000000"),
        ownership_snapshot_id=proof_id,
        ownership_snapshot_sha256=proof_sha256,
        ownership_snapshot_observed_at=proof_observed_at,
    )
    anchor = OwnershipOpeningAnchor(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        anchor_id="synthetic-zero-origin-v1",
        anchor_kind=OwnershipAnchorKind.ZERO_ORIGIN,
        quantity=Decimal("0.000000"),
        effective_at=datetime(2024, 1, 1, tzinfo=UTC),
        observed_at=datetime(2024, 1, 2, tzinfo=UTC),
        evidence_sha256="c" * 64,
    )
    revision_id = (
        "synthetic-settlement-r2" if changed_source_revision else "synthetic-settlement-r1"
    )
    revision_sha256 = "e" * 64 if changed_source_revision else "d" * 64
    rows = (
        (date(2024, 1, 2), "0", "100", "0", "100"),
        (date(2024, 2, 1), "100", "0", "30", "70"),
        (_RECORD_DATE, "70", "0", "0", "70"),
        (_TARGET_DATE, "70", "5", "15", "60"),
    )
    days = tuple(
        TaxSettlementDayEvidence(
            account_id=_ACCOUNT_ID,
            owner_user_id=_OWNER_ID,
            security_id="600000.SH",
            asset_code="equity-cn",
            settlement_date=settled,
            opening_eod_quantity=Decimal(opening),
            gross_purchase_quantity=Decimal(purchase),
            gross_sale_quantity=Decimal(sale),
            non_trade_quantity_delta=Decimal("0.000000"),
            closing_eod_quantity=Decimal(closing),
            purchase_origin=TaxLotOrigin.PURCHASE,
            evidence_id=f"synthetic-settlement-day:{settled.isoformat()}",
            evidence_sha256=f"{settled.day:02x}" * 32,
            source_revision_id=revision_id,
            source_revision_sha256=revision_sha256,
        )
        for settled, opening, purchase, sale, closing in rows
    )
    return QualifiedTaxSettlementHistory(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id="600000.SH",
        asset_code="equity-cn",
        record_date=_RECORD_DATE,
        complete_through=_TARGET_DATE,
        record_date_ownership_proof=proof,
        opening_anchor=anchor,
        settlement_date_rule_id="synthetic-settlement-date-rule-v1",
        settlement_date_rule_sha256="f" * 64,
        settlement_calendar_id="synthetic-calendar-v1",
        settlement_calendar_sha256="1" * 64,
        source_revision_id=revision_id,
        source_revision_sha256=revision_sha256,
        covered_session_dates=tuple(row[0] for row in rows),
        settlement_days=days,
        record_date_entitlement=RecordDateTaxEntitlementEvidence(
            kind=RecordDateTaxEntitlementRuleKind.ALL_COVERED_POSITIONS,
            rule_source_id="synthetic-entitlement-rule-v1",
            rule_source_sha256="2" * 64,
            qualified_total_quantity=Decimal("70.000000"),
            total_evidence_id="synthetic-entitlement-total-v1",
            total_evidence_sha256="3" * 64,
        ),
    )


def _assessment(
    *,
    bundle: TaxAssessmentStatutorySourceBundle | None = None,
    history: QualifiedTaxSettlementHistory | None = None,
    action: QualifiedCorporateActionTaxFacts | None = None,
    policy: DeferredDividendTaxPolicy | None = None,
    revision_id: str = "assessment-revision-1",
    simulated_tax_date_observation: SimulatedTaxSettlementHistoryObservation | None = None,
) -> CorporateActionTaxAssessment:
    """Construct one assessment from explicit synthetic qualified inputs."""

    selected_bundle = _source_bundle() if bundle is None else bundle
    selected_history = _history() if history is None else history
    selected_action = action or QualifiedCorporateActionTaxFacts(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id="600000.SH",
        asset_code="equity-cn",
        corporate_action_id="synthetic-cash-dividend-v1",
        source_namespace="synthetic-disclosure",
        source_record_id="synthetic-record-1",
        source_event_id="synthetic-event-1",
        source_revision_id="synthetic-action-revision-1",
        source_revision_sha256="4" * 64,
        source_payload_sha256="5" * 64,
        record_date=_RECORD_DATE,
        effective_date=date(2025, 3, 10),
        dividend_per_share=Decimal("0.50"),
    )
    selected_policy = _policy(selected_bundle) if policy is None else policy
    return CorporateActionTaxAssessment(
        assessment_revision_id=revision_id,
        supersedes_assessment_revision_id=None,
        action=selected_action,
        history=selected_history,
        target_settlement_date=_TARGET_DATE,
        policy=selected_policy,
        statutory_source_bundle=selected_bundle,
        simulated_tax_date_observation=simulated_tax_date_observation,
    )


def _simulated_tax_date_observation(
    history: QualifiedTaxSettlementHistory | None = None,
) -> SimulatedTaxSettlementHistoryObservation:
    """Build a synthetic Config Center/calendar observation without legal authority."""

    selected_history = _history() if history is None else history
    observed_at = datetime(2026, 11, 12, 8, tzinfo=UTC)
    return SimulatedTaxSettlementHistoryObservation(
        date_rule=SimulatedTaxDateRuleRuntimeProvenance(
            convention_sha256=selected_history.settlement_date_rule_sha256,
            environment="synthetic-test",
            definition_key="config_center.simulated_trading.dividend_tax_date_conventions",
            profile_id="synthetic-profile",
            profile_key="synthetic-profile-key",
            profile_version=1,
            profile_content_hash="7" * 64,
            snapshot_id="synthetic-runtime-snapshot",
            snapshot_hash="8" * 64,
            created_at=observed_at - timedelta(days=2),
            known_at=observed_at - timedelta(days=2),
            activated_at=observed_at - timedelta(days=1),
            snapshot_generated_at=observed_at - timedelta(days=1),
            effective_at=observed_at - timedelta(days=1),
            as_of=observed_at,
        ),
        history_identity_sha256=tax_history_domain._history_identity(selected_history),
        convention_valid_from=observed_at - timedelta(days=1),
        convention_valid_until=observed_at + timedelta(days=1),
        calendar_evidence_sha256="9" * 64,
        calendar_snapshot_id="synthetic-calendar-snapshot",
        calendar_content_sha256="sha256:" + "a" * 64,
        calendar_record_digest="sha256:" + "b" * 64,
        calendar_first_seen_at=observed_at - timedelta(minutes=5),
        calendar_recorded_at=observed_at - timedelta(minutes=4),
        calendar_response_completed_at=observed_at - timedelta(minutes=5),
        calendar_publication_id="synthetic-calendar-publication",
        calendar_publication_hash="c" * 64,
        calendar_published_at=observed_at - timedelta(minutes=3),
        calendar_publication_recorded_at=observed_at - timedelta(minutes=2),
        calendar_reference_valid_from=observed_at - timedelta(days=1),
        calendar_reference_valid_until=observed_at + timedelta(days=1),
        calendar_timezone_name="Asia/Shanghai",
        read_at=observed_at,
        date_observations=(),
    )


def test_assessment_runs_existing_calculator_and_preserves_exact_scope_and_allocations() -> None:
    record = _assessment()

    expected_bridge = record.bridge
    expected_tax = calculate_deferred_dividend_tax(expected_bridge.request, record.policy)
    assert record.calculation == expected_tax
    assert record.account_id == _ACCOUNT_ID
    assert record.owner_user_id == _OWNER_ID
    assert record.asset_code == "equity-cn"
    assert record.security_id == "600000.SH"
    assert record.calculation.settlement_date == _TARGET_DATE
    assert len(record.calculation.allocations) == 1
    assert record.calculation.allocations[0].sold_quantity == Decimal("10.000000")
    assert record.semantic_sha256 == record.verify_integrity().semantic_sha256


def test_semantic_hash_ignores_reobservation_but_manifest_retains_observation() -> None:
    first = _assessment()
    second = _assessment(
        bundle=_source_bundle(
            capture_id=UUID("22222222-2222-4222-8222-222222222222"),
            captured_at=datetime(2026, 11, 12, 1, tzinfo=UTC),
            bundle_id="synthetic-tax-fixture-observation-2",
            bundle_version="capture-v2",
        ),
        history=_history(
            proof_id="synthetic-ownership-proof-2",
            proof_sha256="9" * 64,
            proof_observed_at=datetime(2025, 3, 2, tzinfo=UTC),
        ),
    )

    assert first.semantic_sha256 == second.semantic_sha256
    assert first.semantic_payload_json == second.semantic_payload_json
    assert first.observation_manifest_sha256 != second.observation_manifest_sha256

    assert "synthetic-ownership-proof-1" in first.observation_manifest_json
    assert "synthetic-ownership-proof-2" in second.observation_manifest_json
    assert str(UUID("22222222-2222-4222-8222-222222222222")) in second.observation_manifest_json
    assert "ownership_snapshot_sha256" not in first.semantic_payload_json


def test_v2_timezone_provenance_refresh_preserves_tax_semantics_and_originals() -> None:
    """An unrelated profile activation changes proof provenance, not tax facts."""
    first = replace(_assessment(), semantic_schema_version=2)
    changed_proof = replace(
        first.history.record_date_ownership_proof,
        cutoff_policy_id="refreshed-profile-timezone-proof",
        cutoff_policy_sha256="e" * 64,
    )
    second = replace(
        first, history=replace(first.history, record_date_ownership_proof=changed_proof)
    )
    assert first.semantic_sha256 == second.semantic_sha256
    assert first.observation_manifest_sha256 != second.observation_manifest_sha256
    assert "refreshed-profile-timezone-proof" in second.observation_manifest_json
    assert second.verify_integrity() == second
    # Historical v1 assessment bytes and its stricter original identity remain valid.
    legacy = _assessment()
    assert legacy.semantic_schema_version == 1
    assert replace(legacy, history=second.history).semantic_sha256 != legacy.semantic_sha256


def test_v2_timezone_change_still_changes_tax_semantics() -> None:
    first = replace(_assessment(), semantic_schema_version=2)
    proof = first.history.record_date_ownership_proof
    changed = replace(
        proof,
        exchange_timezone_name="Asia/Tokyo",
        record_date_end_exclusive=proof.record_date_end_exclusive - timedelta(hours=1),
    )
    second = replace(first, history=replace(first.history, record_date_ownership_proof=changed))
    assert second.semantic_sha256 != first.semantic_sha256


def test_simulated_date_runtime_observation_changes_only_the_observation_manifest() -> None:
    original = _assessment()
    observation = _simulated_tax_date_observation()
    first = _assessment(simulated_tax_date_observation=observation)
    later_observation = replace(
        observation,
        calendar_publication_recorded_at=observation.calendar_publication_recorded_at
        + timedelta(seconds=1),
    )
    second = _assessment(simulated_tax_date_observation=later_observation)

    assert first.semantic_payload_json == original.semantic_payload_json
    assert second.semantic_payload_json == original.semantic_payload_json
    assert first.semantic_sha256 == second.semantic_sha256 == original.semantic_sha256
    assert first.observation_manifest_sha256 != original.observation_manifest_sha256
    assert second.observation_manifest_sha256 != first.observation_manifest_sha256
    assert "simulated_tax_settlement_observation" in first.observation_manifest_json


def test_assessment_rejects_a_simulated_date_observation_from_another_history_prefix() -> None:
    original_history = _history()
    changed_history = _history(changed_source_revision=True)
    observation = _simulated_tax_date_observation(original_history)

    with pytest.raises(DeferredDividendTaxValidationError):
        _assessment(
            history=changed_history,
            simulated_tax_date_observation=observation,
        )


def test_semantics_bind_zero_days_source_revisions_action_policy_and_fifo_facts() -> None:
    original = _assessment()
    changed_history = _assessment(history=_history(changed_source_revision=True))
    changed_action = _assessment(
        action=replace(
            original.action,
            source_revision_id="synthetic-action-revision-2",
            source_revision_sha256="6" * 64,
        )
    )
    changed_zero_day = replace(
        original.history.settlement_days[2],
        evidence_sha256="7" * 64,
    )
    changed_zero_day_history = replace(
        original.history,
        settlement_days=(
            *original.history.settlement_days[:2],
            changed_zero_day,
            *original.history.settlement_days[3:],
        ),
    )
    changed_zero_day_assessment = _assessment(history=changed_zero_day_history)
    original_policy = _policy(_source_bundle())
    changed_policy = _assessment(
        policy=replace(
            original_policy,
            bands=(
                replace(original_policy.bands[0], taxable_dividend_ratio=Decimal("0.5")),
                original_policy.bands[1],
            ),
        )
    )
    changed_source_set = _assessment(
        bundle=_source_bundle(
            capture_id=UUID("44444444-4444-4444-8444-444444444444"),
            source_version="fixture-r2",
        )
    )

    assert changed_history.semantic_sha256 != original.semantic_sha256
    assert changed_action.semantic_sha256 != original.semantic_sha256
    assert changed_zero_day_assessment.semantic_sha256 != original.semantic_sha256
    assert changed_policy.semantic_sha256 != original.semantic_sha256
    assert changed_source_set.semantic_sha256 != original.semantic_sha256
    assert "2025-02-28" in original.semantic_payload_json
    assert "gross_purchase_quantity" in original.semantic_payload_json
    assert "synthetic-settlement-day:2025-02-28" in original.semantic_payload_json


def test_low_decimal_context_does_not_change_assessment_semantics_or_result() -> None:
    with localcontext() as context:
        context.prec = 2
        record = _assessment()

    assert record.calculation.allocations[0].sold_quantity == Decimal("10.000000")
    assert record.semantic_sha256 == _assessment().semantic_sha256


def test_decimal_trailing_zeros_are_semantic_canonical_but_retained_in_legacy_hashes() -> None:
    original = _assessment()
    equivalent = _assessment(
        action=replace(original.action, dividend_per_share=Decimal("0.500000"))
    )

    assert equivalent.semantic_sha256 == original.semantic_sha256
    assert equivalent.semantic_payload_json == original.semantic_payload_json
    assert equivalent.calculation.evidence_sha256 != original.calculation.evidence_sha256
    assert equivalent.observation_manifest_sha256 != original.observation_manifest_sha256


@pytest.mark.parametrize(
    "changes",
    (
        {"account_id": 8},
        {"owner_user_id": 12},
        {"asset_code": "equity-us"},
        {"security_id": "000001.SZ"},
        {"record_date": date(2025, 2, 27)},
    ),
)
def test_action_cross_scope_and_date_are_rejected(changes: dict[str, object]) -> None:
    action = _assessment().action
    with pytest.raises(DeferredDividendTaxValidationError):
        _assessment(action=replace(action, **changes))


def test_policy_must_pin_the_complete_native_revision_set() -> None:
    bundle = _source_bundle()
    wrong_policy = replace(_policy(bundle), source_sha256="8" * 64)
    with pytest.raises(DeferredDividendTaxValidationError):
        CorporateActionTaxAssessment(
            assessment_revision_id="assessment-revision-1",
            supersedes_assessment_revision_id=None,
            action=_assessment().action,
            history=_history(),
            target_settlement_date=_TARGET_DATE,
            policy=wrong_policy,
            statutory_source_bundle=bundle,
        )


def test_invalid_revision_link_or_unknown_action_origin_cannot_construct_record() -> None:
    action = _assessment().action
    with pytest.raises(DeferredDividendTaxValidationError):
        _assessment(revision_id=" ")
    with pytest.raises(DeferredDividendTaxValidationError):
        CorporateActionTaxAssessment(
            assessment_revision_id="same",
            supersedes_assessment_revision_id="same",
            action=action,
            history=_history(),
            target_settlement_date=_TARGET_DATE,
            policy=_policy(_source_bundle()),
            statutory_source_bundle=_source_bundle(),
        )


def test_new_action_and_assessment_tokens_reject_unencodable_utf8() -> None:
    action = _assessment().action
    with pytest.raises(DeferredDividendTaxValidationError, match="UTF-8"):
        replace(action, source_event_id="\ud800")
    with pytest.raises(DeferredDividendTaxValidationError, match="UTF-8"):
        _assessment(revision_id="\ud800")
    with pytest.raises(DeferredDividendTaxValidationError, match="UTF-8"):
        replace(_assessment(), supersedes_assessment_revision_id="\ud800")


def test_action_value_requires_finite_supported_exact_decimal_and_real_dates() -> None:
    action = _assessment().action
    for dividend in (1.0, Decimal("NaN"), Decimal("-0.01"), Decimal("1e18"), Decimal("1e-13")):
        with pytest.raises(DeferredDividendTaxValidationError):
            replace(action, dividend_per_share=dividend)
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(action, record_date=datetime(2025, 2, 28, tzinfo=UTC))


def test_domain_canonical_helpers_and_payload_type_guards() -> None:
    with pytest.raises(DeferredDividendTaxValidationError, match="noncanonical value"):
        assessment_domain._canonical_json({"bad": object()})
    with pytest.raises(DeferredDividendTaxValidationError, match="Decimal must be finite"):
        assessment_domain._decimal_text(Decimal("sNaN"))
    with pytest.raises(DeferredDividendTaxValidationError, match="share quantity must be finite"):
        assessment_domain._share_text(Decimal("Infinity"))
    with pytest.raises(DeferredDividendTaxValidationError, match="timezone-aware"):
        assessment_domain._instant_text(datetime(2025, 1, 1), field_name="test")
    with pytest.raises(DeferredDividendTaxValidationError, match="untyped allocation"):
        assessment_domain._allocation_payload(object())
    with pytest.raises(DeferredDividendTaxValidationError, match="untyped day"):
        assessment_domain._settlement_day_payload(object())


@pytest.mark.parametrize(
    "field,value",
    (
        ("action", object()),
        ("history", object()),
        ("policy", object()),
        ("statutory_source_bundle", object()),
        ("supersedes_assessment_revision_id", "assessment-revision-1"),
    ),
)
def test_assessment_revalidates_each_exact_dependency_type_and_revision_link(
    field: str,
    value: object,
) -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(_assessment(), **{field: value})


def test_integrity_check_recomputes_and_rejects_mutated_derived_digest() -> None:
    record = _assessment()
    object.__setattr__(record, "semantic_sha256", "0" * 64)

    with pytest.raises(DeferredDividendTaxValidationError, match="no longer match"):
        record.verify_integrity()
