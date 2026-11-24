"""Fail-closed live-order gate until formal Evidence receipts are integrated."""

from __future__ import annotations

from typing import NoReturn

from django.conf import settings
from django.db import connection

from .use_case_errors import BrokerExecutionConflictError

BROKER_ORDER_EVIDENCE_BLOCKER = "broker_order_evidence_receipt_not_integrated"
BROKER_ORDER_EVIDENCE_BLOCK_MESSAGE = (
    "Live-order execution is blocked until formal Evidence and risk authorization receipts "
    "are integrated"
)


def require_broker_order_evidence(*, checkpoint: str) -> NoReturn:
    """Reject a live-order advancement at one named revalidation checkpoint."""

    normalized = str(checkpoint or "").strip()
    if normalized not in {"create", "approve", "lease", "submitting"}:
        raise ValueError("broker evidence checkpoint is invalid")
    raise BrokerExecutionConflictError(f"{BROKER_ORDER_EVIDENCE_BLOCK_MESSAGE} [{normalized}]")


def broker_order_evidence_integrated() -> bool:
    """Permit source verification only inside the named local PostgreSQL rehearsal database."""
    if settings.SETTINGS_MODULE != "core.settings.critical_postgres_test":
        return False
    db = connection.settings_dict
    name = db["NAME"]
    return (
        connection.vendor == "postgresql"
        and db["HOST"] in {"127.0.0.1", "::1"}
        and isinstance(name, str)
        and name.startswith("test_ash09_rehearsal_")
        and name == db["TEST"]["NAME"]
    )


def blocked_lease_result() -> dict[str, object]:
    """Return a stable, non-mutating Agent poll result while the hard gate is active."""

    return {
        "orders": [],
        "total_count": 0,
        "stopped": True,
        "evidence_gate_active": True,
        "must_not_execute": True,
        "blocker_codes": [BROKER_ORDER_EVIDENCE_BLOCKER],
    }


__all__ = [
    "BROKER_ORDER_EVIDENCE_BLOCKER",
    "BROKER_ORDER_EVIDENCE_BLOCK_MESSAGE",
    "blocked_lease_result",
    "broker_order_evidence_integrated",
    "require_broker_order_evidence",
]
