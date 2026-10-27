"""Owner HTTP contracts for source-backed simulated fee corrections."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
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

from apps.account.infrastructure.account_authority_generation_models import (
    AccountAuthorityGenerationModel,
)
from apps.account.infrastructure.models import UserAccessTokenModel
from apps.simulated_trading.application.fee_correction_evidence_contracts import (
    MAX_UPLOAD_BYTES,
)
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidenceArtifactModel,
    FeeCorrectionEvidenceBindingModel,
    FeeCorrectionEvidencePolicyModel,
)
from tests.component.account.test_authentication import _create_profile
from tests.component.simulated_trading.test_fee_correction_evidence_repository import (
    EvidenceScenario,
    evidence_scenario,
)
from tests.component.simulated_trading.test_fee_correction_repository import (
    _csv_bytes,
    _LedgerFixture,
    _seed_ledger,
)

pytestmark = pytest.mark.django_db
__all__ = ["evidence_scenario"]


@pytest.fixture(autouse=True)
def seed_authority_generation_for_nomigrations_sqlite(
    db: None, django_db_use_migrations: bool
) -> None:
    """Mirror migration 0065's singleton seed only for SQLite no-migration tests."""

    if django_db_use_migrations or connection.vendor != "sqlite":
        return
    active_name = str(connection.settings_dict["NAME"])
    if active_name != connection.creation._get_test_db_name():
        raise RuntimeError("authority-generation test seed requires Django's isolated SQLite DB")
    AccountAuthorityGenerationModel.objects.using(connection.alias).get_or_create(
        singleton=1,
        defaults={"generation": 0},
    )


class _ExecutableUseCase(Protocol):
    """Minimal executable shape used to inject a post-commit connection loss."""

    def execute(self, *args: object, **kwargs: object) -> object: ...


def _upload_url(account_id: int, trade_id: int) -> str:
    """Return the owner-scoped immutable evidence upload endpoint."""

    return (
        f"/api/simulated-trading/accounts/{account_id}/trades/{trade_id}/"
        "fee-correction-evidence/"
    )


def _apply_url(account_id: int, trade_id: int) -> str:
    """Return the owner-scoped fee-correction application endpoint."""

    return f"/api/simulated-trading/accounts/{account_id}/trades/{trade_id}/" "fee-corrections/"


def _head_url(account_id: int, trade_id: int) -> str:
    """Return the read-only owner-scoped correction history head endpoint."""

    return _apply_url(account_id, trade_id) + "head/"


def _upload_payload(
    ledger: _LedgerFixture,
    *,
    idempotency_key: str,
    expected_revision: int = 0,
    expected_predecessor_id: int | None = None,
    csv_text: str | None = None,
    original_filename: str | None = None,
    **extra_fields: object,
) -> dict[str, object]:
    """Build the documented UTF-8 text upload body from the real ledger proof."""

    payload: dict[str, object] = {
        "expected_revision": expected_revision,
        "expected_predecessor_id": expected_predecessor_id,
        "original_filename": original_filename or f"{idempotency_key}.csv",
        "csv_text": (csv_text if csv_text is not None else ledger.raw_evidence.decode("utf-8")),
        "attestation_acknowledged": True,
    }
    payload.update(extra_fields)
    return payload


def _account_id(ledger: _LedgerFixture) -> int:
    """Return the fixture's persisted account ID as an exact integer."""

    return cast(int, ledger.account.pk)


def _trade_id(ledger: _LedgerFixture) -> int:
    """Return the fixture's persisted trade ID as an exact integer."""

    return cast(int, ledger.trade.pk)


def _assert_json(response: HttpResponse, expected_status: int) -> dict[str, object]:
    """Assert the stable JSON transport contract and return its object body."""

    response_text = response.content.decode("utf-8", errors="replace")
    assert (
        response.status_code == expected_status
    ), f"expected HTTP {expected_status}, got {response.status_code}: {response_text}"
    assert response.headers.get("Content-Type", "").split(";", maxsplit=1)[0] == (
        "application/json"
    )
    payload = response.json()
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _assert_sha256(value: object) -> None:
    """Require one exact lowercase SHA-256 digest in an API receipt."""

    assert isinstance(value, str)
    assert re.fullmatch(r"[0-9a-f]{64}", value)


