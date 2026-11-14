"""Synthetic no-DB contracts for full owner event-head replay."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.simulated_trading import corporate_action_owner_event_history_composition as composition
from apps.simulated_trading.application.corporate_action_owner_posting_read import (
    OwnerCorporateActionActivePostingHead,
)
from apps.simulated_trading.domain.corporate_action_owner_revision import (
    OwnerCorporateActionRevisionEntry,
    prepare_owner_corporate_action_revision,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionLedgerDelta,
    calculate_corporate_action_delta,
)
from tests.unit.simulated_trading.test_corporate_action_owner_revision_domain import (
    _cash_correction_history,
    _history,
    _inverse_delta,
    _share_replacements,
)

_ACCOUNT_ID = 1101
_OWNER_ID = 2101
_CANONICAL_ACCOUNT_ID = "canonical-1101"
_SOURCE_NAMESPACE = "exchange_official_disclosure"
_SOURCE_EVENT_ID = "synthetic-logical-action"
_SOURCE_RECORD_ID = "source-record-2"
_SOURCE_REVISION_ID = "revision-2"
_SECURITY_ID = "000001.SZ"
_AS_OF = datetime(2026, 11, 14, 11, 0, tzinfo=UTC)
_RECORD_DATE = date(2026, 10, 30)
_EFFECTIVE_DATE = date(2026, 10, 31)


def _share_correction_history() -> tuple[OwnerCorporateActionRevisionEntry, ...]:
    """Build a complete synthetic share correction using the canonical Domain planner."""

    original = _history(*_share_replacements(revision="revision-1"))
    prepared = prepare_owner_corporate_action_revision(
        history=original,
        expected_head_revision_id="revision-1",
        replacement_requests=_share_replacements(revision="revision-2"),
        as_of_date=date(2026, 11, 14),
    )
    original_by_id = {entry.entry_id: entry for entry in original}
    corrected = tuple(
        OwnerCorporateActionRevisionEntry(
            entry_id=401 + index,
            account_revision=len(original) + index + 1,
            request=request,
            delta=(
                _inverse_delta(original_by_id[request.reversal_of_entry_id].delta)
                if request.entry_kind is CorporateActionEntryKind.REVERSAL
                else calculate_corporate_action_delta(request)
            ),
        )
        for index, request in enumerate(prepared.requests)
    )
    return original + corrected


def _install(
    monkeypatch: pytest.MonkeyPatch,
    history: tuple[OwnerCorporateActionRevisionEntry, ...],
) -> dict[str, object]:
    """Replace only IO seams with in-memory facts and collect read arguments."""

    account_reads: list[dict[str, object]] = []
    history_reads: list[dict[str, object]] = []
    account = SimpleNamespace(pk=_ACCOUNT_ID, user_id=_OWNER_ID, account_type="simulated")

    def read_account(**kwargs: object) -> object:
        account_reads.append(dict(kwargs))
        return account

    def read_history(**kwargs: object) -> tuple[OwnerCorporateActionRevisionEntry, ...]:
        history_reads.append(dict(kwargs))
        return history

    monkeypatch.setattr(composition, "_read_owned_account", read_account)
    monkeypatch.setattr(
        composition,
        "read_locked_owner_corporate_action_revision_history",
        read_history,
    )
    monkeypatch.setattr(composition.transaction, "atomic", lambda **kwargs: nullcontext())
    return {"account": account, "account_reads": account_reads, "history_reads": history_reads}


def _read(
    *,
    canonical_account_id: str | None = _CANONICAL_ACCOUNT_ID,
    source_revision_id: str = _SOURCE_REVISION_ID,
    source_record_id: str = _SOURCE_RECORD_ID,
    action_kind: CorporateActionKind = CorporateActionKind.CASH_DIVIDEND,
) -> OwnerCorporateActionActivePostingHead:
    """Read a synthetic corrected source head using exact revision and owner scope."""

    return composition.read_current_owner_corporate_action_active_postings(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        canonical_account_id=canonical_account_id,
        source_namespace=_SOURCE_NAMESPACE,
        source_event_id=_SOURCE_EVENT_ID,
        source_record_id=source_record_id,
        source_revision_id=source_revision_id,
        security_id=_SECURITY_ID,
        asset_code=_SECURITY_ID,
        action_kind=action_kind,
        record_date=_RECORD_DATE,
        effective_date=_EFFECTIVE_DATE,
        as_of=_AS_OF,
        using="synthetic-test",
    )


def test_full_cash_correction_returns_only_current_active_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = _cash_correction_history()
    calls = _install(monkeypatch, history)

    result = _read()

    assert result.source_revision_id == _SOURCE_REVISION_ID
    assert [entry.request.stage.value for entry in result.active_entries] == [
        "cash_entitlement",
        "cash_payment",
    ]
    assert all(
        entry.request.source_revision_id == _SOURCE_REVISION_ID for entry in result.active_entries
    )
    assert calls["account_reads"] == [
        {
            "account_id": _ACCOUNT_ID,
            "owner_user_id": _OWNER_ID,
            "using": "synthetic-test",
            "as_of": _AS_OF,
        }
    ]
    assert calls["history_reads"] == [
        {
            "account": calls["account"],
            "canonical_account_id": _CANONICAL_ACCOUNT_ID,
            "source_namespace": _SOURCE_NAMESPACE,
            "source_event_id": _SOURCE_EVENT_ID,
            "as_of": _AS_OF,
            "using": "synthetic-test",
        }
    ]


def test_full_share_correction_returns_three_current_active_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = _share_correction_history()
    _install(monkeypatch, history)

    result = _read(action_kind=CorporateActionKind.SHARE_DISTRIBUTION)

    assert [entry.request.stage.value for entry in result.active_entries] == [
        "share_entitlement",
        "share_delivery",
        "share_sellable_release",
    ]


def test_new_current_source_without_matching_ledger_head_requires_explicit_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _cash_correction_history())

    with pytest.raises(composition.CorporateActionOwnerEventPreparationBlocked) as error:
        _read(source_revision_id="revision-3")

    assert error.value.code == "CORPORATE_ACTION_OWNER_CORRECTION_REQUIRED"


def test_missing_canonical_account_identity_blocks_before_history_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, _cash_correction_history())

    with pytest.raises(composition.CorporateActionOwnerEventPreparationBlocked) as error:
        _read(canonical_account_id=None)

    assert error.value.code == "CORPORATE_ACTION_OWNER_CORRECTION_REQUIRED"
    assert calls["account_reads"] == []
    assert calls["history_reads"] == []


def test_partial_correction_batch_is_rejected_after_full_history_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = _cash_correction_history()[:-1]
    _install(monkeypatch, history)

    with pytest.raises(composition.CorporateActionOwnerEventPreparationBlocked) as error:
        _read()

    assert error.value.code == "CORPORATE_ACTION_OWNER_CORRECTION_HISTORY_INVALID"


def test_tampered_original_delta_is_rejected_by_full_revision_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = _cash_correction_history()
    corrupt = replace(
        history[0],
        delta=CorporateActionLedgerDelta(cash_receivable=Decimal("120.01")),
    )
    _install(monkeypatch, (corrupt, *history[1:]))

    with pytest.raises(composition.CorporateActionOwnerEventPreparationBlocked) as error:
        _read()

    assert error.value.code == "CORPORATE_ACTION_OWNER_CORRECTION_HISTORY_INVALID"


def test_mixed_owner_scope_in_full_event_history_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = _cash_correction_history()
    changed_request = replace(history[-1].request, owner_user_id=_OWNER_ID + 1)
    mixed_history = (*history[:-1], replace(history[-1], request=changed_request))
    _install(monkeypatch, mixed_history)

    with pytest.raises(composition.CorporateActionOwnerEventPreparationBlocked) as error:
        _read()

    assert error.value.code == "CORPORATE_ACTION_OWNER_CORRECTION_HISTORY_INVALID"


def test_active_head_dto_rejects_a_stage_from_another_source_record() -> None:
    history = _cash_correction_history()
    active = history[-2:]
    mismatched = replace(active[0].request, source_record_id="wrong-record")

    with pytest.raises(ValueError):
        OwnerCorporateActionActivePostingHead(
            account_id=_ACCOUNT_ID,
            owner_user_id=_OWNER_ID,
            canonical_account_id=_CANONICAL_ACCOUNT_ID,
            source_namespace=_SOURCE_NAMESPACE,
            source_event_id=_SOURCE_EVENT_ID,
            source_record_id=_SOURCE_RECORD_ID,
            source_revision_id=_SOURCE_REVISION_ID,
            security_id=_SECURITY_ID,
            asset_code=_SECURITY_ID,
            action_kind=CorporateActionKind.CASH_DIVIDEND,
            record_date=_RECORD_DATE,
            effective_date=_EFFECTIVE_DATE,
            active_entries=(replace(active[0], request=mismatched), active[1]),
        )


def test_active_head_dto_rejects_changed_delta_with_unchanged_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _cash_correction_history())
    head = _read()
    changed = replace(
        head.active_entries[0],
        delta=CorporateActionLedgerDelta(cash_receivable=Decimal("999.00")),
    )
    with pytest.raises(ValueError):
        replace(head, active_entries=(changed, *head.active_entries[1:]))
