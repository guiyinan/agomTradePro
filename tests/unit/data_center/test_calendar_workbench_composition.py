from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

import apps.data_center.calendar_workbench_composition as composition
from apps.data_center.application.calendar_preview_token import (
    CalendarPreviewTokenContent,
    CalendarPreviewTokenError,
)
from apps.data_center.application.calendar_publication_authority import (
    CalendarPublisherSessionRequestProof,
)
from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationOperationsError,
    CalendarPublicationPreview,
    CalendarPublicationPreviewIdentity,
    CapturedExchangeCalendarSnapshot,
    CaptureExchangeCalendarSnapshotIntent,
    PreviewCalendarPublicationIntent,
)
from apps.data_center.domain.exchange_calendar import ExchangeCalendarSnapshotReference
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarPublicationPointerExpectation,
    exchange_calendar_publication_key,
)
from apps.data_center.infrastructure.calendar_preview_token import (
    EncryptedCalendarPreviewTokenCodec,
)
from shared.config.secrets import clear_secrets_cache
from shared.infrastructure.crypto import FieldEncryptionService

_NOW = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)
_SESSION_KEY = "calendar-workbench-session-key"


class _Connection:
    def __init__(
        self,
        *,
        alias: str = "default",
        in_atomic_block: bool = False,
        autocommit: bool = True,
    ) -> None:
        self.alias = alias
        self.in_atomic_block = in_atomic_block
        self._autocommit = autocommit

    def get_autocommit(self) -> bool:
        return self._autocommit


class _Connections:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def __getitem__(self, alias: str) -> _Connection:
        assert alias == "default"
        return self.connection


@pytest.fixture(autouse=True)
def _clear_secret_cache() -> None:
    clear_secrets_cache()
    yield
    clear_secrets_cache()


def _request() -> Request:
    """Build a request-shaped test input; authentication is faked separately."""

    return Request(APIRequestFactory().post("/calendar-workbench/", data={}, format="json"))


def _proof(
    *,
    user_id: int = 42,
    session_key: str = _SESSION_KEY,
    authenticated_at: datetime = _NOW - timedelta(seconds=2),
    alias: str = "default",
) -> CalendarPublisherSessionRequestProof:
    return CalendarPublisherSessionRequestProof(
        user_id=user_id,
        session_key=session_key,
        request_authenticated_at=authenticated_at,
        request_user_database_alias=alias,
        database_alias=alias,
    )


def _reference() -> ExchangeCalendarSnapshotReference:
    return ExchangeCalendarSnapshotReference(
        snapshot_id=str(uuid4()),
        exchange="SSE",
        coverage_start=date(2026, 10, 16),
        coverage_end=date(2026, 10, 17),
        content_hash=f"sha256:{'1' * 64}",
        record_digest=f"sha256:{'2' * 64}",
        raw_payload_id=str(uuid4()),
        raw_payload_hash=f"sha256:{'3' * 64}",
        raw_record_digest=f"sha256:{'4' * 64}",
    )


def _capture_intent() -> CaptureExchangeCalendarSnapshotIntent:
    return CaptureExchangeCalendarSnapshotIntent(
        exchange="SSE",
        coverage_start=date(2026, 10, 16),
        coverage_end=date(2026, 10, 17),
    )


