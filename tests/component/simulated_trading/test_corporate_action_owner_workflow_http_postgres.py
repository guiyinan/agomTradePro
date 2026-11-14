"""Ordinary-owner corporate-action workflow over real Session/CSRF and databases."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal
from time import sleep
from typing import cast

import pytest
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, connections, transaction
from django.test import override_settings
from django.utils import timezone
from pytest_django.plugin import DjangoDbBlocker
from rest_framework.test import APIClient

from apps.account.application.owner_tenant_authority_v3_contracts import (
    OwnerTenantAuthorityV3Unavailable,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.infrastructure.owner_tenant_authority_v3_read_context import (
    OwnerTenantAuthorityV3OperationReadContext,
)
from apps.account.infrastructure.owner_tenant_authority_v3_repository import (
    lock_owner_tenant_authority_v3_sources,
    lock_owner_tenant_authority_v3_sources_for_read,
)
from apps.audit.domain.system_audit_event import JSONValue
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEventReadScope,
    SecurityDisclosureExchange,
)
from apps.data_center.security_disclosure_capture_composition import (
    make_security_disclosure_event_reader,
)
from apps.simulated_trading import corporate_action_owner_workflow_composition as owner_workflow
from apps.simulated_trading.corporate_action_tax_assessment_window_composition import (
    assert_tax_assessment_window_header,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_window_codec import (
    decode_corporate_action_tax_window_proof,
)
from apps.simulated_trading.infrastructure.models import PositionModel, SimulatedAccountModel
from core.exceptions import AgomTradeProException
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash05_owner_workflow_native_sources import (
    cash_distribution_capture,
    install_synthetic_szse_capture_transport,
    owner_workflow_statutory_bodies,
    share_distribution_capture,
)
from tests.support.ash05_owner_workflow_native_world import (
    OwnerWorkflowNativeWorld,
    build_owner_workflow_native_world,
    recover_owner_workflow_operator_authority,
)
from tests.support.ash05_sql_budget import record_ash05_blocked_origin, record_ash05_sql_budget
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)

_API_ROOT = "/api/simulated-trading/accounts/{account_id}/corporate-actions/"
_CONSENT_ROOT = "/api/simulated-trading/accounts/{account_id}/corporate-action-consent/"
_WORKFLOW_URLCONF = "tests.support.ash05_owner_workflow_test_urls"


def test_native_outer_source_lock_scope_survives_nested_rollback_and_excludes_writers(
    django_db_blocker: DjangoDbBlocker,
) -> None:
    """A held-lock receipt neither releases outer PG locks nor survives its scope."""
    assert connection.vendor == "postgresql"
    competing = "ash05_source_lock_competing"
    assert competing not in connections.databases
    connections.databases[competing] = deepcopy(connections.databases["default"])
    assert connections.databases[competing]["NAME"] == connection.settings_dict["NAME"]
    context = OwnerTenantAuthorityV3OperationReadContext(
        using="default", connection_provider=lambda: connection.connection
    )
    policy_id = "ash05-native-held-source-locks"
    try:
        with django_db_blocker.unblock(), transaction.atomic():
            with context.source_locks(
                policy_id=policy_id,
                acquire=lambda: lock_owner_tenant_authority_v3_sources_for_read(
                    using="default", policy_id=policy_id
                ),
            ):
                assert context.has_source_locks("default", policy_id)
                with pytest.raises(RuntimeError):
                    with transaction.atomic():
                        raise RuntimeError("roll back only the nested savepoint")
                assert context.has_source_locks("default", policy_id)
                with transaction.atomic(using=competing):
                    with pytest.raises(OwnerTenantAuthorityV3Unavailable):
                        lock_owner_tenant_authority_v3_sources(using=competing, policy_id=policy_id)
            assert not context.has_source_locks("default", policy_id)
            with transaction.atomic(using=competing):
                with pytest.raises(OwnerTenantAuthorityV3Unavailable):
                    lock_owner_tenant_authority_v3_sources(using=competing, policy_id=policy_id)
        with django_db_blocker.unblock(), transaction.atomic(using=competing):
            lock_owner_tenant_authority_v3_sources(using=competing, policy_id=policy_id)
    finally:
        connections[competing].close()
        connections.databases.pop(competing)


@pytest.fixture(autouse=True)
def _isolated_workflow_channels(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate process-local task, cache, and memory-broker state for the journey."""
    original = owner_workflow._blocked_payload

    def retain_origin(account_id: int, error: AgomTradeProException) -> dict[str, JSONValue]:
        record_ash05_blocked_origin(error)
        return original(account_id, error)

    monkeypatch.setattr(owner_workflow, "_blocked_payload", retain_origin)
    with isolated_task_channels():
        yield


def _headers(world: OwnerWorkflowNativeWorld) -> dict[str, str | bool]:
    """Return the ordinary owner's exact real-session CSRF headers."""
    return {
        "secure": True,
        "HTTP_ORIGIN": "https://testserver",
        "HTTP_X_CSRFTOKEN": world.owner.csrf_token,
    }


def _post(
    client: APIClient,
    path: str,
    body: dict[str, object],
    headers: dict[str, str | bool],
    *,
    expected_status: int = 200,
) -> dict[str, object]:
    """Make one real JSON POST and require its declared status and media type."""
    with record_ash05_sql_budget(label=f"POST {path}"):
        response = client.post(path, body, format="json", **headers)
    assert response.status_code == expected_status, response.content
    assert response.headers.get("Content-Type", "").startswith("application/json")
    payload = response.json()
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _read(client: APIClient, path: str, headers: dict[str, str | bool]) -> dict[str, object]:
    """Read one real owner-scoped JSON resource."""
    with record_ash05_sql_budget(label=f"GET {path}"):
        response = client.get(path, **headers)
    assert response.status_code == 200, response.content
    assert response.headers.get("Content-Type", "").startswith("application/json")
    payload = response.json()
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _refresh(world: OwnerWorkflowNativeWorld) -> dict[str, object]:
    """Maintain the separate test operator, then refresh through the actual owner endpoint."""
    if CorporateActionPostingModel.objects.filter(account_id=world.account_id).exists():
        recover_owner_workflow_operator_authority(world)
    return _post(
        world.owner.client,
        _API_ROOT.format(account_id=world.account_id) + "refresh/",
        {"account_id": world.account_id, "confirmed": True},
        _headers(world),
    )


