from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from django.test import override_settings

from apps.data_center.application.calendar_preview_token import (
    CalendarPreviewTokenContent,
    CalendarPreviewTokenError,
)
from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationPreview,
    CalendarPublicationPreviewIdentity,
)
from apps.data_center.domain.exchange_calendar import ExchangeCalendarSnapshotReference
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarPublicationPointerExpectation,
)
from apps.data_center.infrastructure.calendar_preview_token import (
    MAX_PREVIEW_TOKEN_CHARACTERS,
    MAX_PREVIEW_TOKEN_CONTENT_BYTES,
    EncryptedCalendarPreviewTokenCodec,
)
from shared.config.secrets import clear_secrets_cache
from shared.infrastructure.crypto import FieldEncryptionService

_UTC_NOW = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clear_secret_cache() -> None:
    clear_secrets_cache()
    yield
    clear_secrets_cache()


@pytest.fixture
def encryption_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = FieldEncryptionService.generate_key()
    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", key)
    return key


def _reference() -> ExchangeCalendarSnapshotReference:
    return ExchangeCalendarSnapshotReference(
        snapshot_id=str(uuid4()),
        exchange="SSE",
        coverage_start=date(2026, 10, 1),
        coverage_end=date(2026, 10, 31),
        content_hash=f"sha256:{'1' * 64}",
        record_digest=f"sha256:{'2' * 64}",
        raw_payload_id=str(uuid4()),
        raw_payload_hash=f"sha256:{'3' * 64}",
        raw_record_digest=f"sha256:{'4' * 64}",
    )


def _pointer(*, present: bool) -> CalendarPublicationPointerExpectation:
    if not present:
        return CalendarPublicationPointerExpectation(
            dataset_key="exchange_calendar",
            publication_key="execution",
            pointer_id=None,
            publication_id=None,
            publication_hash=None,
            activation_id=None,
            updated_at=None,
        )
    return CalendarPublicationPointerExpectation(
        dataset_key="exchange_calendar",
        publication_key="execution",
        pointer_id=str(uuid4()),
        publication_id=str(uuid4()),
        publication_hash="5" * 64,
        activation_id="activation-20261017",
        updated_at=_UTC_NOW - timedelta(minutes=3),
    )


def _preview(
    *,
    pointer_present: bool = True,
    first_seen_at: datetime | None = None,
    previewed_at: datetime = _UTC_NOW,
    response_expires_at: datetime | None = None,
) -> CalendarPublicationPreview:
    source_first_seen_at = first_seen_at or (_UTC_NOW - timedelta(minutes=10))
    identity = CalendarPublicationPreviewIdentity(
        dataset_key="exchange_calendar",
        contract_version="calendar-v1",
        schema_version="exchange-calendar-snapshot-v1",
        policy_identity=f"p2:1:{'6' * 64}",
        policy_version="1",
        calendar_response_max_age_seconds=3600,
    )
    expiry = response_expires_at or (
        source_first_seen_at + timedelta(seconds=identity.calendar_response_max_age_seconds)
    )
    snapshot_recorded_at = min(source_first_seen_at + timedelta(seconds=1), previewed_at)
    return CalendarPublicationPreview(
        snapshot_reference=_reference(),
        identity=identity,
        expected_pointer=_pointer(present=pointer_present),
        activation_id="activation-20261017",
        expected_publication_hash="7" * 64,
        first_seen_at=source_first_seen_at,
        snapshot_recorded_at=snapshot_recorded_at,
        source_published_at=None,
        response_expires_at=expiry,
        previewed_at=previewed_at,
        preview_hash="8" * 64,
    )


def _content(*, pointer_present: bool = True) -> CalendarPreviewTokenContent:
    return CalendarPreviewTokenContent.from_preview(
        _preview(pointer_present=pointer_present),
        actor_user_id=42,
        session_key_sha256=hashlib.sha256(b"server-session-secret").hexdigest(),
    )


def test_content_factory_copies_exact_preview_and_original_ttl_clocks() -> None:
    preview = _preview()
    content = CalendarPreviewTokenContent.from_preview(
        preview,
        actor_user_id=42,
        session_key_sha256=hashlib.sha256(b"server-session-secret").hexdigest(),
    )

    assert content.intent == preview.confirmation_intent()
    assert content.first_seen_at == preview.first_seen_at
    assert content.previewed_at == preview.previewed_at
    assert content.response_expires_at == preview.response_expires_at
    assert content.database_alias == "default"


