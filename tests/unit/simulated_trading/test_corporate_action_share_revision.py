"""Pure contracts for share distribution and rights-decline revision planning."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionInputValidationError,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.domain.corporate_action_share_revision import (
    CorporateActionShareRevisionPlan,
    plan_corporate_action_share_revision,
)

_RECORD_DATE = date(2026, 9, 23)
_EFFECTIVE_DATE = date(2026, 9, 24)
_SELLABLE_DATE = date(2026, 9, 25)
_OBSERVED_AT = datetime(2026, 11, 10, 1, 0, tzinfo=UTC)
_QUALIFIED_AT = datetime(2026, 11, 10, 1, 5, tzinfo=UTC)
_POSTED_AT = datetime(2026, 11, 10, 1, 10, tzinfo=UTC)
_SHARE_STAGES = (
    CorporateActionStage.SHARE_ENTITLEMENT,
    CorporateActionStage.SHARE_DELIVERY,
    CorporateActionStage.SHARE_SELLABLE_RELEASE,
)


def _share_request(
    stage: CorporateActionStage,
    *,
    entry_kind: CorporateActionEntryKind = CorporateActionEntryKind.POSTING,
    source_revision_id: str = "sha256:share-v1",
    supersedes_revision_id: str | None = None,
    reversal_of_entry_id: int | None = None,
    share_amount: Decimal | None = Decimal("40.000000"),
) -> CorporateActionStageRequest:
    """Build a schema-valid synthetic share-stage request for planner tests."""

    reversal = entry_kind is CorporateActionEntryKind.REVERSAL
    entitlement = stage is CorporateActionStage.SHARE_ENTITLEMENT
    release = stage is CorporateActionStage.SHARE_SELLABLE_RELEASE
    delivery = stage is CorporateActionStage.SHARE_DELIVERY
    return CorporateActionStageRequest(
        account_id=11,
        owner_user_id=21,
        security_id="002727.SZ",
        asset_code="002727.SZ",
        asset_name="Synthetic security",
        source_namespace="exchange_official_disclosure",
        source_record_id="SZSE:2026:synthetic-share-pdf",
        source_event_id="SZSE:002727:2026-share-distribution",
        source_revision_id=source_revision_id,
        source_payload_sha256="a" * 64,
        qualification_sha256="b" * 64,
        qualifier_identity="test-share-qualifier-v1",
        source_observed_at=_OBSERVED_AT,
        qualified_at=_QUALIFIED_AT,
        posted_at=_POSTED_AT,
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=stage,
        entry_kind=entry_kind,
        record_date=_RECORD_DATE,
        effective_date=_EFFECTIVE_DATE,
        stage_date=_SELLABLE_DATE if release else _EFFECTIVE_DATE,
        cash_amount=None,
        share_amount=None if reversal else share_amount,
        tax_treatment=None if reversal else "not_applicable",
        ownership_snapshot_id=(
            "snapshot:account-11:2026-09-23" if entitlement and not reversal else None
        ),
        ownership_snapshot_sha256=("c" * 64 if entitlement and not reversal else None),
        ownership_snapshot_as_of_date=(_RECORD_DATE if entitlement and not reversal else None),
        ownership_snapshot_observed_at=(_OBSERVED_AT if entitlement and not reversal else None),
        eligible_quantity=(Decimal("100.000000") if entitlement and not reversal else None),
        entitlement_calculation_sha256=("d" * 64 if entitlement and not reversal else None),
        odd_lot_policy=None if reversal else "whole_shares",
        sellable_date=_SELLABLE_DATE if (delivery or release) and not reversal else None,
        supersedes_revision_id=supersedes_revision_id,
        reversal_of_entry_id=reversal_of_entry_id,
    )


def _rights_no_effect_request() -> CorporateActionStageRequest:
    """Build one exact, source-qualified no-exercise rights row."""

    return CorporateActionStageRequest(
        account_id=11,
        owner_user_id=21,
        security_id="002727.SZ",
        asset_code="002727.SZ",
        asset_name="Synthetic security",
        source_namespace="exchange_official_disclosure",
        source_record_id="SZSE:2026:synthetic-rights-pdf",
        source_event_id="SZSE:002727:2026-rights-issue",
        source_revision_id="sha256:rights-v1",
        source_payload_sha256="a" * 64,
        qualification_sha256="b" * 64,
        qualifier_identity="test-rights-qualifier-v1",
        source_observed_at=_OBSERVED_AT,
        qualified_at=_QUALIFIED_AT,
        posted_at=_POSTED_AT,
        action_kind=CorporateActionKind.RIGHTS_ISSUE,
        stage=CorporateActionStage.RIGHTS_NOT_EXERCISED,
        entry_kind=CorporateActionEntryKind.NO_EFFECT,
        record_date=_RECORD_DATE,
        effective_date=_EFFECTIVE_DATE,
        stage_date=_EFFECTIVE_DATE,
        tax_treatment=None,
        ownership_snapshot_id="snapshot:account-11:2026-09-23",
        ownership_snapshot_sha256="c" * 64,
        ownership_snapshot_as_of_date=_RECORD_DATE,
        ownership_snapshot_observed_at=_OBSERVED_AT,
        eligible_quantity=Decimal("100.000000"),
        entitlement_calculation_sha256="d" * 64,
        rights_terms_sha256="e" * 64,
        rights_election="not_exercised",
    )


def _correction_requests() -> tuple[CorporateActionStageRequest, ...]:
    """Build one complete old-stage reversal and successor batch in caller order."""

    old_and_new = {
        stage: (
            _share_request(
                stage,
                entry_kind=CorporateActionEntryKind.REVERSAL,
                source_revision_id="sha256:share-v2",
                supersedes_revision_id="sha256:share-v1",
                reversal_of_entry_id=100 + index,
            ),
            _share_request(
                stage,
                entry_kind=CorporateActionEntryKind.SUCCESSOR,
                source_revision_id="sha256:share-v2",
                supersedes_revision_id="sha256:share-v1",
                share_amount=Decimal("50.000000"),
            ),
        )
        for index, stage in enumerate(_SHARE_STAGES, start=1)
    }
    return (
        old_and_new[CorporateActionStage.SHARE_SELLABLE_RELEASE][1],
        old_and_new[CorporateActionStage.SHARE_ENTITLEMENT][0],
        old_and_new[CorporateActionStage.SHARE_DELIVERY][1],
        old_and_new[CorporateActionStage.SHARE_SELLABLE_RELEASE][0],
        old_and_new[CorporateActionStage.SHARE_DELIVERY][0],
        old_and_new[CorporateActionStage.SHARE_ENTITLEMENT][1],
    )


@pytest.mark.parametrize(
    "stage,entry_kind",
    [
        (stage, entry_kind)
        for stage in _SHARE_STAGES
        for entry_kind in (CorporateActionEntryKind.POSTING, CorporateActionEntryKind.SUCCESSOR)
    ],
)
def test_planner_accepts_one_ordinary_share_stage_and_binds_gate_anchor(
    stage: CorporateActionStage,
    entry_kind: CorporateActionEntryKind,
) -> None:
    """A single ordinary row stays intact and anchors the owner grant check."""

    request = _share_request(
        stage,
        entry_kind=entry_kind,
        source_revision_id=(
            "sha256:share-v2"
            if entry_kind is CorporateActionEntryKind.SUCCESSOR
            else "sha256:share-v1"
        ),
        supersedes_revision_id=(
            "sha256:share-v1" if entry_kind is CorporateActionEntryKind.SUCCESSOR else None
        ),
    )
    plan = plan_corporate_action_share_revision((request,))

    assert type(plan) is CorporateActionShareRevisionPlan
    assert plan.requests == (request,)
    assert plan.gate_anchor is request
    assert plan.caller_stage_keys == (request.stage_key,)


def test_planner_orders_full_correction_dependent_stages_and_uses_successor_anchor() -> None:
    """Correction rows unwind dependents first and rebuild from entitlement forward."""

    submitted = _correction_requests()
    plan = plan_corporate_action_share_revision(submitted)

    assert tuple((request.entry_kind, request.stage) for request in plan.requests) == (
        (CorporateActionEntryKind.REVERSAL, CorporateActionStage.SHARE_SELLABLE_RELEASE),
        (CorporateActionEntryKind.REVERSAL, CorporateActionStage.SHARE_DELIVERY),
        (CorporateActionEntryKind.REVERSAL, CorporateActionStage.SHARE_ENTITLEMENT),
        (CorporateActionEntryKind.SUCCESSOR, CorporateActionStage.SHARE_ENTITLEMENT),
        (CorporateActionEntryKind.SUCCESSOR, CorporateActionStage.SHARE_DELIVERY),
        (CorporateActionEntryKind.SUCCESSOR, CorporateActionStage.SHARE_SELLABLE_RELEASE),
    )
    assert plan.gate_anchor is plan.requests[3]
    assert plan.caller_stage_keys == tuple(request.stage_key for request in submitted)


def test_planner_accepts_only_single_no_effect_rights_request() -> None:
    """The rights lane records an exact decline without authorizing an exercise."""

    request = _rights_no_effect_request()
    plan = plan_corporate_action_share_revision((request,))

    assert plan.requests == (request,)
    assert plan.gate_anchor is request


@pytest.mark.parametrize(
    "changed_request",
    [
        replace(_correction_requests()[0], account_id=12),
        replace(_correction_requests()[0], security_id="000001.SZ"),
        replace(_correction_requests()[0], source_record_id="another-pdf"),
        replace(_correction_requests()[0], source_event_id="another-logical-event"),
        replace(_correction_requests()[0], source_payload_sha256="f" * 64),
        replace(_correction_requests()[0], qualification_sha256="f" * 64),
        replace(_correction_requests()[0], record_date=date(2026, 9, 22)),
        replace(_correction_requests()[0], effective_date=date(2026, 9, 25)),
        replace(_correction_requests()[0], qualified_at=_QUALIFIED_AT.replace(minute=6)),
    ],
)
def test_correction_rejects_mixed_account_security_source_or_revision_identity(
    changed_request: CorporateActionStageRequest,
) -> None:
    """Every correction member shares the full immutable owner/source identity."""

    with pytest.raises(CorporateActionInputValidationError) as captured:
        plan_corporate_action_share_revision((_correction_requests()[3], changed_request))
    assert captured.value.code == "CORPORATE_ACTION_BATCH_IDENTITY_INVALID"


def test_correction_requires_matching_unique_stage_sets_and_immediate_predecessor() -> None:
    """A correction cannot omit a predecessor stage or name a different head."""

    submitted = _correction_requests()
    incomplete = submitted[:-1]
    wrong_predecessor = replace(submitted[-1], supersedes_revision_id="sha256:older-share-v0")

    for requests in (incomplete, (submitted[0], submitted[0]), (submitted[0], wrong_predecessor)):
        with pytest.raises(CorporateActionInputValidationError):
            plan_corporate_action_share_revision(requests)


def test_planner_rejects_cash_mixed_families_and_rights_corrections() -> None:
    """Only a homogeneous share revision or one no-effect rights row is accepted."""

    rights = _rights_no_effect_request()
    share = _share_request(CorporateActionStage.SHARE_ENTITLEMENT)
    cash = replace(
        share,
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        cash_amount=Decimal("1.00"),
        share_amount=None,
        tax_treatment="deferred_withholding",
        odd_lot_policy=None,
        odd_lot_confirmation_sha256=None,
    )
    for requests in ((rights, _rights_no_effect_request()), (share, rights), (share, cash)):
        with pytest.raises(CorporateActionInputValidationError):
            plan_corporate_action_share_revision(requests)


def test_planner_rejects_invalid_container_empty_requests_and_reversal_only_batch() -> None:
    """Malformed or incomplete revision inputs fail before reaching a persistence gate."""

    reversal = _correction_requests()[1]
    for requests in ([], (), (reversal,)):
        with pytest.raises(CorporateActionInputValidationError):
            plan_corporate_action_share_revision(requests)  # type: ignore[arg-type]


def test_plan_constructor_rejects_incomplete_structural_proofs() -> None:
    """A manually assembled plan cannot omit or substitute its immutable route facts."""

    request = _share_request(CorporateActionStage.SHARE_ENTITLEMENT)
    invalid_values = (
        {
            "requests": (),
            "gate_anchor": request,
            "caller_stage_keys": (request.stage_key,),
        },
        {
            "requests": (object(),),
            "gate_anchor": request,
            "caller_stage_keys": (request.stage_key,),
        },
        {
            "requests": (request,),
            "gate_anchor": _share_request(CorporateActionStage.SHARE_DELIVERY),
            "caller_stage_keys": (request.stage_key,),
        },
        {
            "requests": (request,),
            "gate_anchor": request,
            "caller_stage_keys": ("posting:another-stage",),
        },
    )
    for values in invalid_values:
        with pytest.raises(CorporateActionInputValidationError):
            CorporateActionShareRevisionPlan(**values)  # type: ignore[arg-type]


def test_planner_rejects_wrong_request_type_and_preserves_domain_input_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid request members fail closed with stable Domain error types and codes."""

    request = _share_request(CorporateActionStage.SHARE_ENTITLEMENT)
    with pytest.raises(CorporateActionInputValidationError) as wrong_type:
        plan_corporate_action_share_revision((object(),))  # type: ignore[arg-type]
    assert wrong_type.value.code == "CORPORATE_ACTION_INPUT_INVALID"

    object.__setattr__(request, "share_amount", Decimal("0"))
    with pytest.raises(CorporateActionInputValidationError) as invalid_domain_request:
        plan_corporate_action_share_revision((request,))
    assert invalid_domain_request.value.code == "CORPORATE_ACTION_INPUT_INVALID"

    valid_request = _share_request(CorporateActionStage.SHARE_ENTITLEMENT)

    def invalid_post_init(self: CorporateActionStageRequest) -> None:
        del self
        raise TypeError("synthetic malformed request")

    monkeypatch.setattr(CorporateActionStageRequest, "__post_init__", invalid_post_init)
    with pytest.raises(CorporateActionInputValidationError) as normalized:
        plan_corporate_action_share_revision((valid_request,))
    assert normalized.value.code == "CORPORATE_ACTION_INPUT_INVALID"


def test_planner_rejects_multi_posting_batches_and_reversal_only_revisions() -> None:
    """Ordinary writes stay single-stage and corrections require successor rows."""

    entitlement = _share_request(CorporateActionStage.SHARE_ENTITLEMENT)
    delivery = _share_request(CorporateActionStage.SHARE_DELIVERY)
    correction = _correction_requests()
    reversal_entitlement = correction[1]
    reversal_delivery = correction[4]

    for requests in (
        (entitlement, delivery),
        (reversal_entitlement, reversal_delivery),
    ):
        with pytest.raises(CorporateActionInputValidationError):
            plan_corporate_action_share_revision(requests)