def _issue_v3_cash_tax_consent(world: OwnerWorkflowNativeWorld) -> dict[str, object]:
    """Explicitly select only cash-stage, tax-assessment, and tax-withholding powers."""
    path = _CONSENT_ROOT.format(account_id=world.account_id)
    selected = {
        "cash_dividend": True,
        "share_distribution": False,
        "rights_not_exercised": False,
        "tax_assessment": True,
        "tax_withholding": True,
    }
    prepared = _post(world.owner.client, path + "prepare/", selected, _headers(world))
    assert prepared["selected_capabilities"] == sorted(
        [
            Capability.CASH_STAGE_WRITE.value,
            Capability.TAX_ASSESS.value,
            Capability.TAX_WITHHOLD.value,
        ]
    )
    continuation = prepared.get("continuation")
    assert isinstance(continuation, dict)
    inputs = continuation.get("input")
    assert isinstance(inputs, dict)
    token = inputs.get("consent_token")
    assert isinstance(token, str) and token.startswith("v3.")
    confirmation = _post(
        world.owner.client,
        path,
        {"consent_token": token, "confirmed": True},
        _headers(world),
    )
    assert confirmation["selected_capabilities"] == prepared["selected_capabilities"]
    return confirmation


def _issue_v3_share_consent(world: OwnerWorkflowNativeWorld) -> dict[str, object]:
    """Select only the separate share-stage grant on the real owner CSRF route."""
    path = _CONSENT_ROOT.format(account_id=world.account_id)
    selected = {
        "cash_dividend": False,
        "share_distribution": True,
        "rights_not_exercised": False,
        "tax_assessment": False,
        "tax_withholding": False,
    }
    prepared = _post(world.owner.client, path + "prepare/", selected, _headers(world))
    assert prepared["selected_capabilities"] == [Capability.SHARE_STAGE_WRITE.value]
    continuation = prepared.get("continuation")
    assert isinstance(continuation, dict)
    inputs = continuation.get("input")
    assert isinstance(inputs, dict)
    token = inputs.get("consent_token")
    assert isinstance(token, str) and token.startswith("v3.")
    confirmation = _post(
        world.owner.client,
        path,
        {"consent_token": token, "confirmed": True},
        _headers(world),
    )
    assert confirmation["selected_capabilities"] == prepared["selected_capabilities"]
    return confirmation


def _prepare_and_confirm(
    world: OwnerWorkflowNativeWorld,
    *,
    event_id: str,
    action: str,
    settlement_date: date | None = None,
    exact_retry: bool = True,
    correction_mode: str | None = None,
    expected_revision_counts: tuple[int, int] | None = None,
    assert_prepare_is_read_only: bool = False,
) -> dict[str, object]:
    """Prepare and explicitly confirm one server-built source and financial operation."""
    path = _API_ROOT.format(account_id=world.account_id)
    body: dict[str, object] = {"event_id": event_id, "action": action}
    if settlement_date is not None:
        body["settlement_date"] = settlement_date.isoformat()
    if correction_mode is not None:
        body["correction_mode"] = correction_mode
    state_before_prepare = (
        _owner_effect_snapshot(world.account_id) if assert_prepare_is_read_only else None
    )
    prepared = _post(world.owner.client, path + "prepare/", body, _headers(world))
    assert (
        prepared.get("outcome") == "success"
    ), f"workflow preparation did not succeed: {prepared.get('blocking_reason')}"
    if expected_revision_counts is not None:
        summary = prepared.get("summary")
        assert isinstance(summary, str) and summary.startswith("仅模拟整批更正：")
        assert summary.count("冲正原账项") == expected_revision_counts[0]
        assert summary.count("按新披露重建（") == expected_revision_counts[1]
    if state_before_prepare is not None:
        assert _owner_effect_snapshot(world.account_id) == state_before_prepare
    continuation = prepared.get("continuation")
    assert isinstance(continuation, dict)
    inputs = continuation.get("input")
    assert isinstance(inputs, dict)
    token = inputs.get("continuation_token")
    assert isinstance(token, str) and token
    confirm_body = {
        "account_id": str(world.account_id),
        "continuation_token": token,
        "confirmed": True,
    }
    effects_before = _business_effect_counts(world.account_id)
    cash_before = SimulatedAccountModel.objects.values_list("current_cash", "updated_at").get(
        pk=world.account_id
    )
    shares_before = tuple(
        PositionModel.objects.filter(account_id=world.account_id)
        .order_by("asset_code")
        .values_list("asset_code", "quantity", "available_quantity")
    )
    committed = _post(world.owner.client, path + "confirm/", confirm_body, _headers(world))
    if committed["outcome"] != "success":
        assert _business_effect_counts(world.account_id) == effects_before
        assert (
            SimulatedAccountModel.objects.values_list("current_cash", "updated_at").get(
                pk=world.account_id
            )
            == cash_before
        )
        assert (
            tuple(
                PositionModel.objects.filter(account_id=world.account_id)
                .order_by("asset_code")
                .values_list("asset_code", "quantity", "available_quantity")
            )
            == shares_before
        )
    assert committed["outcome"] == "success", committed
    if exact_retry:
        if action == "tax_assess":
            _wait_for_retained_assessment_window_expiry(world)
        retained_effects = _business_effect_counts(world.account_id)
        retained_originals = _business_original_fingerprints(world.account_id)
        retained_cash = SimulatedAccountModel.objects.values_list("current_cash", "updated_at").get(
            pk=world.account_id
        )
        retained_shares = tuple(
            PositionModel.objects.filter(account_id=world.account_id)
            .order_by("asset_code")
            .values_list("asset_code", "quantity", "available_quantity")
        )
        replay = _post(world.owner.client, path + "confirm/", confirm_body, _headers(world))
        assert _business_effect_counts(world.account_id) == retained_effects
        assert _business_original_fingerprints(world.account_id) == retained_originals
        assert (
            SimulatedAccountModel.objects.values_list("current_cash", "updated_at").get(
                pk=world.account_id
            )
            == retained_cash
        )
        assert (
            tuple(
                PositionModel.objects.filter(account_id=world.account_id)
                .order_by("asset_code")
                .values_list("asset_code", "quantity", "available_quantity")
            )
            == retained_shares
        )
        assert replay["outcome"] == "success", replay
    return committed


