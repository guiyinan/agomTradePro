"""Session-bound HTTP confirmation contracts for simulated fee corrections."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.sessions.models import Session
from django.http import HttpResponse
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.account.infrastructure.models import UserAccessTokenModel
from apps.simulated_trading.application.fee_correction import FeeCorrectionRequest
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel
from shared.config.secrets import clear_secrets_cache, get_secrets
from shared.infrastructure.crypto import FieldEncryptionService
from tests.api.test_fee_correction_flow_api import (
    _account_id,
    _assert_json,
    _event_count,
    _evidence_counts,
    _financial_snapshot,
    _head_url,
    _LedgerFixture,
    _seed_ledger,
    _trade_id,
    seed_authority_generation_for_nomigrations_sqlite,
)
from tests.api.test_fee_correction_preview_api import (
    _post_preview,
    _preview_key,
    _preview_payload,
    _preview_url,
)
from tests.component.account.test_authentication import _create_profile

pytestmark = pytest.mark.django_db
__all__ = ["seed_authority_generation_for_nomigrations_sqlite"]

_ORIGIN = "https://testserver"


@pytest.fixture(autouse=True)
def _test_field_encryption_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Use only a generated test key through the application's secret provider."""

    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", FieldEncryptionService.generate_key())
    clear_secrets_cache()
    assert get_secrets(require_tushare_token=False).field_encryption_key
    yield
    clear_secrets_cache()


def _session_user_client(user: AbstractBaseUser) -> tuple[APIClient, str]:
    """Create one real Django user session with a real admin-login CSRF cookie."""

    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    csrf_response = client.get(
        reverse("admin:login"), secure=True, HTTP_ORIGIN=_ORIGIN, follow=True
    )
    assert csrf_response.status_code == 200
    assert csrf_response["Content-Type"].startswith("text/html")
    csrf_cookie = client.cookies.get(settings.CSRF_COOKIE_NAME)
    assert csrf_cookie is not None
    return client, csrf_cookie.value


def _session_owner_client(ledger: _LedgerFixture) -> tuple[APIClient, str]:
    """Create a real owner session and its CSRF cookie."""

    return _session_user_client(ledger.owner)


def _session_key(client: APIClient) -> str:
    """Return the exact authenticated Django session key stored by this client."""

    value = client.cookies.get(settings.SESSION_COOKIE_NAME)
    assert value is not None and value.value
    return value.value


def _post_session_preview(
    client: APIClient,
    ledger: _LedgerFixture,
    *,
    csrf_token: str | None,
    key: str,
) -> HttpResponse:
    """Issue preview over SessionAuthentication with same-origin CSRF headers."""

    return cast(
        HttpResponse,
        client.post(
            _preview_url(_account_id(ledger), _trade_id(ledger)),
            _preview_payload(ledger),
            format="json",
            secure=True,
            HTTP_ORIGIN=_ORIGIN,
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_IDEMPOTENCY_KEY=key,
        ),
    )


def _post_confirmation(
    client: APIClient,
    ledger: _LedgerFixture,
    *,
    csrf_token: str | None,
    key: str,
    confirmation_token: str,
    account_id: int | None = None,
    trade_id: int | None = None,
) -> HttpResponse:
    """Submit only the encrypted confirmation token under the preview's key."""

    headers: dict[str, str] = {
        "HTTP_ORIGIN": _ORIGIN,
        "HTTP_IDEMPOTENCY_KEY": key,
    }
    if csrf_token is not None:
        headers["HTTP_X_CSRFTOKEN"] = csrf_token
    return cast(
        HttpResponse,
        client.post(
            _confirm_url(
                account_id if account_id is not None else _account_id(ledger),
                trade_id if trade_id is not None else _trade_id(ledger),
            ),
            {"confirmation_token": confirmation_token},
            format="json",
            secure=True,
            **headers,
        ),
    )


