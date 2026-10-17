from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from apps.data_center.application.calendar_preview_token import (
    CALENDAR_PREVIEW_DATABASE_ALIAS,
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
    ConfirmCalendarPublicationIntent,
    PreviewCalendarPublicationIntent,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationCommit,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarSnapshotReference,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarPublicationPointerExpectation,
)

NOW = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)
SESSION_KEY = "session-key-for-calendar-workbench"


def _reference(
    *,
    exchange: str = "SSE",
    coverage_start: date = date(2026, 10, 1),
    coverage_end: date = date(2026, 10, 2),
) -> ExchangeCalendarSnapshotReference:
    return ExchangeCalendarSnapshotReference(
        snapshot_id=str(uuid4()),
        exchange=exchange,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        content_hash=f"sha256:{'1' * 64}",
        record_digest=f"sha256:{'2' * 64}",
        raw_payload_id=str(uuid4()),
        raw_payload_hash=f"sha256:{'3' * 64}",
        raw_record_digest=f"sha256:{'4' * 64}",
    )


def _pointer() -> CalendarPublicationPointerExpectation:
    return CalendarPublicationPointerExpectation(
        dataset_key="tushare.exchange_calendar.raw",
        publication_key="exchange-calendar:SSE",
        pointer_id=None,
        publication_id=None,
        publication_hash=None,
        activation_id=None,
        updated_at=None,
    )


def _capture_intent() -> CaptureExchangeCalendarSnapshotIntent:
    return CaptureExchangeCalendarSnapshotIntent(
        exchange="SSE",
        coverage_start=date(2026, 10, 1),
        coverage_end=date(2026, 10, 2),
    )


def _captured(
    reference: ExchangeCalendarSnapshotReference | None = None,
    *,
    first_seen_at: datetime = NOW - timedelta(seconds=20),
    recorded_at: datetime = NOW - timedelta(seconds=19),
    source_published_at: datetime | None = None,
) -> CapturedExchangeCalendarSnapshot:
    return CapturedExchangeCalendarSnapshot(
        snapshot_reference=reference or _reference(),
        first_seen_at=first_seen_at,
        recorded_at=recorded_at,
        source_published_at=source_published_at,
    )


def _preview(
    captured: CapturedExchangeCalendarSnapshot | None = None,
    *,
    reference: ExchangeCalendarSnapshotReference | None = None,
    first_seen_at: datetime | None = None,
    snapshot_recorded_at: datetime | None = None,
    source_published_at: datetime | None = None,
    previewed_at: datetime = NOW,
) -> CalendarPublicationPreview:
    captured_value = captured or _captured(reference)
    identity = CalendarPublicationPreviewIdentity(
        dataset_key="tushare.exchange_calendar.raw",
        contract_version="calendar-contract-v1",
        schema_version="exchange-calendar-snapshot-v1",
        policy_identity=f"p2:1:{'5' * 64}",
        policy_version="calendar-policy-v1",
        calendar_response_max_age_seconds=60,
    )
    return CalendarPublicationPreview(
        snapshot_reference=reference or captured_value.snapshot_reference,
        identity=identity,
        expected_pointer=_pointer(),
        activation_id="calendar-activation-1",
        expected_publication_hash="6" * 64,
        first_seen_at=first_seen_at or captured_value.first_seen_at,
        snapshot_recorded_at=snapshot_recorded_at or captured_value.recorded_at,
        source_published_at=(
            source_published_at
            if source_published_at is not None
            else captured_value.source_published_at
        ),
        response_expires_at=(first_seen_at or captured_value.first_seen_at)
        + timedelta(seconds=identity.calendar_response_max_age_seconds),
        previewed_at=previewed_at,
        preview_hash="7" * 64,
    )


def _proof(
    *,
    user_id: int = 42,
    session_key: str = SESSION_KEY,
    alias: str = CALENDAR_PREVIEW_DATABASE_ALIAS,
    authenticated_at: datetime = NOW - timedelta(seconds=2),
) -> CalendarPublisherSessionRequestProof:
    return CalendarPublisherSessionRequestProof(
        user_id=user_id,
        session_key=session_key,
        request_authenticated_at=authenticated_at,
        request_user_database_alias=alias,
        database_alias=alias,
    )


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class SequenceClock:
    def __init__(self, values: tuple[datetime, ...]) -> None:
        self.values = values
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.values[min(self.calls - 1, len(self.values) - 1)]


