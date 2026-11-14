"""Historical consent evidence never substitutes for current write authority."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantRecord,
)
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.simulated_trading import corporate_action_owner_ledger_composition as ledger
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingReceipt,
)
from apps.simulated_trading.audited_corporate_action_posting_composition import _build_event
from apps.simulated_trading.domain.corporate_action_owner_revision import (
    OwnerCorporateActionRevisionEntry,
    read_owner_corporate_action_revision_head,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionInputValidationError,
    CorporateActionLedgerDelta,
)
from core.exceptions import BusinessLogicError
from tests.unit.account.test_simulated_corporate_action_write_grant import (
    _binding,
    _grant,
    _revocation,
)
from tests.unit.simulated_trading.test_corporate_action_current_official_window import (
    _NOW,
    _request,
)


def test_genuinely_empty_owned_ledger_needs_no_audit_stream_lock(monkeypatch):
    account = SimpleNamespace(
        pk=17,
        user_id=23,
        account_type="simulated",
        updated_at=_NOW,
        _state=SimpleNamespace(db="default"),
    )

    class Rows:
        def using(self, *args):
            return self

        def select_for_update(self):
            return self

        def filter(self, **kwargs):
            return self

        def order_by(self, *args):
            return self

        def get(self, **kwargs):
            return account

        def __getitem__(self, key):
            return ()

    rows = Rows()
    monkeypatch.setattr(
        ledger,
        "connections",
        {"default": SimpleNamespace(in_atomic_block=True, get_autocommit=lambda: False)},
    )
    monkeypatch.setattr(ledger, "SimulatedAccountModel", SimpleNamespace(_base_manager=rows))
    monkeypatch.setattr(ledger, "CorporateActionPostingModel", SimpleNamespace(_base_manager=rows))
    monkeypatch.setattr(
        ledger,
        "build_tax_assessment_audit_coordinator",
        lambda **kwargs: pytest.fail("empty original ledger has no Audit streams"),
    )
    result = ledger.read_locked_owner_corporate_action_posting_state(
        account=account, canonical_account_id="actual-canonical-17", as_of=_NOW, using="default"
    )
    assert result.dividend_receivable == 0
    assert result.share_receivables == result.audit_receipts == ()
    assert result.revision_entries == ()


def test_posting_state_keeps_three_argument_constructor_compatible():
    state = ledger.OwnerCorporateActionPostingState(Decimal("0"), (), ())

    assert state.revision_entries == ()


def _revision_entry(
    entry_id: int,
    account_revision: int,
    *,
    request=None,
) -> OwnerCorporateActionRevisionEntry:
    selected_request = request if request is not None else _request()
    return OwnerCorporateActionRevisionEntry(
        entry_id=entry_id,
        account_revision=account_revision,
        request=selected_request,
        delta=CorporateActionLedgerDelta(cash_receivable=selected_request.cash_amount),
    )


def test_event_history_filters_only_after_verified_account_read_and_keeps_mixed_asset_rows(
    monkeypatch,
):
    account = SimpleNamespace(pk=17, user_id=23, account_type="simulated", updated_at=_NOW)
    request = _request()
    same_event_other_asset = replace(
        request,
        asset_code="000002.SZ",
        security_id="000002.SZ",
    )
    other_event = replace(
        request,
        source_record_id="other-event",
        source_event_id="other-event",
        source_revision_id="other-revision",
    )
    state = ledger.OwnerCorporateActionPostingState(
        Decimal("100.00"),
        (),
        (),
        (
            _revision_entry(1, 1, request=request),
            _revision_entry(2, 2, request=same_event_other_asset),
            _revision_entry(3, 3, request=other_event),
        ),
    )
    calls = []

    def read_full_account(**kwargs):
        calls.append(kwargs)
        return state

    monkeypatch.setattr(
        ledger, "read_locked_owner_corporate_action_posting_state", read_full_account
    )
    entries = ledger.read_locked_owner_corporate_action_revision_history(
        account=account,
        canonical_account_id="actual-canonical-17",
        source_namespace=request.source_namespace,
        source_event_id=request.source_event_id,
        as_of=_NOW,
        using="default",
    )

    assert calls == [
        {
            "account": account,
            "canonical_account_id": "actual-canonical-17",
            "as_of": _NOW,
            "using": "default",
        }
    ]
    assert tuple(entry.entry_id for entry in entries) == (1, 2)
    assert {entry.request.asset_code for entry in entries} == {"000001.SZ", "000002.SZ"}
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(entries, request.source_revision_id)


def test_event_history_rejects_empty_identity_before_database_read(monkeypatch):
    monkeypatch.setattr(
        ledger,
        "read_locked_owner_corporate_action_posting_state",
        lambda **kwargs: pytest.fail("invalid event identity must not begin the account read"),
    )

    with pytest.raises(BusinessLogicError) as error:
        ledger.read_locked_owner_corporate_action_revision_history(
            account=SimpleNamespace(pk=17),
            canonical_account_id="canonical-17",
            source_namespace=" ",
            source_event_id="event-1",
            as_of=_NOW,
            using="default",
        )

    assert error.value.code == "CORPORATE_ACTION_ORIGINAL_LEDGER_UNVERIFIED"


def _facts(*, expires=False):
    request = _request()
    grant = _grant(
        recorded_at=_NOW - timedelta(minutes=1),
        valid_until=_NOW if expires else _NOW + timedelta(minutes=1),
        binding=_binding(owner_user_id=request.owner_user_id),
    )
    scope = AuditScopeRef(grant.binding.tenant_id, grant.binding.owner_id)
    receipt = CorporateActionPostingReceipt(1, 1, request.stage_key, request.payload_sha256, False)
    event = _build_event(
        request,
        receipt,
        recorded_at=_NOW,
        sequence_no=1,
        predecessor_hash=None,
        scope=scope,
        owner_grant=grant,
    )
    return request, grant, event


@pytest.mark.parametrize("withdrawn_later", (False, True))
def test_original_consent_remains_readable_after_later_withdrawal(withdrawn_later):
    request, grant, event = _facts()
    record = SimulatedCorporateActionWriteGrantRecord(
        grant,
        _revocation(grant, recorded_at=_NOW + timedelta(seconds=10)) if withdrawn_later else None,
    )
    assert (
        ledger._verified_original_grant(
            request,
            event,
            (record,),
            canonical_account_id=grant.binding.account_id,
            required_capability=Capability.CASH_STAGE_WRITE,
        )
        == grant
    )


@pytest.mark.parametrize("failure", ("expired", "revoked_before", "wrong_capability", "superseded"))
def test_readback_rejects_consent_that_was_invalid_at_the_original_audit(failure):
    request, grant, event = _facts(expires=failure == "expired")
    record = SimulatedCorporateActionWriteGrantRecord(
        grant,
        (
            _revocation(grant, recorded_at=_NOW - timedelta(seconds=10))
            if failure == "revoked_before"
            else None
        ),
    )
    records = (record,)
    if failure == "superseded":
        successor = _grant(
            grant_version="2",
            recorded_at=_NOW - timedelta(seconds=5),
            valid_until=_NOW + timedelta(minutes=1),
            supersedes_content_hash=grant.content_hash,
            binding=grant.binding,
        )
        records += (SimulatedCorporateActionWriteGrantRecord(successor),)
    with pytest.raises(BusinessLogicError):
        ledger._verified_original_grant(
            request,
            event,
            records,
            canonical_account_id=grant.binding.account_id,
            required_capability=(
                Capability.SHARE_STAGE_WRITE
                if failure == "wrong_capability"
                else Capability.CASH_STAGE_WRITE
            ),
        )