def _owner_effect_snapshot(
    account_id: int,
) -> tuple[
    tuple[int, int, int, int, int],
    tuple[str, ...],
    tuple[Decimal, datetime],
    tuple[tuple[str, Decimal, Decimal], ...],
]:
    """Fingerprint every owner-financial row before a read-only correction preview."""
    current_cash, updated_at = SimulatedAccountModel.objects.values_list(
        "current_cash", "updated_at"
    ).get(pk=account_id)
    positions = tuple(
        PositionModel.objects.filter(account_id=account_id)
        .order_by("asset_code")
        .values_list("asset_code", "quantity", "available_quantity")
    )
    return (
        _business_effect_counts(account_id),
        _business_original_fingerprints(account_id),
        (current_cash, updated_at),
        positions,
    )


def _wait_for_retained_assessment_window_expiry(world: OwnerWorkflowNativeWorld) -> None:
    """Wait on the actual original deadline, without altering any source or server clock."""
    header = CorporateActionTaxAssessmentHeaderModel.objects.get(account_id=world.account_id)
    event = SystemAuditEventModel.objects.get(
        event_type="simulated.corporate_action.tax_assessed",
        resource_type="simulated_tax_assessment",
        resource_id=str(header.pk),
    )
    proof = decode_corporate_action_tax_window_proof(event.detail.get("current_official_window"))
    assert_tax_assessment_window_header(proof, header)
    deadline = proof.evidence.expires_at
    assert deadline is not None
    remaining = (deadline - timezone.now()).total_seconds()
    assert remaining <= 60, "the synthetic source fixture must keep its original bounded TTL"
    if remaining > 0:
        sleep(min(remaining + 0.05, 60))
    assert timezone.now() >= deadline


