"""JSON adapters for explicitly authorized price-limit reference management."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import cast
from uuid import UUID

from django.http import QueryDict
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.data_center.application.price_limit_publication_operations import (
    PreviewPriceLimitPublicationIntent,
    PriceLimitPublicationAction,
    PriceLimitPublicationReceipt,
    PriceLimitPublicationScope,
    ReadPriceLimitPublicationIntent,
)
from apps.data_center.domain.formal_price_limit_publication import (
    PriceLimitFormalPublicationRecord,
    PriceLimitPublicationError,
)
from apps.data_center.domain.price_limit_snapshot import PriceLimitSnapshotError
from apps.data_center.price_limit_publication_operations_composition import (
    confirm_price_limit_publication,
    preview_price_limit_publication,
    read_price_limit_publication,
)
from core.exceptions import AgomTradeProException, InvalidInputError

_SCOPE_KEYS = {"provider_id", "provider_name", "asset_code", "effective_trade_date"}


def _object(data: object, allowed: set[str]) -> dict[str, object]:
    if not isinstance(data, Mapping) or any(type(key) is not str for key in data):
        raise InvalidInputError("Expected an object", code="PRICE_LIMIT_INPUT_INVALID")
    if set(data) - allowed:
        raise InvalidInputError("Unknown input fields", code="PRICE_LIMIT_INPUT_INVALID")
    if isinstance(data, QueryDict) and any(len(data.getlist(key)) != 1 for key in data):
        raise InvalidInputError("Repeated query fields", code="PRICE_LIMIT_INPUT_INVALID")
    return {cast(str, key): value for key, value in data.items()}


def _text(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if type(value) is not str:
        raise InvalidInputError(f"{key} must be text", code="PRICE_LIMIT_INPUT_INVALID")
    return value


def _scope(data: dict[str, object], *, query: bool) -> PriceLimitPublicationScope:
    provider_id = data.get("provider_id")
    if query and type(provider_id) is str and re.fullmatch(r"[1-9][0-9]*", provider_id):
        provider_id = int(provider_id)
    if type(provider_id) is not int:
        raise InvalidInputError("provider_id must be an integer", code="PRICE_LIMIT_INPUT_INVALID")
    raw_date = _text(data, "effective_trade_date")
    try:
        effective_date = date.fromisoformat(raw_date)
    except ValueError as error:
        raise InvalidInputError(
            "Invalid effective date", code="PRICE_LIMIT_INPUT_INVALID"
        ) from error
    if effective_date.isoformat() != raw_date:
        raise InvalidInputError("Use an ISO date", code="PRICE_LIMIT_INPUT_INVALID")
    return PriceLimitPublicationScope(
        provider_id, _text(data, "provider_name"), _text(data, "asset_code"), effective_date
    )


def _reference_flags() -> dict[str, object]:
    return {
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "blocked_reason": "PRICE_LIMIT_REFERENCE_ONLY",
        "freshness": "unknown",
        "reliability": "reference_only",
        "coverage_scope": "single_explicit_provider_security_date",
    }


def _record(record: PriceLimitFormalPublicationRecord) -> dict[str, object]:
    return {
        "publication_id": record.publication_id,
        "publication_hash": record.publication_hash,
        "first_published_at": record.first_published_at.isoformat(),
        "first_activation_id": record.first_activation_id,
        "member_manifest_hash": record.seal.member_manifest_hash,
        "snapshot": record.seal.snapshot.to_payload(),
        **_reference_flags(),
    }


def _receipt(receipt: PriceLimitPublicationReceipt) -> dict[str, object]:
    return {
        **_record(receipt.record),
        "operation_id": receipt.operation_id,
        "replayed": receipt.replayed,
        "visible_from": (
            receipt.pointer.updated_at.isoformat() if receipt.pointer.updated_at else None
        ),
    }


class _PriceLimitJsonView(APIView):
    """Require JSON, a real authenticated session, and explicit locked permissions."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)

    def handle_exception(self, exc: Exception) -> Response:
        """Preserve stable business/Domain denial codes in JSON responses."""
        if isinstance(exc, AgomTradeProException):
            return Response(
                {"error": exc.message, "code": exc.code, **_reference_flags()},
                status=exc.status_code,
            )
        if isinstance(exc, (PriceLimitPublicationError, PriceLimitSnapshotError)):
            return Response({"error": str(exc), "code": exc.code, **_reference_flags()}, status=422)
        return super().handle_exception(exc)