def test_content_factory_rejects_preview_with_extended_source_ttl() -> None:
    preview = _preview(response_expires_at=_UTC_NOW + timedelta(hours=2))

    with pytest.raises(CalendarPreviewTokenError):
        CalendarPreviewTokenContent.from_preview(
            preview,
            actor_user_id=42,
            session_key_sha256=hashlib.sha256(b"server-session-secret").hexdigest(),
        )


def test_content_allows_preview_at_source_completion_boundary() -> None:
    preview = _preview(first_seen_at=_UTC_NOW, previewed_at=_UTC_NOW)

    content = CalendarPreviewTokenContent.from_preview(
        preview,
        actor_user_id=42,
        session_key_sha256=hashlib.sha256(b"server-session-secret").hexdigest(),
    )

    assert content.first_seen_at == content.previewed_at


@pytest.mark.parametrize("pointer_present", [False, True])
def test_token_round_trip_preserves_exact_intent_and_cas(
    encryption_key: str,
    pointer_present: bool,
) -> None:
    codec = EncryptedCalendarPreviewTokenCodec()
    original = _content(pointer_present=pointer_present)

    token = codec.encode(original)
    decoded = codec.decode(
        token,
        actor_user_id=42,
        session_key_sha256=original.session_key_sha256,
        database_alias="default",
        now=_UTC_NOW + timedelta(seconds=1),
    )

    assert decoded == original
    assert decoded.intent.expected_pointer.is_absent is (not pointer_present)
    assert encryption_key not in token


def test_token_ciphertext_does_not_reveal_preview_or_session_content(
    encryption_key: str,
) -> None:
    content = _content()
    token = EncryptedCalendarPreviewTokenCodec().encode(content)

    assert token.startswith(FieldEncryptionService.PREFIX)
    assert content.intent.snapshot_reference.snapshot_id not in token
    assert content.intent.preview_hash not in token
    assert content.session_key_sha256 not in token
    assert "server-session-secret" not in token
    assert encryption_key not in token
    assert content.session_key_sha256 not in repr(content)


def test_decoder_rejects_nonprefixed_plaintext_before_legacy_decrypt_fallback(
    encryption_key: str,
) -> None:
    with pytest.raises(CalendarPreviewTokenError) as error:
        EncryptedCalendarPreviewTokenCodec().decode(
            '{"purpose":"calendar-publication-preview-confirmation"}',
            actor_user_id=42,
            session_key_sha256=hashlib.sha256(b"server-session-secret").hexdigest(),
            database_alias="default",
            now=_UTC_NOW,
        )

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_PREFIX_INVALID"


@pytest.mark.parametrize(
    ("actor_user_id", "session_key_sha256", "database_alias", "expected_code"),
    [
        (
            43,
            hashlib.sha256(b"server-session-secret").hexdigest(),
            "default",
            "CALENDAR_PREVIEW_TOKEN_BINDING_MISMATCH",
        ),
        (
            42,
            hashlib.sha256(b"other-session-secret").hexdigest(),
            "default",
            "CALENDAR_PREVIEW_TOKEN_BINDING_MISMATCH",
        ),
        (
            42,
            hashlib.sha256(b"server-session-secret").hexdigest(),
            "replica",
            "CALENDAR_PREVIEW_TOKEN_BINDING_INVALID",
        ),
    ],
)
def test_decoder_rejects_actor_session_or_alias_binding_mismatch(
    encryption_key: str,
    actor_user_id: int,
    session_key_sha256: str,
    database_alias: str,
    expected_code: str,
) -> None:
    content = _content()
    token = EncryptedCalendarPreviewTokenCodec().encode(content)

    with pytest.raises(CalendarPreviewTokenError) as error:
        EncryptedCalendarPreviewTokenCodec().decode(
            token,
            actor_user_id=actor_user_id,
            session_key_sha256=session_key_sha256,
            database_alias=database_alias,
            now=_UTC_NOW + timedelta(seconds=1),
        )

    assert error.value.code == expected_code


def test_decoder_rejects_original_expiry_and_clock_rollback(
    encryption_key: str,
) -> None:
    content = _content()
    token = EncryptedCalendarPreviewTokenCodec().encode(content)
    codec = EncryptedCalendarPreviewTokenCodec()

    with pytest.raises(CalendarPreviewTokenError) as expired:
        codec.decode(
            token,
            actor_user_id=42,
            session_key_sha256=content.session_key_sha256,
            database_alias="default",
            now=content.response_expires_at,
        )
    assert expired.value.code == "CALENDAR_PREVIEW_TOKEN_EXPIRED"

    with pytest.raises(CalendarPreviewTokenError) as rollback:
        codec.decode(
            token,
            actor_user_id=42,
            session_key_sha256=content.session_key_sha256,
            database_alias="default",
            now=content.previewed_at - timedelta(microseconds=1),
        )
    assert rollback.value.code == "CALENDAR_PREVIEW_TOKEN_CLOCK_INVALID"