class CapturePort:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[object, CalendarPublisherSessionRequestProof]] = []

    def execute(
        self,
        intent: object,
        *,
        proof: CalendarPublisherSessionRequestProof,
    ) -> object:
        self.calls.append((intent, proof))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class PreviewPort:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[object, CalendarPublisherSessionRequestProof]] = []

    def execute(
        self,
        intent: object,
        *,
        proof: CalendarPublisherSessionRequestProof,
    ) -> object:
        self.calls.append((intent, proof))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class ConfirmationPort:
    def __init__(self, result: object | None = None) -> None:
        self.result = result
        self.calls: list[
            tuple[ConfirmCalendarPublicationIntent, CalendarPublisherSessionRequestProof]
        ] = []

    def execute(
        self,
        intent: ConfirmCalendarPublicationIntent,
        *,
        proof: CalendarPublisherSessionRequestProof,
    ) -> CalendarFormalPublicationCommit:
        self.calls.append((intent, proof))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result  # type: ignore[return-value]


class TokenCodec:
    def __init__(self, decoded: object | None = None) -> None:
        self.decoded = decoded
        self.encoded: list[CalendarPreviewTokenContent] = []
        self.decode_calls: list[dict[str, object]] = []
        self.encode_error: BaseException | None = None
        self.decode_error: BaseException | None = None

    def encode(self, content: CalendarPreviewTokenContent) -> str:
        self.encoded.append(content)
        if self.encode_error is not None:
            raise self.encode_error
        return "opaque-calendar-token"

    def decode(
        self,
        token: str,
        *,
        actor_user_id: int,
        session_key_sha256: str,
        database_alias: str,
        now: datetime,
    ) -> CalendarPreviewTokenContent:
        self.decode_calls.append(
            {
                "token": token,
                "actor_user_id": actor_user_id,
                "session_key_sha256": session_key_sha256,
                "database_alias": database_alias,
                "now": now,
            }
        )
        if self.decode_error is not None:
            raise self.decode_error
        return self.decoded  # type: ignore[return-value]


def _workbench(
    capture: CapturePort,
    preview: PreviewPort,
    confirmation: ConfirmationPort | None = None,
    codec: TokenCodec | None = None,
    clock: FixedClock | None = None,
) -> object:
    from apps.data_center.application.calendar_workbench import (
        CalendarPublicationWorkbench,
    )

    return CalendarPublicationWorkbench(
        capture=capture,
        preview=preview,
        confirmation=confirmation or ConfirmationPort(),
        token_codec=codec or TokenCodec(),
        clock=clock or FixedClock(NOW + timedelta(seconds=1)),
    )


def test_prepare_captures_then_previews_and_returns_hidden_opaque_token() -> None:
    from apps.data_center.application.calendar_workbench import (
        CalendarWorkbenchPreview,
    )

    captured = _captured()
    preview = _preview(captured)
    capture_port = CapturePort(captured)
    preview_port = PreviewPort(preview)
    confirmation_port = ConfirmationPort()
    codec = TokenCodec()
    workbench = _workbench(capture_port, preview_port, confirmation_port, codec)
    proof = _proof()

    result = workbench.prepare_preview(_capture_intent(), proof=proof)

    assert type(result) is CalendarWorkbenchPreview
    assert result.captured is captured
    assert result.preview is preview
    assert result.confirmation_token == "opaque-calendar-token"
    assert "opaque-calendar-token" not in repr(result)
    assert [call[0] for call in capture_port.calls] == [_capture_intent()]
    assert capture_port.calls[0][1] is proof
    assert type(preview_port.calls[0][0]) is PreviewCalendarPublicationIntent
    assert preview_port.calls[0][0].snapshot_reference == captured.snapshot_reference
    assert preview_port.calls[0][1] is proof
    assert confirmation_port.calls == []
    content = codec.encoded[0]
    assert content.intent == preview.confirmation_intent()
    assert content.actor_user_id == proof.user_id
    assert content.session_key_sha256 == hashlib.sha256(SESSION_KEY.encode()).hexdigest()
    assert content.database_alias == CALENDAR_PREVIEW_DATABASE_ALIAS
    assert content.first_seen_at == captured.first_seen_at
    assert content.response_expires_at == preview.response_expires_at