def _capture_preview_pair() -> tuple[
    CapturedExchangeCalendarSnapshot,
    CalendarPublicationPreview,
]:
    reference = _reference()
    first_seen_at = _NOW - timedelta(seconds=10)
    captured = CapturedExchangeCalendarSnapshot(
        snapshot_reference=reference,
        first_seen_at=first_seen_at,
        recorded_at=_NOW - timedelta(seconds=9),
        source_published_at=None,
    )
    identity = CalendarPublicationPreviewIdentity(
        dataset_key="tushare.exchange_calendar.raw",
        contract_version="calendar-contract-v1",
        schema_version="exchange-calendar-snapshot-v1",
        policy_identity=f"p2:1:{'5' * 64}",
        policy_version="calendar-policy-v1",
        calendar_response_max_age_seconds=120,
    )
    pointer = CalendarPublicationPointerExpectation(
        dataset_key=identity.dataset_key,
        publication_key=exchange_calendar_publication_key(reference.exchange),
        pointer_id=None,
        publication_id=None,
        publication_hash=None,
        activation_id=None,
        updated_at=None,
    )
    preview = CalendarPublicationPreview(
        snapshot_reference=reference,
        identity=identity,
        expected_pointer=pointer,
        activation_id="calendar-workbench-activation",
        expected_publication_hash="6" * 64,
        first_seen_at=first_seen_at,
        snapshot_recorded_at=captured.recorded_at,
        source_published_at=None,
        response_expires_at=first_seen_at
        + timedelta(seconds=identity.calendar_response_max_age_seconds),
        previewed_at=_NOW,
        preview_hash="7" * 64,
    )
    return captured, preview


def _patch_connection(
    monkeypatch: pytest.MonkeyPatch,
    connection: _Connection | None = None,
) -> _Connection:
    """Use an in-memory boundary stub so composition tests never open a DB."""

    value = connection or _Connection()
    monkeypatch.setattr(composition, "connections", _Connections(value))
    return value


def _patch_session_proofs(
    monkeypatch: pytest.MonkeyPatch,
    request: Request,
    proofs: tuple[CalendarPublisherSessionRequestProof, ...],
) -> list[tuple[Request, str]]:
    calls: list[tuple[Request, str]] = []
    remaining = iter(proofs)

    def prove(
        adapter: object,
        actual_request: Request,
        *,
        using: str,
    ) -> CalendarPublisherSessionRequestProof:
        assert actual_request is request
        calls.append((actual_request, using))
        try:
            return next(remaining)
        except StopIteration as error:
            raise AssertionError("unexpected extra session proof request") from error

    monkeypatch.setattr(composition.CalendarPublisherSessionAdapter, "prove", prove)
    return calls


def test_prepare_entry_binds_request_intents_and_existing_owner_wrappers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    intent = _capture_intent()
    proof = _proof()
    fresh_one = replace(
        proof,
        request_authenticated_at=proof.request_authenticated_at + timedelta(seconds=1),
    )
    fresh_two = replace(
        proof,
        request_authenticated_at=proof.request_authenticated_at + timedelta(seconds=2),
    )
    proof_calls = _patch_session_proofs(monkeypatch, request, (proof, fresh_one, fresh_two))
    connection = _patch_connection(monkeypatch)
    captured, preview = _capture_preview_pair()
    encryption_key = FieldEncryptionService.generate_key()
    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", encryption_key)
    monkeypatch.setattr(
        composition.timezone,
        "now",
        lambda: _NOW + timedelta(seconds=3),
    )
    owner_calls: list[tuple[str, Request, object]] = []

    def capture(actual_request: Request, actual_intent: CaptureExchangeCalendarSnapshotIntent):
        assert actual_request is request
        assert actual_intent is intent
        assert not connection.in_atomic_block and connection.get_autocommit()
        owner_calls.append(("capture", actual_request, actual_intent))
        return captured

    def prepare(
        actual_request: Request,
        actual_intent: PreviewCalendarPublicationIntent,
    ) -> CalendarPublicationPreview:
        assert actual_request is request
        assert actual_intent.snapshot_reference == captured.snapshot_reference
        assert not connection.in_atomic_block and connection.get_autocommit()
        owner_calls.append(("preview", actual_request, actual_intent))
        return preview

    monkeypatch.setattr(composition, "capture_exchange_calendar_snapshot", capture)
    monkeypatch.setattr(composition, "preview_calendar_publication", prepare)

    result = composition.prepare_calendar_workbench_preview(request, intent)

    assert result.captured is captured
    assert result.preview is preview
    assert result.confirmation_token.startswith(FieldEncryptionService.PREFIX)
    assert [call[0] for call in owner_calls] == ["capture", "preview"]
    assert all(call[1] is request for call in owner_calls)
    assert len(proof_calls) == 3
    assert all(call[0] is request and call[1] == "default" for call in proof_calls)


