"""Celery boundary for one explicitly delegated SZSE renewal."""

from uuid import UUID

from django.db import DatabaseError

from apps.data_center.calendar_renewal_composition import TASK_NAME, renew_calendar_grant
from core.exceptions import AgomTradeProException, AuthenticationError, AuthorizationError
from shared.infrastructure.celery_typing import BoundTask, typed_shared_task


def _uuid(value: str | None) -> UUID | None:
    if type(value) is not str:
        return None
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return parsed if str(parsed) == value else None


@typed_shared_task(bind=True, name=TASK_NAME)
def renew_szse_calendar(self: BoundTask, grant_id: str) -> dict[str, str | bool | int]:
    """Resolve one delivery against its durable grant and completion receipt."""
    outcome, reason = "failed", "invalid_input"
    identity = _uuid(grant_id)
    delivery_id = _uuid(self.request.id)
    if identity is not None and delivery_id is not None:
        try:
            reason = renew_calendar_grant(identity, delivery_id=delivery_id)
            outcome = "success" if reason == "renewed" else "noop"
        except (AuthenticationError, AuthorizationError) as exc:
            outcome, reason = "blocked", exc.code
        except AgomTradeProException as exc:
            reason = exc.code
        except DatabaseError:
            reason = "CALENDAR_RENEWAL_STORAGE_FAILURE"
    return {
        "outcome": outcome,
        "reason_code": reason,
        "success": outcome in ("success", "noop"),
        "requested": 1,
        "succeeded": int(outcome == "success"),
        "failed": int(outcome == "failed"),
        "stored": int(outcome == "success"),
    }