class PriceLimitPublicationPreviewView(_PriceLimitJsonView):
    """Prepare a signed publish or rollback preview without changing any pointer."""

    def post(self, request: Request) -> Response:
        """Validate explicit scope and exact target, then return the original reference values."""
        data = _object(
            request.data, _SCOPE_KEYS | {"action", "snapshot_id", "target_publication_id", "reason"}
        )
        try:
            action = PriceLimitPublicationAction(_text(data, "action"))
        except ValueError as error:
            raise InvalidInputError("Unknown action", code="PRICE_LIMIT_ACTION_INVALID") from error
        intent = PreviewPriceLimitPublicationIntent(
            _scope(data, query=False),
            action,
            _text(data, "snapshot_id") if "snapshot_id" in data else None,
            _text(data, "target_publication_id") if "target_publication_id" in data else None,
            _text(data, "reason") if "reason" in data else "",
        )
        result, token = preview_price_limit_publication(request, intent)
        return Response(
            {
                "confirmation_token": token,
                "operation_id": result.preview.operation_id,
                "publication_hash": result.preview.publication_hash,
                "expires_at": result.preview.expires_at.isoformat(),
                "snapshot": result.snapshot.to_payload(),
                **_reference_flags(),
            }
        )


class PriceLimitPublicationConfirmView(_PriceLimitJsonView):
    """Confirm only a server-signed publish preview."""

    def post(self, request: Request) -> Response:
        """Publish exact reference evidence after live authority and CAS revalidation."""
        data = _object(request.data, {"confirmation_token"})
        receipt = confirm_price_limit_publication(
            request, _text(data, "confirmation_token"), action=PriceLimitPublicationAction.PUBLISH
        )
        return Response(_receipt(receipt), status=200)


class PriceLimitPublicationRollbackView(_PriceLimitJsonView):
    """Confirm only an explicit signed rollback preview."""

    def post(self, request: Request) -> Response:
        """Move the pointer with an immutable reason and the original history preserved."""
        data = _object(request.data, {"confirmation_token"})
        receipt = confirm_price_limit_publication(
            request, _text(data, "confirmation_token"), action=PriceLimitPublicationAction.ROLLBACK
        )
        return Response(_receipt(receipt), status=200)


def _read_response(
    request: Request, *, history: bool = False, publication_id: UUID | None = None
) -> Response:
    data = _object(request.query_params, _SCOPE_KEYS | ({"as_of"} if history else set()))
    cutoff: datetime | None = None
    if history:
        try:
            cutoff = datetime.fromisoformat(_text(data, "as_of"))
        except ValueError as error:
            raise InvalidInputError("Invalid cutoff", code="PRICE_LIMIT_INPUT_INVALID") from error
    intent = ReadPriceLimitPublicationIntent(
        _scope(data, query=True), cutoff, str(publication_id) if publication_id else None
    )
    result = read_price_limit_publication(request, intent)
    if result is None:
        return Response(
            {"code": "PRICE_LIMIT_PUBLICATION_NOT_FOUND", **_reference_flags()}, status=404
        )
    return Response(
        {
            **_record(result.record),
            "as_of": result.as_of.isoformat(),
            "lookup_basis": result.lookup_basis,
            "visible_from": result.visible_from.isoformat() if result.visible_from else None,
        }
    )


class CurrentPriceLimitPublicationView(_PriceLimitJsonView):
    """Read this exact request scope's current reference, without a freshness claim."""

    def get(self, request: Request) -> Response:
        """Read under current explicit publisher authority."""
        return _read_response(request)


class HistoricalPriceLimitPublicationView(_PriceLimitJsonView):
    """Read the publication actually visible at a supplied historical cutoff."""

    def get(self, request: Request) -> Response:
        """Resolve the verified publication/rollback event chain."""
        return _read_response(request, history=True)


class ExactPriceLimitPublicationView(_PriceLimitJsonView):
    """Read one exact historical publication without calling it current."""

    def get(self, request: Request, publication_id: UUID) -> Response:
        """Require the original full scope and current management permission."""
        return _read_response(request, publication_id=publication_id)