def _financial_snapshot(ledger: _LedgerFixture) -> tuple[object, ...]:
    """Read financial state and immutable Trade facts without applying overlays."""

    ledger.account.refresh_from_db()
    ledger.position.refresh_from_db()
    ledger.trade.refresh_from_db()
    return (
        ledger.account.current_cash,
        ledger.account.current_market_value,
        ledger.account.total_value,
        ledger.position.quantity,
        ledger.position.total_cost,
        ledger.position.avg_cost,
        ledger.trade.commission,
        ledger.trade.transfer_fee,
        ledger.trade.stamp_duty,
        ledger.trade.slippage,
        ledger.trade.total_cost,
    )


def _evidence_counts(ledger: _LedgerFixture) -> tuple[int, int]:
    """Count immutable artifacts and bindings for this account."""

    return (
        FeeCorrectionEvidenceArtifactModel.objects.filter(account_id=_account_id(ledger)).count(),
        FeeCorrectionEvidenceBindingModel.objects.filter(account_id=_account_id(ledger)).count(),
    )


def _event_count(ledger: _LedgerFixture) -> int:
    """Count committed correction events for this exact account and trade."""

    return SimulatedFeeCorrectionEventModel.objects.filter(
        account_id=_account_id(ledger), trade_id=_trade_id(ledger)
    ).count()


def _api_idempotency_key(ledger: _LedgerFixture) -> str:
    """Create a stable HTTP idempotency key distinct from the seed upload."""

    return f"api-{ledger.request.idempotency_key}"


