"""Authenticate server-prepared confirmation claims without storing duplicate drafts."""

from __future__ import annotations

from datetime import date, datetime
from typing import cast

from django.core import signing

from apps.data_center.application.price_limit_publication_operations import (
    PreviewPriceLimitPublicationIntent,
    PriceLimitPublicationAction,
    PriceLimitPublicationPreview,
    PriceLimitPublicationScope,
)
from apps.data_center.domain.formal_price_limit_publication import (
    PriceLimitPublicationPointerExpectation,
)
from core.exceptions import InvalidInputError

_SALT = "data-center.price-limit-publication-preview.v1"


def encode_price_limit_preview(preview: PriceLimitPublicationPreview) -> str:
    """Sign only exact preview claims using Django's configured signing key."""
    preview.__post_init__()
    intent, pointer = preview.intent, preview.expected_pointer
    return signing.dumps(
        {
            "schema": _SALT,
            "provider_id": intent.scope.provider_id,
            "provider_name": intent.scope.provider_name,
            "asset_code": intent.scope.asset_code,
            "effective_trade_date": intent.scope.effective_trade_date.isoformat(),
            "action": intent.action.value,
            "snapshot_id": intent.snapshot_id,
            "target_publication_id": intent.target_publication_id,
            "reason": intent.reason,
            "publication_hash": preview.publication_hash,
            "pointer_id": pointer.pointer_id,
            "current_publication_id": pointer.publication_id,
            "current_publication_hash": pointer.publication_hash,
            "current_activation_id": pointer.activation_id,
            "current_updated_at": pointer.updated_at.isoformat() if pointer.updated_at else None,
            "operation_id": preview.operation_id,
            "actor_id": preview.actor_id,
            "previewed_at": preview.previewed_at.isoformat(),
            "expires_at": preview.expires_at.isoformat(),
        },
        salt=_SALT,
        compress=False,
    )


def decode_price_limit_preview(token: str) -> PriceLimitPublicationPreview:
    """Verify the signature before narrowing claims; expiry is rechecked under authorization."""
    if type(token) is not str or not token or len(token) > 16384:
        raise _invalid()
    try:
        raw: object = signing.loads(token, salt=_SALT)
        if not isinstance(raw, dict):
            raise _invalid()
        payload = cast(dict[str, object], raw)
        expected_keys = {
            "schema",
            "provider_id",
            "provider_name",
            "asset_code",
            "effective_trade_date",
            "action",
            "snapshot_id",
            "target_publication_id",
            "reason",
            "publication_hash",
            "pointer_id",
            "current_publication_id",
            "current_publication_hash",
            "current_activation_id",
            "current_updated_at",
            "operation_id",
            "actor_id",
            "previewed_at",
            "expires_at",
        }
        if set(payload) != expected_keys or payload["schema"] != _SALT:
            raise _invalid()
        provider_id = payload["provider_id"]
        if type(provider_id) is not int:
            raise _invalid()
        scope = PriceLimitPublicationScope(
            provider_id,
            _text(payload, "provider_name"),
            _text(payload, "asset_code"),
            date.fromisoformat(_text(payload, "effective_trade_date")),
        )
        updated_at = _optional_text(payload, "current_updated_at")
        pointer = PriceLimitPublicationPointerExpectation(
            "equity.price.limit",
            scope.publication_key,
            _optional_text(payload, "pointer_id"),
            _optional_text(payload, "current_publication_id"),
            _optional_text(payload, "current_publication_hash"),
            _optional_text(payload, "current_activation_id"),
            datetime.fromisoformat(updated_at) if updated_at is not None else None,
        )
        return PriceLimitPublicationPreview(
            intent=PreviewPriceLimitPublicationIntent(
                scope,
                PriceLimitPublicationAction(_text(payload, "action")),
                _optional_text(payload, "snapshot_id"),
                _optional_text(payload, "target_publication_id"),
                _text(payload, "reason"),
            ),
            publication_hash=_text(payload, "publication_hash"),
            expected_pointer=pointer,
            operation_id=_text(payload, "operation_id"),
            actor_id=_text(payload, "actor_id"),
            previewed_at=datetime.fromisoformat(_text(payload, "previewed_at")),
            expires_at=datetime.fromisoformat(_text(payload, "expires_at")),
        )
    except (signing.BadSignature, KeyError, TypeError, ValueError) as error:
        raise _invalid() from error


def _text(payload: dict[str, object], key: str) -> str:
    value = payload[key]
    if type(value) is not str:
        raise _invalid()
    return value


def _optional_text(payload: dict[str, object], key: str) -> str | None:
    value = payload[key]
    if value is None:
        return None
    return _text(payload, key)


def _invalid() -> InvalidInputError:
    return InvalidInputError(
        "Publication confirmation token is invalid", code="PRICE_LIMIT_PREVIEW_TOKEN_INVALID"
    )
