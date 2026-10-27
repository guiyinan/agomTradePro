"""Owner HTTP contracts for previewing source-backed fee corrections."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol, cast
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import OperationalError, connection
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.account.infrastructure.models import UserAccessTokenModel
from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionRequest,
)
from apps.simulated_trading.application.fee_correction_evidence import (
    FeeCorrectionEvidenceUploadCommand,
    FeeCorrectionEvidenceUploadReceipt,
)
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidenceArtifactModel,
    FeeCorrectionEvidenceBindingModel,
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_repository import (
    DjangoFeeCorrectionEvidenceRepository,
)
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel
from tests.api.test_fee_correction_flow_api import (
    _account_id,
    _api_idempotency_key,
    _assert_json,
    _assert_sha256,
    _event_count,
    _evidence_counts,
    _financial_snapshot,
    _LedgerFixture,
    _post_apply,
    _trade_id,
    seed_authority_generation_for_nomigrations_sqlite,
)
from tests.component.account.test_authentication import _create_profile
from tests.component.simulated_trading.test_fee_correction_repository import (
    _csv_bytes,
    _seed_ledger,
)

pytestmark = pytest.mark.django_db
__all__ = ["seed_authority_generation_for_nomigrations_sqlite"]


def _preview_url(account_id: int, trade_id: int) -> str:
    """Return the account-scoped, evidence-only fee preview endpoint."""

    return (
        f"/api/simulated-trading/accounts/{account_id}/trades/{trade_id}/" "fee-correction-preview/"
    )


def _preview_payload(
    ledger: _LedgerFixture,
    *,
    csv_text: str | None = None,
    original_filename: str = "owner-fee-proof.csv",
    **extra_fields: object,
) -> dict[str, object]:
    """Build the exact owner-facing request without revision or amount claims."""

    payload: dict[str, object] = {
        "original_filename": original_filename,
        "csv_text": (csv_text if csv_text is not None else ledger.raw_evidence.decode("utf-8")),
        "attestation_acknowledged": True,
    }
    payload.update(extra_fields)
    return payload


def _post_preview(
    client: APIClient,
    ledger: _LedgerFixture,
    *,
    idempotency_key: str,
    payload: dict[str, object] | None = None,
) -> HttpResponse:
    """Send one exact JSON preview request with its stable operation key."""

    return client.post(
        _preview_url(_account_id(ledger), _trade_id(ledger)),
        payload if payload is not None else _preview_payload(ledger),
        format="json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def _preview_key(ledger: _LedgerFixture, suffix: str = "") -> str:
    """Return a preview key distinct from the fixture's pre-seeded evidence."""

    return f"preview-{_api_idempotency_key(ledger)}{suffix}"


def _aware_datetime(value: object) -> datetime:
    """Parse one required ISO timestamp and reject missing or naive values."""

    assert isinstance(value, str) and value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None and parsed.utcoffset() is not None
    return parsed


def _decimal_string(value: object, expected: Decimal) -> None:
    """Require a decimal-string wire value with its exact accounting amount."""

    assert isinstance(value, str)
    assert Decimal(value) == expected