def _other_trade(ledger: _LedgerFixture) -> SimulatedTradeModel:
    """Create a second persisted Trade under the same owner account."""

    other = SimulatedTradeModel.objects.get(pk=_trade_id(ledger))
    other.pk = None
    other.asset_code = "000001.SZ"
    other.asset_name = "Different confirmation Trade"
    other.save(force_insert=True)
    assert type(other.pk) is int and other.pk != _trade_id(ledger)
    return other


def _create_unrelated_user(*, superuser: bool = False) -> AbstractBaseUser:
    """Create a distinct authenticated account principal for denial coverage."""

    user_model = get_user_model()
    username = f"fee-confirm-{uuid4().hex[:12]}"
    manager = user_model.objects
    if superuser:
        user = manager.create_superuser(username=username, password="unused")
    else:
        user = manager.create_user(username=username, password="unused")
    return cast(AbstractBaseUser, user)


def _confirm_url(account_id: int, trade_id: int) -> str:
    """Return the one-shot owner confirmation route."""

    return (
        f"/api/simulated-trading/accounts/{account_id}/trades/{trade_id}/"
        "fee-corrections/confirm/"
    )


def _confirmation_token(body: dict[str, object], ledger: _LedgerFixture) -> str:
    """Validate the owner-only continuation created by a session preview."""

    assert body["success"] is True
    assert body["outcome"] == "success"
    assert body["status"] == "preview"
    continuation = body.get("continuation")
    assert isinstance(continuation, dict)
    assert set(continuation) == {"action_key", "input", "expires_at"}
    assert continuation["action_key"] == "simulated-trading.fee-correction-confirm"
    token_input = continuation.get("input")
    assert isinstance(token_input, dict)
    assert set(token_input) == {"account_id", "trade_id", "confirmation_token"}
    assert token_input["account_id"] == str(_account_id(ledger))
    assert token_input["trade_id"] == str(_trade_id(ledger))
    token = token_input.get("confirmation_token")
    assert isinstance(token, str) and token.startswith(FieldEncryptionService.PREFIX)
    expires_at = continuation.get("expires_at")
    assert isinstance(expires_at, str) and expires_at
    parsed_expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    assert parsed_expiry.tzinfo is not None and parsed_expiry.utcoffset() == timedelta(0)
    preview = body.get("preview")
    assert isinstance(preview, dict)
    assert token not in str(preview)
    return token


def test_session_preview_issues_private_confirmation_continuation() -> None:
    """A real owner session receives the exact opaque continuation and CSRF is required."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client, csrf_token = _session_owner_client(ledger)
    key = _preview_key(ledger, "-session-confirm")

    response = _post_session_preview(client, ledger, csrf_token=csrf_token, key=key)

    body = _assert_json(response, 200)
    _confirmation_token(body, ledger)
    assert _evidence_counts(ledger)[1] == 2
    assert (
        SimulatedFeeCorrectionEventModel.objects.filter(
            account_id=_account_id(ledger), trade_id=_trade_id(ledger)
        ).count()
        == 0
    )


def test_confirmation_route_rejects_a_malformed_token_for_a_real_session() -> None:
    """The session-only confirmation route must exist and reject malformed tokens."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client, csrf_token = _session_owner_client(ledger)
    before_financial = _financial_snapshot(ledger)
    before_counts = _evidence_counts(ledger)

    response = _post_confirmation(
        client,
        ledger,
        csrf_token=csrf_token,
        key=f"unused-{_preview_key(ledger)}",
        confirmation_token=f"{FieldEncryptionService.PREFIX}malformed-test-token",
    )

    body = _assert_json(response, 400)
    assert isinstance(body.get("code"), str) and body["code"]
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_counts
    assert (
        SimulatedFeeCorrectionEventModel.objects.filter(
            account_id=_account_id(ledger), trade_id=_trade_id(ledger)
        ).count()
        == 0
    )