def test_decoder_rejects_expiry_extended_inside_valid_encrypted_payload(
    encryption_key: str,
) -> None:
    content = _content()
    codec = EncryptedCalendarPreviewTokenCodec()
    service = FieldEncryptionService(encryption_key=encryption_key)
    payload = json.loads(service.decrypt(codec.encode(content)))
    ttl = content.intent.expected_identity.calendar_response_max_age_seconds
    forged_expiry = content.first_seen_at + timedelta(seconds=ttl + 1)
    payload["response_expires_at"] = forged_expiry.isoformat().replace("+00:00", "Z")
    forged_plaintext = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    forged_token = service.encrypt(forged_plaintext)

    with pytest.raises(CalendarPreviewTokenError) as error:
        codec.decode(
            forged_token,
            actor_user_id=42,
            session_key_sha256=content.session_key_sha256,
            database_alias="default",
            now=_UTC_NOW + timedelta(seconds=1),
        )

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_JSON_INVALID"


def test_content_rejects_expiry_extended_beyond_original_source_ttl() -> None:
    content = _content()
    with pytest.raises(CalendarPreviewTokenError):
        replace(
            content,
            response_expires_at=content.previewed_at + timedelta(hours=2),
        )


def test_content_rejects_expiry_shortened_from_original_source_ttl() -> None:
    content = _content()
    with pytest.raises(CalendarPreviewTokenError):
        replace(
            content,
            response_expires_at=content.response_expires_at - timedelta(seconds=1),
        )


def test_content_rejects_source_ttl_datetime_overflow() -> None:
    content = _content()
    end_of_datetime = datetime.max.replace(tzinfo=UTC)

    with pytest.raises(CalendarPreviewTokenError):
        replace(
            content,
            first_seen_at=end_of_datetime,
            previewed_at=end_of_datetime,
            response_expires_at=end_of_datetime,
        )


def test_decoder_rejects_duplicate_json_keys(
    encryption_key: str,
) -> None:
    codec = EncryptedCalendarPreviewTokenCodec()
    duplicate_payload = (
        '{"purpose":"calendar-publication-preview-confirmation",'
        '"purpose":"other","schema":"calendar-publication-preview-token.v2"}'
    )
    token = FieldEncryptionService(encryption_key=encryption_key).encrypt(duplicate_payload)

    with pytest.raises(CalendarPreviewTokenError) as error:
        codec.decode(
            token,
            actor_user_id=42,
            session_key_sha256=hashlib.sha256(b"server-session-secret").hexdigest(),
            database_alias="default",
            now=_UTC_NOW,
        )

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_JSON_INVALID"


def test_decoder_requires_source_completion_time_in_wire_payload(
    encryption_key: str,
) -> None:
    content = _content()
    codec = EncryptedCalendarPreviewTokenCodec()
    service = FieldEncryptionService(encryption_key=encryption_key)
    payload = json.loads(service.decrypt(codec.encode(content)))
    del payload["first_seen_at"]
    changed_plaintext = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    changed_token = service.encrypt(changed_plaintext)

    with pytest.raises(CalendarPreviewTokenError) as error:
        codec.decode(
            changed_token,
            actor_user_id=42,
            session_key_sha256=content.session_key_sha256,
            database_alias="default",
            now=_UTC_NOW + timedelta(seconds=1),
        )

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_JSON_INVALID"


def test_decoder_requires_canonical_utc_source_completion_text(
    encryption_key: str,
) -> None:
    content = _content()
    codec = EncryptedCalendarPreviewTokenCodec()
    service = FieldEncryptionService(encryption_key=encryption_key)
    payload = json.loads(service.decrypt(codec.encode(content)))
    payload["first_seen_at"] = content.first_seen_at.isoformat()
    changed_plaintext = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    changed_token = service.encrypt(changed_plaintext)

    with pytest.raises(CalendarPreviewTokenError) as error:
        codec.decode(
            changed_token,
            actor_user_id=42,
            session_key_sha256=content.session_key_sha256,
            database_alias="default",
            now=_UTC_NOW + timedelta(seconds=1),
        )

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_JSON_INVALID"