def test_prepare_rejects_capture_scope_mismatch_before_preview_or_token() -> None:
    captured = _captured(_reference(exchange="SZE"))
    capture_port = CapturePort(captured)
    preview_port = PreviewPort(_preview(captured))
    codec = TokenCodec()
    workbench = _workbench(capture_port, preview_port, codec=codec)

    with pytest.raises(CalendarPublicationOperationsError) as error:
        workbench.prepare_preview(_capture_intent(), proof=_proof())

    assert error.value.code == "CALENDAR_WORKBENCH_CAPTURE_SCOPE_MISMATCH"
    assert preview_port.calls == []
    assert codec.encoded == []


@pytest.mark.parametrize(
    "preview_changes",
    [
        {"first_seen_at": NOW - timedelta(seconds=21)},
        {"snapshot_recorded_at": NOW - timedelta(seconds=18)},
        {"source_published_at": NOW - timedelta(days=1)},
        {"reference": _reference(exchange="SZE")},
    ],
)
def test_prepare_rejects_preview_not_bound_to_capture_receipt(
    preview_changes: dict[str, object],
) -> None:
    captured = _captured(source_published_at=NOW - timedelta(days=2))
    if "source_published_at" not in preview_changes:
        preview_changes["source_published_at"] = captured.source_published_at
    preview = _preview(captured, **preview_changes)
    codec = TokenCodec()
    workbench = _workbench(CapturePort(captured), PreviewPort(preview), codec=codec)

    with pytest.raises(CalendarPublicationOperationsError) as error:
        workbench.prepare_preview(_capture_intent(), proof=_proof())

    assert error.value.code == "CALENDAR_WORKBENCH_PREVIEW_BINDING_MISMATCH"
    assert codec.encoded == []


def test_prepare_bad_preview_type_does_not_mint_token() -> None:
    captured = _captured()
    codec = TokenCodec()
    workbench = _workbench(CapturePort(captured), PreviewPort(object()), codec=codec)

    with pytest.raises(CalendarPublicationOperationsError) as error:
        workbench.prepare_preview(_capture_intent(), proof=_proof())

    assert error.value.code == "CALENDAR_WORKBENCH_PREVIEW_INVALID"
    assert codec.encoded == []


def test_prepare_rejects_catalog_pointer_scope_not_bound_to_exchange() -> None:
    captured = _captured()
    preview = _preview(captured)
    object.__setattr__(
        preview,
        "expected_pointer",
        CalendarPublicationPointerExpectation(
            dataset_key="another.calendar.dataset",
            publication_key="exchange-calendar:SSE",
            pointer_id=None,
            publication_id=None,
            publication_hash=None,
            activation_id=None,
            updated_at=None,
        ),
    )
    codec = TokenCodec()
    workbench = _workbench(CapturePort(captured), PreviewPort(preview), codec=codec)

    with pytest.raises(CalendarPublicationOperationsError) as error:
        workbench.prepare_preview(_capture_intent(), proof=_proof())

    assert error.value.code == "CALENDAR_WORKBENCH_PREVIEW_SCOPE_MISMATCH"
    assert codec.encoded == []


def test_prepare_requires_default_alias_before_capture() -> None:
    capture_port = CapturePort(_captured())
    workbench = _workbench(capture_port, PreviewPort(_preview()))

    with pytest.raises(CalendarPreviewTokenError) as error:
        workbench.prepare_preview(
            _capture_intent(),
            proof=_proof(alias="archive"),
        )

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID"
    assert capture_port.calls == []


@pytest.mark.parametrize(
    "initial_clock",
    [
        NOW - timedelta(seconds=3),
        datetime(2026, 10, 17, 8, 0),
        datetime(2026, 10, 17, 16, 0, tzinfo=timezone(timedelta(hours=8))),
    ],
)
def test_prepare_rejects_invalid_or_rolled_back_clock_before_any_port(
    initial_clock: datetime,
) -> None:
    captured = _captured()
    capture_port = CapturePort(captured)
    preview_port = PreviewPort(_preview(captured))
    codec = TokenCodec()
    clock = SequenceClock((initial_clock,))
    workbench = _workbench(
        capture_port,
        preview_port,
        codec=codec,
        clock=clock,
    )

    with pytest.raises(CalendarPreviewTokenError) as error:
        workbench.prepare_preview(
            _capture_intent(),
            proof=_proof(authenticated_at=NOW - timedelta(seconds=2)),
        )

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID"
    assert clock.calls == 1
    assert capture_port.calls == []
    assert preview_port.calls == []
    assert codec.encoded == []