@pytest.mark.parametrize(
    ("connection",),
    [
        (_Connection(alias="replica"),),
        (_Connection(in_atomic_block=True),),
        (_Connection(autocommit=False),),
    ],
)
def test_preview_rejects_wrong_alias_or_caller_owned_transaction_before_proof(
    monkeypatch: pytest.MonkeyPatch,
    connection: _Connection,
) -> None:
    _patch_connection(monkeypatch, connection)
    proof_calls: list[object] = []

    def unexpected_proof(*args: object, **kwargs: object) -> CalendarPublisherSessionRequestProof:
        proof_calls.append((args, kwargs))
        raise AssertionError("unsafe connection must be rejected before session proof")

    monkeypatch.setattr(composition.CalendarPublisherSessionAdapter, "prove", unexpected_proof)
    owner_calls: list[object] = []
    monkeypatch.setattr(
        composition,
        "capture_exchange_calendar_snapshot",
        lambda *args, **kwargs: owner_calls.append((args, kwargs)),
    )

    with pytest.raises(CalendarPreviewTokenError) as error:
        composition.prepare_calendar_workbench_preview(_request(), _capture_intent())

    assert error.value.status_code == 409
    assert proof_calls == []
    assert owner_calls == []


def test_preview_rejects_session_identity_drift_before_owner_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    initial = _proof()
    drifted = replace(initial, session_key="different-calendar-session")
    assert drifted == initial  # session_key is intentionally compare=False on the proof.
    _patch_session_proofs(monkeypatch, request, (initial, drifted))
    _patch_connection(monkeypatch)
    monkeypatch.setattr(
        composition.timezone,
        "now",
        lambda: _NOW + timedelta(seconds=3),
    )
    owner_calls: list[object] = []
    monkeypatch.setattr(
        composition,
        "capture_exchange_calendar_snapshot",
        lambda *args, **kwargs: owner_calls.append((args, kwargs)),
    )

    with pytest.raises(CalendarPreviewTokenError) as error:
        composition.prepare_calendar_workbench_preview(request, _capture_intent())

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_BINDING_MISMATCH"
    assert owner_calls == []


def test_preview_rejects_adapter_proof_for_nondefault_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    _patch_session_proofs(monkeypatch, request, (_proof(alias="replica"),))
    _patch_connection(monkeypatch)
    owner_calls: list[object] = []
    monkeypatch.setattr(
        composition,
        "capture_exchange_calendar_snapshot",
        lambda *args, **kwargs: owner_calls.append((args, kwargs)),
    )

    with pytest.raises(CalendarPreviewTokenError) as error:
        composition.prepare_calendar_workbench_preview(request, _capture_intent())

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_BINDING_INVALID"
    assert owner_calls == []


def test_preview_rejects_app_supplied_proof_drift_even_when_dataclass_equal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    initial = _proof()
    _patch_session_proofs(monkeypatch, request, (initial,))
    _patch_connection(monkeypatch)
    owner_calls: list[object] = []
    monkeypatch.setattr(
        composition,
        "capture_exchange_calendar_snapshot",
        lambda *args, **kwargs: owner_calls.append((args, kwargs)),
    )

    def drift_proof(
        workbench: object,
        intent: CaptureExchangeCalendarSnapshotIntent,
        *,
        proof: CalendarPublisherSessionRequestProof,
    ) -> object:
        drifted = replace(proof, session_key="different-calendar-session")
        assert drifted == proof
        return workbench._capture.execute(intent, proof=drifted)  # type: ignore[attr-defined]

    monkeypatch.setattr(composition.CalendarPublicationWorkbench, "prepare_preview", drift_proof)

    with pytest.raises(CalendarPreviewTokenError) as error:
        composition.prepare_calendar_workbench_preview(request, _capture_intent())

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_BINDING_MISMATCH"
    assert owner_calls == []