@pytest.mark.parametrize(
    ("changed_field", "changed_value", "expected_code"),
    [
        (
            "schema",
            "calendar-publication-preview-token.v3",
            "CALENDAR_PREVIEW_TOKEN_VERSION_UNSUPPORTED",
        ),
        (
            "purpose",
            "calendar-publication-preview-other",
            "CALENDAR_PREVIEW_TOKEN_PURPOSE_UNSUPPORTED",
        ),
        (
            "purpose",
            None,
            "CALENDAR_PREVIEW_TOKEN_JSON_INVALID",
        ),
    ],
)
def test_decoder_validates_purpose_type_and_rejects_unknown_values(
    encryption_key: str,
    changed_field: str,
    changed_value: object,
    expected_code: str,
) -> None:
    content = _content()
    codec = EncryptedCalendarPreviewTokenCodec()
    token = codec.encode(content)
    plaintext = FieldEncryptionService(encryption_key=encryption_key).decrypt(token)
    payload = json.loads(plaintext)
    payload[changed_field] = changed_value
    changed_plaintext = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    changed_token = FieldEncryptionService(encryption_key=encryption_key).encrypt(changed_plaintext)

    with pytest.raises(CalendarPreviewTokenError) as error:
        codec.decode(
            changed_token,
            actor_user_id=42,
            session_key_sha256=content.session_key_sha256,
            database_alias="default",
            now=_UTC_NOW + timedelta(seconds=1),
        )

    assert error.value.code == expected_code


def test_decoder_rejects_unknown_nested_fields_and_invalid_ttl_type(
    encryption_key: str,
) -> None:
    content = _content()
    codec = EncryptedCalendarPreviewTokenCodec()
    token = codec.encode(content)
    service = FieldEncryptionService(encryption_key=encryption_key)
    payload = json.loads(service.decrypt(token))
    payload["intent"]["expected_pointer"]["future_field"] = "unexpected"
    changed = service.encrypt(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    )

    with pytest.raises(CalendarPreviewTokenError) as unknown_field:
        codec.decode(
            changed,
            actor_user_id=42,
            session_key_sha256=content.session_key_sha256,
            database_alias="default",
            now=_UTC_NOW + timedelta(seconds=1),
        )
    assert unknown_field.value.code == "CALENDAR_PREVIEW_TOKEN_JSON_INVALID"

    payload = json.loads(service.decrypt(token))
    payload["intent"]["expected_identity"]["calendar_response_max_age_seconds"] = True
    changed = service.encrypt(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    )
    with pytest.raises(CalendarPreviewTokenError) as invalid_ttl:
        codec.decode(
            changed,
            actor_user_id=42,
            session_key_sha256=content.session_key_sha256,
            database_alias="default",
            now=_UTC_NOW + timedelta(seconds=1),
        )
    assert invalid_ttl.value.code == "CALENDAR_PREVIEW_TOKEN_JSON_INVALID"


def test_decoder_rejects_token_and_decrypted_content_over_technical_limits(
    encryption_key: str,
) -> None:
    codec = EncryptedCalendarPreviewTokenCodec()
    binding = {
        "actor_user_id": 42,
        "session_key_sha256": hashlib.sha256(b"server-session-secret").hexdigest(),
        "database_alias": "default",
        "now": _UTC_NOW,
    }

    with pytest.raises(CalendarPreviewTokenError) as token_error:
        codec.decode(
            FieldEncryptionService.PREFIX + ("A" * MAX_PREVIEW_TOKEN_CHARACTERS),
            **binding,
        )
    assert token_error.value.code == "CALENDAR_PREVIEW_TOKEN_TOO_LARGE"

    oversized_plaintext = " " * (MAX_PREVIEW_TOKEN_CONTENT_BYTES + 1)
    oversized_ciphertext = FieldEncryptionService(encryption_key=encryption_key).encrypt(
        oversized_plaintext
    )
    with pytest.raises(CalendarPreviewTokenError) as content_error:
        codec.decode(oversized_ciphertext, **binding)
    assert content_error.value.code == "CALENDAR_PREVIEW_TOKEN_TOO_LARGE"