@override_settings(SESSION_COOKIE_AGE=60)
def test_session_confirmation_posts_only_the_previewed_delta_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session confirmation applies exactly 7→9 once and preserves the Trade row."""

    from apps.simulated_trading.infrastructure import fee_correction_confirmation_repository

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client, csrf_token = _session_owner_client(ledger)
    session = Session.objects.get(session_key=_session_key(client))
    session.expire_date = timezone.now() + timedelta(days=2)
    session.save(update_fields=("expire_date",))
    key = _preview_key(ledger, "-session-confirm")
    before = _financial_snapshot(ledger)
    before_counts = _evidence_counts(ledger)
    preview_body = _assert_json(
        _post_session_preview(client, ledger, csrf_token=csrf_token, key=key),
        200,
    )
    token = _confirmation_token(preview_body, ledger)
    continuation = cast(dict[str, object], preview_body["continuation"])
    token_expires_at = datetime.fromisoformat(
        cast(str, continuation["expires_at"]).replace("Z", "+00:00")
    )
    pending_read = _assert_json(
        client.get(
            _head_url(_account_id(ledger), _trade_id(ledger)),
            secure=True,
            HTTP_ORIGIN=_ORIGIN,
            HTTP_IDEMPOTENCY_KEY=key,
        ),
        200,
    )
    assert pending_read["outcome"] == "partial"
    pending_head = cast(dict[str, object], pending_read["head"])
    assert pending_head.get("request_receipt") is None

    response = _post_confirmation(
        client,
        ledger,
        csrf_token=csrf_token,
        key=key,
        confirmation_token=token,
    )

    body = _assert_json(response, 200)
    assert body["success"] is True
    receipt = body.get("receipt")
    assert isinstance(receipt, dict)
    assert receipt["account_id"] == _account_id(ledger)
    assert receipt["trade_id"] == _trade_id(ledger)
    assert receipt["revision"] == 1
    assert receipt["replayed"] is False
    assert _evidence_counts(ledger) == (before_counts[0] + 1, before_counts[1] + 1)
    assert _financial_snapshot(ledger) != before
    ledger.account.refresh_from_db()
    ledger.trade.refresh_from_db()
    assert ledger.account.current_cash == Decimal("8990.98")
    assert ledger.trade.commission == Decimal("7.00")
    assert ledger.trade.slippage == Decimal("0.02")
    after_first_confirmation = _financial_snapshot(ledger)
    assert (
        SimulatedFeeCorrectionEventModel.objects.filter(
            account_id=_account_id(ledger), trade_id=_trade_id(ledger)
        ).count()
        == 1
    )

    replay = _assert_json(
        _post_confirmation(
            client,
            ledger,
            csrf_token=csrf_token,
            key=key,
            confirmation_token=token,
        ),
        200,
    )
    replay_receipt = cast(dict[str, object], replay["receipt"])
    assert replay_receipt["event_id"] == receipt["event_id"]
    assert replay_receipt["replayed"] is True
    assert _financial_snapshot(ledger) == after_first_confirmation
    assert (
        SimulatedFeeCorrectionEventModel.objects.filter(
            account_id=_account_id(ledger), trade_id=_trade_id(ledger)
        ).count()
        == 1
    )

    monkeypatch.setattr(
        fee_correction_confirmation_repository.timezone,
        "now",
        lambda: token_expires_at + timedelta(seconds=1),
    )
    recovered = _assert_json(
        client.get(
            _head_url(_account_id(ledger), _trade_id(ledger)),
            secure=True,
            HTTP_ORIGIN=_ORIGIN,
            HTTP_IDEMPOTENCY_KEY=key,
        ),
        200,
    )
    assert recovered["outcome"] == "success"
    head = cast(dict[str, object], recovered["head"])
    receipt_readback = head.get("request_receipt")
    assert isinstance(receipt_readback, dict)
    assert receipt_readback["event_id"] == receipt["event_id"]
    assert receipt_readback["replayed"] is True

    policy = FeeCorrectionEvidencePolicyModel.objects.get(account_id=_account_id(ledger))
    policy.enabled = False
    policy.save(update_fields=("enabled",))
    completed_preview_retry = _assert_json(
        _post_session_preview(client, ledger, csrf_token=csrf_token, key=key),
        200,
    )
    assert completed_preview_retry["outcome"] == "noop"
    assert completed_preview_retry["status"] == "already_applied"
    assert completed_preview_retry.get("continuation") is None
    completed_receipt = cast(dict[str, object], completed_preview_retry["receipt"])
    assert completed_receipt["event_id"] == receipt["event_id"]
    assert _financial_snapshot(ledger) == after_first_confirmation
    assert _evidence_counts(ledger) == (before_counts[0] + 1, before_counts[1] + 1)
    assert (
        SimulatedFeeCorrectionEventModel.objects.filter(
            account_id=_account_id(ledger), trade_id=_trade_id(ledger)
        ).count()
        == 1
    )


def test_legacy_force_authenticated_and_write_token_previews_have_no_continuation() -> None:
    """Only a real browser session receives the new confirmation action."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    force_client = APIClient()
    force_client.force_authenticate(user=ledger.owner)
    forced = _assert_json(
        _post_preview(force_client, ledger, idempotency_key=_preview_key(ledger, "-force")),
        200,
    )
    assert forced["outcome"] == "success"
    assert forced.get("continuation") is None

    _create_profile(ledger.owner)
    _token_id, token = UserAccessTokenModel.create_token(
        user=ledger.owner,
        name="fee-correction-confirmation-token-preview",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_WRITE,
    )
    token_client = APIClient()
    token_client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    token_preview = _assert_json(
        _post_preview(
            token_client,
            ledger,
            idempotency_key=_preview_key(ledger, "-token"),
        ),
        200,
    )
    assert token_preview["outcome"] == "success"
    assert token_preview.get("continuation") is None