def _business_original_fingerprints(account_id: int) -> tuple[str, ...]:
    """Compare original financial rows without exposing their bodies in assertion output."""
    financial_events = SystemAuditEventModel.objects.filter(
        event_type__startswith="simulated.corporate_action."
    )
    queries = (
        CorporateActionPostingModel.objects.filter(account_id=account_id),
        CorporateActionTaxAssessmentHeaderModel.objects.filter(account_id=account_id),
        CorporateActionTaxLiabilityOperationModel.objects.filter(account_id=account_id),
        financial_events,
        SystemAuditOutboxModel.objects.filter(
            event_id__in=financial_events.values_list("event_id", flat=True)
        ),
    )
    return tuple(
        hashlib.sha256(
            json.dumps(
                list(query.order_by("pk").values()),
                sort_keys=True,
                separators=(",", ":"),
                cls=DjangoJSONEncoder,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        for query in queries
    )


def _business_effect_counts(account_id: int) -> tuple[int, int, int, int, int]:
    """Count financial effects separately from independently captured disclosure evidence."""
    financial_events = SystemAuditEventModel.objects.filter(
        event_type__startswith="simulated.corporate_action."
    )
    return (
        CorporateActionPostingModel.objects.filter(account_id=account_id).count(),
        CorporateActionTaxAssessmentHeaderModel.objects.filter(account_id=account_id).count(),
        CorporateActionTaxLiabilityOperationModel.objects.filter(account_id=account_id).count(),
        financial_events.count(),
        SystemAuditOutboxModel.objects.filter(
            event_id__in=financial_events.values_list("event_id", flat=True)
        ).count(),
    )


def _event_id(world: OwnerWorkflowNativeWorld, *, payload: dict[str, object] | None = None) -> str:
    """Select the unique current listing event for this explicit synthetic notice."""
    if payload is None:
        payload = _read(
            world.owner.client,
            _API_ROOT.format(account_id=world.account_id),
            _headers(world),
        )
    events = payload.get("events")
    assert isinstance(events, list) and len(events) == 1, payload
    event = events[0]
    assert isinstance(event, dict)
    assert event.get("asset_code") == world.asset_code
    assert isinstance(event.get("title"), str) and event["title"]
    identifier = event.get("event_id")
    assert isinstance(identifier, str) and identifier
    return identifier


def _assert_direct_retained_source_successor(
    *, world: OwnerWorkflowNativeWorld, previous_event_id: str, current_event_id: str
) -> None:
    """Verify the real Data Center append contains the exact direct correction parent."""
    records = make_security_disclosure_event_reader(using="default").execute(
        SecurityDisclosureEventReadScope(
            as_of=timezone.now(),
            exchange=SecurityDisclosureExchange.SZSE,
            asset_code=world.asset_code,
        )
    )
    previous = tuple(row.event for row in records if row.event.source_event_id == previous_event_id)
    current = tuple(row.event for row in records if row.event.source_event_id == current_event_id)
    assert len(previous) == len(current) == 1
    assert current[0].supersedes_source_event_id == previous[0].source_event_id
    assert current[0].supersedes_source_revision_id == previous[0].source_revision_id
    assert current[0].source_revision_id != previous[0].source_revision_id


def _future_weekday(value: date) -> date:
    """Choose a finite future weekday inside the persisted synthetic calendar."""
    result = value + timedelta(days=3)
    while result.weekday() >= 5:
        result += timedelta(days=1)
    return result


def test_nonstaff_owner_completes_audited_cash_payment_and_tax_with_exact_retries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Run synthetic source facts through real capture, consent, posting, and tax readback."""
    if connection.vendor != "postgresql":
        pytest.skip("this migrated ordinary-owner journey runs only on assigned PostgreSQL")
    with override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF):
        world = build_owner_workflow_native_world(monkeypatch=monkeypatch, tmp_path=tmp_path)
        before = _business_effect_counts(world.account_id)

        # The ordinary owner must use Session/CSRF, and the serializer rejects
        # client facts that could impersonate ownership or source-derived money.
        base = _API_ROOT.format(account_id=world.account_id)
        missing_csrf = world.owner.client.post(
            base + "prepare/",
            {"event_id": "forged", "action": "cash_entitlement"},
            format="json",
            secure=True,
        )
        assert missing_csrf.status_code == 403
        event = _post(
            world.owner.client,
            base + "prepare/",
            {
                "event_id": "forged",
                "action": "cash_entitlement",
                "cash_amount": "999999.99",
            },
            _headers(world),
            expected_status=400,
        )
        assert "continuation" not in event
        assert _business_effect_counts(world.account_id) == before

        refreshed = _refresh(world)
        assert refreshed["outcome"] == "success", refreshed
        assert world.capture.listing_reads >= 1 and world.capture.pdf_reads >= 1
        consent = _issue_v3_cash_tax_consent(world)
        assert consent["grant_schema"].endswith(".v3")
        initial_event_id = _event_id(world, payload=refreshed)

        # The original synthetic history holds 100 shares at the record date,
        # then sells 30 shares. Payment uses the full dividend, not the later
        # 70-share position or the one disposition used for tax calculation.
        account = SimulatedAccountModel.objects.get(pk=world.account_id)
        starting_cash = account.current_cash
        first_posting = _prepare_and_confirm(
            world, event_id=initial_event_id, action="cash_entitlement"
        )
        entitlement = CorporateActionPostingModel.objects.get(
            account_id=world.account_id,
            source_event_id=initial_event_id,
            stage="cash_entitlement",
            entry_kind="posting",
        )
        assert entitlement.eligible_quantity == Decimal("100.000000")
        assert entitlement.cash_amount == Decimal("20.00")
        assert _business_effect_counts(world.account_id)[0] == before[0] + 1
        _refresh(world)
        _issue_v3_cash_tax_consent(world)

        payment = _prepare_and_confirm(world, event_id=initial_event_id, action="cash_payment")
        payment_row = CorporateActionPostingModel.objects.get(
            account_id=world.account_id,
            source_event_id=initial_event_id,
            stage="cash_payment",
            entry_kind="posting",
        )
        assert payment_row.cash_delta == entitlement.cash_amount
        assert payment_row.cash_receivable_delta == -entitlement.cash_amount
        account.refresh_from_db()
        after_payment_cash = account.current_cash
        assert after_payment_cash == starting_cash + entitlement.cash_amount
        assert first_posting["outcome"] == payment["outcome"] == "success"
        assert _business_effect_counts(world.account_id)[0] == before[0] + 2
        _refresh(world)

        renewed_consent = _issue_v3_cash_tax_consent(world)
        assert renewed_consent["grant_id"] == consent["grant_id"]
        assert renewed_consent["grant_version"] != consent["grant_version"]
        for index, action in enumerate(("tax_assess", "tax_recognize", "tax_collect")):
            if index:
                _refresh(world)
                _issue_v3_cash_tax_consent(world)
            result = _prepare_and_confirm(
                world,
                event_id=initial_event_id,
                action=action,
                settlement_date=world.settlement_date,
            )
            assert result["outcome"] == "success", result

        account.refresh_from_db()
        assert account.current_cash < after_payment_cash
        rows = list(
            CorporateActionPostingModel.objects.filter(
                account_id=world.account_id,
                source_event_id=initial_event_id,
            ).order_by("account_revision")
        )
        assert [row.stage for row in rows] == ["cash_entitlement", "cash_payment"]
        assert sum((row.cash_delta for row in rows), Decimal("0")) == entitlement.cash_amount
        assert (
            CorporateActionTaxAssessmentHeaderModel.objects.filter(
                account_id=world.account_id,
                source_event_id=initial_event_id,
                settlement_date=world.settlement_date,
            ).count()
            == 1
        )
        liability_rows = list(
            CorporateActionTaxLiabilityOperationModel.objects.filter(account_id=world.account_id)
        )
        assert [row.sequence for row in liability_rows] == [1, 2]
        assert liability_rows[-1].collected_delta_text != "0"

        final_read = _read(
            world.owner.client,
            base,
            _headers(world),
        )
        receipts = final_read.get("audit_receipts")
        assert isinstance(receipts, list)
        assert {str(row.get("stage_label")) for row in receipts if isinstance(row, dict)} >= {
            "登记模拟现金权益",
            "模拟分红到账",
            "模拟税务评估",
            "模拟税务财务回执",
        }
        assert b"%ASH05 synthetic fixture" in world.capture.pdf_body
        assert "%ASH05 synthetic fixture" not in repr(final_read)


def test_unreached_payment_date_and_missing_paid_basis_never_debit_the_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """A future synthetic payout cannot create payment or collection entries."""
    if connection.vendor != "postgresql":
        pytest.skip("this migrated ordinary-owner journey runs only on assigned PostgreSQL")
    with override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF):
        world = build_owner_workflow_native_world(
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            payment_date_override=_future_weekday(timezone.localdate()),
        )
        assert world.capture.published_on <= world.decision_date
        refreshed = _refresh(world)
        assert refreshed["outcome"] == "success", refreshed
        _issue_v3_cash_tax_consent(world)
        event_id = _event_id(world, payload=refreshed)
        before = _business_effect_counts(world.account_id)
        entitlement = _prepare_and_confirm(world, event_id=event_id, action="cash_entitlement")
        assert entitlement["outcome"] == "success"
        _refresh(world)
        _issue_v3_cash_tax_consent(world)
        baseline = _business_effect_counts(world.account_id)

        prepared = _post(
            world.owner.client,
            _API_ROOT.format(account_id=world.account_id) + "prepare/",
            {"event_id": event_id, "action": "cash_payment"},
            _headers(world),
        )
        if prepared.get("outcome") == "success":
            continuation = prepared.get("continuation")
            assert isinstance(continuation, dict)
            inputs = continuation.get("input")
            assert isinstance(inputs, dict)
            token = inputs.get("continuation_token")
            assert isinstance(token, str)
            result = _post(
                world.owner.client,
                _API_ROOT.format(account_id=world.account_id) + "confirm/",
                {
                    "account_id": str(world.account_id),
                    "continuation_token": token,
                    "confirmed": True,
                },
                _headers(world),
            )
            assert result["outcome"] == "blocked", result
            assert result["blocking_reason"] == "CORPORATE_ACTION_PAYMENT_DATE_NOT_REACHED"
        else:
            assert prepared["outcome"] == "blocked", prepared
            assert prepared["blocking_reason"] == "CORPORATE_ACTION_OWNER_PAYMENT_DATE_NOT_REACHED"
        assert _business_effect_counts(world.account_id) == baseline

        _refresh(world)
        _issue_v3_cash_tax_consent(world)
        assessment = _prepare_and_confirm(
            world,
            event_id=event_id,
            action="tax_assess",
            settlement_date=world.settlement_date,
        )
        assert assessment["outcome"] == "success", assessment
        _refresh(world)
        _issue_v3_cash_tax_consent(world)
        _prepare_and_confirm(
            world,
            event_id=event_id,
            action="tax_recognize",
            settlement_date=world.settlement_date,
        )
        _refresh(world)
        _issue_v3_cash_tax_consent(world)
        baseline = _business_effect_counts(world.account_id)

        collect = _post(
            world.owner.client,
            _API_ROOT.format(account_id=world.account_id) + "prepare/",
            {
                "event_id": event_id,
                "action": "tax_collect",
                "settlement_date": world.settlement_date.isoformat(),
            },
            _headers(world),
        )
        assert collect["outcome"] == "blocked", collect
        assert collect["blocking_reason"] == "CORPORATE_ACTION_OWNER_PAYMENT_BASIS_REQUIRED"
        assert _business_effect_counts(world.account_id) == baseline
        assert baseline[0] == before[0] + 1


def test_nonstaff_owner_records_rights_no_effect_after_confirmed_source_dates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """A successful synthetic rights source permits only an audited no-exercise row."""
    if connection.vendor != "postgresql":
        pytest.skip("this migrated ordinary-owner journey runs only on assigned PostgreSQL")
    with override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF):
        world = build_owner_workflow_native_world(
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            capture_kind="rights",
        )
        refreshed = _refresh(world)
        assert refreshed["outcome"] == "success", refreshed
        path = _CONSENT_ROOT.format(account_id=world.account_id)
        selection = {
            "cash_dividend": False,
            "share_distribution": False,
            "rights_not_exercised": True,
            "tax_assessment": False,
            "tax_withholding": False,
        }
        prepared = _post(world.owner.client, path + "prepare/", selection, _headers(world))
        assert prepared["selected_capabilities"] == [Capability.RIGHTS_NOT_EXERCISED.value]
        continuation = prepared.get("continuation")
        assert isinstance(continuation, dict)
        inputs = continuation.get("input")
        assert isinstance(inputs, dict)
        consent_token = inputs.get("consent_token")
        assert isinstance(consent_token, str) and consent_token.startswith("v3.")
        _post(
            world.owner.client,
            path,
            {"consent_token": consent_token, "confirmed": True},
            _headers(world),
        )

        event_id = _event_id(world, payload=refreshed)
        account = SimulatedAccountModel.objects.get(pk=world.account_id)
        original_cash = account.current_cash
        posting_count = CorporateActionPostingModel.objects.filter(
            account_id=world.account_id
        ).count()
        _, _, _, event_count, outbox_count = _business_effect_counts(world.account_id)
        result = _prepare_and_confirm(
            world,
            event_id=event_id,
            action="rights_not_exercised",
        )
        row = CorporateActionPostingModel.objects.get(
            account_id=world.account_id,
            source_event_id=event_id,
            stage="rights_not_exercised",
        )
        assert row.action_kind == "rights_issue"
        assert row.entry_kind == "no_effect"
        assert row.rights_election == "not_exercised"
        assert row.rights_terms_sha256
        assert row.cash_delta == row.share_delta == Decimal("0")
        assert row.cash_receivable_delta == row.share_receivable_delta == Decimal("0")
        assert result["outcome"] == "success"
        assert (
            CorporateActionPostingModel.objects.filter(account_id=world.account_id).count()
            == posting_count + 1
        )
        assert _business_effect_counts(world.account_id)[3:] == (event_count + 1, outbox_count + 1)
        account.refresh_from_db()
        assert account.current_cash == original_cash

        receipts = _read(
            world.owner.client,
            _API_ROOT.format(account_id=world.account_id),
            _headers(world),
        )["audit_receipts"]
        assert isinstance(receipts, list)
        assert any(
            isinstance(receipt, dict)
            and receipt.get("receipt_id")
            and receipt.get("stage_label") == "模拟未参与配股"
            for receipt in receipts
        )
        assert b"%ASH05 synthetic fixture" in world.capture.pdf_body


def test_nonstaff_owner_completes_audited_share_entitlement_delivery_and_sellable_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Post all share stages from exact synthetic retained facts and one V3 power."""
    if connection.vendor != "postgresql":
        pytest.skip("this migrated ordinary-owner journey runs only on assigned PostgreSQL")
    with override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF):
        world = build_owner_workflow_native_world(
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            capture_kind="share",
        )
        assert world.record_date < world.sale_date
        assert world.settlement_date == world.share_delivery_date
        assert world.share_delivery_date <= world.share_sellable_date <= world.decision_date
        assert world.share_tax_bundle_id and len(world.share_tax_bundle_sha256) == 64
        refreshed = _refresh(world)
        assert refreshed["outcome"] == "success", refreshed
        assert world.capture.listing_reads >= 1 and world.capture.pdf_reads >= 1
        consent = _issue_v3_share_consent(world)
        assert consent["grant_schema"].endswith(".v3")
        event_id = _event_id(world, payload=refreshed)
        account = SimulatedAccountModel.objects.get(pk=world.account_id)
        position = PositionModel.objects.get(
            account_id=world.account_id, asset_code=world.asset_code
        )
        starting_cash = account.current_cash
        starting_quantity = position.quantity
        starting_available = position.available_quantity
        assert starting_quantity == Decimal("70.000000")
        assert starting_available == Decimal("70.000000")

        expected_rows = {
            "share_entitlement": {
                "share_delta": Decimal("0.000000"),
                "share_receivable_delta": Decimal("10.000000"),
                "available_share_delta": Decimal("0.000000"),
            },
            "share_delivery": {
                "share_delta": Decimal("10.000000"),
                "share_receivable_delta": Decimal("-10.000000"),
                "available_share_delta": Decimal("0.000000"),
            },
            "share_sellable_release": {
                "share_delta": Decimal("0.000000"),
                "share_receivable_delta": Decimal("0.000000"),
                "available_share_delta": Decimal("10.000000"),
            },
        }
        for action in expected_rows:
            if action != "share_entitlement":
                _issue_v3_share_consent(world)
            before = _business_effect_counts(world.account_id)
            result = _prepare_and_confirm(world, event_id=event_id, action=action)
            assert result["outcome"] == "success", result
            after = _business_effect_counts(world.account_id)
            assert tuple(new - old for old, new in zip(before, after, strict=True)) == (
                1,
                0,
                0,
                1,
                1,
            )
            _refresh(world)

        rows = list(
            CorporateActionPostingModel.objects.filter(
                account_id=world.account_id,
                source_event_id=event_id,
            ).order_by("account_revision")
        )
        assert [row.stage for row in rows] == list(expected_rows)
        assert [row.entry_kind for row in rows] == ["posting", "posting", "posting"]
        assert rows[0].eligible_quantity == Decimal("100.000000")
        assert rows[0].share_amount == Decimal("10.000000")
        assert rows[0].odd_lot_policy == "whole_shares"
        assert all(row.tax_treatment == "not_applicable" for row in rows)
        for row in rows:
            for field, value in expected_rows[row.stage].items():
                assert getattr(row, field) == value
            assert row.cash_delta == row.cash_receivable_delta == Decimal("0.00")
        account.refresh_from_db()
        position.refresh_from_db()
        assert account.current_cash == starting_cash
        assert position.quantity == starting_quantity + Decimal("10.000000")
        assert position.available_quantity == starting_available + Decimal("10.000000")
        assert (
            CorporateActionTaxAssessmentHeaderModel.objects.filter(
                account_id=world.account_id, source_event_id=event_id
            ).count()
            == 0
        )
        assert (
            CorporateActionTaxLiabilityOperationModel.objects.filter(
                account_id=world.account_id
            ).count()
            == 0
        )
        final_read = _read(
            world.owner.client,
            _API_ROOT.format(account_id=world.account_id),
            _headers(world),
        )
        receipts = final_read.get("audit_receipts")
        assert isinstance(receipts, list)
        assert {str(row.get("stage_label")) for row in receipts if isinstance(row, dict)} >= {
            "登记送转权益",
            "送转记入模拟持仓",
            "释放模拟可用股份",
        }
        assert b"%ASH05 synthetic fixture" in world.capture.pdf_body


def test_nonstaff_owner_corrects_paid_cash_as_one_audited_batch_before_tax(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Block ordinary stale-source cash, then post one complete synthetic correction."""
    if connection.vendor != "postgresql":
        pytest.skip("ordinary owner correction runs only on assigned PostgreSQL")
    with override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF):
        world = build_owner_workflow_native_world(monkeypatch=monkeypatch, tmp_path=tmp_path)
        initial = _refresh(world)
        assert initial.get("outcome") == "success"
        original_event_id = _event_id(world, payload=initial)
        consent = _issue_v3_cash_tax_consent(world)
        assert consent.get("grant_schema", "").endswith(".v3")

        account = SimulatedAccountModel.objects.get(pk=world.account_id)
        initial_cash = account.current_cash
        _prepare_and_confirm(world, event_id=original_event_id, action="cash_entitlement")
        _refresh(world)
        _issue_v3_cash_tax_consent(world)
        _prepare_and_confirm(world, event_id=original_event_id, action="cash_payment")
        account.refresh_from_db()
        paid_cash = account.current_cash
        assert paid_cash == initial_cash + Decimal("20.00")
        assert not CorporateActionTaxAssessmentHeaderModel.objects.filter(
            account_id=world.account_id
        ).exists()
        original_rows = tuple(
            CorporateActionPostingModel.objects.filter(
                account_id=world.account_id, source_event_id=original_event_id
            )
            .order_by("pk")
            .values()
        )
        original_ids = tuple(
            CorporateActionPostingModel.objects.filter(
                account_id=world.account_id, source_event_id=original_event_id
            )
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        assert len(original_rows) == 2

        successor = cash_distribution_capture(
            asset_code=world.asset_code,
            published_on=world.decision_date,
            record_date=world.record_date,
            ex_date=world.settlement_date,
            payment_date=world.decision_date,
            cash_per_ten="3.00",
            title_suffix="（更正后）",
        )
        successor.announcement_id = world.capture.announcement_id + 1
        assert b"%ASH05 synthetic fixture" in successor.pdf_body
        install_synthetic_szse_capture_transport(
            monkeypatch,
            world.capture,
            statutory_documents=owner_workflow_statutory_bodies(),
            additional_captures=(successor,),
        )
        current = _refresh(world)
        assert current.get("outcome") == "success"
        current_event_id = _event_id(world, payload=current)
        assert current_event_id != original_event_id
        _assert_direct_retained_source_successor(
            world=world,
            previous_event_id=original_event_id,
            current_event_id=current_event_id,
        )
        assert successor.pdf_reads >= 1 and world.capture.pdf_reads >= 2
        _issue_v3_cash_tax_consent(world)

        before_block = _owner_effect_snapshot(world.account_id)
        blocked = _post(
            world.owner.client,
            _API_ROOT.format(account_id=world.account_id) + "prepare/",
            {"event_id": current_event_id, "action": "cash_payment"},
            _headers(world),
        )
        assert blocked.get("outcome") == "blocked"
        assert blocked.get("blocking_reason") == "CORPORATE_ACTION_OWNER_CORRECTION_REQUIRED"
        assert _owner_effect_snapshot(world.account_id) == before_block

        before_correction = _business_effect_counts(world.account_id)
        committed = _prepare_and_confirm(
            world,
            event_id=current_event_id,
            action="cash_payment",
            correction_mode="correct_existing",
            expected_revision_counts=(2, 2),
            assert_prepare_is_read_only=True,
        )
        assert committed.get("outcome") == "success"
        after_correction = _business_effect_counts(world.account_id)
        assert tuple(
            new - old for old, new in zip(before_correction, after_correction, strict=True)
        ) == (4, 0, 0, 4, 4)

        retained_originals = tuple(
            CorporateActionPostingModel.objects.filter(pk__in=original_ids).order_by("pk").values()
        )
        assert retained_originals == original_rows
        rows = list(
            CorporateActionPostingModel.objects.filter(
                account_id=world.account_id, source_event_id=original_event_id
            ).order_by("account_revision")
        )
        assert [row.stage for row in rows] == [
            "cash_entitlement",
            "cash_payment",
            "cash_payment",
            "cash_entitlement",
            "cash_entitlement",
            "cash_payment",
        ]
        assert [row.entry_kind for row in rows] == [
            "posting",
            "posting",
            "reversal",
            "reversal",
            "successor",
            "successor",
        ]
        assert [(row.cash_delta, row.cash_receivable_delta) for row in rows] == [
            (Decimal("0.00"), Decimal("20.00")),
            (Decimal("20.00"), Decimal("-20.00")),
            (Decimal("-20.00"), Decimal("20.00")),
            (Decimal("0.00"), Decimal("-20.00")),
            (Decimal("0.00"), Decimal("30.00")),
            (Decimal("30.00"), Decimal("-30.00")),
        ]
        assert rows[-2].cash_amount == rows[-1].cash_amount == Decimal("30.00")
        correction_rows = rows[2:]
        assert sum((row.cash_delta for row in correction_rows), Decimal("0.00")) == Decimal("10.00")
        assert sum(
            (row.cash_receivable_delta for row in correction_rows), Decimal("0.00")
        ) == Decimal("0.00")
        account.refresh_from_db()
        assert account.current_cash == paid_cash + Decimal("10.00")
        assert not CorporateActionTaxAssessmentHeaderModel.objects.filter(
            account_id=world.account_id
        ).exists()
        assert not CorporateActionTaxLiabilityOperationModel.objects.filter(
            account_id=world.account_id
        ).exists()
        final = _read(
            world.owner.client,
            _API_ROOT.format(account_id=world.account_id),
            _headers(world),
        )
        receipts = final.get("audit_receipts")
        assert isinstance(receipts, list) and len(receipts) >= 6


def test_nonstaff_owner_corrects_share_entitlement_then_delivers_current_head(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Correct a synthetic share entitlement, then use ordinary audited next stages."""
    if connection.vendor != "postgresql":
        pytest.skip("ordinary owner correction runs only on assigned PostgreSQL")
    with override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF):
        world = build_owner_workflow_native_world(
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            capture_kind="share",
        )
        initial = _refresh(world)
        assert initial.get("outcome") == "success"
        original_event_id = _event_id(world, payload=initial)
        consent = _issue_v3_share_consent(world)
        assert consent.get("selected_capabilities") == [Capability.SHARE_STAGE_WRITE.value]

        account = SimulatedAccountModel.objects.get(pk=world.account_id)
        position = PositionModel.objects.get(
            account_id=world.account_id, asset_code=world.asset_code
        )
        initial_cash = account.current_cash
        initial_quantity = position.quantity
        initial_available = position.available_quantity
        assert initial_quantity == initial_available == Decimal("70.000000")
        _prepare_and_confirm(world, event_id=original_event_id, action="share_entitlement")
        original_rows = tuple(
            CorporateActionPostingModel.objects.filter(
                account_id=world.account_id, source_event_id=original_event_id
            )
            .order_by("pk")
            .values()
        )
        original_ids = tuple(
            CorporateActionPostingModel.objects.filter(
                account_id=world.account_id, source_event_id=original_event_id
            )
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        assert len(original_rows) == 1

        successor = share_distribution_capture(
            asset_code=world.asset_code,
            published_on=world.decision_date,
            record_date=world.record_date,
            ex_date=world.settlement_date,
            delivery_date=world.share_delivery_date,
            sellable_date=world.share_sellable_date,
            shares_per_ten="2.00",
            title_suffix="（更正后）",
        )
        successor.announcement_id = world.capture.announcement_id + 1
        assert b"%ASH05 synthetic fixture" in successor.pdf_body
        install_synthetic_szse_capture_transport(
            monkeypatch,
            world.capture,
            statutory_documents=owner_workflow_statutory_bodies(),
            additional_captures=(successor,),
        )
        current = _refresh(world)
        assert current.get("outcome") == "success"
        current_event_id = _event_id(world, payload=current)
        assert current_event_id != original_event_id
        _assert_direct_retained_source_successor(
            world=world,
            previous_event_id=original_event_id,
            current_event_id=current_event_id,
        )
        assert successor.pdf_reads >= 1 and world.capture.pdf_reads >= 2
        _issue_v3_share_consent(world)

        before_correction = _business_effect_counts(world.account_id)
        committed = _prepare_and_confirm(
            world,
            event_id=current_event_id,
            action="share_entitlement",
            correction_mode="correct_existing",
            expected_revision_counts=(1, 1),
            assert_prepare_is_read_only=True,
        )
        assert committed.get("outcome") == "success"
        after_correction = _business_effect_counts(world.account_id)
        assert tuple(
            new - old for old, new in zip(before_correction, after_correction, strict=True)
        ) == (2, 0, 0, 2, 2)
        assert (
            tuple(
                CorporateActionPostingModel.objects.filter(pk__in=original_ids)
                .order_by("pk")
                .values()
            )
            == original_rows
        )
        rows = list(
            CorporateActionPostingModel.objects.filter(
                account_id=world.account_id, source_event_id=original_event_id
            ).order_by("account_revision")
        )
        assert [row.entry_kind for row in rows] == ["posting", "reversal", "successor"]
        assert all(row.stage == "share_entitlement" for row in rows)
        assert [row.share_receivable_delta for row in rows] == [
            Decimal("10.000000"),
            Decimal("-10.000000"),
            Decimal("20.000000"),
        ]
        assert [
            (row.share_delta, row.share_receivable_delta, row.available_share_delta) for row in rows
        ] == [
            (Decimal("0.000000"), Decimal("10.000000"), Decimal("0.000000")),
            (Decimal("0.000000"), Decimal("-10.000000"), Decimal("0.000000")),
            (Decimal("0.000000"), Decimal("20.000000"), Decimal("0.000000")),
        ]
        assert all(row.cash_delta == row.cash_receivable_delta == Decimal("0.00") for row in rows)
        assert len(rows) == 3
        assert rows[2].share_amount == Decimal("20.000000")
        account.refresh_from_db()
        position.refresh_from_db()
        assert account.current_cash == initial_cash
        assert position.quantity == initial_quantity
        assert position.available_quantity == initial_available

        _refresh(world)
        _issue_v3_share_consent(world)
        delivered = _prepare_and_confirm(world, event_id=current_event_id, action="share_delivery")
        assert delivered.get("outcome") == "success"
        _refresh(world)
        _issue_v3_share_consent(world)
        released = _prepare_and_confirm(
            world, event_id=current_event_id, action="share_sellable_release"
        )
        assert released.get("outcome") == "success"

        account.refresh_from_db()
        position.refresh_from_db()
        assert account.current_cash == initial_cash
        assert position.quantity == initial_quantity + Decimal("20.000000")
        assert position.available_quantity == initial_available + Decimal("20.000000")
        rows = list(
            CorporateActionPostingModel.objects.filter(
                account_id=world.account_id, source_event_id=original_event_id
            ).order_by("account_revision")
        )
        assert len(rows) == 5
        assert [row.stage for row in rows] == [
            "share_entitlement",
            "share_entitlement",
            "share_entitlement",
            "share_delivery",
            "share_sellable_release",
        ]
        assert [row.entry_kind for row in rows] == [
            "posting",
            "reversal",
            "successor",
            "posting",
            "posting",
        ]
        assert [
            (row.share_delta, row.share_receivable_delta, row.available_share_delta) for row in rows
        ] == [
            (Decimal("0.000000"), Decimal("10.000000"), Decimal("0.000000")),
            (Decimal("0.000000"), Decimal("-10.000000"), Decimal("0.000000")),
            (Decimal("0.000000"), Decimal("20.000000"), Decimal("0.000000")),
            (Decimal("20.000000"), Decimal("-20.000000"), Decimal("0.000000")),
            (Decimal("0.000000"), Decimal("0.000000"), Decimal("20.000000")),
        ]
        assert [row.share_amount for row in rows[2:]] == [
            Decimal("20.000000"),
            Decimal("20.000000"),
            Decimal("20.000000"),
        ]
        assert sum((row.cash_delta for row in rows), Decimal("0.00")) == Decimal("0.00")
        assert sum((row.cash_receivable_delta for row in rows), Decimal("0.00")) == Decimal("0.00")
        assert sum((row.share_delta for row in rows), Decimal("0.000000")) == Decimal("20.000000")
        assert sum((row.share_receivable_delta for row in rows), Decimal("0.000000")) == Decimal(
            "0.000000"
        )
        assert sum((row.available_share_delta for row in rows), Decimal("0.000000")) == Decimal(
            "20.000000"
        )
        assert not CorporateActionTaxAssessmentHeaderModel.objects.filter(
            account_id=world.account_id
        ).exists()
        assert not CorporateActionTaxLiabilityOperationModel.objects.filter(
            account_id=world.account_id
        ).exists()
        final = _read(
            world.owner.client,
            _API_ROOT.format(account_id=world.account_id),
            _headers(world),
        )
        receipts = final.get("audit_receipts")
        assert isinstance(receipts, list) and len(receipts) >= 5