def _post_upload(
    client: APIClient,
    ledger: _LedgerFixture,
    *,
    idempotency_key: str,
    payload: dict[str, object] | None = None,
) -> HttpResponse:
    """Send the exact documented JSON text upload over the owner API."""

    body = payload or _upload_payload(ledger, idempotency_key=idempotency_key)
    return client.post(
        _upload_url(_account_id(ledger), _trade_id(ledger)),
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def _post_apply(
    client: APIClient,
    ledger: _LedgerFixture,
    *,
    idempotency_key: str,
    source_locator: str,
    expected_revision: int,
) -> HttpResponse:
    """Apply only the uploaded locator and the explicit expected revision."""

    return client.post(
        _apply_url(_account_id(ledger), _trade_id(ledger)),
        {"source_locator": source_locator, "expected_revision": expected_revision},
        format="json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def _upload_revision_one(
    client: APIClient,
    ledger: _LedgerFixture,
    *,
    idempotency_key: str,
    predecessor_id: int,
    commission: Decimal,
) -> dict[str, object]:
    """Upload a second real CSV revision tied to the first persisted event."""

    raw = _csv_bytes(
        account_id=_account_id(ledger),
        trade=ledger.trade,
        source_observed_at=timezone.now() - timedelta(minutes=1),
        commission=commission,
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    )
    response = _post_upload(
        client,
        ledger,
        idempotency_key=idempotency_key,
        payload=_upload_payload(
            ledger,
            idempotency_key=idempotency_key,
            expected_revision=1,
            expected_predecessor_id=predecessor_id,
            csv_text=raw.decode("utf-8"),
        ),
    )
    body = _assert_json(response, 200)
    evidence = body.get("evidence")
    assert isinstance(evidence, dict)
    assert isinstance(evidence.get("source_locator"), str)
    return cast(dict[str, object], evidence)


def test_owner_upload_apply_replay_and_head_use_one_stable_key() -> None:
    """POST upload then apply 7→9 once, without rewriting the original Trade."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    account_id = _account_id(ledger)
    trade_id = _trade_id(ledger)
    idempotency_key = _api_idempotency_key(ledger)
    before = _financial_snapshot(ledger)
    before_counts = _evidence_counts(ledger)

    initial_head = _assert_json(client.get(_head_url(account_id, trade_id)), 200)
    head = initial_head.get("head")
    assert isinstance(head, dict)
    assert head["account_id"] == account_id
    assert head["trade_id"] == trade_id
    assert head["revision"] == 0
    assert head["expected_predecessor_id"] is None
    assert _event_count(ledger) == 0

    upload_response = _post_upload(client, ledger, idempotency_key=idempotency_key)
    upload_body = _assert_json(upload_response, 200)
    assert upload_body["success"] is True
    evidence = upload_body.get("evidence")
    assert isinstance(evidence, dict)
    locator = evidence.get("source_locator")
    assert isinstance(locator, str)
    assert str(UUID(locator)) == locator
    _assert_sha256(evidence.get("content_sha256"))
    _assert_sha256(evidence.get("payload_sha256"))
    assert evidence.get("assurance_class") == "operator_attested_upload"
    stored_at = evidence.get("stored_at")
    assert isinstance(stored_at, str) and stored_at
    stored_datetime = datetime.fromisoformat(stored_at.replace("Z", "+00:00"))
    assert stored_datetime.tzinfo is not None
    assert _evidence_counts(ledger) == (before_counts[0] + 1, before_counts[1] + 1)
    assert _financial_snapshot(ledger) == before
    assert _event_count(ledger) == 0

    upload_replay = _assert_json(_post_upload(client, ledger, idempotency_key=idempotency_key), 200)
    assert upload_replay["evidence"]["source_locator"] == locator
    assert _evidence_counts(ledger) == (before_counts[0] + 1, before_counts[1] + 1)

    changed_content = _csv_bytes(
        account_id=account_id,
        trade=ledger.trade,
        source_observed_at=timezone.now() - timedelta(minutes=1),
        commission=Decimal("10.00"),
        transfer_fee=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
    ).decode("utf-8")
    conflicting_upload = _post_upload(
        client,
        ledger,
        idempotency_key=idempotency_key,
        payload=_upload_payload(
            ledger,
            idempotency_key=idempotency_key,
            csv_text=changed_content,
        ),
    )
    _assert_json(conflicting_upload, 409)
    assert _evidence_counts(ledger) == (before_counts[0] + 1, before_counts[1] + 1)

    apply_response = _post_apply(
        client,
        ledger,
        idempotency_key=idempotency_key,
        source_locator=locator,
        expected_revision=0,
    )
    apply_body = _assert_json(apply_response, 200)
    assert apply_body["success"] is True
    receipt = apply_body.get("receipt")
    assert isinstance(receipt, dict)
    event_id = receipt.get("event_id")
    assert type(event_id) is int
    assert receipt["account_id"] == account_id
    assert receipt["trade_id"] == trade_id
    assert receipt["revision"] == 1
    assert receipt["replayed"] is False
    _assert_sha256(receipt.get("payload_hash"))
    assert _event_count(ledger) == 1
    assert _financial_snapshot(ledger) != before
    ledger.account.refresh_from_db()
    ledger.position.refresh_from_db()
    ledger.trade.refresh_from_db()
    assert ledger.account.current_cash == Decimal("8990.98")
    assert ledger.account.total_value == Decimal("9990.98")
    assert ledger.position.total_cost == Decimal("1009.02")
    assert ledger.position.avg_cost == Decimal("10.0902")
    assert (
        ledger.trade.commission,
        ledger.trade.transfer_fee,
        ledger.trade.stamp_duty,
        ledger.trade.slippage,
        ledger.trade.total_cost,
    ) == (
        Decimal("7.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.02"),
        Decimal("1007.02"),
    )

    replay_body = _assert_json(
        _post_apply(
            client,
            ledger,
            idempotency_key=idempotency_key,
            source_locator=locator,
            expected_revision=0,
        ),
        200,
    )
    assert replay_body["receipt"]["event_id"] == event_id
    assert replay_body["receipt"]["replayed"] is True
    assert _event_count(ledger) == 1
    assert ledger.account.current_cash == Decimal("8990.98")

    head_after_apply = _assert_json(client.get(_head_url(account_id, trade_id)), 200)
    current_head = head_after_apply.get("head")
    assert isinstance(current_head, dict)
    assert current_head["revision"] == 1
    assert current_head["expected_predecessor_id"] == event_id
    assert _event_count(ledger) == 1


def test_head_revision_one_upload_and_refund_preserve_predecessor_chain() -> None:
    """A revision-1 upload bound to head event refunds 9→7 exactly once."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    account_id = _account_id(ledger)
    trade_id = _trade_id(ledger)
    first_key = _api_idempotency_key(ledger)
    first_upload = _assert_json(_post_upload(client, ledger, idempotency_key=first_key), 200)
    first_evidence = cast(dict[str, object], first_upload["evidence"])
    first_locator = cast(str, first_evidence["source_locator"])
    first_apply = _assert_json(
        _post_apply(
            client,
            ledger,
            idempotency_key=first_key,
            source_locator=first_locator,
            expected_revision=0,
        ),
        200,
    )
    first_receipt = cast(dict[str, object], first_apply["receipt"])
    first_event_id = cast(int, first_receipt["event_id"])
    ledger.account.refresh_from_db()
    assert ledger.account.current_cash == Decimal("8990.98")

    second_key = f"{first_key}-revision-1"
    second_evidence = _upload_revision_one(
        client,
        ledger,
        idempotency_key=second_key,
        predecessor_id=first_event_id,
        commission=Decimal("7.00"),
    )
    second_locator = cast(str, second_evidence["source_locator"])
    second_apply = _assert_json(
        _post_apply(
            client,
            ledger,
            idempotency_key=second_key,
            source_locator=second_locator,
            expected_revision=1,
        ),
        200,
    )
    second_receipt = cast(dict[str, object], second_apply["receipt"])
    second_event_id = cast(int, second_receipt["event_id"])
    assert second_receipt["revision"] == 2
    assert second_receipt["replayed"] is False
    ledger.account.refresh_from_db()
    ledger.position.refresh_from_db()
    assert ledger.account.current_cash == Decimal("8992.98")
    assert ledger.position.total_cost == Decimal("1007.02")
    assert _event_count(ledger) == 2

    events = list(
        SimulatedFeeCorrectionEventModel.objects.filter(
            account_id=account_id, trade_id=trade_id
        ).order_by("revision")
    )
    assert [event.revision for event in events] == [1, 2]
    assert [event.previous_event_id for event in events] == [None, first_event_id]
    assert [event.total_fee_delta for event in events] == [
        Decimal("2.00"),
        Decimal("-2.00"),
    ]
    head_body = _assert_json(client.get(_head_url(account_id, trade_id)), 200)
    head = cast(dict[str, object], head_body["head"])
    assert head["revision"] == 2
    assert head["expected_predecessor_id"] == second_event_id
    assert _event_count(ledger) == 2
    ledger.trade.refresh_from_db()
    assert ledger.trade.commission == Decimal("7.00")
    assert ledger.trade.slippage == Decimal("0.02")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("original_filename", "../unsafe.csv"),
        ("attestation_acknowledged", False),
        ("attestation_acknowledged", "true"),
        ("expected_revision", 0.0),
        ("actor_user_id", 123),
    ],
)
def test_invalid_upload_body_is_json_400_without_writes(
    field: str,
    value: object,
) -> None:
    """Reject malformed file metadata and actor assertions before persistence."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    key = f"invalid-{_api_idempotency_key(ledger)}-{field}"
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    response = _post_upload(
        client,
        ledger,
        idempotency_key=key,
        payload=_upload_payload(
            ledger,
            idempotency_key=key,
            **{field: value},
        ),
    )

    _assert_json(response, 400)
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


def test_upload_over_one_mib_is_rejected_without_writes() -> None:
    """Enforce the application upload byte limit on the UTF-8 JSON field."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    key = f"oversize-{_api_idempotency_key(ledger)}"
    oversized_text = "x" * (MAX_UPLOAD_BYTES + 1)
    assert len(oversized_text.encode("utf-8")) > MAX_UPLOAD_BYTES
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    response = _post_upload(
        client,
        ledger,
        idempotency_key=key,
        payload=_upload_payload(
            ledger,
            idempotency_key=key,
            csv_text=oversized_text,
        ),
    )

    _assert_json(response, 400)
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