def test_same_key_session_preview_retry_does_not_refresh_confirmation_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated preview uses the saved material time, not a fresh lifetime window."""

    from apps.simulated_trading.infrastructure import fee_correction_confirmation_repository

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    with override_settings(SESSION_COOKIE_AGE=3600):
        client, csrf_token = _session_owner_client(ledger)
        key = f"session-{_preview_key(ledger, '-no-refresh')}"
        session = Session.objects.get(session_key=_session_key(client))
        session.expire_date = timezone.now() + timedelta(minutes=10)
        session.save(update_fields=("expire_date",))

        first = _assert_json(
            _post_session_preview(client, ledger, csrf_token=csrf_token, key=key),
            200,
        )
        first_continuation = cast(dict[str, object], first["continuation"])
        first_preview = cast(dict[str, object], first["preview"])
        first_expiry = datetime.fromisoformat(
            cast(str, first_continuation["expires_at"]).replace("Z", "+00:00")
        )
        first_stored_at = datetime.fromisoformat(
            cast(str, first_preview["stored_at"]).replace("Z", "+00:00")
        )
        assert first_expiry == first_stored_at + timedelta(seconds=3600)

        # Session renewal does not extend a confirmation window already issued.
        session.expire_date = timezone.now() + timedelta(days=2)
        session.save(update_fields=("expire_date",))

        current_time = timezone.now()
        monkeypatch.setattr(
            fee_correction_confirmation_repository.timezone,
            "now",
            lambda: current_time + timedelta(minutes=5),
        )
        replay = _assert_json(
            _post_session_preview(client, ledger, csrf_token=csrf_token, key=key),
            200,
        )
        replay_continuation = cast(dict[str, object], replay["continuation"])
        replay_expiry = datetime.fromisoformat(
            cast(str, replay_continuation["expires_at"]).replace("Z", "+00:00")
        )
        assert replay_expiry == first_expiry
        assert _evidence_counts(ledger) == (2, 2)
        assert (
            SimulatedFeeCorrectionEventModel.objects.filter(
                account_id=_account_id(ledger), trade_id=_trade_id(ledger)
            ).count()
            == 0
        )


def test_expired_confirmation_is_rejected_but_original_key_head_is_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expiry blocks the write without turning an unreadable result into a failure claim."""

    from apps.simulated_trading.infrastructure import fee_correction_confirmation_repository

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    with override_settings(SESSION_COOKIE_AGE=60):
        client, csrf_token = _session_owner_client(ledger)
        session = Session.objects.get(session_key=_session_key(client))
        session.expire_date = timezone.now() + timedelta(days=2)
        session.save(update_fields=("expire_date",))
        key = f"session-{_preview_key(ledger, '-expired') }"
        preview = _assert_json(
            _post_session_preview(client, ledger, csrf_token=csrf_token, key=key),
            200,
        )
        token = _confirmation_token(preview, ledger)
        continuation = cast(dict[str, object], preview["continuation"])
        expires_at = datetime.fromisoformat(
            cast(str, continuation["expires_at"]).replace("Z", "+00:00")
        )
        before_financial = _financial_snapshot(ledger)
        before_counts = _evidence_counts(ledger)

        monkeypatch.setattr(
            fee_correction_confirmation_repository.timezone,
            "now",
            lambda: expires_at + timedelta(seconds=1),
        )
        expired = _assert_json(
            _post_confirmation(
                client,
                ledger,
                csrf_token=csrf_token,
                key=key,
                confirmation_token=token,
            ),
            409,
        )
        assert expired["code"] == "FEE_CORRECTION_CONFIRMATION_EXPIRED"
        assert _financial_snapshot(ledger) == before_financial
        assert _evidence_counts(ledger) == before_counts
        assert (
            SimulatedFeeCorrectionEventModel.objects.filter(
                account_id=_account_id(ledger), trade_id=_trade_id(ledger)
            ).count()
            == 0
        )

        recovered = _assert_json(
            client.get(
                _head_url(_account_id(ledger), _trade_id(ledger)),
                secure=True,
                HTTP_ORIGIN=_ORIGIN,
                HTTP_IDEMPOTENCY_KEY=key,
            ),
            200,
        )
        assert recovered["outcome"] == "partial"
        assert cast(dict[str, object], recovered["head"])["request_receipt"] is None