def test_decoder_maps_bounded_deep_json_to_typed_invalid_payload(
    encryption_key: str,
) -> None:
    nested_value = "[" * 3000 + "null" + "]" * 3000
    plaintext = (
        '{"actor_user_id":42,"database_alias":"default",'
        '"first_seen_at":"2026-10-17T07:50:00Z","intent":{},'
        '"previewed_at":"2026-10-17T08:00:00Z","purpose":'
        f"{nested_value}"
        ',"response_expires_at":"2026-10-17T08:20:00Z",'
        '"schema":"calendar-preview-token.v2",'
        f'"session_key_sha256":"{"a" * 64}"' + "}"
    )
    assert len(plaintext.encode("utf-8")) < MAX_PREVIEW_TOKEN_CONTENT_BYTES
    token = FieldEncryptionService(encryption_key=encryption_key).encrypt(plaintext)

    with pytest.raises(CalendarPreviewTokenError) as error:
        EncryptedCalendarPreviewTokenCodec().decode(
            token,
            actor_user_id=42,
            session_key_sha256="a" * 64,
            database_alias="default",
            now=_UTC_NOW,
        )

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_JSON_INVALID"


def test_key_rotation_invalidates_old_tokens_without_key_ring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_key = FieldEncryptionService.generate_key()
    second_key = FieldEncryptionService.generate_key()
    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", first_key)
    clear_secrets_cache()
    content = _content()
    token = EncryptedCalendarPreviewTokenCodec().encode(content)

    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", second_key)
    clear_secrets_cache()
    with pytest.raises(CalendarPreviewTokenError) as error:
        EncryptedCalendarPreviewTokenCodec().decode(
            token,
            actor_user_id=42,
            session_key_sha256=content.session_key_sha256,
            database_alias="default",
            now=_UTC_NOW + timedelta(seconds=1),
        )

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_DECRYPT_FAILED"


def test_missing_encryption_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGOMTRADEPRO_ENCRYPTION_KEY", raising=False)
    clear_secrets_cache()

    with pytest.raises(CalendarPreviewTokenError) as error:
        EncryptedCalendarPreviewTokenCodec().encode(_content())

    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_KEY_UNAVAILABLE"


def test_codec_reads_env_only_key_without_provider_or_settings_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shared.config.secrets as secrets_module

    monkeypatch.setattr(
        secrets_module,
        "_database_secrets_loader",
        lambda: pytest.fail("preview key lookup must not call database provider loader"),
    )
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("AGOMTRADEPRO_ENCRYPTION_KEY", raising=False)
    clear_secrets_cache()
    with override_settings(AGOMTRADEPRO_ENCRYPTION_KEY=FieldEncryptionService.generate_key()):
        with pytest.raises(CalendarPreviewTokenError) as error:
            EncryptedCalendarPreviewTokenCodec().encode(_content())
    assert error.value.code == "CALENDAR_PREVIEW_TOKEN_KEY_UNAVAILABLE"

    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", FieldEncryptionService.generate_key())
    clear_secrets_cache()
    token = EncryptedCalendarPreviewTokenCodec().encode(_content())
    assert token.startswith(FieldEncryptionService.PREFIX)


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("actor_user_id", True),
        ("session_key_sha256", "A" * 64),
        ("database_alias", "replica"),
        ("first_seen_at", _UTC_NOW + timedelta(minutes=1)),
        ("previewed_at", datetime(2026, 10, 17, 8, 0)),
        ("response_expires_at", _UTC_NOW),
    ],
)
def test_content_rejects_invalid_owner_binding_and_time(
    field_name: str,
    field_value: object,
) -> None:
    values: dict[str, object] = {
        "intent": _content().intent,
        "actor_user_id": 42,
        "session_key_sha256": hashlib.sha256(b"server-session-secret").hexdigest(),
        "database_alias": "default",
        "first_seen_at": _UTC_NOW - timedelta(minutes=10),
        "previewed_at": _UTC_NOW,
        "response_expires_at": _UTC_NOW + timedelta(minutes=50),
    }
    values[field_name] = field_value

    with pytest.raises(CalendarPreviewTokenError):
        CalendarPreviewTokenContent(**values)  # type: ignore[arg-type]


def test_wire_payload_uses_exact_schema_and_no_duplicate_keys(
    encryption_key: str,
) -> None:
    content = _content()
    token = EncryptedCalendarPreviewTokenCodec().encode(content)
    plaintext = FieldEncryptionService(encryption_key=encryption_key).decrypt(token)
    decoded = json.loads(plaintext)

    assert set(decoded) == {
        "purpose",
        "schema",
        "actor_user_id",
        "session_key_sha256",
        "database_alias",
        "first_seen_at",
        "previewed_at",
        "response_expires_at",
        "intent",
    }
    assert decoded["schema"] == "calendar-publication-preview-token.v2"
    assert decoded["purpose"] == "calendar-publication-preview-confirmation"