def test_missing_policy_blocks_upload_for_legacy_account_without_policy(
    evidence_scenario: EvidenceScenario,
) -> None:
    """A legacy account with no policy cannot store owner-attested evidence."""

    scenario = evidence_scenario
    account_id = cast(int, scenario.other_account.pk)
    trade_id = cast(int, scenario.other_trade.pk)
    assert not FeeCorrectionEvidencePolicyModel.objects.filter(account_id=account_id).exists()
    client = APIClient()
    client.force_authenticate(user=scenario.owner)
    key = "missing-policy-http-upload"
    raw = _csv_bytes(
        account_id=account_id,
        trade=scenario.other_trade,
        source_observed_at=timezone.now() - timedelta(minutes=1),
        commission=Decimal("4.00"),
        transfer_fee=Decimal("0.10"),
        stamp_duty=Decimal("0.00"),
    )
    before_account = scenario.other_account.current_cash
    before_events = SimulatedFeeCorrectionEventModel.objects.filter(account_id=account_id).count()

    response = client.post(
        _upload_url(account_id, trade_id),
        {
            "expected_revision": 0,
            "expected_predecessor_id": None,
            "original_filename": "missing-policy.csv",
            "csv_text": raw.decode("utf-8"),
            "attestation_acknowledged": True,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )

    _assert_json(response, 422)
    assert not FeeCorrectionEvidenceArtifactModel.objects.filter(account_id=account_id).exists()
    assert not FeeCorrectionEvidenceBindingModel.objects.filter(account_id=account_id).exists()
    assert (
        SimulatedFeeCorrectionEventModel.objects.filter(account_id=account_id).count()
        == before_events
    )
    scenario.other_account.refresh_from_db()
    assert scenario.other_account.current_cash == before_account


def test_disabled_policy_blocks_upload_and_apply_without_financial_writes() -> None:
    """An enabled-policy snapshot cannot authorize a later disabled-policy write."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    policy = FeeCorrectionEvidencePolicyModel.objects.get(account_id=_account_id(ledger))
    policy.enabled = False
    policy.save(update_fields=("enabled",))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    key = f"disabled-{_api_idempotency_key(ledger)}"
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    upload = _post_upload(client, ledger, idempotency_key=key)
    _assert_json(upload, 422)
    apply = _post_apply(
        client,
        ledger,
        idempotency_key=ledger.request.idempotency_key,
        source_locator=ledger.request.source_locator,
        expected_revision=0,
    )
    _assert_json(apply, 422)
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


def test_readonly_token_cannot_upload_or_apply() -> None:
    """Read-only API credentials may not create evidence or post fee events."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    _create_profile(ledger.owner)
    _token_id, token = UserAccessTokenModel.create_token(
        user=ledger.owner,
        name="fee-correction-read-only",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    key = f"readonly-{_api_idempotency_key(ledger)}"
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    head_body = _assert_json(client.get(_head_url(_account_id(ledger), _trade_id(ledger))), 200)
    assert head_body["head"]["revision"] == 0

    upload = _post_upload(client, ledger, idempotency_key=key)
    _assert_json(upload, 403)
    apply = _post_apply(
        client,
        ledger,
        idempotency_key=ledger.request.idempotency_key,
        source_locator=ledger.request.source_locator,
        expected_revision=0,
    )
    _assert_json(apply, 403)
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


def test_readwrite_token_can_upload_and_apply_over_real_http_authentication() -> None:
    """A real write-scoped API token can submit evidence and post one correction."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    _create_profile(ledger.owner)
    _token_id, token = UserAccessTokenModel.create_token(
        user=ledger.owner,
        name="fee-correction-read-write",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_WRITE,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    key = f"read-write-{_api_idempotency_key(ledger)}"

    upload_body = _assert_json(_post_upload(client, ledger, idempotency_key=key), 200)
    evidence = cast(dict[str, object], upload_body["evidence"])
    locator = cast(str, evidence["source_locator"])
    apply_body = _assert_json(
        _post_apply(
            client,
            ledger,
            idempotency_key=key,
            source_locator=locator,
            expected_revision=0,
        ),
        200,
    )

    receipt = cast(dict[str, object], apply_body["receipt"])
    assert receipt["revision"] == 1
    assert receipt["replayed"] is False
    assert _event_count(ledger) == 1
    ledger.account.refresh_from_db()
    assert ledger.account.current_cash == Decimal("8990.98")


@pytest.mark.parametrize("operation", ["upload", "apply"])
def test_anonymous_and_session_without_csrf_cannot_write(
    operation: str,
) -> None:
    """Both POST routes reject anonymous calls and session writes without CSRF."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    key = f"csrf-{operation}-{_api_idempotency_key(ledger)}"
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    def post(client: APIClient) -> HttpResponse:
        if operation == "upload":
            return _post_upload(client, ledger, idempotency_key=key)
        return _post_apply(
            client,
            ledger,
            idempotency_key=key,
            source_locator=str(uuid4()),
            expected_revision=0,
        )

    anonymous_client = APIClient(enforce_csrf_checks=True)
    _assert_json(post(anonymous_client), 403)

    session_client = APIClient(enforce_csrf_checks=True)
    session_client.force_login(ledger.owner)
    _assert_json(post(session_client), 403)

    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


@pytest.mark.parametrize("superuser", [False, True])
def test_foreign_owner_and_superuser_cannot_read_upload_or_apply(
    superuser: bool,
) -> None:
    """Neither a foreign user nor an unrelated superuser inherits account authority."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    other_user = get_user_model().objects.create_user(
        username=f"foreign-fee-correction-{uuid4().hex}", password="unused"
    )
    if superuser:
        other_user.is_staff = True
        other_user.is_superuser = True
        other_user.save(update_fields=("is_staff", "is_superuser"))
    client = APIClient()
    client.force_authenticate(user=other_user)
    key = f"foreign-{_api_idempotency_key(ledger)}"
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    head = client.get(_head_url(_account_id(ledger), _trade_id(ledger)))
    _assert_json(head, 403)
    _assert_json(_post_upload(client, ledger, idempotency_key=key), 403)
    _assert_json(
        _post_apply(
            client,
            ledger,
            idempotency_key=ledger.request.idempotency_key,
            source_locator=ledger.request.source_locator,
            expected_revision=0,
        ),
        403,
    )
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


def test_unknown_locator_and_stale_revision_do_not_write_financial_events() -> None:
    """Unknown evidence and stale heads fail closed before any cash posting."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    unknown_locator = str(uuid4())
    unknown = _post_apply(
        client,
        ledger,
        idempotency_key=f"unknown-{_api_idempotency_key(ledger)}",
        source_locator=unknown_locator,
        expected_revision=0,
    )
    _assert_json(unknown, 422)
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0

    key = _api_idempotency_key(ledger)
    evidence_body = _assert_json(_post_upload(client, ledger, idempotency_key=key), 200)
    evidence = cast(dict[str, object], evidence_body["evidence"])
    locator = cast(str, evidence["source_locator"])
    first = _assert_json(
        _post_apply(
            client,
            ledger,
            idempotency_key=key,
            source_locator=locator,
            expected_revision=0,
        ),
        200,
    )
    assert first["receipt"]["revision"] == 1
    after_first = _financial_snapshot(ledger)
    after_counts = _evidence_counts(ledger)

    stale = _post_apply(
        client,
        ledger,
        idempotency_key=f"stale-{key}",
        source_locator=locator,
        expected_revision=0,
    )
    _assert_json(stale, 409)
    assert _financial_snapshot(ledger) == after_first
    assert _evidence_counts(ledger) == after_counts
    assert _event_count(ledger) == 1


@pytest.mark.parametrize(
    ("operation", "write_builder_name"),
    [
        ("upload", "build_fee_correction_evidence_upload_use_case"),
        ("apply", "build_apply_simulated_fee_correction_use_case"),
    ],
)
def test_policy_preflight_database_error_is_read_unavailable_without_writes(
    operation: str,
    write_builder_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed owner/policy read is not misreported as an uncertain write."""

    from apps.simulated_trading.interface import fee_correction_views

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    key = f"policy-read-unavailable-{operation}-{_api_idempotency_key(ledger)}"
    before_financial = _financial_snapshot(ledger)
    before_evidence = _evidence_counts(ledger)

    policy_use_case = Mock()
    policy_use_case.get.side_effect = OperationalError("simulated policy read outage")
    monkeypatch.setattr(
        fee_correction_views,
        "build_fee_correction_policy_use_case",
        Mock(return_value=policy_use_case),
    )
    write_builder = Mock()
    monkeypatch.setattr(fee_correction_views, write_builder_name, write_builder)

    if operation == "upload":
        response = _post_upload(client, ledger, idempotency_key=key)
    else:
        response = _post_apply(
            client,
            ledger,
            idempotency_key=key,
            source_locator=str(uuid4()),
            expected_revision=0,
        )

    body = _assert_json(response, 503)
    assert body["code"] == "FEE_CORRECTION_READ_UNAVAILABLE"
    assert body.get("effects_indeterminate") is not True
    assert body.get("recovery_required") is not True
    write_builder.assert_not_called()
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_evidence
    assert _event_count(ledger) == 0


@pytest.mark.django_db(transaction=True)
def test_database_commit_uncertainty_returns_recovery_contract_and_head_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A committed write followed by connection loss is reported as indeterminate."""

    from apps.simulated_trading.interface import fee_correction_views

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    key = _api_idempotency_key(ledger)
    evidence_body = _assert_json(_post_upload(client, ledger, idempotency_key=key), 200)
    locator = cast(str, cast(dict[str, object], evidence_body["evidence"])["source_locator"])
    real_builder = fee_correction_views.build_apply_simulated_fee_correction_use_case

    class _CommitThenDisconnect:
        """Run the real use case, then model a lost response after its commit."""

        def __init__(self, use_case: object) -> None:
            self._use_case = cast(_ExecutableUseCase, use_case)

        def execute(self, *args: object, **kwargs: object) -> object:
            self._use_case.execute(*args, **kwargs)
            raise OperationalError("simulated lost database acknowledgement")

    monkeypatch.setattr(
        fee_correction_views,
        "build_apply_simulated_fee_correction_use_case",
        lambda *args, **kwargs: _CommitThenDisconnect(real_builder(*args, **kwargs)),
    )
    response = _post_apply(
        client,
        ledger,
        idempotency_key=key,
        source_locator=locator,
        expected_revision=0,
    )
    body = _assert_json(response, 503)
    assert body["effects_indeterminate"] is True
    assert body["recovery_required"] is True
    assert _event_count(ledger) == 1
    ledger.account.refresh_from_db()
    assert ledger.account.current_cash == Decimal("8990.98")

    readback = client.get(
        _head_url(_account_id(ledger), _trade_id(ledger)),
        HTTP_IDEMPOTENCY_KEY=key,
    )
    readback_body = _assert_json(readback, 200)
    head = cast(dict[str, object], readback_body["head"])
    request_receipt = head.get("request_receipt")
    assert isinstance(request_receipt, dict)
    assert request_receipt["replayed"] is True
    assert request_receipt["revision"] == 1
    assert _event_count(ledger) == 1
    assert ledger.account.current_cash == Decimal("8990.98")


def test_apply_cannot_replace_the_upload_request_key() -> None:
    """An uploaded source remains bound to its original operation identity."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client = APIClient()
    client.force_authenticate(user=ledger.owner)
    key = _api_idempotency_key(ledger)
    upload = _assert_json(_post_upload(client, ledger, idempotency_key=key), 200)
    locator = cast(str, cast(dict[str, object], upload["evidence"])["source_locator"])
    before = _financial_snapshot(ledger)
    response = _post_apply(
        client,
        ledger,
        idempotency_key=f"replacement-{key}",
        source_locator=locator,
        expected_revision=0,
    )
    _assert_json(response, 409)
    assert _financial_snapshot(ledger) == before
    assert _event_count(ledger) == 0