def test_owner_preview_reports_exact_delta_without_posting_financial_state() -> None:
    """A 7→9 preview stores evidence but does not mutate the cash ledger."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    key = _preview_key(ledger)
    external_account_ref = "broker-ledger-account-17"
    external_trade_ref = "broker-execution-20261027-0001"
    source_csv = ledger.raw_evidence.decode("utf-8")
    source_csv = source_csv.replace(f"account-{_account_id(ledger)}", external_account_ref)
    source_csv = source_csv.replace(f"trade-{_trade_id(ledger)}", external_trade_ref)
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)
    assert _event_count(ledger) == 0

    response = _post_preview(
        client,
        ledger,
        idempotency_key=key,
        payload=_preview_payload(ledger, csv_text=source_csv),
    )
    body = _assert_json(response, 200)

    assert body["success"] is True
    assert body["status"] == "preview"
    assert isinstance(body.get("assurance_notice"), str) and body["assurance_notice"]
    assert isinstance(body.get("message"), str) and body["message"]
    assert body.get("receipt") is None
    preview = body.get("preview")
    assert isinstance(preview, dict)
    assert preview["account_id"] == _account_id(ledger)
    assert preview["trade_id"] == _trade_id(ledger)
    assert preview["asset_code"] == ledger.trade.asset_code
    assert preview["ledger_currency"] == "CNY"
    assert preview["expected_revision"] == 0
    assert preview["expected_predecessor_id"] is None
    assert str(UUID(cast(str, preview["source_locator"]))) == preview["source_locator"]
    _assert_sha256(preview.get("content_sha256"))
    _assert_sha256(preview.get("payload_sha256"))
    assert preview["assurance_class"] == "operator_attested_upload"
    binding = FeeCorrectionEvidenceBindingModel.objects.select_related("artifact").get(
        account_id=_account_id(ledger), idempotency_key=key
    )
    retained_csv = bytes(
        cast(FeeCorrectionEvidenceArtifactModel, binding.artifact).raw_bytes
    ).decode("utf-8")
    assert external_account_ref in retained_csv
    assert external_trade_ref in retained_csv
    assert f"account-{_account_id(ledger)}" not in retained_csv
    assert f"trade-{_trade_id(ledger)}" not in retained_csv

    previous = preview.get("previous_fee_components")
    revised = preview.get("revised_fee_components")
    delta = preview.get("delta")
    assert isinstance(previous, dict)
    assert isinstance(revised, dict)
    assert isinstance(delta, dict)
    _decimal_string(previous.get("commission"), Decimal("7.00"))
    _decimal_string(previous.get("transfer_fee"), Decimal("0.00"))
    _decimal_string(previous.get("stamp_duty"), Decimal("0.00"))
    _decimal_string(revised.get("commission"), Decimal("9.00"))
    _decimal_string(revised.get("transfer_fee"), Decimal("0.00"))
    _decimal_string(revised.get("stamp_duty"), Decimal("0.00"))
    _decimal_string(delta.get("commission"), Decimal("2.00"))
    _decimal_string(delta.get("transfer_fee"), Decimal("0.00"))
    _decimal_string(delta.get("stamp_duty"), Decimal("0.00"))
    _decimal_string(delta.get("total_fee_delta"), Decimal("2.00"))
    _decimal_string(delta.get("cash_delta"), Decimal("-2.00"))

    source_observed_at = _aware_datetime(preview.get("source_observed_at"))
    verified_at = _aware_datetime(preview.get("verified_at"))
    stored_at = _aware_datetime(preview.get("stored_at"))
    as_of = _aware_datetime(preview.get("as_of"))
    assert source_observed_at < stored_at
    assert source_observed_at != as_of
    assert stored_at != as_of
    assert verified_at >= source_observed_at

    assert _evidence_counts(ledger) == (before_evidence[0] + 1, before_evidence[1] + 1)
    assert _financial_snapshot(ledger) == before_financial
    assert _event_count(ledger) == 0


def test_preview_replay_preserves_one_binding_and_changed_bytes_conflict() -> None:
    """An exact retry returns the original locator; changed bytes cannot rebind it."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    key = _preview_key(ledger)
    payload = _preview_payload(ledger)
    before = _evidence_counts(ledger)

    first = _assert_json(_post_preview(client, ledger, idempotency_key=key, payload=payload), 200)
    first_preview = cast(dict[str, object], first["preview"])
    binding = FeeCorrectionEvidenceBindingModel.objects.get(
        account_id=_account_id(ledger), idempotency_key=key
    )
    counts_after_first = _evidence_counts(ledger)
    assert counts_after_first == (before[0] + 1, before[1] + 1)

    replay = _assert_json(_post_preview(client, ledger, idempotency_key=key, payload=payload), 200)
    replay_preview = cast(dict[str, object], replay["preview"])
    assert replay["status"] == "preview"
    assert replay_preview["source_locator"] == first_preview["source_locator"]
    assert replay_preview["content_sha256"] == first_preview["content_sha256"]
    assert replay_preview["payload_sha256"] == first_preview["payload_sha256"]
    assert _evidence_counts(ledger) == counts_after_first

    changed_csv = _csv_bytes(
        account_id=_account_id(ledger),
        trade=ledger.trade,
        source_observed_at=timezone.now(),
        commission=Decimal("10.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    ).decode("utf-8")
    conflict = _post_preview(
        client,
        ledger,
        idempotency_key=key,
        payload=_preview_payload(ledger, csv_text=changed_csv),
    )
    _assert_json(conflict, 409)
    binding.refresh_from_db()
    assert binding.expected_revision == 0
    assert binding.expected_predecessor_id is None
    assert _evidence_counts(ledger) == counts_after_first
    assert _event_count(ledger) == 0


def test_applied_preview_retry_returns_original_receipt_after_policy_is_disabled() -> None:
    """The original preview key recovers its posted event without another write."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    key = _preview_key(ledger)
    first = _assert_json(_post_preview(client, ledger, idempotency_key=key), 200)
    preview = cast(dict[str, object], first["preview"])
    locator = cast(str, preview["source_locator"])
    counts_after_preview = _evidence_counts(ledger)
    before_apply = _financial_snapshot(ledger)

    applied = _assert_json(
        _post_apply(
            client,
            ledger,
            idempotency_key=key,
            source_locator=locator,
            expected_revision=0,
        ),
        200,
    )
    receipt = cast(dict[str, object], applied["receipt"])
    assert receipt["revision"] == 1
    assert receipt["replayed"] is False
    assert _financial_snapshot(ledger) != before_apply
    assert _event_count(ledger) == 1

    changed_csv = _csv_bytes(
        account_id=_account_id(ledger),
        trade=ledger.trade,
        source_observed_at=timezone.now(),
        commission=Decimal("10.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    ).decode("utf-8")
    applied_snapshot = _financial_snapshot(ledger)
    changed_after_apply = _post_preview(
        client,
        ledger,
        idempotency_key=key,
        payload=_preview_payload(ledger, csv_text=changed_csv),
    )
    _assert_json(changed_after_apply, 409)
    assert _financial_snapshot(ledger) == applied_snapshot
    assert _evidence_counts(ledger) == counts_after_preview
    assert _event_count(ledger) == 1

    policy = FeeCorrectionEvidencePolicyModel.objects.get(account_id=_account_id(ledger))
    policy.enabled = False
    policy.save(update_fields=("enabled",))
    after_apply = _financial_snapshot(ledger)
    replay = _assert_json(_post_preview(client, ledger, idempotency_key=key), 200)

    assert replay["status"] == "already_applied"
    assert replay.get("preview") is None
    recovered = cast(dict[str, object], replay["receipt"])
    assert recovered["event_id"] == receipt["event_id"]
    assert recovered["account_id"] == _account_id(ledger)
    assert recovered["trade_id"] == _trade_id(ledger)
    assert recovered["revision"] == 1
    assert recovered["replayed"] is True
    assert _evidence_counts(ledger) == counts_after_preview
    assert _financial_snapshot(ledger) == after_apply
    assert _event_count(ledger) == 1


def test_pending_preview_cannot_rebind_after_another_key_advances_the_head() -> None:
    """A pending revision-0 preview stays bound and conflicts after another apply."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    pending_key = _preview_key(ledger, "-pending")
    _assert_json(_post_preview(client, ledger, idempotency_key=pending_key), 200)
    binding = FeeCorrectionEvidenceBindingModel.objects.get(
        account_id=_account_id(ledger), idempotency_key=pending_key
    )
    assert binding.expected_revision == 0
    assert binding.expected_predecessor_id is None

    # The fixture's separately seeded original evidence advances revision 1.
    applied = _assert_json(
        _post_apply(
            client,
            ledger,
            idempotency_key=ledger.request.idempotency_key,
            source_locator=ledger.request.source_locator,
            expected_revision=0,
        ),
        200,
    )
    assert applied["receipt"]["revision"] == 1
    counts_after_apply = _evidence_counts(ledger)
    financial_after_apply = _financial_snapshot(ledger)

    conflict = _post_preview(client, ledger, idempotency_key=pending_key)
    _assert_json(conflict, 409)
    binding.refresh_from_db()
    assert binding.expected_revision == 0
    assert binding.expected_predecessor_id is None
    assert _evidence_counts(ledger) == counts_after_apply
    assert _financial_snapshot(ledger) == financial_after_apply
    assert _event_count(ledger) == 1


def test_new_key_after_valid_prior_event_creates_a_revision_one_preview() -> None:
    """A prior event under J does not make a later key K appear already applied."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    first_apply = _assert_json(
        _post_apply(
            client,
            ledger,
            idempotency_key=ledger.request.idempotency_key,
            source_locator=ledger.request.source_locator,
            expected_revision=0,
        ),
        200,
    )
    prior_event_id = cast(int, first_apply["receipt"]["event_id"])
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)
    reversal_csv = _csv_bytes(
        account_id=_account_id(ledger),
        trade=ledger.trade,
        source_observed_at=timezone.now(),
        commission=Decimal("7.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    ).decode("utf-8")
    new_key = _preview_key(ledger, "-revision-one")

    body = _assert_json(
        _post_preview(
            client,
            ledger,
            idempotency_key=new_key,
            payload=_preview_payload(ledger, csv_text=reversal_csv),
        ),
        200,
    )

    assert body["status"] == "preview"
    assert body.get("receipt") is None
    preview = cast(dict[str, object], body["preview"])
    assert preview["expected_revision"] == 1
    assert preview["expected_predecessor_id"] == prior_event_id
    _decimal_string(
        cast(dict[str, object], preview["delta"]).get("total_fee_delta"),
        Decimal("-2.00"),
    )
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == (before_evidence[0] + 1, before_evidence[1] + 1)
    assert _event_count(ledger) == 1


def test_same_key_on_a_different_trade_in_the_account_conflicts() -> None:
    """An account's preview key cannot silently migrate to another Trade."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    key = _preview_key(ledger, "-cross-trade")
    first = _assert_json(_post_preview(client, ledger, idempotency_key=key), 200)
    first_locator = cast(dict[str, object], first["preview"])["source_locator"]

    other_trade = SimulatedTradeModel.objects.create(
        account=ledger.account,
        asset_code="000001.SZ",
        asset_name="Second preview trade",
        asset_type="equity",
        action="buy",
        quantity=Decimal("100.000000"),
        price=Decimal("10.0000"),
        amount=Decimal("1000.00"),
        commission=Decimal("7.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
        slippage=Decimal("0.02"),
        total_cost=Decimal("1007.02"),
        fee_amounts_known=True,
        cost_basis_known=True,
        realized_pnl=None,
        realized_pnl_pct=None,
        order_date=ledger.trade.order_date,
        execution_date=ledger.trade.execution_date,
        execution_time=ledger.trade.execution_time,
        status="executed",
    )
    other_trade_csv = _csv_bytes(
        account_id=_account_id(ledger),
        trade=other_trade,
        source_observed_at=timezone.now(),
        commission=Decimal("8.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    ).decode("utf-8")
    before_evidence = _evidence_counts(ledger)
    before_financial = _financial_snapshot(ledger)

    response = client.post(
        _preview_url(_account_id(ledger), cast(int, other_trade.pk)),
        _preview_payload(ledger, csv_text=other_trade_csv),
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )

    _assert_json(response, 409)
    binding = FeeCorrectionEvidenceBindingModel.objects.get(
        account_id=_account_id(ledger), idempotency_key=key
    )
    assert str(binding.public_id) == str(first_locator)
    assert binding.trade_id == _trade_id(ledger)
    assert _evidence_counts(ledger) == before_evidence
    assert _financial_snapshot(ledger) == before_financial
    assert _event_count(ledger) == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_revision", 0),
        ("expected_predecessor_id", None),
        ("amount", "2.00"),
        ("actor_user_id", 1),
    ],
)
def test_preview_rejects_client_supplied_technical_or_financial_fields(
    field: str,
    value: object,
) -> None:
    """The server, not the caller, chooses revision, predecessor and fee delta."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    key = _preview_key(ledger, f"-{field}")
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    response = _post_preview(
        client,
        ledger,
        idempotency_key=key,
        payload=_preview_payload(ledger, **{field: value}),
    )

    _assert_json(response, 400)
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


def test_malformed_proof_does_not_create_preview_material() -> None:
    """An invalid source CSV cannot create a durable preview binding."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    response = _post_preview(
        client,
        ledger,
        idempotency_key=_preview_key(ledger, "-malformed"),
        payload=_preview_payload(ledger, csv_text="not a fee correction CSV"),
    )

    _assert_json(response, 422)
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


def test_economic_identity_mismatch_is_rejected_without_retaining_material() -> None:
    """A different asset identity is rejected without relying on source reference IDs."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    mismatched_asset_csv = (
        _csv_bytes(
            account_id=_account_id(ledger),
            trade=ledger.trade,
            source_observed_at=timezone.now(),
            commission=Decimal("9.00"),
            transfer_fee=Decimal("0.00"),
            stamp_duty=Decimal("0.00"),
        )
        .decode("utf-8")
        .replace(ledger.trade.asset_code, "000001.SZ")
    )
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    response = _post_preview(
        client,
        ledger,
        idempotency_key=_preview_key(ledger, "-wrong-asset-proof"),
        payload=_preview_payload(ledger, csv_text=mismatched_asset_csv),
    )

    _assert_json(response, 422)
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


def test_verify_rejection_rolls_back_a_binding_already_captured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outer preview unit rolls back capture when source verification rejects it."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    key = _preview_key(ledger, "-verify-rejection")
    real_capture = DjangoFeeCorrectionEvidenceRepository.capture

    def capture_then_assert_binding(
        repository: DjangoFeeCorrectionEvidenceRepository,
        command: FeeCorrectionEvidenceUploadCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionEvidenceUploadReceipt:
        receipt = real_capture(repository, command, principal=principal)
        assert FeeCorrectionEvidenceBindingModel.objects.filter(
            account_id=_account_id(ledger), idempotency_key=key
        ).exists()
        return receipt

    def reject_after_capture(
        _repository: DjangoFeeCorrectionEvidenceRepository,
        _request: FeeCorrectionRequest,
    ) -> None:
        assert FeeCorrectionEvidenceBindingModel.objects.filter(
            account_id=_account_id(ledger), idempotency_key=key
        ).exists()
        return None

    monkeypatch.setattr(
        DjangoFeeCorrectionEvidenceRepository,
        "capture",
        capture_then_assert_binding,
    )
    monkeypatch.setattr(
        DjangoFeeCorrectionEvidenceRepository,
        "verify",
        reject_after_capture,
    )
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    response = _post_preview(client, ledger, idempotency_key=key)

    _assert_json(response, 422)
    assert not FeeCorrectionEvidenceBindingModel.objects.filter(
        account_id=_account_id(ledger), idempotency_key=key
    ).exists()
    assert _evidence_counts(ledger) == before_evidence
    assert _financial_snapshot(ledger) == before_financial
    assert _event_count(ledger) == 0


def test_owner_policy_read_outage_is_read_unavailable_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure before the preview write use case is a read outage, not uncertainty."""

    from apps.simulated_trading.interface import fee_correction_views

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    policy_use_case = Mock()
    policy_use_case.get.side_effect = OperationalError("simulated policy read outage")
    monkeypatch.setattr(
        fee_correction_views,
        "build_fee_correction_policy_use_case",
        Mock(return_value=policy_use_case),
    )
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    response = _post_preview(
        client,
        ledger,
        idempotency_key=_preview_key(ledger, "-read-outage"),
    )

    body = _assert_json(response, 503)
    assert body["code"] == "FEE_CORRECTION_READ_UNAVAILABLE"
    assert body.get("effects_indeterminate") is not True
    assert body.get("recovery_required") is not True
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


def test_readonly_token_cannot_create_preview_material() -> None:
    """A read-only token remains restricted from preview evidence writes."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    _create_profile(ledger.owner)
    _token_id, token = UserAccessTokenModel.create_token(
        user=ledger.owner,
        name="fee-correction-preview-read-only",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    response = _post_preview(client, ledger, idempotency_key=_preview_key(ledger))

    _assert_json(response, 403)
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


@pytest.mark.parametrize("mode", ["anonymous", "session-without-csrf"])
def test_anonymous_or_csrfless_session_cannot_preview(mode: str) -> None:
    """The material-write endpoint requires authenticated CSRF-safe ownership."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient(enforce_csrf_checks=True)
    if mode == "session-without-csrf":
        client.force_login(ledger.owner)
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    response = _post_preview(client, ledger, idempotency_key=_preview_key(ledger, f"-{mode}"))

    _assert_json(response, 403)
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


@pytest.mark.parametrize("superuser", [False, True])
def test_foreign_owner_and_unrelated_superuser_cannot_preview(superuser: bool) -> None:
    """Account ownership is required even when the unrelated user is staff."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    other_user = get_user_model().objects.create_user(
        username=f"foreign-fee-preview-{uuid4().hex}",
        password="unused",
    )
    if superuser:
        other_user.is_staff = True
        other_user.is_superuser = True
        other_user.save(update_fields=("is_staff", "is_superuser"))
    client = APIClient()
    client.force_authenticate(user=other_user)
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    response = _post_preview(client, ledger, idempotency_key=_preview_key(ledger))

    _assert_json(response, 403)
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


def test_readwrite_token_can_create_a_preview_without_applying_it() -> None:
    """The owner write token can store verified material but cannot post a fee event."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    _create_profile(ledger.owner)
    _token_id, token = UserAccessTokenModel.create_token(
        user=ledger.owner,
        name="fee-correction-preview-read-write",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_WRITE,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    before_financial = _financial_snapshot(ledger)

    body = _assert_json(
        _post_preview(client, ledger, idempotency_key=_preview_key(ledger, "-write-token")),
        200,
    )

    assert body["status"] == "preview"
    assert isinstance(body.get("preview"), dict)
    assert _financial_snapshot(ledger) == before_financial
    assert _event_count(ledger) == 0


def test_corrupt_fee_history_blocks_new_preview_without_material_writes() -> None:
    """A malformed prior event blocks a fresh proof instead of creating a preview."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    applied = _assert_json(
        _post_apply(
            client,
            ledger,
            idempotency_key=ledger.request.idempotency_key,
            source_locator=ledger.request.source_locator,
            expected_revision=0,
        ),
        200,
    )
    event = SimulatedFeeCorrectionEventModel.objects.get(pk=applied["receipt"]["event_id"])
    table = connection.ops.quote_name(SimulatedFeeCorrectionEventModel._meta.db_table)
    column = connection.ops.quote_name("revised_commission")
    primary_key = connection.ops.quote_name(SimulatedFeeCorrectionEventModel._meta.pk.column)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET {column} = %s WHERE {primary_key} = %s",
            [Decimal("8.00"), event.pk],
        )
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    changed_csv = _csv_bytes(
        account_id=_account_id(ledger),
        trade=ledger.trade,
        source_observed_at=timezone.now(),
        commission=Decimal("10.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    ).decode("utf-8")
    response = _post_preview(
        client,
        ledger,
        idempotency_key=_preview_key(ledger, "-corrupt-history"),
        payload=_preview_payload(ledger, csv_text=changed_csv),
    )

    _assert_json(response, 422)
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 1


def test_disabled_policy_blocks_a_new_preview_without_retaining_material() -> None:
    """A valid owner cannot create fresh preview evidence under a disabled policy."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    policy = FeeCorrectionEvidencePolicyModel.objects.get(account_id=_account_id(ledger))
    policy.enabled = False
    policy.save(update_fields=("enabled",))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    response = _post_preview(
        client,
        ledger,
        idempotency_key=_preview_key(ledger, "-disabled-policy"),
    )

    _assert_json(response, 422)
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


def test_preview_write_database_error_is_indeterminate_and_original_key_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lost acknowledgement retains no financial write and recovers one binding."""

    from apps.simulated_trading.interface import fee_correction_views

    class _ExecutablePreview(Protocol):
        """Minimal use-case shape for a post-commit acknowledgement failure."""

        def execute(self, *args: object, **kwargs: object) -> object: ...

    class _CommitThenDisconnect:
        """Commit the real preview, then simulate losing the database acknowledgement."""

        def __init__(self, use_case: object) -> None:
            self._use_case = cast(_ExecutablePreview, use_case)

        def execute(self, *args: object, **kwargs: object) -> object:
            self._use_case.execute(*args, **kwargs)
            raise OperationalError("simulated preview acknowledgement loss")

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    key = _preview_key(ledger, "-lost-response")
    payload = _preview_payload(ledger)
    real_builder = fee_correction_views.build_fee_correction_preview_use_case
    monkeypatch.setattr(
        fee_correction_views,
        "build_fee_correction_preview_use_case",
        lambda *args, **kwargs: _CommitThenDisconnect(real_builder(*args, **kwargs)),
    )
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    uncertain = _post_preview(client, ledger, idempotency_key=key, payload=payload)
    body = _assert_json(uncertain, 503)
    assert body["code"] == "FEE_CORRECTION_RESULT_INDETERMINATE"
    assert body["effects_indeterminate"] is True
    assert body["recovery_required"] is True
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == (before_evidence[0] + 1, before_evidence[1] + 1)
    assert _event_count(ledger) == 0

    monkeypatch.setattr(
        fee_correction_views,
        "build_fee_correction_preview_use_case",
        real_builder,
    )
    recovered = _assert_json(
        _post_preview(client, ledger, idempotency_key=key, payload=payload), 200
    )
    assert recovered["status"] == "preview"
    recovered_preview = cast(dict[str, object], recovered["preview"])
    binding = FeeCorrectionEvidenceBindingModel.objects.get(
        account_id=_account_id(ledger), idempotency_key=key
    )
    assert recovered_preview["source_locator"] == str(binding.public_id)
    assert _evidence_counts(ledger) == (before_evidence[0] + 1, before_evidence[1] + 1)
    assert _financial_snapshot(ledger) == before_financial
    assert _event_count(ledger) == 0
