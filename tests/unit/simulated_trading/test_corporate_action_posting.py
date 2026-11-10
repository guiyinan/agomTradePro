"""Pure contract tests for source-qualified corporate-action stage requests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

import pytest

from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingReceipt,
    PostCorporateActionStageUseCase,
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
        "tax_rule_id": "exchange-disclosed-holding-period-tax",
        "tax_rule_sha256": "c" * 64,
        "ownership_snapshot_id": "account-history:11:2026-09-23",
        "ownership_snapshot_sha256": "d" * 64,
        "ownership_snapshot_as_of_date": _RECORD_DATE,
        "ownership_snapshot_observed_at": _OBSERVED_AT,
        "eligible_quantity": Decimal("1000.000000"),
        "entitlement_calculation_sha256": "e" * 64,
    }
    values.update(overrides)
    return cast(CorporateActionStageRequest, CorporateActionStageRequest(**values))


def test_cash_entitlement_requires_record_date_snapshot_and_tax_terms() -> None:
    """Late source capture still requires actual historical account ownership proof."""

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
            tax_rule_id="official-no-tax-term",
            tax_rule_sha256="c" * 64,
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
            tax_rule_id="official-no-tax-term",
            tax_rule_sha256="c" * 64,
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
            tax_rule_id="official-no-tax-term",
            tax_rule_sha256="c" * 64,
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