def test_prepare_rereads_clock_before_encoding_and_honors_original_ttl_expiry() -> None:
    captured = _captured()
    preview = _preview(captured)
    expiration = preview.response_expires_at
    capture_port = CapturePort(captured)
    preview_port = PreviewPort(preview)
    codec = TokenCodec()
    clock = SequenceClock((NOW, expiration))
    workbench = _workbench(
        capture_port,
        preview_port,
        codec=codec,
        clock=clock,
    )

    with pytest.raises(CalendarPreviewTokenError) as error:
        workbench.prepare_preview(_capture_intent(), proof=_proof())

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_EXPIRED"
    assert clock.calls == 2
    assert len(capture_port.calls) == 1
    assert len(preview_port.calls) == 1
    assert codec.encoded == []


def test_prepare_encode_failure_does_not_confirm_or_hide_capture_side_effect() -> None:
    captured = _captured()
    confirmation_port = ConfirmationPort()
    codec = TokenCodec()
    codec.encode_error = CalendarPreviewTokenError(
        "key unavailable", code="CALENDAR_PREVIEW_TOKEN_KEY_UNAVAILABLE"
    )
    workbench = _workbench(
        CapturePort(captured),
        PreviewPort(_preview(captured)),
        confirmation_port,
        codec,
    )

    with pytest.raises(CalendarPreviewTokenError) as error:
        workbench.prepare_preview(_capture_intent(), proof=_proof())

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_KEY_UNAVAILABLE"
    assert confirmation_port.calls == []


def test_capture_failure_short_circuits_preview_and_token_encoding() -> None:
    capture_port = CapturePort(
        CalendarPublicationOperationsError(
            "source unavailable", code="CALENDAR_CAPTURE_TEST_UNAVAILABLE"
        )
    )
    preview_port = PreviewPort(_preview())
    codec = TokenCodec()
    workbench = _workbench(capture_port, preview_port, codec=codec)

    with pytest.raises(CalendarPublicationOperationsError) as error:
        workbench.prepare_preview(_capture_intent(), proof=_proof())

    assert error.value.code == "CALENDAR_CAPTURE_TEST_UNAVAILABLE"
    assert preview_port.calls == []
    assert codec.encoded == []


def test_preview_failure_short_circuits_token_encoding() -> None:
    captured = _captured()
    preview_port = PreviewPort(
        CalendarPublicationOperationsError(
            "catalog unavailable", code="CALENDAR_PREVIEW_TEST_UNAVAILABLE"
        )
    )
    codec = TokenCodec()
    workbench = _workbench(CapturePort(captured), preview_port, codec=codec)

    with pytest.raises(CalendarPublicationOperationsError) as error:
        workbench.prepare_preview(_capture_intent(), proof=_proof())

    assert error.value.code == "CALENDAR_PREVIEW_TEST_UNAVAILABLE"
    assert codec.encoded == []


def test_confirm_decodes_with_current_server_binding_then_forwards_original_intent_only() -> None:
    captured = _captured()
    preview = _preview(captured)
    proof = _proof()
    digest = hashlib.sha256(SESSION_KEY.encode()).hexdigest()
    content = CalendarPreviewTokenContent.from_preview(
        preview,
        actor_user_id=proof.user_id,
        session_key_sha256=digest,
    )
    codec = TokenCodec(content)
    confirmation_port = ConfirmationPort(
        CalendarPublicationOperationsError(
            "publisher sentinel", code="CALENDAR_WORKBENCH_TEST_SENTINEL"
        )
    )
    clock = FixedClock(NOW + timedelta(seconds=1))
    workbench = _workbench(
        CapturePort(captured),
        PreviewPort(preview),
        confirmation_port,
        codec,
        clock,
    )

    with pytest.raises(CalendarPublicationOperationsError) as error:
        workbench.confirm("opaque-input-token", proof=proof)

    assert error.value.code == "CALENDAR_WORKBENCH_TEST_SENTINEL"
    assert codec.decode_calls == [
        {
            "token": "opaque-input-token",
            "actor_user_id": 42,
            "session_key_sha256": digest,
            "database_alias": CALENDAR_PREVIEW_DATABASE_ALIAS,
            "now": NOW + timedelta(seconds=1),
        }
    ]
    assert confirmation_port.calls == [(content.intent, proof)]
    assert clock.calls == 1


