"""Append-only security audit receivers owned by broker execution."""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_login_failed
from django.db import DatabaseError
from django.dispatch import receiver

from .models import BrokerExecutionAuditModel

logger = logging.getLogger(__name__)


@receiver(user_login_failed, dispatch_uid="broker_execution.audit_login_failed")
def audit_login_failure(
    sender: Any,
    credentials: dict[str, Any],
    request: Any | None,
    **kwargs: Any,
) -> None:
    """Record login failure context without persisting supplied credentials."""

    del sender, kwargs
    username_field = get_user_model().USERNAME_FIELD
    username = str(
        credentials.get(username_field) or credentials.get("username") or "unknown"
    )[:128]
    user = get_user_model()._default_manager.filter(
        **{username_field: username}
    ).first()
    meta = getattr(request, "META", {}) if request is not None else {}
    headers = getattr(request, "headers", {}) if request is not None else {}
    try:
        BrokerExecutionAuditModel._default_manager.create(
            user=user,
            actor=None,
            actor_type="user",
            action="login_failed",
            account_id=0,
            resource_type="user_authentication",
            resource_id=username,
            after={
                "source_ip": str(meta.get("REMOTE_ADDR") or "")[:64],
                "user_agent": str(meta.get("HTTP_USER_AGENT") or "")[:256],
                "result": "denied",
            },
            reason="User authentication failed",
            request_id=str(headers.get("X-Request-ID") or "")[:128],
        )
    except DatabaseError:
        logger.exception("Unable to persist broker execution login failure audit")
