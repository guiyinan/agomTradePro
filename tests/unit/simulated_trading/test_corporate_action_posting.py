"""Pure contract tests for source-qualified corporate-action stage requests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from apps.simulated_trading.application.corporate_action_posting import (
    AuditedCorporateActionPostingRepositoryPort,
    AuditedCorporateActionPostingRepositoryProtocol,
    CorporateActionOwnershipProofVerifier,
    CorporateActionPostingBlockedError,
    CorporateActionPostingReceipt,
    CorporateActionSourceQualificationVerifierProtocol,
    CorporateActionTaxBasisVerifierProtocol,
    HistoricalAccountOwnershipVerifierProtocol,
    PostCashDividendPaymentUseCase,
    PostCorporateActionStageUseCase,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.corporate_action_posting_composition import (
    build_corporate_action_payment_use_case,
    build_corporate_action_posting_use_case,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionInputValidationError,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
    calculate_corporate_action_delta,
)

_RECORD_DATE = date(2026, 9, 23)
_EFFECTIVE_DATE = date(2026, 9, 24)
_OBSERVED_AT = datetime(2026, 11, 10, 1, 0, tzinfo=UTC)
_QUALIFIED_AT = datetime(2026, 11, 10, 1, 5, tzinfo=UTC)
_POSTED_AT = datetime(2026, 11, 10, 1, 10, tzinfo=UTC)


def _request(**overrides: object) -> CorporateActionStageRequest:
    """Build one explicitly qualified synthetic exchange disclosure stage."""

    values: dict[str, object] = {
        "account_id": 11,
        "owner_user_id": 21,
        "security_id": "002727.SZ",
        "asset_code": "002727.SZ",
        "asset_name": "Synthetic security",
        "source_namespace": "exchange_official_disclosure",
        "source_record_id": "SZSE:2026:synthetic-pdf",
        "source_event_id": "SZSE:002727:2026-dividend",
        "source_revision_id": "sha256:notice-v1",
        "source_payload_sha256": "a" * 64,
        "qualification_sha256": "b" * 64,
        "qualifier_identity": "test-qualifier-v1",
        "source_observed_at": _OBSERVED_AT,
        "qualified_at": _QUALIFIED_AT,
        "posted_at": _POSTED_AT,
        "action_kind": CorporateActionKind.CASH_DIVIDEND,
        "stage": CorporateActionStage.CASH_ENTITLEMENT,
        "entry_kind": CorporateActionEntryKind.POSTING,
        "record_date": _RECORD_DATE,
        "effective_date": _EFFECTIVE_DATE,
        "stage_date": _EFFECTIVE_DATE,
        "cash_amount": Decimal("200.00"),
        "tax_treatment": "deferred_withholding",
        "tax_rule_id": None,
        "tax_rule_sha256": None,
        "ownership_snapshot_id": "account-history:11:2026-09-23",
        "ownership_snapshot_sha256": "d" * 64,
        "ownership_snapshot_as_of_date": _RECORD_DATE,
        "ownership_snapshot_observed_at": _OBSERVED_AT,
        "eligible_quantity": Decimal("1000.000000"),
        "entitlement_calculation_sha256": "e" * 64,
    }
    values.update(overrides)
    return cast(CorporateActionStageRequest, CorporateActionStageRequest(**values))


def _payment_request(**overrides: object) -> CorporateActionStageRequest:
    """Build a payment for the exact announced date without entitlement-only proof fields."""

    return _request(
        stage=CorporateActionStage.CASH_PAYMENT,
        stage_date=_EFFECTIVE_DATE,
        payment_date=_EFFECTIVE_DATE,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        **overrides,
    )


def _share_entitlement_request(
    entry_kind: CorporateActionEntryKind = CorporateActionEntryKind.POSTING,
) -> CorporateActionStageRequest:
    """Build one valid share entitlement with exact persisted ownership proof terms."""

    revision_values: dict[str, object] = {}
    if entry_kind is CorporateActionEntryKind.SUCCESSOR:
        revision_values["supersedes_revision_id"] = "sha256:notice-v0"
    return _request(
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        entry_kind=entry_kind,
        cash_amount=None,
        share_amount=Decimal("40.000000"),
        tax_treatment="not_applicable",
        tax_rule_id=None,
        tax_rule_sha256=None,
        odd_lot_policy="whole_shares",
        ownership_snapshot_observed_at=_QUALIFIED_AT,
        **revision_values,
    )


def _rights_no_effect_request() -> CorporateActionStageRequest:
    """Build one exact no-exercise rights row with the same retained snapshot proof."""

    return _request(
        action_kind=CorporateActionKind.RIGHTS_ISSUE,
        stage=CorporateActionStage.RIGHTS_NOT_EXERCISED,
        entry_kind=CorporateActionEntryKind.NO_EFFECT,
        cash_amount=None,
        share_amount=None,
        tax_treatment=None,
        tax_rule_id=None,
        tax_rule_sha256=None,
        rights_terms_sha256="f" * 64,
        rights_election="not_exercised",
        ownership_snapshot_observed_at=_QUALIFIED_AT,
    )


def _share_delivery_request() -> CorporateActionStageRequest:
    """Build a well-formed delivery request for the entitlement-only gate negative."""

    return _request(
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=CorporateActionStage.SHARE_DELIVERY,
        cash_amount=None,
        share_amount=Decimal("40.000000"),
        tax_treatment="not_applicable",
        tax_rule_id=None,
        tax_rule_sha256=None,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        odd_lot_policy="whole_shares",
        sellable_date=date(2026, 9, 25),
    )


def _share_release_request() -> CorporateActionStageRequest:
    """Build a reached sellable-release request for the entitlement-only gate negative."""

    return _request(
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=CorporateActionStage.SHARE_SELLABLE_RELEASE,
        stage_date=date(2026, 9, 25),
        cash_amount=None,
        share_amount=Decimal("40.000000"),
        tax_treatment="not_applicable",
        tax_rule_id=None,
        tax_rule_sha256=None,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        odd_lot_policy="whole_shares",
        sellable_date=date(2026, 9, 25),
    )


def _share_entitlement_reversal_request() -> CorporateActionStageRequest:
    """Build a valid reversal whose stage must not qualify as an ownership entry."""

    return _request(
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        source_revision_id="sha256:notice-v2",
        supersedes_revision_id="sha256:notice-v1",
        reversal_of_entry_id=101,
        cash_amount=None,
        share_amount=None,
        tax_treatment=None,
        tax_rule_id=None,
        tax_rule_sha256=None,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        odd_lot_policy=None,
        odd_lot_confirmation_sha256=None,
    )


def _rights_posting_request(
    entry_kind: CorporateActionEntryKind = CorporateActionEntryKind.POSTING,
) -> CorporateActionStageRequest:
    """Build a domain-valid non-NO_EFFECT rights row that the proof gate must deny."""

    revision_values: dict[str, object] = {}
    if entry_kind is CorporateActionEntryKind.SUCCESSOR:
        revision_values["supersedes_revision_id"] = "sha256:notice-v0"
    return _request(
        action_kind=CorporateActionKind.RIGHTS_ISSUE,
        stage=CorporateActionStage.RIGHTS_NOT_EXERCISED,
        entry_kind=entry_kind,
        cash_amount=None,
        share_amount=Decimal("40.000000"),
        tax_treatment="not_applicable",
        tax_rule_id=None,
        tax_rule_sha256=None,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        odd_lot_policy="whole_shares",
        **revision_values,
    )


def _tax_withholding_request() -> CorporateActionStageRequest:
    """Build a valid legacy tax stage that ownership proof must not authorize."""

    return _request(
        stage=CorporateActionStage.TAX_WITHHOLDING,
        stage_date=date(2026, 10, 20),
        cash_amount=Decimal("5.00"),
        tax_treatment="deferred_withholding",
        tax_rule_id="tax-rule:2026",
        tax_rule_sha256="a" * 64,
        tax_basis_record_id="assessment:disposition-1",
        tax_basis_sha256="b" * 64,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )


def _ownership_request_for_family(family: str) -> CorporateActionStageRequest:
    """Return a request family accepted by the record-date proof reader contract."""

    if family == "share":
        return _share_entitlement_request()
    if family == "rights":
        return _rights_no_effect_request()
    raise AssertionError(f"unknown ownership request family: {family}")


def _ownership_proof(**overrides: object) -> RecordDateOwnershipProof:
    """Build one exact account- and record-date-scoped replay proof."""

    values: dict[str, object] = {
        "account_id": 11,
        "owner_user_id": 21,
        "security_id": "002727.SZ",
        "asset_code": "002727.SZ",
        "record_date": _RECORD_DATE,
        "ownership_snapshot_as_of_date": _RECORD_DATE,
        "record_date_end_exclusive": datetime(2026, 9, 23, 16, 0, tzinfo=UTC),
        "exchange": "SZSE",
        "exchange_timezone_name": "Asia/Shanghai",
        "cutoff_policy_id": "exchange-timezone:v1",
        "cutoff_policy_sha256": "f" * 64,
        "eligible_quantity": Decimal("1000.000000"),
        "ownership_snapshot_id": "account-history:11:2026-09-23",
        "ownership_snapshot_sha256": "d" * 64,
        "ownership_snapshot_observed_at": _QUALIFIED_AT,
    }
    values.update(overrides)
    return cast(RecordDateOwnershipProof, RecordDateOwnershipProof(**values))


class _OwnershipProofReader:
    """Capture an exact proof read request for the application verifier tests."""

    def __init__(
        self,
        proof: RecordDateOwnershipProof,
        error: SimulatedTradeExecutionBlocked | None = None,
    ) -> None:
        self.proof = proof
        self.error = error
        self.scope: dict[str, object] | None = None

    def read_record_date_ownership_proof(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        security_id: str,
        asset_code: str,
        record_date: date,
        evidence_cutoff_at: datetime,
    ) -> RecordDateOwnershipProof:
        self.scope = {
            "account_id": account_id,
            "owner_user_id": owner_user_id,
            "security_id": security_id,
            "asset_code": asset_code,
            "record_date": record_date,
            "evidence_cutoff_at": evidence_cutoff_at,
        }
        if self.error is not None:
            raise self.error
        return self.proof


def test_cash_entitlement_requires_record_date_snapshot_and_disclosed_tax_treatment() -> None:
    """Late source capture still requires actual ownership proof and disclosed treatment."""

    with pytest.raises(CorporateActionInputValidationError) as missing_snapshot:
        _request(
            ownership_snapshot_id=None,
            ownership_snapshot_sha256=None,
            ownership_snapshot_as_of_date=None,
            ownership_snapshot_observed_at=None,
            eligible_quantity=None,
            entitlement_calculation_sha256=None,
        )
    assert missing_snapshot.value.code == "CORPORATE_ACTION_HISTORICAL_OWNERSHIP_UNKNOWN"

    with pytest.raises(CorporateActionInputValidationError) as wrong_record_date:
        _request(ownership_snapshot_as_of_date=date(2026, 11, 10))
    assert wrong_record_date.value.code == "CORPORATE_ACTION_HISTORICAL_OWNERSHIP_UNKNOWN"

    with pytest.raises(CorporateActionInputValidationError) as unknown_tax:
        _request(tax_rule_id=None, tax_rule_sha256=None, tax_treatment=None)
    assert unknown_tax.value.code == "CORPORATE_ACTION_TAX_TERMS_UNKNOWN"


def test_cash_entitlement_does_not_treat_disclosure_as_legal_tax_rule() -> None:
    """Disclosure tax terms stay separate from the later statutory withholding rule."""

    request = _request(tax_rule_id=None, tax_rule_sha256=None)
    assert request.tax_treatment == "deferred_withholding"
    assert request.tax_rule_id is None
    assert request.tax_rule_sha256 is None

    with pytest.raises(CorporateActionInputValidationError) as pseudo_rule:
        _request(
            tax_rule_id="szse:source-event-id",
            tax_rule_sha256="a" * 64,
        )
    assert pseudo_rule.value.code == "CORPORATE_ACTION_TAX_TERMS_UNKNOWN"


@pytest.mark.parametrize("exchange", ("SZSE", "SZ"))
@pytest.mark.parametrize(
    "entry_kind",
    (CorporateActionEntryKind.POSTING, CorporateActionEntryKind.SUCCESSOR),
)
def test_ownership_proof_verifier_reads_and_compares_exact_record_date_scope(
    exchange: str,
    entry_kind: CorporateActionEntryKind,
) -> None:
    """A caller-supplied snapshot is accepted only when the persisted replay matches it."""

    revision_values: dict[str, object] = {}
    if entry_kind is CorporateActionEntryKind.SUCCESSOR:
        revision_values["supersedes_revision_id"] = "sha256:notice-v0"
    request = _request(
        tax_rule_id=None,
        tax_rule_sha256=None,
        ownership_snapshot_observed_at=_QUALIFIED_AT,
        entry_kind=entry_kind,
        **revision_values,
    )
    reader = _OwnershipProofReader(_ownership_proof(exchange=exchange))
    verifier = CorporateActionOwnershipProofVerifier(reader)

    assert verifier.verify_ownership(request)
    assert reader.scope == {
        "account_id": request.account_id,
        "owner_user_id": request.owner_user_id,
        "security_id": request.security_id,
        "asset_code": request.asset_code,
        "record_date": request.record_date,
        "evidence_cutoff_at": request.qualified_at,
    }


@pytest.mark.parametrize("exchange", ("SZSE", "SZ"))
@pytest.mark.parametrize(
    "entry_kind",
    (CorporateActionEntryKind.POSTING, CorporateActionEntryKind.SUCCESSOR),
)
def test_ownership_proof_verifier_accepts_exact_share_entitlement_scope(
    exchange: str,
    entry_kind: CorporateActionEntryKind,
) -> None:
    """A share entitlement can use an exact record-date proof on an ordinary revision."""

    request = _share_entitlement_request(entry_kind)
    reader = _OwnershipProofReader(_ownership_proof(exchange=exchange))

    assert CorporateActionOwnershipProofVerifier(reader).verify_ownership(request)
    assert reader.scope == {
        "account_id": request.account_id,
        "owner_user_id": request.owner_user_id,
        "security_id": request.security_id,
        "asset_code": request.asset_code,
        "record_date": request.record_date,
        "evidence_cutoff_at": request.qualified_at,
    }


@pytest.mark.parametrize("exchange", ("SZSE", "SZ"))
def test_ownership_proof_verifier_accepts_only_the_exact_unexercised_rights_row(
    exchange: str,
) -> None:
    """A no-exercise rights row can bind to the same exact retained ownership scope."""

    request = _rights_no_effect_request()
    reader = _OwnershipProofReader(_ownership_proof(exchange=exchange))

    assert CorporateActionOwnershipProofVerifier(reader).verify_ownership(request)
    assert reader.scope == {
        "account_id": request.account_id,
        "owner_user_id": request.owner_user_id,
        "security_id": request.security_id,
        "asset_code": request.asset_code,
        "record_date": request.record_date,
        "evidence_cutoff_at": request.qualified_at,
    }


@pytest.mark.parametrize("family", ("share", "rights"))
@pytest.mark.parametrize(
    ("proof_field", "changed_value"),
    (
        ("account_id", 12),
        ("owner_user_id", 22),
        ("security_id", "301237.SZ"),
        ("asset_code", "301237.SZ"),
        ("record_date", date(2026, 9, 24)),
        ("ownership_snapshot_as_of_date", date(2026, 9, 24)),
        ("ownership_snapshot_id", "other-snapshot"),
        ("ownership_snapshot_sha256", "9" * 64),
        ("eligible_quantity", Decimal("999.000000")),
        ("ownership_snapshot_observed_at", _OBSERVED_AT),
        ("exchange", "SSE"),
        ("exchange", "SH"),
        ("exchange", "BJ"),
        ("exchange", "UNKNOWN"),
    ),
)
def test_ownership_proof_verifier_rejects_share_and_rights_proof_drift(
    family: str,
    proof_field: str,
    changed_value: object,
) -> None:
    """Every supported family still requires exact identity, quantity, clock, and seal."""

    request = _ownership_request_for_family(family)
    proof = replace(_ownership_proof(), **{proof_field: changed_value})
    reader = _OwnershipProofReader(proof)

    assert not CorporateActionOwnershipProofVerifier(reader).verify_ownership(request)
    assert reader.scope is not None


@pytest.mark.parametrize("family", ("share", "rights"))
def test_ownership_proof_verifier_rejects_request_identity_drift_for_new_families(
    family: str,
) -> None:
    """A persisted proof cannot authorize a request that changes its owner identity."""

    request = _ownership_request_for_family(family)
    reader = _OwnershipProofReader(_ownership_proof())

    assert not CorporateActionOwnershipProofVerifier(reader).verify_ownership(
        replace(request, owner_user_id=22)
    )


@pytest.mark.parametrize(
    ("proof_field", "changed_value"),
    (
        ("account_id", 12),
        ("owner_user_id", 22),
        ("security_id", "301237.SZ"),
        ("asset_code", "301237.SZ"),
        ("record_date", date(2026, 9, 24)),
        ("ownership_snapshot_as_of_date", date(2026, 9, 24)),
        ("ownership_snapshot_id", "other-snapshot"),
        ("ownership_snapshot_sha256", "9" * 64),
        ("eligible_quantity", Decimal("999.000000")),
        ("ownership_snapshot_observed_at", _OBSERVED_AT),
        ("exchange", "SSE"),
        ("exchange", "SH"),
        ("exchange", "BJ"),
        ("exchange", "UNKNOWN"),
    ),
)
def test_ownership_proof_verifier_blocks_any_proof_scope_or_content_drift(
    proof_field: str,
    changed_value: object,
) -> None:
    """A changed owner, instrument, record date, quantity, or evidence seal blocks."""

    request = _request(
        tax_rule_id=None,
        tax_rule_sha256=None,
        ownership_snapshot_observed_at=_QUALIFIED_AT,
    )
    reader = _OwnershipProofReader(replace(_ownership_proof(), **{proof_field: changed_value}))
    assert not CorporateActionOwnershipProofVerifier(reader).verify_ownership(request)


def test_ownership_proof_verifier_blocks_mismatched_request_and_unavailable_history() -> None:
    """Request identity and unavailable replay evidence cannot reach the ledger."""

    request = _request(
        tax_rule_id=None,
        tax_rule_sha256=None,
        ownership_snapshot_observed_at=_QUALIFIED_AT,
    )
    mismatched_reader = _OwnershipProofReader(_ownership_proof())
    assert not CorporateActionOwnershipProofVerifier(mismatched_reader).verify_ownership(
        replace(request, owner_user_id=22)
    )

    blocked_reader = _OwnershipProofReader(
        _ownership_proof(),
        SimulatedTradeExecutionBlocked("missing V4 history"),
    )
    assert not CorporateActionOwnershipProofVerifier(blocked_reader).verify_ownership(request)


def test_ownership_proof_verifier_requires_snapshot_clock_to_equal_qualified_cutoff() -> None:
    """An earlier caller clock cannot stand in for the exact replay cutoff."""

    request = _request(
        tax_rule_id=None,
        tax_rule_sha256=None,
        ownership_snapshot_observed_at=_OBSERVED_AT,
    )
    reader = _OwnershipProofReader(_ownership_proof())
    assert not CorporateActionOwnershipProofVerifier(reader).verify_ownership(request)
    assert reader.scope is None


@pytest.mark.parametrize(
    "candidate_request",
    (
        _payment_request(),
        _share_delivery_request(),
        _share_release_request(),
        _share_entitlement_reversal_request(),
        _tax_withholding_request(),
        _rights_posting_request(),
        _rights_posting_request(CorporateActionEntryKind.SUCCESSOR),
    ),
    ids=(
        "cash-payment",
        "share-delivery",
        "share-release",
        "share-reversal",
        "tax",
        "rights-posting",
        "rights-successor",
    ),
)
def test_ownership_proof_verifier_rejects_non_entitlement_stages_before_reading(
    candidate_request: CorporateActionStageRequest,
) -> None:
    """Payments, deliveries, releases, reversals, tax, and rights exercise are not proof grants."""

    reader = _OwnershipProofReader(_ownership_proof())

    assert not CorporateActionOwnershipProofVerifier(reader).verify_ownership(candidate_request)
    assert reader.scope is None


def test_tax_withholding_requires_legal_rule_and_tax_basis() -> None:
    """A withholding stage cannot substitute the corporate-action disclosure hash."""

    ownership_fields = {
        "ownership_snapshot_id": None,
        "ownership_snapshot_sha256": None,
        "ownership_snapshot_as_of_date": None,
        "ownership_snapshot_observed_at": None,
        "eligible_quantity": None,
        "entitlement_calculation_sha256": None,
    }
    with pytest.raises(CorporateActionInputValidationError) as missing_rule:
        _request(
            stage=CorporateActionStage.TAX_WITHHOLDING,
            stage_date=date(2026, 10, 20),
            tax_basis_record_id="assessment:disposition-1",
            tax_basis_sha256="f" * 64,
            tax_rule_id=None,
            tax_rule_sha256=None,
            **ownership_fields,
        )
    assert missing_rule.value.code == "CORPORATE_ACTION_TAX_TERMS_UNKNOWN"


def test_event_version_identity_is_a_stable_source_string() -> None:
    """Do not infer provider revision order from when a source was fetched."""

    request = _request(source_revision_id="sha256:canonical-source-version-2026-09-23")
    assert request.source_revision_id == "sha256:canonical-source-version-2026-09-23"
    assert request.stage_key == "posting:cash_entitlement"
    assert len(request.payload_sha256) == 64


def test_unknown_odd_lot_and_sellable_terms_fail_closed() -> None:
    """Share delivery requires exact whole-share allocation and an explicit T+1 date."""

    with pytest.raises(CorporateActionInputValidationError) as odd_lot:
        _request(
            action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
            stage=CorporateActionStage.SHARE_ENTITLEMENT,
            cash_amount=None,
            share_amount=Decimal("40.400000"),
            ownership_snapshot_id="account-history:11:2026-09-23",
            ownership_snapshot_sha256="d" * 64,
            ownership_snapshot_as_of_date=_RECORD_DATE,
            ownership_snapshot_observed_at=_OBSERVED_AT,
            eligible_quantity=Decimal("101.000000"),
            entitlement_calculation_sha256="e" * 64,
            tax_treatment="not_applicable",
            tax_rule_id=None,
            tax_rule_sha256=None,
            odd_lot_policy="whole_shares",
        )
    assert odd_lot.value.code == "CORPORATE_ACTION_ODD_LOT_TERMS_UNKNOWN"

    with pytest.raises(CorporateActionInputValidationError):
        _request(
            action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
            stage=CorporateActionStage.SHARE_DELIVERY,
            cash_amount=None,
            share_amount=Decimal("40.000000"),
            ownership_snapshot_id=None,
            ownership_snapshot_sha256=None,
            ownership_snapshot_as_of_date=None,
            ownership_snapshot_observed_at=None,
            eligible_quantity=None,
            entitlement_calculation_sha256=None,
            tax_treatment="not_applicable",
            tax_rule_id=None,
            tax_rule_sha256=None,
            odd_lot_policy="registry_final_quantity",
            odd_lot_confirmation_sha256="f" * 64,
            sellable_date=None,
        )

    with pytest.raises(CorporateActionInputValidationError):
        _request(
            action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
            stage=CorporateActionStage.SHARE_SELLABLE_RELEASE,
            entry_kind=CorporateActionEntryKind.POSTING,
            source_revision_id="sha256:share-v1",
            cash_amount=None,
            share_amount=Decimal("40.000000"),
            ownership_snapshot_id=None,
            ownership_snapshot_sha256=None,
            ownership_snapshot_as_of_date=None,
            ownership_snapshot_observed_at=None,
            eligible_quantity=None,
            entitlement_calculation_sha256=None,
            tax_treatment="not_applicable",
            tax_rule_id=None,
            tax_rule_sha256=None,
            odd_lot_policy="whole_shares",
            sellable_date=date(2026, 9, 25),
            stage_date=date(2026, 9, 24),
        )


def test_unexercised_rights_record_zero_economic_effect() -> None:
    """A no-exercise election records qualified ownership and terms without changes."""

    request = _request(
        action_kind=CorporateActionKind.RIGHTS_ISSUE,
        stage=CorporateActionStage.RIGHTS_NOT_EXERCISED,
        entry_kind=CorporateActionEntryKind.NO_EFFECT,
        cash_amount=None,
        tax_treatment=None,
        tax_rule_id=None,
        tax_rule_sha256=None,
        rights_terms_sha256="f" * 64,
        rights_election="not_exercised",
    )
    delta = calculate_corporate_action_delta(request)
    assert delta.cash == 0
    assert delta.cash_receivable == 0
    assert delta.shares == 0
    assert delta.share_receivable == 0
    assert delta.available_shares == 0


def test_source_revision_successor_names_stable_predecessor_id() -> None:
    """A correction names its source predecessor rather than using an ordinal."""

    corrected = replace(
        _request(),
        source_revision_id="sha256:notice-v2",
        supersedes_revision_id="sha256:notice-v1",
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        source_payload_sha256="9" * 64,
        qualification_sha256="8" * 64,
    )
    assert corrected.source_revision_id == "sha256:notice-v2"
    assert corrected.supersedes_revision_id == "sha256:notice-v1"
    assert corrected.stage_key == "successor:cash_entitlement"


def test_use_case_delegates_only_typed_explicit_stages() -> None:
    """Application facade forwards qualified stage tuples without I/O of its own."""

    class _Repository:
        def post_revision(
            self,
            requests: tuple[CorporateActionStageRequest, ...],
        ) -> tuple[CorporateActionPostingReceipt, ...]:
            return (
                CorporateActionPostingReceipt(
                    entry_id=7,
                    account_revision=3,
                    stage_key=requests[0].stage_key,
                    request_payload_sha256=requests[0].payload_sha256,
                    replayed=False,
                ),
            )

    result = PostCorporateActionStageUseCase(_Repository()).execute((_request(),))
    assert result[0].entry_id == 7
    assert not result[0].replayed


def test_cash_payment_use_case_accepts_only_one_cash_payment() -> None:
    """The payment facade delegates one typed payment and keeps entitlement separate."""

    class _Repository:
        def __init__(self) -> None:
            self.requests: tuple[CorporateActionStageRequest, ...] = ()

        def post_revision(
            self,
            requests: tuple[CorporateActionStageRequest, ...],
        ) -> tuple[CorporateActionPostingReceipt, ...]:
            self.requests = requests
            return (
                CorporateActionPostingReceipt(
                    entry_id=8,
                    account_revision=4,
                    stage_key=requests[0].stage_key,
                    request_payload_sha256=requests[0].payload_sha256,
                    replayed=False,
                ),
            )

    repository = _Repository()
    use_case = PostCashDividendPaymentUseCase(repository)
    payment = _payment_request()

    receipt = use_case.execute(payment)[0]

    assert receipt.entry_id == 8
    assert repository.requests == (payment,)
    with pytest.raises(CorporateActionPostingBlockedError) as blocked:
        use_case.execute(_request())
    assert blocked.value.code == "CORPORATE_ACTION_STAGE_UNSUPPORTED"


def test_production_composition_fails_closed_without_audited_repository() -> None:
    """A missing same-alias Audit/Outbox writer never exposes direct ledger posting."""

    with pytest.raises(CorporateActionPostingBlockedError) as blocked:
        build_corporate_action_posting_use_case(
            body_store_root=Path("official-bodies"),
            runtime_environment="test",
            audited_repository=None,
        )
    assert blocked.value.code == "CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE"
    with pytest.raises(CorporateActionPostingBlockedError) as payment_blocked:
        build_corporate_action_payment_use_case(
            body_store_root=Path("official-bodies"),
            runtime_environment="test",
            audited_repository=None,
        )
    assert payment_blocked.value.code == "CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE"


def test_production_composition_binds_required_audit_factory_and_blocks_withholding() -> None:
    """The runtime builder injects exact verifiers and never enables deferred withholding."""

    class _Repository:
        def get_database_alias(self) -> str:
            return "corporate_action_test"

        def post_revision_with_audit(
            self,
            requests: tuple[CorporateActionStageRequest, ...],
        ) -> tuple[CorporateActionPostingReceipt, ...]:
            return (
                CorporateActionPostingReceipt(
                    entry_id=9,
                    account_revision=4,
                    stage_key=requests[0].stage_key,
                    request_payload_sha256=requests[0].payload_sha256,
                    replayed=False,
                ),
            )

    class _AuditedRepositoryFactory:
        """Capture production-bound ports without providing a database implementation."""

        def __init__(self) -> None:
            self.source_qualifier: CorporateActionSourceQualificationVerifierProtocol | None = None
            self.ownership_verifier: HistoricalAccountOwnershipVerifierProtocol | None = None
            self.tax_basis_verifier: CorporateActionTaxBasisVerifierProtocol | None = None
            self.using: str | None = None
            self.repository = _Repository()

        def build_posting_repository(
            self,
            *,
            source_qualifier: CorporateActionSourceQualificationVerifierProtocol,
            ownership_verifier: HistoricalAccountOwnershipVerifierProtocol,
            tax_basis_verifier: CorporateActionTaxBasisVerifierProtocol | None,
            using: str,
        ) -> AuditedCorporateActionPostingRepositoryPort:
            self.source_qualifier = source_qualifier
            self.ownership_verifier = ownership_verifier
            self.tax_basis_verifier = tax_basis_verifier
            self.using = using
            return self.repository

    factory = _AuditedRepositoryFactory()
    use_case = build_corporate_action_posting_use_case(
        body_store_root=Path("official-bodies"),
        runtime_environment="test",
        audited_repository=cast(AuditedCorporateActionPostingRepositoryProtocol, factory),
        using="corporate_action_test",
    )

    receipt = use_case.execute(_request())[0]
    assert receipt.entry_id == 9
    assert factory.source_qualifier is not None
    assert isinstance(factory.ownership_verifier, CorporateActionOwnershipProofVerifier)
    assert factory.tax_basis_verifier is None
    assert factory.using == "corporate_action_test"

    payment_use_case = build_corporate_action_payment_use_case(
        body_store_root=Path("official-bodies"),
        runtime_environment="test",
        audited_repository=cast(AuditedCorporateActionPostingRepositoryProtocol, factory),
        using="corporate_action_test",
    )
    payment_receipt = payment_use_case.execute(_payment_request())[0]
    assert payment_receipt.entry_id == 9
    assert factory.source_qualifier is not None
    assert isinstance(factory.ownership_verifier, CorporateActionOwnershipProofVerifier)
    assert factory.tax_basis_verifier is None
    assert factory.using == "corporate_action_test"

    with pytest.raises(CorporateActionPostingBlockedError) as payment_rejected:
        use_case.execute(_payment_request())
    assert payment_rejected.value.code == "CORPORATE_ACTION_STAGE_UNSUPPORTED"

    withholding = replace(
        _request(),
        stage=CorporateActionStage.TAX_WITHHOLDING,
        stage_date=date(2026, 10, 20),
        tax_rule_id="synthetic-statutory-rule-v1",
        tax_rule_sha256="f" * 64,
        tax_basis_record_id="assessment:disposition-1",
        tax_basis_sha256="e" * 64,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )
    with pytest.raises(CorporateActionPostingBlockedError) as blocked:
        use_case.execute(withholding)
    assert blocked.value.code == "CORPORATE_ACTION_STAGE_UNSUPPORTED"


def test_production_composition_rejects_bare_repository_and_wrong_alias() -> None:
    """A factory cannot smuggle a raw ledger repository past the Audit/Outbox boundary."""

    class _BareRepository:
        def post_revision(
            self,
            requests: tuple[CorporateActionStageRequest, ...],
        ) -> tuple[CorporateActionPostingReceipt, ...]:
            return ()

    class _WrongAliasAuditedRepository:
        def get_database_alias(self) -> str:
            return "another_database"

        def post_revision_with_audit(
            self,
            requests: tuple[CorporateActionStageRequest, ...],
        ) -> tuple[CorporateActionPostingReceipt, ...]:
            return ()

    class _Factory:
        def __init__(self, result: object) -> None:
            self.result = result

        def build_posting_repository(
            self,
            *,
            source_qualifier: CorporateActionSourceQualificationVerifierProtocol,
            ownership_verifier: HistoricalAccountOwnershipVerifierProtocol,
            tax_basis_verifier: CorporateActionTaxBasisVerifierProtocol | None,
            using: str,
        ) -> AuditedCorporateActionPostingRepositoryPort:
            del source_qualifier, ownership_verifier, tax_basis_verifier, using
            return cast(AuditedCorporateActionPostingRepositoryPort, self.result)

    for factory in (
        _Factory(_BareRepository()),
        _Factory(_WrongAliasAuditedRepository()),
    ):
        with pytest.raises(CorporateActionPostingBlockedError) as blocked:
            build_corporate_action_posting_use_case(
                body_store_root=Path("official-bodies"),
                runtime_environment="test",
                audited_repository=cast(AuditedCorporateActionPostingRepositoryProtocol, factory),
                using="corporate_action_test",
            )
        assert blocked.value.code == "CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE"