@pytest.mark.parametrize("expiry_kind", ("token", "session"))
def test_expiry_during_source_verification_rolls_back_the_correction(
    monkeypatch: pytest.MonkeyPatch,
    expiry_kind: str,
) -> None:
    """Crossing either independent deadline during verification rolls back posting."""

    from apps.simulated_trading.infrastructure import fee_correction_confirmation_repository
    from apps.simulated_trading.infrastructure.fee_correction_evidence_repository import (
        DjangoFeeCorrectionEvidenceRepository,
    )

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    with override_settings(SESSION_COOKIE_AGE=3600):
        client, csrf_token = _session_owner_client(ledger)
        session = Session.objects.get(session_key=_session_key(client))
        session.expire_date = timezone.now() + (
            timedelta(minutes=10) if expiry_kind == "session" else timedelta(days=2)
        )
        session.save(update_fields=("expire_date",))
        key = f"session-{_preview_key(ledger, '-verification-expiry')}"
        preview = _assert_json(
            _post_session_preview(client, ledger, csrf_token=csrf_token, key=key),
            200,
        )
        token = _confirmation_token(preview, ledger)
        continuation = cast(dict[str, object], preview["continuation"])
        expires_at = datetime.fromisoformat(
            cast(str, continuation["expires_at"]).replace("Z", "+00:00")
        )
        verification_deadline = session.expire_date if expiry_kind == "session" else expires_at
        if expiry_kind == "session":
            assert verification_deadline < expires_at
        else:
            assert verification_deadline < session.expire_date
        before_financial = _financial_snapshot(ledger)
        before_counts = _evidence_counts(ledger)
        original_verify = DjangoFeeCorrectionEvidenceRepository.verify
        verification_calls: list[bool] = []

        def verify_then_expire(
            repository: DjangoFeeCorrectionEvidenceRepository,
            request: FeeCorrectionRequest,
        ) -> object:
            verified = original_verify(repository, request)
            assert verified is not None
            verification_calls.append(True)
            if len(verification_calls) == 2:
                monkeypatch.setattr(
                    fee_correction_confirmation_repository.timezone,
                    "now",
                    lambda: verification_deadline,
                )
            return verified

        monkeypatch.setattr(
            DjangoFeeCorrectionEvidenceRepository,
            "verify",
            verify_then_expire,
        )
        expired = _assert_json(
            _post_confirmation(
                client,
                ledger,
                csrf_token=csrf_token,
                key=key,
                confirmation_token=token,
            ),
            409,
        )
        assert verification_calls == [True, True]
        assert expired["code"] == "FEE_CORRECTION_CONFIRMATION_EXPIRED"
        assert _financial_snapshot(ledger) == before_financial
        assert _evidence_counts(ledger) == before_counts
        assert (
            SimulatedFeeCorrectionEventModel.objects.filter(
                account_id=_account_id(ledger), trade_id=_trade_id(ledger)
            ).count()
            == 0
        )


