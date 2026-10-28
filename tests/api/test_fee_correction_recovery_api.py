"""HTTP contracts for recovering exact pending simulated fee evidence."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast
from urllib.parse import urlencode
from uuid import UUID, uuid4

import pytest
from django.contrib.sessions.models import Session
from django.db import connection
from django.http import HttpResponse
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidenceArtifactModel,
    FeeCorrectionEvidenceBindingModel,
)
from tests.api.test_fee_correction_confirmation_api import (
    _ORIGIN,
    _confirmation_token,
    _create_unrelated_user,
    _other_trade,
    _post_confirmation,
    _session_key,
    _session_owner_client,
    _test_field_encryption_key,
)
from tests.api.test_fee_correction_flow_api import (
    _account_id,
    _apply_url,
    _assert_json,
    _event_count,
    _evidence_counts,
    _financial_snapshot,
    _head_url,
    _post_apply,
    _post_upload,
    _trade_id,
    _upload_payload,
    seed_authority_generation_for_nomigrations_sqlite,
)
from tests.api.test_fee_correction_policy_api import _payload as _policy_payload
from tests.api.test_fee_correction_policy_api import _url as _policy_url
from tests.api.test_fee_correction_preview_api import (
    _post_preview,
    _preview_payload,
    _preview_url,
)
from tests.component.simulated_trading.test_fee_correction_repository import (
    _csv_bytes,
    _LedgerFixture,
    _LedgerRowsFixture,
    _seed_ledger,
    _seed_ledger_without_evidence,
)

pytestmark = pytest.mark.django_db
__all__ = ["seed_authority_generation_for_nomigrations_sqlite", "_test_field_encryption_key"]


def _recovery_url(account_id: int, trade_id: int) -> str:
    """Return the owner-scoped discovery route for one exact Trade."""

    return _apply_url(account_id, trade_id) + "recovery/"


def _recovery_head_url(account_id: int, trade_id: int, source_locator: str) -> str:
    """Return the exact-locator read route without an idempotency-key identity."""

    return (
        f"/api/simulated-trading/accounts/{account_id}/trades/{trade_id}/"
        f"fee-corrections/recovery/{source_locator}/head/"
    )


def _get_recovery(
    client: APIClient,
    account_id: int,
    trade_id: int,
    *,
    query: dict[str, str] | None = None,
) -> HttpResponse:
    """Read one discovery page using the real account owner API."""

    url = _recovery_url(account_id, trade_id)
    if query:
        url = f"{url}?{urlencode(query)}"
    return cast(HttpResponse, client.get(url))


def _post_recovery_preview(
    client: APIClient,
    ledger: _LedgerFixture,
    *,
    source_locator: str,
    transport_key: str,
) -> HttpResponse:
    """Submit only a persisted locator under this preview transport key."""

    return cast(
        HttpResponse,
        client.post(
            _preview_url(_account_id(ledger), _trade_id(ledger)),
            {"source_locator": source_locator},
            format="json",
            HTTP_IDEMPOTENCY_KEY=transport_key,
        ),
    )


def _post_session_recovery_preview(
    client: APIClient,
    ledger: _LedgerFixture,
    *,
    source_locator: str,
    transport_key: str,
    csrf_token: str,
) -> HttpResponse:
    """Submit a locator-only recovery preview over the live browser session."""

    return cast(
        HttpResponse,
        client.post(
            _preview_url(_account_id(ledger), _trade_id(ledger)),
            {"source_locator": source_locator},
            format="json",
            secure=True,
            HTTP_ORIGIN=_ORIGIN,
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_IDEMPOTENCY_KEY=transport_key,
        ),
    )


def _post_original_session_preview(
    client: APIClient,
    ledger: _LedgerFixture,
    *,
    original_filename: str,
    csrf_token: str,
    key: str,
) -> HttpResponse:
    """Replay the exact seeded filename and bytes over the real browser session."""

    return cast(
        HttpResponse,
        client.post(
            _preview_url(_account_id(ledger), _trade_id(ledger)),
            _preview_payload(ledger, original_filename=original_filename),
            format="json",
            secure=True,
            HTTP_ORIGIN=_ORIGIN,
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_IDEMPOTENCY_KEY=key,
        ),
    )


def _recovery_items(payload: dict[str, object]) -> list[dict[str, object]]:
    """Narrow the documented paged recovery response."""

    recovery = payload.get("recovery")
    assert isinstance(recovery, dict)
    items = recovery.get("items")
    assert isinstance(items, list)
    assert all(isinstance(item, dict) for item in items)
    return cast(list[dict[str, object]], items)


def _aware_datetime(value: object) -> datetime:
    """Parse one ISO timestamp and reject missing or naive wire values."""

    assert isinstance(value, str) and value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None and parsed.utcoffset() is not None
    return parsed


def _rows_financial_snapshot(rows: _LedgerRowsFixture) -> tuple[object, ...]:
    """Read the exact account, position, and Trade fields before and after discovery."""

    rows.account.refresh_from_db()
    rows.position.refresh_from_db()
    rows.trade.refresh_from_db()
    return (
        rows.account.current_cash,
        rows.account.current_market_value,
        rows.account.total_value,
        rows.position.quantity,
        rows.position.total_cost,
        rows.position.avg_cost,
        rows.trade.commission,
        rows.trade.transfer_fee,
        rows.trade.stamp_duty,
        rows.trade.slippage,
        rows.trade.total_cost,
    )


def _rows_evidence_counts(rows: _LedgerRowsFixture) -> tuple[int, int]:
    """Count append-only materials for one exact account."""

    return (
        FeeCorrectionEvidenceArtifactModel.objects.filter(account_id=rows.account.pk).count(),
        FeeCorrectionEvidenceBindingModel.objects.filter(account_id=rows.account.pk).count(),
    )


def _write_policy_state(
    client: APIClient,
    ledger: _LedgerFixture,
    *,
    enabled: bool,
    allow_operator_attested_upload: bool,
    attestation_acknowledged: bool,
) -> dict[str, object]:
    """Use the existing owner policy endpoint and preserve its current validity window."""

    current = _assert_json(client.get(_policy_url(_account_id(ledger))), 200)
    policy = current.get("policy")
    assert isinstance(policy, dict)
    payload = _policy_payload(
        expected_version=policy["version"],
        enabled=enabled,
        allow_operator_attested_upload=allow_operator_attested_upload,
        ledger_currency=policy["ledger_currency"],
        valid_from=policy["valid_from"],
        valid_until=policy["valid_until"],
        attestation_acknowledged=attestation_acknowledged,
    )
    response = _assert_json(
        client.put(_policy_url(_account_id(ledger)), payload, format="json"),
        200,
    )
    state = response.get("policy")
    assert isinstance(state, dict)
    return cast(dict[str, object], state)


def _create_legacy_pending_binding(
    ledger: _LedgerFixture,
    *,
    idempotency_key: str,
) -> FeeCorrectionEvidenceBindingModel:
    """Insert a second valid legacy pending binding without bypassing append-only saves."""

    original = FeeCorrectionEvidenceBindingModel.objects.select_related("artifact", "policy").get(
        account_id=_account_id(ledger),
        idempotency_key=ledger.request.idempotency_key,
    )
    source = original.artifact
    now = timezone.now()
    artifact = FeeCorrectionEvidenceArtifactModel.objects.create(
        account_id=source.account_id,
        uploaded_by_id=source.uploaded_by_id,
        original_filename="legacy-second-fee-proof.csv",
        assurance_class=source.assurance_class,
        schema_version=source.schema_version,
        raw_bytes=bytes(source.raw_bytes),
        content_sha256=source.content_sha256,
        payload_sha256=source.payload_sha256,
        raw_row_json=source.raw_row_json,
        parsed_metadata_json=source.parsed_metadata_json,
        uploaded_at=now,
    )
    return FeeCorrectionEvidenceBindingModel.objects.create(
        account_id=original.account_id,
        trade_id=original.trade_id,
        artifact=artifact,
        policy_id=original.policy_id,
        idempotency_key=idempotency_key,
        attested_by_id=original.attested_by_id,
        attestation_version=original.attestation_version,
        attestation_acknowledged=original.attestation_acknowledged,
        assurance_class=original.assurance_class,
        expected_revision=original.expected_revision,
        expected_predecessor_id=original.expected_predecessor_id,
        content_sha256=original.content_sha256,
        payload_sha256=original.payload_sha256,
        trade_snapshot_sha256=original.trade_snapshot_sha256,
        policy_version=original.policy_version,
        policy_sha256=original.policy_sha256,
        policy_snapshot_json=original.policy_snapshot_json,
        created_at=now,
    )


def _tamper_artifact_bytes(artifact: FeeCorrectionEvidenceArtifactModel) -> None:
    """Create a test-only damaged immutable row through parameterized SQL."""

    table = connection.ops.quote_name(FeeCorrectionEvidenceArtifactModel._meta.db_table)
    raw_bytes_column = connection.ops.quote_name("raw_bytes")
    primary_key_column = connection.ops.quote_name("id")
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET {raw_bytes_column} = %s WHERE {primary_key_column} = %s",
            [bytes(artifact.raw_bytes) + b"damaged", artifact.pk],
        )
        assert cursor.rowcount == 1


def test_discovery_reports_exact_pending_binding_and_empty_state_without_writes() -> None:
    """Read discovery is owner scoped and does not capture evidence or post a correction."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    owner_client = APIClient()
    owner_client.force_authenticate(user=ledger.owner)
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    pending_body = _assert_json(
        _get_recovery(owner_client, _account_id(ledger), _trade_id(ledger)),
        200,
    )
    pending = _recovery_items(pending_body)
    assert len(pending) == 1
    item = pending[0]
    binding = FeeCorrectionEvidenceBindingModel.objects.select_related("artifact").get(
        account_id=_account_id(ledger),
        idempotency_key=ledger.request.idempotency_key,
    )
    assert item["source_locator"] == ledger.request.source_locator
    assert item["content_sha256"] == binding.content_sha256
    assert item["payload_sha256"] == binding.payload_sha256
    assert item["expected_revision"] == binding.expected_revision == 0
    assert item["expected_predecessor_id"] is None
    assert item["binding_policy_version"] == binding.policy_version
    assert item["current_policy_version"] == binding.policy_version
    assert item["state"] == "unresolved"
    assert _aware_datetime(item["stored_at"]) == binding.artifact.uploaded_at
    assert "idempotency_key" not in item
    assert "original_filename" not in item
    assert pending_body["success"] is True
    assert _evidence_counts(ledger) == before_evidence
    assert _financial_snapshot(ledger) == before_financial
    assert _event_count(ledger) == 0

    empty_rows = _seed_ledger_without_evidence(
        commission=Decimal("7.00"),
        revised_commission=Decimal("9.00"),
    )
    empty_client = APIClient()
    empty_client.force_authenticate(user=empty_rows.owner)
    empty_before = _rows_financial_snapshot(empty_rows)
    empty_response = _assert_json(
        _get_recovery(empty_client, empty_rows.account.pk, empty_rows.trade.pk),
        200,
    )
    recovery = empty_response.get("recovery")
    assert isinstance(recovery, dict)
    assert recovery["items"] == []
    assert recovery["has_more"] is False
    assert recovery["next_cursor"] is None
    assert _rows_evidence_counts(empty_rows) == (0, 0)
    assert (
        SimulatedFeeCorrectionEventModel.objects.filter(
            account_id=empty_rows.account.pk,
            trade_id=empty_rows.trade.pk,
        ).count()
        == 0
    )
    assert _rows_financial_snapshot(empty_rows) == empty_before