@pytest.mark.parametrize("token", ["", "   ", None, 7])
def test_confirm_rejects_invalid_token_before_clock_codec_or_confirmation(token: object) -> None:
    codec = TokenCodec()
    clock = FixedClock(NOW)
    confirmation_port = ConfirmationPort()
    workbench = _workbench(
        CapturePort(_captured()),
        PreviewPort(_preview()),
        confirmation_port,
        codec,
        clock,
    )

    with pytest.raises(CalendarPreviewTokenError) as error:
        workbench.confirm(token, proof=_proof())

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_INVALID"
    assert clock.calls == 0
    assert codec.decode_calls == []
    assert confirmation_port.calls == []


@pytest.mark.parametrize(
    "content_change",
    [
        {"actor_user_id": 43},
        {"session_key_sha256": hashlib.sha256(b"other-session").hexdigest()},
        {"database_alias": "archive"},
        {"previewed_at": NOW + timedelta(seconds=2)},
        {"response_expires_at": NOW + timedelta(seconds=61)},
    ],
)
def test_confirm_rejects_decoded_binding_or_original_ttl_tampering(
    content_change: dict[str, object],
) -> None:
    proof = _proof()
    preview = _preview(_captured())
    content = CalendarPreviewTokenContent.from_preview(
        preview,
        actor_user_id=proof.user_id,
        session_key_sha256=hashlib.sha256(SESSION_KEY.encode()).hexdigest(),
    )
    for field_name, field_value in content_change.items():
        object.__setattr__(content, field_name, field_value)
    codec = TokenCodec(content)
    confirmation_port = ConfirmationPort()
    workbench = _workbench(
        CapturePort(_captured()),
        PreviewPort(preview),
        confirmation_port,
        codec,
        FixedClock(NOW + timedelta(seconds=1)),
    )

    with pytest.raises(CalendarPreviewTokenError):
        workbench.confirm("opaque-token", proof=proof)

    assert confirmation_port.calls == []


def test_confirm_rejects_clock_rollback_before_codec() -> None:
    proof = _proof(authenticated_at=NOW + timedelta(seconds=1))
    codec = TokenCodec()
    clock = FixedClock(NOW)
    confirmation_port = ConfirmationPort()
    workbench = _workbench(
        CapturePort(_captured()),
        PreviewPort(_preview()),
        confirmation_port,
        codec,
        clock,
    )

    with pytest.raises(CalendarPreviewTokenError) as error:
        workbench.confirm("opaque-token", proof=proof)

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID"
    assert codec.decode_calls == []
    assert confirmation_port.calls == []


def test_confirm_bad_codec_content_type_is_rejected_before_confirmation() -> None:
    codec = TokenCodec(object())
    confirmation_port = ConfirmationPort()
    workbench = _workbench(
        CapturePort(_captured()),
        PreviewPort(_preview()),
        confirmation_port,
        codec,
        FixedClock(NOW + timedelta(seconds=1)),
    )

    with pytest.raises(CalendarPreviewTokenError) as error:
        workbench.confirm("opaque-token", proof=_proof())

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID"
    assert confirmation_port.calls == []


def test_confirm_wrong_proof_type_fails_before_clock_codec_or_confirmation() -> None:
    codec = TokenCodec()
    clock = FixedClock(NOW)
    confirmation_port = ConfirmationPort()
    workbench = _workbench(
        CapturePort(_captured()),
        PreviewPort(_preview()),
        confirmation_port,
        codec,
        clock,
    )

    with pytest.raises(CalendarPreviewTokenError) as error:
        workbench.confirm("opaque-token", proof=object())

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID"
    assert clock.calls == 0
    assert codec.decode_calls == []
    assert confirmation_port.calls == []