def test_capture_owner_failure_stops_preview_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    proof = _proof()
    _patch_session_proofs(
        monkeypatch,
        request,
        (
            proof,
            replace(
                proof,
                request_authenticated_at=proof.request_authenticated_at + timedelta(seconds=1),
            ),
        ),
    )
    _patch_connection(monkeypatch)
    monkeypatch.setattr(
        composition.timezone,
        "now",
        lambda: _NOW + timedelta(seconds=3),
    )
    owner_error = CalendarPublicationOperationsError(
        "captured source is unavailable",
        code="CALENDAR_CAPTURE_SOURCE_UNAVAILABLE",
    )
    owner_calls: list[str] = []

    def capture(
        actual_request: Request,
        actual_intent: CaptureExchangeCalendarSnapshotIntent,
    ) -> CapturedExchangeCalendarSnapshot:
        assert actual_request is request
        assert actual_intent == _capture_intent()
        owner_calls.append("capture")
        raise owner_error

    def preview(
        actual_request: Request,
        actual_intent: PreviewCalendarPublicationIntent,
    ) -> CalendarPublicationPreview:
        owner_calls.append("preview")
        raise AssertionError("preview must not run after capture fails")

    monkeypatch.setattr(composition, "capture_exchange_calendar_snapshot", capture)
    monkeypatch.setattr(composition, "preview_calendar_publication", preview)

    with pytest.raises(CalendarPublicationOperationsError) as error:
        composition.prepare_calendar_workbench_preview(request, _capture_intent())

    assert error.value is owner_error
    assert owner_calls == ["capture"]


def test_confirm_passes_decoded_intent_to_owner_and_propagates_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    proof = _proof()
    fresh = replace(
        proof,
        request_authenticated_at=proof.request_authenticated_at + timedelta(seconds=1),
    )
    _patch_session_proofs(monkeypatch, request, (proof, fresh))
    _patch_connection(monkeypatch)
    captured, preview = _capture_preview_pair()
    del captured
    encryption_key = FieldEncryptionService.generate_key()
    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", encryption_key)
    monkeypatch.setattr(
        composition.timezone,
        "now",
        lambda: _NOW + timedelta(seconds=3),
    )
    expected_intent = preview.confirmation_intent()
    token_content = CalendarPreviewTokenContent.from_preview(
        preview,
        actor_user_id=proof.user_id,
        session_key_sha256=hashlib.sha256(proof.session_key.encode("utf-8")).hexdigest(),
    )
    token = EncryptedCalendarPreviewTokenCodec().encode(token_content)
    owner_error = CalendarPublicationOperationsError(
        "publication owner rejected confirmation",
        code="CALENDAR_PUBLICATION_CONFIRMATION_REJECTED",
    )
    owner_calls: list[tuple[Request, object]] = []

    def unexpected_capture(*args: object, **kwargs: object) -> CapturedExchangeCalendarSnapshot:
        raise AssertionError("confirmation must not capture another source")

    def unexpected_preview(*args: object, **kwargs: object) -> CalendarPublicationPreview:
        raise AssertionError("confirmation must not generate a new preview")

    def confirm(
        actual_request: Request,
        intent: object,
    ) -> object:
        assert actual_request is request
        owner_calls.append((actual_request, intent))
        raise owner_error

    monkeypatch.setattr(composition, "capture_exchange_calendar_snapshot", unexpected_capture)
    monkeypatch.setattr(composition, "preview_calendar_publication", unexpected_preview)
    monkeypatch.setattr(composition, "confirm_calendar_publication", confirm)

    with pytest.raises(CalendarPublicationOperationsError) as error:
        composition.confirm_calendar_workbench_preview(request, token)

    assert error.value is owner_error
    assert len(owner_calls) == 1
    actual_intent = owner_calls[0][1]
    assert type(actual_intent) is type(expected_intent)
    assert actual_intent == expected_intent
