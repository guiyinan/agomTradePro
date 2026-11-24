"""Session-authenticated, CSRF-protected daily benchmark owner operations."""

from datetime import date
from uuid import UUID

from django.http import JsonResponse
from django.urls import path
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from apps.portfolio.benchmark_daily_valuation_composition import (
    publish_benchmark_day,
    start_benchmark_epoch,
)
from apps.portfolio.benchmark_predecessor_composition import revoke_benchmark_statement
from apps.portfolio.domain.policy_benchmark_daily_valuation import BenchmarkDayUnavailable
from core.exceptions import AuthenticationError


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def start_epoch(request: Request) -> JsonResponse:
    """Open a prospective epoch for the authenticated reconciliation owner."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "authentication required"}, status=403)
    form = request.data
    if not isinstance(form, dict):
        return JsonResponse({"error": "expected form object"}, status=400)
    try:
        previous = form.get("previous_epoch")
        if previous is not None and not isinstance(previous, str):
            return JsonResponse({"error": "previous_epoch must be a UUID string"}, status=400)
        if any(
            not isinstance(form.get(key), str) or not form[key].strip()
            for key in ("account_namespace", "account_id", "policy_id", "definition_id")
        ):
            return JsonResponse(
                {"error": "expected nonempty account and configuration selectors"}, status=400
            )
        epoch = start_benchmark_epoch(
            request=request,
            account_namespace=form["account_namespace"],
            account_id=form["account_id"],
            policy_id=form["policy_id"],
            definition_id=form["definition_id"],
            previous_epoch=UUID(previous) if previous is not None else None,
        )
    except AuthenticationError:
        return JsonResponse({"error": "current owner session required"}, status=403)
    except (KeyError, ValueError) as error:
        return JsonResponse({"error": str(error)}, status=409)
    return JsonResponse({"epoch_id": str(epoch)}, status=200)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def close_day(request: Request, epoch_id: UUID) -> JsonResponse:
    """Certify the retained independent custody statement against the exact signed QMT capture."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "authentication required"}, status=403)
    form = request.data
    if not isinstance(form, dict):
        return JsonResponse({"error": "expected form object"}, status=400)
    try:
        packet = request.FILES.get("statement")
        if (
            form.get("certify_complete") != "true"
            or packet is None
            or not 0 < packet.size <= 2_000_000
        ):
            raise BenchmarkDayUnavailable(
                "owner certification and a bounded original day ledger are required"
            )
        fact = publish_benchmark_day(
            request=request,
            epoch_id=epoch_id,
            snapshot_id=int(form["broker_snapshot_id"]),
            original_statement=packet.read(),
        )
    except AuthenticationError:
        return JsonResponse({"error": "current owner session required"}, status=403)
    except (KeyError, ValueError, TypeError) as error:
        return JsonResponse({"error": str(error)}, status=409)
    return JsonResponse(
        {
            "valuation_id": str(fact.valuation_id),
            "version": fact.valuation_version,
            "content_hash": fact.content_hash,
            "observed_at": fact.observed_at.isoformat(),
        },
        status=200,
    )


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def revoke_statement(request: Request, epoch_id: UUID) -> JsonResponse:
    """Withdraw the exact original custody statement and invalidate dependent valuations."""
    form = request.data
    if not isinstance(form, dict):
        return JsonResponse({"error": "expected form object"}, status=400)
    try:
        day = date.fromisoformat(str(form["observation_date"]))
        digest = form["original_hash"]
        if not isinstance(digest, str):
            raise BenchmarkDayUnavailable("expected an exact original hash")
        revoke_benchmark_statement(
            request=request, epoch_id=epoch_id, day=day, original_hash=digest
        )
    except AuthenticationError:
        return JsonResponse({"error": "current owner session required"}, status=403)
    except (KeyError, ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    return JsonResponse({"revoked": True})


urlpatterns = [
    path("epochs/", start_epoch, name="benchmark-valuation-start"),
    path(
        "epochs/<uuid:epoch_id>/statements/revoke/",
        revoke_statement,
        name="benchmark-statement-revoke",
    ),
    path("epochs/<uuid:epoch_id>/close/", close_day, name="benchmark-valuation-close"),
]