@pytest.mark.parametrize("superuser", (False, True), ids=("foreign-owner", "superuser"))
def test_other_authenticated_principals_cannot_confirm_owner_preview(
    superuser: bool,
) -> None:
    """Neither another user nor a superuser can consume an owner's token."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    owner_client, owner_csrf = _session_owner_client(ledger)
    key = f"session-{_preview_key(ledger, '-principal-scope')}"
    preview = _assert_json(
        _post_session_preview(owner_client, ledger, csrf_token=owner_csrf, key=key),
        200,
    )
    token = _confirmation_token(preview, ledger)
    outsider_client, outsider_csrf = _session_user_client(
        _create_unrelated_user(superuser=superuser)
    )
    before_financial = _financial_snapshot(ledger)
    before_counts = _evidence_counts(ledger)

    denied = _assert_json(
        _post_confirmation(
            outsider_client,
            ledger,
            csrf_token=outsider_csrf,
            key=key,
            confirmation_token=token,
        ),
        403,
    )
    assert denied["success"] is False
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_counts
    assert (
        SimulatedFeeCorrectionEventModel.objects.filter(
            account_id=_account_id(ledger), trade_id=_trade_id(ledger)
        ).count()
        == 0
    )


def test_same_user_different_session_cannot_confirm_original_session_token() -> None:
    """Tokens are bound to the exact authenticated session, not only the user ID."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    original_client, original_csrf = _session_owner_client(ledger)
    key = f"session-{_preview_key(ledger, '-session-scope')}"
    preview = _assert_json(
        _post_session_preview(original_client, ledger, csrf_token=original_csrf, key=key),
        200,
    )
    token = _confirmation_token(preview, ledger)
    second_client, second_csrf = _session_owner_client(ledger)
    assert _session_key(original_client) != _session_key(second_client)
    before_financial = _financial_snapshot(ledger)
    before_counts = _evidence_counts(ledger)

    denied = _assert_json(
        _post_confirmation(
            second_client,
            ledger,
            csrf_token=second_csrf,
            key=key,
            confirmation_token=token,
        ),
        409,
    )
    assert denied["code"] == "FEE_CORRECTION_CONFIRMATION_BINDING_MISMATCH"
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_counts
    assert _event_count(ledger) == 0


