"""Synthetic orchestration checks; native locks and browser authority are separate."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
from apps.simulated_trading import corporate_action_owner_workflow_composition as workflow
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingReceipt,
)
from core.exceptions import AuthorizationError, BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_owner_intent_codec import _intent


def _prepare_context(context, monkeypatch):
    intent, account = context
    monkeypatch.setattr(
        workflow,
        "select_owner_workflow_event",
        lambda *a, **k: SimpleNamespace(asset_code=intent.source_reference.asset_code),
    )
    monkeypatch.setattr(
        workflow,
        "read_owner_preparation_window",
        lambda *a, **k: SimpleNamespace(
            expires_at=intent.prepared_at + timedelta(seconds=40), checked_at=intent.prepared_at
        ),
    )
    return intent, account


def test_ordinary_prepare_never_calls_the_correction_builder(context, monkeypatch):
    intent, account = _prepare_context(context, monkeypatch)
    monkeypatch.setattr(
        workflow,
        "prepare_owner_official_corporate_action",
        lambda **k: SimpleNamespace(
            source_reference=intent.source_reference,
            requests=intent.requests,
            tax_action=None,
            revision_preview=None,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "prepare_owner_official_corporate_action_revision",
        lambda **k: pytest.fail("ordinary operation selected a correction"),
    )
    monkeypatch.setattr(workflow, "seal_owner_corporate_action_intent", lambda *a, **k: "opaque")
    result = workflow.prepare_owner_corporate_action_workflow(
        object(), account_id=account.account_id, event_id="known", action="cash_entitlement"
    )
    assert result["outcome"] == "success"


def test_explicit_correction_rejects_a_missing_full_batch_preview(context, monkeypatch):
    intent, account = _prepare_context(context, monkeypatch)
    monkeypatch.setattr(
        workflow,
        "prepare_owner_official_corporate_action",
        lambda **k: pytest.fail("correction fell back to ordinary"),
    )
    monkeypatch.setattr(
        workflow,
        "prepare_owner_official_corporate_action_revision",
        lambda **k: SimpleNamespace(
            source_reference=intent.source_reference,
            requests=intent.requests,
            tax_action=None,
            revision_preview=None,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "seal_owner_corporate_action_intent",
        lambda *a, **k: pytest.fail("incomplete correction was sealed"),
    )
    result = workflow.prepare_owner_corporate_action_workflow(
        object(),
        account_id=account.account_id,
        event_id="known",
        action="cash_entitlement",
        correction_mode="correct_existing",
    )
    assert result["blocking_reason"] == "CORPORATE_ACTION_OWNER_REVISION_PREVIEW_INVALID"


def test_explicit_correction_seals_the_complete_previewed_batch(context, monkeypatch):
    from apps.simulated_trading.application.corporate_action_owner_revision_preview import (
        build_owner_corporate_action_revision_preview,
    )
    from apps.simulated_trading.domain.corporate_action_owner_revision import (
        OwnerCorporateActionRevisionEntry,
        prepare_owner_corporate_action_revision,
    )
    from apps.simulated_trading.domain.corporate_action_posting import (
        calculate_corporate_action_delta,
    )

    intent, account = _prepare_context(context, monkeypatch)
    original = intent.source_reference
    entry = OwnerCorporateActionRevisionEntry(
        11, 1, original, calculate_corporate_action_delta(original)
    )
    successor = replace(
        original,
        source_revision_id="explicit-next-revision",
        source_record_id="explicit-next-document",
    )
    batch = prepare_owner_corporate_action_revision(
        history=(entry,),
        expected_head_revision_id=original.source_revision_id,
        replacement_requests=(successor,),
        as_of_date=successor.stage_date,
    )
    preview = build_owner_corporate_action_revision_preview(
        prepared_batch=batch, active_entries=(entry,)
    )
    calls = []

    def correction(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            source_reference=batch.gate_anchor,
            requests=batch.requests,
            tax_action=None,
            revision_preview=preview,
        )

    monkeypatch.setattr(workflow, "prepare_owner_official_corporate_action_revision", correction)
    monkeypatch.setattr(
        workflow,
        "prepare_owner_official_corporate_action",
        lambda **k: pytest.fail("explicit correction fell back"),
    )
    sealed = []
    monkeypatch.setattr(
        workflow,
        "seal_owner_corporate_action_intent",
        lambda value, **k: sealed.append(value) or "opaque",
    )
    result = workflow.prepare_owner_corporate_action_workflow(
        object(),
        account_id=account.account_id,
        event_id="known",
        action="cash_entitlement",
        correction_mode="correct_existing",
    )
    assert result["outcome"] == "success"
    assert calls[0]["canonical_account_id"] == account.source.account_id
    assert sealed[0].requests == batch.requests and len(sealed[0].requests) == 2
    assert "冲正原账项 11" in result["summary"] and "按新披露重建" in result["summary"]
    assert "未参与配股" not in result["summary"]
    assert "全部成功才生效" in result["summary"]


def test_correction_does_not_accept_an_unrelated_tax_settlement_date(context, monkeypatch):
    intent, account = _prepare_context(context, monkeypatch)
    monkeypatch.setattr(
        workflow,
        "prepare_owner_official_corporate_action_revision",
        lambda **k: pytest.fail("unsupported date reached builder"),
    )
    result = workflow.prepare_owner_corporate_action_workflow(
        object(),
        account_id=account.account_id,
        event_id="known",
        action="cash_entitlement",
        correction_mode="correct_existing",
        settlement_date=intent.source_reference.stage_date,
    )
    assert (
        result["blocking_reason"] == "CORPORATE_ACTION_OWNER_REVISION_SETTLEMENT_DATE_UNSUPPORTED"
    )


@pytest.fixture
def context(monkeypatch):
    intent = _intent()
    account = SimpleNamespace(
        account_id=intent.account_id,
        owner_user_id=intent.owner_user_id,
        source=SimpleNamespace(account_id=intent.selector.binding.account_id),
        preparation_valid_until=intent.valid_until,
        checked_at=intent.prepared_at,
        grant=SimpleNamespace(selector=intent.selector, valid_until=intent.valid_until),
        asset_codes=(intent.source_reference.asset_code,),
    )
    monkeypatch.setattr(workflow.timezone, "now", lambda: intent.prepared_at)
    monkeypatch.setattr(workflow, "get_simulated_execution_runtime_environment", lambda: "test")
    monkeypatch.setattr(workflow, "read_owner_corporate_action_account", lambda *a, **k: account)
    monkeypatch.setattr(workflow, "refresh_new_owner_posting_window", lambda *a, **k: None)
    monkeypatch.setattr(
        workflow,
        "read_owner_corporate_action_confirmation_owner",
        lambda *a, **k: intent.owner_user_id,
    )
    monkeypatch.setattr(
        workflow, "owner_corporate_action_session_binding", lambda request: "session"
    )
    monkeypatch.setattr(
        workflow,
        "read_owner_workflow_payload",
        lambda account: workflow.empty_owner_workflow_payload(account.account_id),
    )
    return intent, account


@pytest.mark.parametrize(
    "action", ["cash_payment", "tax_assess", "share_delivery", "rights_not_exercised"]
)
def test_prepare_checks_owned_current_capability_before_any_event_lookup(monkeypatch, action):
    calls = []

    def deny(*args, **kwargs):
        calls.append(kwargs)
        raise AuthorizationError()

    monkeypatch.setattr(workflow, "read_owner_corporate_action_account", deny)
    monkeypatch.setattr(
        workflow, "select_owner_workflow_event", lambda *a, **k: pytest.fail("foreign event lookup")
    )
    with pytest.raises(AuthorizationError):
        workflow.prepare_owner_corporate_action_workflow(
            object(), account_id=41, event_id="known", action=action
        )
    assert calls[0]["require_current_source"] is True
    assert calls[0]["capability"] is workflow.capability_for_owner_operation(action)


def test_prepare_seals_only_server_facts_after_current_window_and_final_clock(context, monkeypatch):
    intent, account = context
    reference = intent.source_reference
    selected = SimpleNamespace(asset_code=reference.asset_code)
    monkeypatch.setattr(workflow, "select_owner_workflow_event", lambda *a, **k: selected)
    monkeypatch.setattr(
        workflow,
        "prepare_owner_official_corporate_action",
        lambda **k: SimpleNamespace(
            source_reference=reference,
            requests=intent.requests,
            tax_action=None,
            revision_preview=None,
        ),
    )
    expiry = intent.prepared_at + timedelta(seconds=40)
    monkeypatch.setattr(
        workflow,
        "read_owner_preparation_window",
        lambda *a, **k: SimpleNamespace(expires_at=expiry, checked_at=intent.prepared_at),
    )
    captured = []
    monkeypatch.setattr(
        workflow,
        "seal_owner_corporate_action_intent",
        lambda value, **k: captured.append((value, k)) or "opaque",
    )
    result = workflow.prepare_owner_corporate_action_workflow(
        object(),
        account_id=account.account_id,
        event_id=reference.source_record_id,
        action="cash_entitlement",
    )
    assert result["outcome"] == "success"
    assert result["must_not_use_for_decision"] is True
    assert captured[0][0].requests == intent.requests
    assert captured[0][0].valid_until == intent.valid_until
    assert captured[0][1] == {"session_binding": "session"}
    assert "opaque" not in str({k: v for k, v in result.items() if k != "continuation"})


def test_prepare_blocks_when_clock_expires_during_original_source_reads(context, monkeypatch):
    intent, account = context
    monkeypatch.setattr(
        workflow,
        "select_owner_workflow_event",
        lambda *a, **k: SimpleNamespace(asset_code="001211.SZ"),
    )
    monkeypatch.setattr(
        workflow,
        "prepare_owner_official_corporate_action",
        lambda **k: SimpleNamespace(
            source_reference=intent.source_reference,
            requests=intent.requests,
            tax_action=None,
            revision_preview=None,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "read_owner_preparation_window",
        lambda *a, **k: SimpleNamespace(
            expires_at=intent.prepared_at, checked_at=intent.prepared_at
        ),
    )
    monkeypatch.setattr(
        workflow, "seal_owner_corporate_action_intent", lambda *a, **k: pytest.fail("expired token")
    )
    result = workflow.prepare_owner_corporate_action_workflow(
        object(), account_id=account.account_id, event_id="known", action="cash_entitlement"
    )
    assert result["outcome"] == "blocked"
    assert result["blocking_reason"] == "CORPORATE_ACTION_PREPARATION_EXPIRED"


def test_confirm_preserves_exact_original_intent_and_leaves_replay_to_financial_gate(
    context, monkeypatch
):
    intent, account = context
    calls = []

    def read(*args, **kwargs):
        calls.append(kwargs)
        return account

    monkeypatch.setattr(workflow, "read_owner_corporate_action_account", read)
    monkeypatch.setattr(
        workflow, "restore_owner_corporate_action_intent", lambda token, **kwargs: intent
    )
    observed = []
    monkeypatch.setattr(
        workflow,
        "execute_owner_corporate_action_intent",
        lambda value, **kwargs: observed.append(value)
        or (
            CorporateActionPostingReceipt(
                7,
                1,
                intent.source_reference.stage_key,
                intent.source_reference.payload_sha256,
                True,
            ),
        ),
    )
    result = workflow.confirm_owner_corporate_action_workflow(
        object(),
        account_id=account.account_id,
        continuation_token="sealed-original",
        confirmed=True,
    )
    assert observed == [intent]
    assert all(call.get("require_current_source", False) is False for call in calls)
    assert result["outcome"] == "success"
    assert "原始" in result["summary"]


def test_confirm_checks_owner_and_source_then_acknowledges_without_balance_reconstruction(
    context, monkeypatch
):
    intent, account = context
    calls = []

    def owner(*args, **kwargs):
        calls.append("physical-owner")
        return account.owner_user_id

    def restore(token, **kwargs):
        assert kwargs["owner_user_id"] == account.owner_user_id
        calls.append("restore")
        return intent

    def execute(value, **kwargs):
        assert value is intent
        calls.append("locked-execution")
        return ()

    def read(*args, **kwargs):
        pytest.fail("committed acknowledgement must not reconstruct current account balances")

    monkeypatch.setattr(workflow, "read_owner_corporate_action_confirmation_owner", owner)
    monkeypatch.setattr(workflow, "restore_owner_corporate_action_intent", restore)
    monkeypatch.setattr(
        workflow, "refresh_new_owner_posting_window", lambda *a, **k: calls.append("source-capture")
    )
    monkeypatch.setattr(workflow, "execute_owner_corporate_action_intent", execute)
    monkeypatch.setattr(workflow, "read_owner_corporate_action_account", read)
    result = workflow.confirm_owner_corporate_action_workflow(
        object(), account_id=account.account_id, continuation_token="sealed", confirmed=True
    )
    assert result["outcome"] == "success"
    assert calls == ["physical-owner", "restore", "source-capture", "locked-execution"]
    assert result["book_cash"] is None
    assert result["audit_receipts"] == []


def test_confirm_denied_physical_owner_never_opens_token_or_financial_path(context, monkeypatch):
    _, account = context

    def deny(*args, **kwargs):
        raise AuthorizationError()

    monkeypatch.setattr(workflow, "read_owner_corporate_action_confirmation_owner", deny)
    for name in ("restore_owner_corporate_action_intent", "execute_owner_corporate_action_intent"):
        monkeypatch.setattr(workflow, name, lambda *a, **k: pytest.fail("foreign confirmation"))
    with pytest.raises(AuthorizationError):
        workflow.confirm_owner_corporate_action_workflow(
            object(), account_id=account.account_id, continuation_token="sealed", confirmed=True
        )


def test_new_source_capture_failure_cannot_enter_the_financial_executor(context, monkeypatch):
    intent, account = context
    monkeypatch.setattr(workflow, "restore_owner_corporate_action_intent", lambda *a, **k: intent)

    def unavailable(*args, **kwargs):
        raise BusinessLogicError("new observation is incomplete", code="SOURCE_CAPTURE_INCOMPLETE")

    monkeypatch.setattr(workflow, "refresh_new_owner_posting_window", unavailable)
    monkeypatch.setattr(
        workflow,
        "execute_owner_corporate_action_intent",
        lambda *a, **k: pytest.fail("failed source capture cannot write money"),
    )
    result = workflow.confirm_owner_corporate_action_workflow(
        object(), account_id=account.account_id, continuation_token="sealed", confirmed=True
    )
    assert result["outcome"] == "blocked"
    assert result["blocking_reason"] == "SOURCE_CAPTURE_INCOMPLETE"
    assert result["book_cash"] is None


def test_missing_capture_audit_authority_returns_blocked_before_financial_execution(
    context, monkeypatch
):
    intent, account = context
    monkeypatch.setattr(workflow, "restore_owner_corporate_action_intent", lambda *a, **k: intent)

    def unavailable(*args, **kwargs):
        raise SystemAuditCompositionUnavailable(
            "internal diagnostic", reason_code="authority_unavailable"
        )

    monkeypatch.setattr(workflow, "refresh_new_owner_posting_window", unavailable)
    monkeypatch.setattr(
        workflow,
        "execute_owner_corporate_action_intent",
        lambda *a, **k: pytest.fail("unavailable capture authority cannot write money"),
    )
    result = workflow.confirm_owner_corporate_action_workflow(
        object(), account_id=account.account_id, continuation_token="sealed", confirmed=True
    )
    assert result["outcome"] == "blocked"
    assert result["blocking_reason"] == "CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE"
    assert "internal diagnostic" not in repr(result)


def test_missing_capture_audit_authority_preserves_committed_account_refresh_as_partial(
    context, monkeypatch
):
    intent, account = context
    monkeypatch.setattr(
        workflow,
        "refresh_owner_simulated_account_evidence",
        lambda *a, **k: SimpleNamespace(source_observed_at=intent.prepared_at),
    )
    monkeypatch.setattr(
        workflow,
        "build_current_reference_identity_reader",
        lambda **k: SimpleNamespace(
            resolve_current_reference_identity=lambda **k: SimpleNamespace(security_id="synthetic")
        ),
    )

    def unavailable(**kwargs):
        raise SystemAuditCompositionUnavailable(
            "internal diagnostic", reason_code="authority_unavailable"
        )

    monkeypatch.setattr(
        workflow,
        "build_official_szse_distribution_refresher",
        lambda **k: SimpleNamespace(refresh=unavailable),
    )
    result = workflow.refresh_owner_corporate_action_workflow(
        object(),
        account_id=account.account_id,
        confirmed=True,
    )
    assert result["outcome"] == "partial"
    assert result["blocking_reason"] == "CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE"
    assert result["source_observed_at"] == intent.prepared_at.isoformat()
    assert "internal diagnostic" not in repr(result)


def test_confirm_preserves_receipt_when_post_commit_owner_read_becomes_unavailable(
    context, monkeypatch
):
    intent, account = context
    monkeypatch.setattr(workflow, "restore_owner_corporate_action_intent", lambda *a, **k: intent)
    receipt = CorporateActionPostingReceipt(
        19, 3, intent.source_reference.stage_key, intent.source_reference.payload_sha256, False
    )
    monkeypatch.setattr(
        workflow, "execute_owner_corporate_action_intent", lambda *a, **k: (receipt,)
    )

    def unavailable(*args, **kwargs):
        raise AuthorizationError()

    monkeypatch.setattr(workflow, "read_owner_corporate_action_account", unavailable)
    result = workflow.confirm_owner_corporate_action_workflow(
        object(), account_id=account.account_id, continuation_token="sealed", confirmed=True
    )
    assert result["outcome"] == "success"
    assert "19" in result["summary"]
    assert result["blocking_reason"] == "CORPORATE_ACTION_COMMITTED_READBACK_PENDING"
    assert result["book_cash"] is None
    assert result["audit_receipts"] == []


@pytest.mark.parametrize("audit_failure", (None, *workflow.RETAINED_SYSTEM_AUDIT_READ_FAILURES))
def test_committed_payment_is_not_reported_failed_if_followup_readback_is_unavailable(
    context, monkeypatch, audit_failure
):
    intent, account = context
    monkeypatch.setattr(
        workflow, "restore_owner_corporate_action_intent", lambda token, **kwargs: intent
    )
    receipt = CorporateActionPostingReceipt(
        12, 3, intent.source_reference.stage_key, intent.source_reference.payload_sha256, False
    )
    monkeypatch.setattr(
        workflow, "execute_owner_corporate_action_intent", lambda *a, **k: (receipt,)
    )

    def unavailable(*args):
        if audit_failure is not None:
            raise audit_failure("original Audit readback unavailable")
        raise BusinessLogicError("readback unavailable", code="ORIGINAL_READ_UNAVAILABLE")

    monkeypatch.setattr(workflow, "read_owner_workflow_payload", unavailable)
    result = workflow.confirm_owner_corporate_action_workflow(
        object(), account_id=account.account_id, continuation_token="sealed", confirmed=True
    )
    assert result["outcome"] == "success"
    assert "12" in result["summary"]
    assert result["blocking_reason"] == "CORPORATE_ACTION_COMMITTED_READBACK_PENDING"
    assert result["audit_receipts"] == []
    assert result["net_asset_value"] is None


def test_event_discovery_is_independent_of_financial_readback(context, monkeypatch):
    _, account = context
    payload = workflow.empty_owner_workflow_payload(account.account_id)
    payload["outcome"] = "success"
    reads = []
    monkeypatch.setattr(
        workflow,
        "read_owner_workflow_payload",
        lambda *a: pytest.fail("event discovery read financial balances"),
    )

    def source(value):
        reads.append(value)
        return payload

    monkeypatch.setattr(workflow, "read_owner_workflow_source_payload", source)
    assert (
        workflow.read_owner_corporate_action_events(object(), account_id=account.account_id)
        is payload
    )
    assert reads == [account]
    assert payload["net_asset_value"] is None
    assert payload["must_not_use_for_decision"] is True


def test_event_discovery_does_not_swallow_foreign_owner_denial(context, monkeypatch):
    _, account = context

    def deny(*a, **k):
        raise AuthorizationError()

    monkeypatch.setattr(workflow, "read_owner_corporate_action_account", deny)
    monkeypatch.setattr(
        workflow,
        "read_owner_workflow_source_payload",
        lambda *a: pytest.fail("foreign account source read"),
    )
    with pytest.raises(AuthorizationError):
        workflow.read_owner_corporate_action_events(object(), account_id=account.account_id)


def test_refresh_acknowledgement_keeps_source_lease_for_the_actual_operation(context, monkeypatch):
    _, account = context
    monkeypatch.setattr(
        workflow,
        "read_owner_workflow_payload",
        lambda *args: pytest.fail("refresh must not rebuild financial balances"),
    )
    monkeypatch.setattr(
        workflow,
        "read_owner_workflow_source_payload",
        lambda value: workflow.empty_owner_workflow_payload(value.account_id),
        raising=False,
    )
    result = workflow._read_after_commit(
        account, summary="Official source capture completed.", include_balances=False
    )
    assert result["outcome"] == "success"
    assert result["book_cash"] is None
    assert result["net_asset_value"] is None


@pytest.mark.parametrize("confirmed", [False, 1, "true"])
def test_nonliteral_confirmation_never_reads_or_executes(context, monkeypatch, confirmed):
    monkeypatch.setattr(
        workflow, "read_owner_corporate_action_account", lambda *a, **k: pytest.fail("cancel reads")
    )
    monkeypatch.setattr(
        workflow,
        "execute_owner_corporate_action_intent",
        lambda *a, **k: pytest.fail("cancel writes"),
    )
    if confirmed is False:
        assert (
            workflow.confirm_owner_corporate_action_workflow(
                object(), account_id=41, continuation_token="anything", confirmed=confirmed
            )["outcome"]
            == "noop"
        )
    else:
        with pytest.raises(ValueError):
            workflow.confirm_owner_corporate_action_workflow(
                object(), account_id=41, continuation_token="anything", confirmed=confirmed
            )