def test_new_key_is_blocked_but_exact_original_key_can_recover() -> None:
    """A pending ledger key blocks new material while exact retries stay idempotent."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    binding = FeeCorrectionEvidenceBindingModel.objects.select_related("artifact").get(
        account_id=_account_id(ledger),
        idempotency_key=ledger.request.idempotency_key,
    )
    before_evidence = _evidence_counts(ledger)
    before_financial = _financial_snapshot(ledger)

    upload_key = f"new-upload-{uuid4().hex}"
    new_upload = _assert_json(
        _post_upload(
            client,
            ledger,
            idempotency_key=upload_key,
            payload=_upload_payload(
                ledger,
                idempotency_key=upload_key,
                expected_revision=0,
                expected_predecessor_id=None,
            ),
        ),
        409,
    )
    assert new_upload["code"] == "FEE_CORRECTION_RECOVERY_REQUIRED"

    preview_key = f"new-preview-{uuid4().hex}"
    new_preview = _assert_json(
        _post_preview(
            client,
            ledger,
            idempotency_key=preview_key,
            payload=_preview_payload(ledger, original_filename=binding.artifact.original_filename),
        ),
        409,
    )
    assert new_preview["code"] == "FEE_CORRECTION_RECOVERY_REQUIRED"
    assert _evidence_counts(ledger) == before_evidence
    assert _financial_snapshot(ledger) == before_financial
    assert _event_count(ledger) == 0

    exact_upload = _assert_json(
        _post_upload(
            client,
            ledger,
            idempotency_key=ledger.request.idempotency_key,
            payload=_upload_payload(
                ledger,
                idempotency_key=ledger.request.idempotency_key,
                original_filename=binding.artifact.original_filename,
                expected_revision=binding.expected_revision,
                expected_predecessor_id=binding.expected_predecessor_id,
            ),
        ),
        200,
    )
    evidence = exact_upload.get("evidence")
    assert isinstance(evidence, dict)
    assert evidence["source_locator"] == ledger.request.source_locator

    exact_preview = _assert_json(
        _post_preview(
            client,
            ledger,
            idempotency_key=ledger.request.idempotency_key,
            payload=_preview_payload(ledger, original_filename=binding.artifact.original_filename),
        ),
        200,
    )
    assert exact_preview["status"] == "preview"
    preview = exact_preview.get("preview")
    assert isinstance(preview, dict)
    assert preview["source_locator"] == ledger.request.source_locator
    assert preview["content_sha256"] == binding.content_sha256
    assert preview["payload_sha256"] == binding.payload_sha256
    assert _evidence_counts(ledger) == before_evidence
    assert _financial_snapshot(ledger) == before_financial
    assert _event_count(ledger) == 0


def test_pending_binding_blocks_only_its_trade_within_the_same_account() -> None:
    """A pending source guards its Trade while a distinct Trade can still capture."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    other_trade = _other_trade(ledger)
    other_bytes = _csv_bytes(
        account_id=_account_id(ledger),
        trade=other_trade,
        source_observed_at=timezone.now() - timedelta(minutes=1),
        commission=Decimal("8.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    )
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    key = f"other-trade-{uuid4().hex}"
    before_counts = _evidence_counts(ledger)

    response = client.post(
        _preview_url(_account_id(ledger), cast(int, other_trade.pk)),
        _preview_payload(
            ledger,
            csv_text=other_bytes.decode("utf-8"),
            original_filename="other-trade-fees.csv",
        ),
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )

    body = _assert_json(response, 200)
    assert body["status"] == "preview"
    assert _evidence_counts(ledger) == (before_counts[0] + 1, before_counts[1] + 1)
    assert FeeCorrectionEvidenceBindingModel.objects.filter(
        account_id=_account_id(ledger),
        trade_id=other_trade.pk,
        idempotency_key=key,
    ).exists()
    assert _event_count(ledger) == 0


def test_new_transport_recovery_preserves_material_and_confirms_original_ledger_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new transport key resumes the original binding and posts exactly one old-key event."""

    from apps.simulated_trading.infrastructure import fee_correction_confirmation_repository

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    binding = FeeCorrectionEvidenceBindingModel.objects.select_related("artifact").get(
        account_id=_account_id(ledger),
        idempotency_key=ledger.request.idempotency_key,
    )
    client, csrf_token = _session_owner_client(ledger)
    counts_before = _evidence_counts(ledger)

    with override_settings(SESSION_COOKIE_AGE=3600):
        original = _assert_json(
            _post_original_session_preview(
                client,
                ledger,
                original_filename=binding.artifact.original_filename,
                csrf_token=csrf_token,
                key=ledger.request.idempotency_key,
            ),
            200,
        )
        original_preview = cast(dict[str, object], original["preview"])
        original_continuation = cast(dict[str, object], original["continuation"])
        original_expiry = _aware_datetime(original_continuation["expires_at"])
        later = timezone.now() + timedelta(minutes=5)
        monkeypatch.setattr(fee_correction_confirmation_repository.timezone, "now", lambda: later)

        transport_key = f"recovery-transport-{uuid4().hex}"
        recovered = _assert_json(
            _post_session_recovery_preview(
                client,
                ledger,
                source_locator=ledger.request.source_locator,
                transport_key=transport_key,
                csrf_token=csrf_token,
            ),
            200,
        )
        assert recovered["status"] == "preview"
        preview = cast(dict[str, object], recovered["preview"])
        continuation = cast(dict[str, object], recovered["continuation"])
        assert preview["source_locator"] == original_preview["source_locator"]
        assert preview["content_sha256"] == original_preview["content_sha256"]
        assert preview["payload_sha256"] == original_preview["payload_sha256"]
        assert preview["stored_at"] == original_preview["stored_at"]
        assert preview["expected_revision"] == original_preview["expected_revision"]
        assert preview["expected_predecessor_id"] == original_preview["expected_predecessor_id"]
        assert _aware_datetime(continuation["expires_at"]) == original_expiry
        token = _confirmation_token(recovered, ledger)
        assert set(cast(dict[str, object], continuation["input"])) == {
            "account_id",
            "trade_id",
            "confirmation_token",
        }
        assert "idempotency_key" not in continuation["input"]

        artifact_after_preview = FeeCorrectionEvidenceArtifactModel.objects.get(
            pk=binding.artifact_id
        )
        assert bytes(artifact_after_preview.raw_bytes) == ledger.raw_evidence
        assert artifact_after_preview.original_filename == binding.artifact.original_filename
        assert artifact_after_preview.uploaded_at == binding.artifact.uploaded_at
        assert _evidence_counts(ledger) == counts_before
        assert _event_count(ledger) == 0

        wrong_transport = _assert_json(
            _post_confirmation(
                client,
                ledger,
                csrf_token=csrf_token,
                key=ledger.request.idempotency_key,
                confirmation_token=token,
            ),
            409,
        )
        assert wrong_transport["code"] == "FEE_CORRECTION_CONFIRMATION_BINDING_MISMATCH"
        assert _event_count(ledger) == 0

        applied = _assert_json(
            _post_confirmation(
                client,
                ledger,
                csrf_token=csrf_token,
                key=transport_key,
                confirmation_token=token,
            ),
            200,
        )
        receipt = cast(dict[str, object], applied["receipt"])
        assert receipt["replayed"] is False
        event = SimulatedFeeCorrectionEventModel.objects.get(pk=receipt["event_id"])
        assert event.idempotency_key == ledger.request.idempotency_key
        assert _event_count(ledger) == 1
        assert _evidence_counts(ledger) == counts_before

        replay = _assert_json(
            _post_session_recovery_preview(
                client,
                ledger,
                source_locator=ledger.request.source_locator,
                transport_key=f"recovery-replay-{uuid4().hex}",
                csrf_token=csrf_token,
            ),
            200,
        )
        assert replay["status"] == "already_applied"
        assert replay.get("continuation") is None
        replayed_receipt = cast(dict[str, object], replay["receipt"])
        assert replayed_receipt["event_id"] == receipt["event_id"]
        assert replayed_receipt["replayed"] is True
        assert _event_count(ledger) == 1
        assert _evidence_counts(ledger) == counts_before


def test_expired_recovery_keeps_original_deadline_and_does_not_fence_pending_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing confirmation response cannot refresh the artifact-derived deadline."""

    from apps.simulated_trading.infrastructure import fee_correction_confirmation_repository

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    binding = FeeCorrectionEvidenceBindingModel.objects.select_related("artifact").get(
        account_id=_account_id(ledger),
        idempotency_key=ledger.request.idempotency_key,
    )
    client, csrf_token = _session_owner_client(ledger)
    session = Session.objects.get(session_key=_session_key(client))
    session.expire_date = timezone.now() + timedelta(days=2)
    session.save(update_fields=("expire_date",))
    counts_before = _evidence_counts(ledger)

    with override_settings(SESSION_COOKIE_AGE=60):
        first = _assert_json(
            _post_original_session_preview(
                client,
                ledger,
                original_filename=binding.artifact.original_filename,
                csrf_token=csrf_token,
                key=ledger.request.idempotency_key,
            ),
            200,
        )
        continuation = cast(dict[str, object], first["continuation"])
        original_expiry = _aware_datetime(continuation["expires_at"])
        after_expiry = original_expiry + timedelta(seconds=1)
        monkeypatch.setattr(
            fee_correction_confirmation_repository.timezone,
            "now",
            lambda: after_expiry,
        )

        reader = APIClient()
        reader.force_authenticate(user=ledger.owner)
        discovery = _assert_json(
            _get_recovery(reader, _account_id(ledger), _trade_id(ledger)),
            200,
        )
        item = _recovery_items(discovery)[0]
        assert item["state"] == "unresolved"

        expired = _assert_json(
            _post_session_recovery_preview(
                client,
                ledger,
                source_locator=ledger.request.source_locator,
                transport_key=f"expired-recovery-{uuid4().hex}",
                csrf_token=csrf_token,
            ),
            409,
        )
        assert expired["code"] == "FEE_CORRECTION_CONFIRMATION_EXPIRED"
        assert expired.get("continuation") is None
        assert _evidence_counts(ledger) == counts_before
        assert _event_count(ledger) == 0


def test_same_value_policy_write_does_not_fence_and_new_key_remains_blocked() -> None:
    """A no-op owner policy PUT preserves its version and the pending binding state."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    current = _assert_json(client.get(_policy_url(_account_id(ledger))), 200)
    state = cast(dict[str, object], current["policy"])
    unchanged = _write_policy_state(
        client,
        ledger,
        enabled=cast(bool, state["enabled"]),
        allow_operator_attested_upload=cast(bool, state["allow_operator_attested_upload"]),
        attestation_acknowledged=True,
    )
    assert unchanged["version"] == state["version"]

    discovery = _assert_json(
        _get_recovery(client, _account_id(ledger), _trade_id(ledger)),
        200,
    )
    assert _recovery_items(discovery)[0]["state"] == "unresolved"
    blocked = _assert_json(
        _post_upload(
            client,
            ledger,
            idempotency_key=f"same-policy-new-{uuid4().hex}",
        ),
        409,
    )
    assert blocked["code"] == "FEE_CORRECTION_RECOVERY_REQUIRED"
    assert _evidence_counts(ledger) == (1, 1)
    assert _event_count(ledger) == 0


def test_explicit_policy_revoke_fences_only_pending_material_and_history_stays_readable() -> None:
    """A real policy version change fences old pending bytes but preserves old receipts."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    original = _assert_json(
        _post_apply(
            client,
            ledger,
            idempotency_key=ledger.request.idempotency_key,
            source_locator=ledger.request.source_locator,
            expected_revision=0,
        ),
        200,
    )
    original_receipt = cast(dict[str, object], original["receipt"])
    original_event_id = cast(int, original_receipt["event_id"])

    pending_key = f"old-policy-pending-{uuid4().hex}"
    pending_csv = _csv_bytes(
        account_id=_account_id(ledger),
        trade=ledger.trade,
        source_observed_at=timezone.now() - timedelta(minutes=1),
        commission=Decimal("11.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    ).decode("utf-8")
    pending_body = _assert_json(
        _post_preview(
            client,
            ledger,
            idempotency_key=pending_key,
            payload=_preview_payload(
                ledger,
                csv_text=pending_csv,
                original_filename="old-policy-pending.csv",
            ),
        ),
        200,
    )
    pending_preview = cast(dict[str, object], pending_body["preview"])
    pending_locator = cast(str, pending_preview["source_locator"])
    assert pending_preview["expected_revision"] == 1
    assert pending_preview["expected_predecessor_id"] == original_event_id

    disabled = _write_policy_state(
        client,
        ledger,
        enabled=False,
        allow_operator_attested_upload=False,
        attestation_acknowledged=False,
    )
    reenabled = _write_policy_state(
        client,
        ledger,
        enabled=True,
        allow_operator_attested_upload=True,
        attestation_acknowledged=True,
    )
    assert disabled["version"] == 2
    assert reenabled["version"] == 3

    discovery = _assert_json(
        _get_recovery(client, _account_id(ledger), _trade_id(ledger)),
        200,
    )
    states = {
        cast(str, item["source_locator"]): item["state"] for item in _recovery_items(discovery)
    }
    assert states[ledger.request.source_locator] == "completed"
    assert states[pending_locator] == "fenced"

    old_pending = _assert_json(
        _post_recovery_preview(
            client,
            ledger,
            source_locator=pending_locator,
            transport_key=f"fenced-recovery-{uuid4().hex}",
        ),
        409,
    )
    assert old_pending["code"] == "FEE_CORRECTION_RECOVERY_FENCED"

    old_history = _assert_json(
        client.get(
            _recovery_head_url(
                _account_id(ledger),
                _trade_id(ledger),
                ledger.request.source_locator,
            ),
            HTTP_IDEMPOTENCY_KEY=f"unrelated-read-transport-{uuid4().hex}",
        ),
        200,
    )
    assert old_history["outcome"] == "success"
    old_head = cast(dict[str, object], old_history["head"])
    old_receipt = cast(dict[str, object], old_head["request_receipt"])
    assert old_receipt["event_id"] == original_event_id
    assert old_receipt["replayed"] is True

    fresh_key = f"new-policy-material-{uuid4().hex}"
    fresh_csv = _csv_bytes(
        account_id=_account_id(ledger),
        trade=ledger.trade,
        source_observed_at=timezone.now() - timedelta(minutes=1),
        commission=Decimal("12.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    ).decode("utf-8")
    fresh = _assert_json(
        _post_preview(
            client,
            ledger,
            idempotency_key=fresh_key,
            payload=_preview_payload(
                ledger,
                csv_text=fresh_csv,
                original_filename="new-policy-material.csv",
            ),
        ),
        200,
    )
    fresh_preview = cast(dict[str, object], fresh["preview"])
    assert fresh_preview["expected_revision"] == 1
    assert fresh_preview["expected_predecessor_id"] == original_event_id
    fresh_binding = FeeCorrectionEvidenceBindingModel.objects.get(
        account_id=_account_id(ledger),
        idempotency_key=fresh_key,
    )
    assert fresh_binding.policy_version == reenabled["version"]
    assert _event_count(ledger) == 1


def test_multiple_pending_locators_are_paged_and_never_implicitly_selected() -> None:
    """Pagination is display-only; recovery requires one explicit source locator."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    second = _create_legacy_pending_binding(
        ledger,
        idempotency_key=f"legacy-second-{uuid4().hex}",
    )
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    counts_before = _evidence_counts(ledger)

    first_page = _assert_json(
        _get_recovery(
            client,
            _account_id(ledger),
            _trade_id(ledger),
            query={"limit": "1"},
        ),
        200,
    )
    recovery = cast(dict[str, object], first_page["recovery"])
    first_items = _recovery_items(first_page)
    assert len(first_items) == 1
    assert recovery["has_more"] is True
    next_cursor = recovery.get("next_cursor")
    assert isinstance(next_cursor, str) and next_cursor

    second_page = _assert_json(
        _get_recovery(
            client,
            _account_id(ledger),
            _trade_id(ledger),
            query={"limit": "1", "cursor": next_cursor},
        ),
        200,
    )
    second_items = _recovery_items(second_page)
    assert len(second_items) == 1
    assert first_items[0]["source_locator"] != second_items[0]["source_locator"]
    assert {
        first_items[0]["source_locator"],
        second_items[0]["source_locator"],
    } == {ledger.request.source_locator, str(second.public_id)}

    no_selection = _assert_json(
        client.post(
            _preview_url(_account_id(ledger), _trade_id(ledger)),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"no-selection-{uuid4().hex}",
        ),
        400,
    )
    assert no_selection["success"] is False
    blocked_new_key = _assert_json(
        _post_upload(
            client,
            ledger,
            idempotency_key=f"page-limit-bypass-{uuid4().hex}",
        ),
        409,
    )
    assert blocked_new_key["code"] == "FEE_CORRECTION_RECOVERY_REQUIRED"
    assert _evidence_counts(ledger) == counts_before

    explicit = _assert_json(
        _post_recovery_preview(
            client,
            ledger,
            source_locator=str(second.public_id),
            transport_key=f"explicit-second-{uuid4().hex}",
        ),
        200,
    )
    explicit_preview = cast(dict[str, object], explicit["preview"])
    assert explicit_preview["source_locator"] == str(second.public_id)
    assert _evidence_counts(ledger) == counts_before
    assert _event_count(ledger) == 0


@pytest.mark.parametrize("damage", ["bytes", "future_binding_clock"])
def test_damaged_binding_is_unknown_not_fenced_after_policy_version_changes(damage: str) -> None:
    """A new policy version cannot fence evidence whose persisted bytes fail validation."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    _write_policy_state(
        client,
        ledger,
        enabled=False,
        allow_operator_attested_upload=False,
        attestation_acknowledged=False,
    )
    _write_policy_state(
        client,
        ledger,
        enabled=True,
        allow_operator_attested_upload=True,
        attestation_acknowledged=True,
    )
    binding = FeeCorrectionEvidenceBindingModel.objects.select_related("artifact").get(
        account_id=_account_id(ledger),
        idempotency_key=ledger.request.idempotency_key,
    )
    if damage == "bytes":
        _tamper_artifact_bytes(binding.artifact)
    else:
        table = connection.ops.quote_name(FeeCorrectionEvidenceBindingModel._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET created_at = %s WHERE id = %s",
                [timezone.now() + timedelta(days=2), binding.pk],
            )
            assert cursor.rowcount == 1
    counts_after_damage = _evidence_counts(ledger)

    discovery = _assert_json(
        _get_recovery(client, _account_id(ledger), _trade_id(ledger)),
        200,
    )
    item = _recovery_items(discovery)[0]
    assert item["state"] == "unknown"
    assert item["state"] != "fenced"

    invalid_source = _assert_json(
        _post_recovery_preview(
            client,
            ledger,
            source_locator=ledger.request.source_locator,
            transport_key=f"damaged-recovery-{uuid4().hex}",
        ),
        409,
    )
    assert invalid_source["code"] == "FEE_CORRECTION_RECOVERY_SOURCE_INVALID"
    blocked_new_key = _assert_json(
        _post_upload(
            client,
            ledger,
            idempotency_key=f"damaged-new-key-{uuid4().hex}",
        ),
        409,
    )
    assert blocked_new_key["code"] == "FEE_CORRECTION_RECOVERY_REQUIRED"
    assert _evidence_counts(ledger) == counts_after_damage
    assert _event_count(ledger) == 0


def test_locator_route_uses_url_identity_and_rejects_wrong_scope() -> None:
    """Locator reads ignore a transport header while legacy key/locator conflicts remain 409."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    owner_client = APIClient()
    owner_client.force_authenticate(user=ledger.owner)
    locator_url = _recovery_head_url(
        _account_id(ledger),
        _trade_id(ledger),
        ledger.request.source_locator,
    )

    located = _assert_json(
        owner_client.get(
            locator_url,
            HTTP_IDEMPOTENCY_KEY=f"read-transport-{uuid4().hex}",
        ),
        200,
    )
    assert located["outcome"] == "partial"
    located_head = cast(dict[str, object], located["head"])
    assert located_head["request_receipt"] is None

    legacy_conflict = _assert_json(
        owner_client.get(
            f"{_head_url(_account_id(ledger), _trade_id(ledger))}"
            f"?source_locator={ledger.request.source_locator}",
            HTTP_IDEMPOTENCY_KEY=f"wrong-legacy-key-{uuid4().hex}",
        ),
        409,
    )
    assert legacy_conflict["code"] == "FEE_CORRECTION_IDEMPOTENCY_CONFLICT"

    missing_locator = _assert_json(
        owner_client.get(_recovery_head_url(_account_id(ledger), _trade_id(ledger), str(uuid4()))),
        404,
    )
    assert missing_locator["code"] == "FEE_CORRECTION_EVIDENCE_NOT_FOUND"

    other_trade = _other_trade(ledger)
    wrong_trade = _assert_json(
        owner_client.get(
            _recovery_head_url(_account_id(ledger), other_trade.pk, ledger.request.source_locator)
        ),
        404,
    )
    assert wrong_trade["code"] == "FEE_CORRECTION_EVIDENCE_NOT_FOUND"

    wrong_account = _assert_json(
        owner_client.get(
            _recovery_head_url(
                _account_id(ledger) + 100_000, _trade_id(ledger), ledger.request.source_locator
            )
        ),
        403,
    )
    assert wrong_account["code"] == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"

    outsider = APIClient()
    outsider.force_authenticate(user=_create_unrelated_user())
    wrong_owner = _assert_json(
        _get_recovery(outsider, _account_id(ledger), _trade_id(ledger)),
        403,
    )
    assert wrong_owner["code"] == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"

    bad_preview_locator = _assert_json(
        owner_client.post(
            _preview_url(_account_id(ledger), _trade_id(ledger)),
            {"source_locator": "not-a-uuid"},
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"bad-locator-{uuid4().hex}",
        ),
        400,
    )
    assert bad_preview_locator["success"] is False


def test_recovery_preview_rejects_mixed_inputs_and_foreign_owner() -> None:
    """Recovery selects one stored locator and remains limited to its current owner."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    binding = FeeCorrectionEvidenceBindingModel.objects.select_related("artifact").get(
        account_id=_account_id(ledger),
        idempotency_key=ledger.request.idempotency_key,
    )
    counts_before = _evidence_counts(ledger)
    owner_client = APIClient()
    owner_client.force_authenticate(user=ledger.owner)
    mixed = _assert_json(
        owner_client.post(
            _preview_url(_account_id(ledger), _trade_id(ledger)),
            {
                "source_locator": ledger.request.source_locator,
                "original_filename": binding.artifact.original_filename,
                "csv_text": ledger.raw_evidence.decode("utf-8"),
                "attestation_acknowledged": True,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"mixed-recovery-{uuid4().hex}",
        ),
        400,
    )
    assert mixed["code"] == "VALIDATION_ERROR"
    assert "non_field_errors" in cast(dict[str, object], mixed["details"])

    foreign_client = APIClient()
    foreign_client.force_authenticate(user=_create_unrelated_user())
    foreign = _assert_json(
        _post_recovery_preview(
            foreign_client,
            ledger,
            source_locator=ledger.request.source_locator,
            transport_key=f"foreign-recovery-{uuid4().hex}",
        ),
        403,
    )
    assert foreign["success"] is False
    assert _evidence_counts(ledger) == counts_before
    assert _event_count(ledger) == 0


def test_capture_guard_checks_pending_material_beyond_the_visible_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A first page containing only fenced material cannot hide a pending tail row."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    for enabled in (False, True):
        _write_policy_state(
            client,
            ledger,
            enabled=enabled,
            allow_operator_attested_upload=enabled,
            attestation_acknowledged=enabled,
        )
    # Warm Django's cached default before overriding its public accessor. Changing
    # field.default alone leaves the cached UUID factory active in longer suites.
    # Both rows still use the real capture use case and immutable model saves.
    field = FeeCorrectionEvidenceBindingModel._meta.get_field("public_id")
    field.get_default()
    pending_locator = UUID(int=(1 << 128) - 1)
    monkeypatch.setattr(field, "get_default", lambda: pending_locator)
    pending_key = f"current-policy-{uuid4().hex}"
    _assert_json(
        _post_upload(client, ledger, idempotency_key=pending_key),
        200,
    )
    pending_binding = FeeCorrectionEvidenceBindingModel.objects.get(
        account_id=_account_id(ledger), idempotency_key=pending_key
    )
    assert pending_binding.public_id == pending_locator
    assert UUID(ledger.request.source_locator) < pending_binding.public_id
    first_page = _assert_json(
        _get_recovery(
            client,
            _account_id(ledger),
            _trade_id(ledger),
            query={"limit": "1"},
        ),
        200,
    )
    assert _recovery_items(first_page)[0]["state"] == "fenced"
    page = cast(dict[str, object], first_page["recovery"])
    assert page["has_more"] is True
    second_page = _assert_json(
        _get_recovery(
            client,
            _account_id(ledger),
            _trade_id(ledger),
            query={"limit": "1", "cursor": cast(str, page["next_cursor"])},
        ),
        200,
    )
    assert _recovery_items(second_page)[0]["state"] == "unresolved"
    blocked = _assert_json(
        _post_upload(client, ledger, idempotency_key=f"hidden-pending-{uuid4().hex}"),
        409,
    )
    assert blocked["code"] == "FEE_CORRECTION_RECOVERY_REQUIRED"
    assert _evidence_counts(ledger) == (2, 2)
    assert _event_count(ledger) == 0


@pytest.mark.parametrize("trade_state", ["missing", "unexecuted"])
def test_discovery_preserves_trade_not_found_status_and_has_no_writes(trade_state: str) -> None:
    """Discovery uses the existing head 422 contract instead of an empty successful page."""

    rows = _seed_ledger_without_evidence(
        commission=Decimal("7.00"), revised_commission=Decimal("9.00")
    )
    if trade_state == "unexecuted":
        rows.trade.status = "pending"
        rows.trade.save(update_fields=["status"])
        trade_id = rows.trade.pk
    else:
        trade_id = rows.trade.pk + 100_000
    client = APIClient()
    client.force_authenticate(user=rows.owner)
    financial_before = _rows_financial_snapshot(rows)
    body = _assert_json(_get_recovery(client, rows.account.pk, trade_id), 422)
    assert body["success"] is False
    assert body["code"] == "FEE_CORRECTION_TRADE_NOT_FOUND"
    assert "recovery" not in body
    assert _rows_evidence_counts(rows) == (0, 0)
    assert SimulatedFeeCorrectionEventModel.objects.filter(account_id=rows.account.pk).count() == 0
    assert _rows_financial_snapshot(rows) == financial_before
