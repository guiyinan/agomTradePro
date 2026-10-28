"""Actor, confirmation lifetime and authenticated preview transport regressions."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.core import signing

from apps.data_center.application.price_limit_publication_authority import (
    LockedPriceLimitPublisherPrincipal,
)
from apps.data_center.application.price_limit_publication_operations import (
    ConfirmPriceLimitPublicationUseCase,
    PreviewPriceLimitPublicationIntent,
    PreviewPriceLimitPublicationUseCase,
    PriceLimitPublicationAction,
    PriceLimitPublicationOperationsPort,
    PriceLimitPublicationPreparation,
    PriceLimitPublicationPreview,
    PriceLimitPublicationScope,
)
from apps.data_center.domain.formal_price_limit_publication import (
    PriceLimitFormalPublicationSeal,
    PriceLimitPublicationPointerExpectation,
)
from apps.data_center.infrastructure.price_limit_publication_preview_token import (
    decode_price_limit_preview,
    encode_price_limit_preview,
)
from core.exceptions import AuthorizationError, InvalidInputError
from tests.unit.data_center.test_formal_price_limit_publication import _NOW, _seal


def _inputs(
    seal: PriceLimitFormalPublicationSeal | None = None,
) -> tuple[PriceLimitPublicationPreview, LockedPriceLimitPublisherPrincipal]:
    seal = seal or _seal()
    candidate = seal.snapshot.candidate
    scope = PriceLimitPublicationScope(
        candidate.provider_id,
        candidate.provider_name,
        candidate.asset_code,
        candidate.effective_trade_date,
    )
    principal = cast(
        LockedPriceLimitPublisherPrincipal,
        SimpleNamespace(
            actor_id="django-user:7",
            actor_type="django_user",
            user_id=7,
            permission_codename="publish_price_limit",
            database_alias="default",
            permission_id=9,
            verified_at=_NOW,
            session_expires_at=_NOW + timedelta(minutes=5),
            assert_live=Mock(),
        ),
    )
    preview = PriceLimitPublicationPreview(
        PreviewPriceLimitPublicationIntent(
            scope, PriceLimitPublicationAction.PUBLISH, seal.snapshot.snapshot_id
        ),
        seal.publication_hash,
        PriceLimitPublicationPointerExpectation(
            "equity.price.limit", scope.publication_key, None, None, None, None, None
        ),
        str(uuid4()),
        principal.actor_id,
        _NOW,
        principal.session_expires_at,
    )
    return preview, principal


def test_preview_preserves_original_source_and_locked_session_expiry() -> None:
    seal = _seal()
    original, principal = _inputs(seal)
    repo = Mock(spec=PriceLimitPublicationOperationsPort)
    repo.prepare.return_value = PriceLimitPublicationPreparation(seal, original.expected_pointer)
    result = PreviewPriceLimitPublicationUseCase(
        repo, clock=lambda: _NOW, operation_ids=lambda: original.operation_id
    ).execute(original.intent, principal=principal)
    assert result.preview == original
    assert result.snapshot.recorded_at == seal.snapshot.recorded_at
    repo.confirm.assert_not_called()


def test_substituted_source_is_rejected_before_a_preview_is_issued() -> None:
    original, principal = _inputs()
    repo = Mock(spec=PriceLimitPublicationOperationsPort)
    repo.prepare.return_value = PriceLimitPublicationPreparation(_seal(), original.expected_pointer)
    with pytest.raises(InvalidInputError, match="Prepared source"):
        PreviewPriceLimitPublicationUseCase(
            repo, clock=lambda: _NOW, operation_ids=lambda: original.operation_id
        ).execute(original.intent, principal=principal)


@pytest.mark.parametrize("change", ["actor", "expired", "future", "wrong_permission"])
def test_confirm_rejects_actor_time_or_capability_before_writer(change: str) -> None:
    preview, principal = _inputs()
    now = _NOW + timedelta(seconds=1)
    if change == "actor":
        preview = replace(preview, actor_id="django-user:8")
    elif change == "expired":
        preview = replace(preview, expires_at=now)
    elif change == "future":
        preview = replace(preview, previewed_at=now + timedelta(seconds=1))
    else:
        principal.permission_codename = "publish_exchange_calendar"
    repo = Mock(spec=PriceLimitPublicationOperationsPort)
    with pytest.raises((AuthorizationError, InvalidInputError)):
        ConfirmPriceLimitPublicationUseCase(repo, clock=lambda: now).execute(
            preview, principal=principal
        )
    repo.confirm.assert_not_called()


def test_confirmation_expiry_cannot_be_refreshed_by_a_new_session() -> None:
    preview, principal = _inputs()
    principal.session_expires_at = _NOW + timedelta(days=1)
    repo = Mock(spec=PriceLimitPublicationOperationsPort)
    with pytest.raises(InvalidInputError, match="expired"):
        ConfirmPriceLimitPublicationUseCase(repo, clock=lambda: preview.expires_at).execute(
            preview, principal=principal
        )
    repo.confirm.assert_not_called()


def test_signed_preview_round_trip_and_tamper_rejection() -> None:
    preview, _ = _inputs()
    token = encode_price_limit_preview(preview)
    assert decode_price_limit_preview(token) == preview
    with pytest.raises(InvalidInputError):
        decode_price_limit_preview("x" + token)


def test_another_signing_family_and_extra_claims_are_rejected() -> None:
    preview, _ = _inputs()
    with pytest.raises(InvalidInputError):
        decode_price_limit_preview(
            signing.dumps({"operation_id": preview.operation_id}, salt="another-family")
        )
    token = encode_price_limit_preview(preview)
    payload = signing.loads(token, salt="data-center.price-limit-publication-preview.v1")
    payload["database_alias"] = "other"
    with pytest.raises(InvalidInputError):
        decode_price_limit_preview(
            signing.dumps(payload, salt="data-center.price-limit-publication-preview.v1")
        )


def test_foreign_scope_pointer_is_rejected_before_signing() -> None:
    preview, _ = _inputs()
    with pytest.raises(InvalidInputError):
        replace(
            preview,
            expected_pointer=replace(
                preview.expected_pointer, publication_key="price-limit:" + "0" * 64
            ),
        )
