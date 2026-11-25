"""HTTP contracts for the authenticated C2 Owner apply/revoke API."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from django.db import models
from django.http import HttpRequest
from django.http.response import HttpResponse
from rest_framework.test import APIClient

from apps.data_center.domain.financial_availability_governance import (
    FinancialAvailabilityGovernanceRecord,
    FinancialAvailabilityOwnerEventAction,
    FinancialAvailabilityOwnerEventIdentity,
    FinancialAvailabilityRecordKind,
)
from apps.data_center.domain.financial_next_session_availability import (
    ExchangeSessionOpeningPhase,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialDisclosureAvailabilityPolicy,
)
from apps.data_center.infrastructure.financial_availability_governance_codec import (
    serialize_financial_availability_record,
)
from apps.data_center.interface import financial_availability_governance_api

pytestmark = pytest.mark.django_db

_APPLY_PATH = "/api/data-center/financial-availability/governance/apply/"
_REVOKE_PATH = "/api/data-center/financial-availability/governance/revoke/"
_NOW = datetime(2026, 11, 16, 1, 2, 3, tzinfo=UTC)


def _policy_record() -> FinancialAvailabilityGovernanceRecord:
    """Build a synthetic explicit policy record; no production defaults are implied."""

    policy = FinancialDisclosureAvailabilityPolicy.create(
        policy_id="synthetic-policy-v1",
        policy_version="v1",
        exchange="SZSE",
        opening_phase=ExchangeSessionOpeningPhase.CONTINUOUS_AUCTION,
        effective_start=date(2026, 1, 1),
        effective_end=date(2026, 12, 31),
        calendar_response_max_age_seconds=3600,
        first_seen_at=_NOW,
        recorded_at=_NOW,
    )
    return FinancialAvailabilityGovernanceRecord(
        record_id="synthetic-policy-v1",
        record_version="v1",
        exchange="SZSE",
        kind=FinancialAvailabilityRecordKind.DISCLOSURE_POLICY,
        content=policy,
        recorded_at=_NOW,
    )


def _apply_payload() -> dict[str, object]:
    """Return one valid strict stored-record envelope for interface tests."""

    raw = serialize_financial_availability_record(_policy_record())
    return {
        "record": cast(dict[str, object], json.loads(raw.decode("utf-8"))),
        "reason": "synthetic contract test",
    }


def _apply_event(
    record: FinancialAvailabilityGovernanceRecord,
    *,
    actor_user_id: int = 7,
) -> FinancialAvailabilityOwnerEventIdentity:
    """Build a local synthetic event for response presentation only."""

    permission_verified_at = max(_NOW, record.recorded_at)
    occurred_at = permission_verified_at + timedelta(seconds=1)
    return FinancialAvailabilityOwnerEventIdentity.create(
        action=FinancialAvailabilityOwnerEventAction.APPLY,
        event_id=uuid4(),
        record=record,
        resulting_content_sha256=record.resulting_content_sha256(approved_at=occurred_at),
        actor_user_id=actor_user_id,
        permission_id=9,
        permission_verified_at=permission_verified_at,
        occurred_at=occurred_at,
        recorded_at=occurred_at + timedelta(seconds=1),
        reason="synthetic contract test",
    )


def _session_client(
    django_user_model: type[models.Model],
    *,
    enforce_csrf: bool,
) -> tuple[APIClient, str | None, models.Model]:
    """Create a real Django session and optionally acquire a real CSRF cookie."""

    username = f"owner-api-{uuid4().hex}"
    password = "synthetic-test-password"
    user = django_user_model.objects.create_user(username=username, password=password)
    client = APIClient(enforce_csrf_checks=enforce_csrf)
    token: str | None = None
    if enforce_csrf:
        response = client.get("/admin/login/")
        assert response.status_code == 200
        token = response.cookies["csrftoken"].value
    assert client.login(username=username, password=password)
    return client, token, user


def _post_json(
    client: APIClient,
    path: str,
    payload: dict[str, object],
    *,
    csrf_token: str | None,
) -> HttpResponse:
    """POST one JSON body with the session client's actual CSRF token when given."""

    extra: dict[str, str] = {}
    if csrf_token is not None:
        extra["HTTP_X_CSRFTOKEN"] = csrf_token
    return client.post(path, payload, format="json", **extra)