@pytest.mark.parametrize("binding_change", ("account", "key", "trade", "tampered-token"))
def test_confirmation_token_rejects_changed_request_binding(
    binding_change: str,
) -> None:
    """The token cannot be moved to another key, Trade, or encrypted payload."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client, csrf_token = _session_owner_client(ledger)
    key = f"session-{_preview_key(ledger, '-binding')}"
    preview = _assert_json(
        _post_session_preview(client, ledger, csrf_token=csrf_token, key=key),
        200,
    )
    token = _confirmation_token(preview, ledger)
    target_account_id = _account_id(ledger)
    target_trade_id = _trade_id(ledger)
    target_key = key
    if binding_change == "account":
        target_account_id += 1_000_000
    elif binding_change == "key":
        target_key += "-different"
    elif binding_change == "trade":
        target_trade_id = cast(int, _other_trade(ledger).pk)
    else:
        token = token[:-1] + ("A" if token[-1] != "A" else "B")
    before_financial = _financial_snapshot(ledger)
    before_counts = _evidence_counts(ledger)

    response = _post_confirmation(
        client,
        ledger,
        csrf_token=csrf_token,
        key=target_key,
        confirmation_token=token,
        account_id=target_account_id,
        trade_id=target_trade_id,
    )
    expected_status = {
        "account": 403,
        "key": 409,
        "trade": 409,
        "tampered-token": 400,
    }[binding_change]
    body = _assert_json(response, expected_status)
    assert isinstance(body.get("code"), str)
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_counts
    assert (
        SimulatedFeeCorrectionEventModel.objects.filter(
            account_id=_account_id(ledger), trade_id=_trade_id(ledger)
        ).count()
        == 0
    )


def test_confirmation_requires_csrf_and_rejects_api_tokens() -> None:
    """Browser confirmation is session-and-CSRF only, never API-token based."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client, csrf_token = _session_owner_client(ledger)
    key = f"session-{_preview_key(ledger, '-auth-scope')}"
    preview = _assert_json(
        _post_session_preview(client, ledger, csrf_token=csrf_token, key=key),
        200,
    )
    token = _confirmation_token(preview, ledger)
    before_financial = _financial_snapshot(ledger)
    before_counts = _evidence_counts(ledger)

    csrf_denied = _post_confirmation(
        client,
        ledger,
        csrf_token=None,
        key=key,
        confirmation_token=token,
    )
    assert csrf_denied.status_code == 403

    _create_profile(ledger.owner)
    _, access_token = UserAccessTokenModel.create_token(
        user=ledger.owner,
        name="fee-correction-confirmation-readonly",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )
    token_client = APIClient()
    token_client.credentials(HTTP_AUTHORIZATION=f"Token {access_token}")
    token_denied = _assert_json(
        _post_confirmation(
            token_client,
            ledger,
            csrf_token=None,
            key=key,
            confirmation_token=token,
        ),
        403,
    )
    assert token_denied["code"] == "API_ERROR"
    assert isinstance(token_denied["error"], str) and token_denied["error"]
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_counts
    assert _event_count(ledger) == 0


def test_disabled_policy_blocks_pending_session_confirmation() -> None:
    """A saved preview cannot bypass a later owner-policy revocation."""

    ledger = _seed_ledger(commission=Decimal("7.00"), revised_commission=Decimal("9.00"))
    client, csrf_token = _session_owner_client(ledger)
    key = f"session-{_preview_key(ledger, '-policy-revoked')}"
    preview = _assert_json(
        _post_session_preview(client, ledger, csrf_token=csrf_token, key=key),
        200,
    )
    token = _confirmation_token(preview, ledger)
    policy = FeeCorrectionEvidencePolicyModel.objects.get(account_id=_account_id(ledger))
    policy.enabled = False
    policy.save(update_fields=("enabled",))
    before_financial = _financial_snapshot(ledger)
    before_counts = _evidence_counts(ledger)

    denied = _assert_json(
        _post_confirmation(
            client,
            ledger,
            csrf_token=csrf_token,
            key=key,
            confirmation_token=token,
        ),
        422,
    )
    assert denied["success"] is False
    assert denied["code"] == "FEE_CORRECTION_SOURCE_UNAVAILABLE"
    assert _financial_snapshot(ledger) == before_financial
    assert _evidence_counts(ledger) == before_counts
    assert _event_count(ledger) == 0
