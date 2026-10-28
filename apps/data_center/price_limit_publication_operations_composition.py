"""Wire authenticated management requests to the complete reference publication UoW."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from django.utils import timezone
from rest_framework.request import Request

from apps.data_center.application.price_limit_publication_authority import (
    AuthorizePriceLimitPublisherUseCase,
    LockedPriceLimitPublisherPrincipal,
)
from apps.data_center.application.price_limit_publication_operations import (
    ConfirmPriceLimitPublicationUseCase,
    PreviewPriceLimitPublicationIntent,
    PreviewPriceLimitPublicationUseCase,
    PriceLimitPublicationAction,
    PriceLimitPublicationPreviewResult,
    PriceLimitPublicationReadResult,
    PriceLimitPublicationReceipt,
    ReadPriceLimitPublicationIntent,
    ReadPriceLimitPublicationUseCase,
)
from apps.data_center.infrastructure.formal_price_limit_publication_repository import (
    DjangoFormalPriceLimitPublicationRepository,
)
from apps.data_center.infrastructure.price_limit_publication_authority_repository import (
    DjangoPriceLimitPublisherAuthorityRepository,
)
from apps.data_center.infrastructure.price_limit_publication_preview_token import (
    decode_price_limit_preview,
    encode_price_limit_preview,
)
from apps.data_center.interface.price_limit_publication_session_adapter import (
    PriceLimitPublisherSessionAdapter,
)
from core.exceptions import InvalidInputError
from core.integration.price_limit_formal_publication_audit import (
    CorePriceLimitFormalPublicationAuditBridge,
)


@contextmanager
def _authorized(request: Request) -> Iterator[LockedPriceLimitPublisherPrincipal]:
    proof = PriceLimitPublisherSessionAdapter().prove(request, using="default")
    authorizer = AuthorizePriceLimitPublisherUseCase(
        DjangoPriceLimitPublisherAuthorityRepository(using="default")
    )
    with authorizer.execute(proof) as principal:
        yield principal


def _repository() -> DjangoFormalPriceLimitPublicationRepository:
    return DjangoFormalPriceLimitPublicationRepository(
        CorePriceLimitFormalPublicationAuditBridge(using="default")
    )


def preview_price_limit_publication(
    request: Request, intent: PreviewPriceLimitPublicationIntent
) -> tuple[PriceLimitPublicationPreviewResult, str]:
    """Prepare and sign an exact preview before returning from the authority transaction."""
    with _authorized(request) as principal:
        result = PreviewPriceLimitPublicationUseCase(
            _repository(), clock=timezone.now, operation_ids=lambda: str(uuid4())
        ).execute(intent, principal=principal)
        token = encode_price_limit_preview(result.preview)
    return result, token


def confirm_price_limit_publication(
    request: Request, token: str, *, action: PriceLimitPublicationAction
) -> PriceLimitPublicationReceipt:
    """Recheck the signed action, exact source, current permission and pointer before writing."""
    preview = decode_price_limit_preview(token)
    if preview.intent.action is not action:
        raise InvalidInputError("Confirmation action differs", code="PRICE_LIMIT_ACTION_MISMATCH")
    with _authorized(request) as principal:
        result = ConfirmPriceLimitPublicationUseCase(_repository(), clock=timezone.now).execute(
            preview, principal=principal
        )
    return result


def read_price_limit_publication(
    request: Request, intent: ReadPriceLimitPublicationIntent
) -> PriceLimitPublicationReadResult | None:
    """Read exact/history/current reference evidence under today's explicit permission."""
    with _authorized(request) as principal:
        result = ReadPriceLimitPublicationUseCase(_repository(), clock=timezone.now).execute(
            intent, principal=principal
        )
    return result