def test_owner_get_is_json_method_not_allowed(
    django_user_model: type[models.Model],
) -> None:
    """Only write methods are exposed and failures retain JSON media type."""

    client, _token, _user = _session_client(django_user_model, enforce_csrf=False)
    response = client.get(_APPLY_PATH)
    assert response.status_code == 405
    assert response["Content-Type"].startswith("application/json")


def test_owner_post_requires_an_authenticated_session() -> None:
    """Anonymous writes are denied before the C2 composition is called."""

    response = APIClient().post(_APPLY_PATH, {}, format="json")
    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/json")
    assert "code" in response.json()


def test_session_authenticated_owner_post_enforces_csrf(
    django_user_model: type[models.Model],
) -> None:
    """A live session without the matching CSRF header cannot submit an Owner write."""

    client, _token, _user = _session_client(django_user_model, enforce_csrf=True)
    response = client.post(_APPLY_PATH, _apply_payload(), format="json")
    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/json")


def test_owner_post_requires_json_content_type(
    django_user_model: type[models.Model],
) -> None:
    """Non-JSON bodies receive the documented JSON 415 error response."""

    client, token, _user = _session_client(django_user_model, enforce_csrf=True)
    response = client.post(
        _APPLY_PATH,
        data="{}",
        content_type="text/plain",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 415
    assert response["Content-Type"].startswith("application/json")


@pytest.mark.parametrize(
    "forbidden_key",
    (
        "actor_user_id",
        "session_key",
        "database_alias",
        "source_known_at",
        "occurred_at",
        "permission_verified_at",
    ),
)
def test_apply_rejects_caller_supplied_principal_alias_and_operation_clocks(
    django_user_model: type[models.Model],
    forbidden_key: str,
) -> None:
    """Only the strict record and reason may reach the Owner composition."""

    client, token, _user = _session_client(django_user_model, enforce_csrf=True)
    payload = _apply_payload()
    payload[forbidden_key] = "caller-controlled"
    response = _post_json(client, _APPLY_PATH, payload, csrf_token=token)
    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")


def test_apply_success_returns_restamped_record_and_json_owner_event(
    django_user_model: type[models.Model],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful handler passes Django's real HttpRequest and returns DB result data."""

    client, token, user = _session_client(django_user_model, enforce_csrf=True)
    source_record = _policy_record()
    persisted_record = _policy_record()
    persisted_record = FinancialAvailabilityGovernanceRecord(
        record_id=persisted_record.record_id,
        record_version=persisted_record.record_version,
        exchange=persisted_record.exchange,
        kind=persisted_record.kind,
        content=FinancialDisclosureAvailabilityPolicy.create(
            policy_id=persisted_record.record_id,
            policy_version=persisted_record.record_version,
            exchange=persisted_record.exchange,
            opening_phase=ExchangeSessionOpeningPhase.CONTINUOUS_AUCTION,
            effective_start=date(2026, 1, 1),
            effective_end=date(2026, 12, 31),
            calendar_response_max_age_seconds=3600,
            first_seen_at=_NOW,
            recorded_at=_NOW + timedelta(seconds=10),
        ),
        recorded_at=_NOW + timedelta(seconds=10),
    )
    assert type(user.pk) is int
    event = _apply_event(persisted_record, actor_user_id=user.pk)
    observed: dict[str, object] = {}

    def fake_apply(
        request: HttpRequest,
        *,
        record_payload: dict[str, object],
        reason: str,
    ) -> tuple[FinancialAvailabilityGovernanceRecord, FinancialAvailabilityOwnerEventIdentity]:
        assert isinstance(request, HttpRequest)
        assert request.user.pk == user.pk
        assert request.user.is_authenticated is True
        assert type(request.session.session_key) is str
        observed["record_payload"] = record_payload
        observed["reason"] = reason
        return persisted_record, event

    monkeypatch.setattr(
        financial_availability_governance_api,
        "apply_financial_availability_owner_request",
        fake_apply,
    )
    response = _post_json(client, _APPLY_PATH, _apply_payload(), csrf_token=token)
    assert response.status_code == 201
    assert response["Content-Type"].startswith("application/json")
    body = response.json()
    assert body["outcome"] == "success" and body["success"] is True
    assert body["record"]["recorded_at"] == persisted_record.to_payload()["recorded_at"]
    assert body["record"]["recorded_at"] != source_record.to_payload()["recorded_at"]
    assert body["owner_event"]["actor_user_id"] == user.pk
    assert observed["reason"] == "synthetic contract test"


def test_revoke_rejects_caller_principal_and_clock_fields(
    django_user_model: type[models.Model],
) -> None:
    """Revoke accepts only an exact target and reason, never caller identity/time."""

    client, token, _user = _session_client(django_user_model, enforce_csrf=True)
    payload: dict[str, object] = {
        "target": {
            "record_id": "synthetic-policy-v1",
            "record_version": "v1",
            "record_content_sha256": "a" * 64,
            "apply_event_id": "40000000-0000-4000-8000-000000000004",
            "apply_event_sha256": "b" * 64,
        },
        "reason": "synthetic revoke test",
        "actor_user_id": 7,
    }
    response = _post_json(client, _REVOKE_PATH, payload, csrf_token=token)
    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")


def test_revoke_success_returns_json_event(
    django_user_model: type[models.Model],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid exact-target request returns one append-only local revoke event."""

    client, token, user = _session_client(django_user_model, enforce_csrf=True)
    record = _policy_record()
    apply_event = _apply_event(record)
    revoke_event = FinancialAvailabilityOwnerEventIdentity.create(
        action=FinancialAvailabilityOwnerEventAction.REVOKE,
        event_id=uuid4(),
        record=record,
        resulting_content_sha256=apply_event.resulting_content_sha256,
        actor_user_id=7,
        permission_id=9,
        permission_verified_at=_NOW + timedelta(seconds=2),
        occurred_at=_NOW + timedelta(seconds=3),
        recorded_at=_NOW + timedelta(seconds=4),
        reason="synthetic revoke test",
        predecessor_apply_event_id=apply_event.event_id,
        predecessor_apply_event_sha256=apply_event.event_sha256,
    )

    def fake_revoke(
        request: HttpRequest,
        *,
        target: dict[str, str],
        reason: str,
    ) -> FinancialAvailabilityOwnerEventIdentity:
        assert isinstance(request, HttpRequest)
        assert request.user.pk == user.pk
        assert type(request.session.session_key) is str
        assert target["apply_event_id"] == str(apply_event.event_id)
        assert reason == "synthetic revoke test"
        return revoke_event

    monkeypatch.setattr(
        financial_availability_governance_api,
        "revoke_financial_availability_owner_request",
        fake_revoke,
    )
    payload: dict[str, object] = {
        "target": {
            "record_id": record.record_id,
            "record_version": record.record_version,
            "record_content_sha256": record.content_sha256,
            "apply_event_id": str(apply_event.event_id),
            "apply_event_sha256": apply_event.event_sha256,
        },
        "reason": "synthetic revoke test",
    }
    response = _post_json(client, _REVOKE_PATH, payload, csrf_token=token)
    assert response.status_code == 201
    assert response["Content-Type"].startswith("application/json")
    body = response.json()
    assert body["outcome"] == "success" and body["success"] is True
    assert body["owner_event"]["action"] == "revoke"
    assert body["owner_event"]["predecessor_apply_event_id"] == str(apply_event.event_id)
