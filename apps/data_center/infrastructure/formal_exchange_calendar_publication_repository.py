"""Stable façade for formal exchange-calendar publication storage."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from django.utils import timezone

from apps.data_center.application.calendar_formal_publication_audit_port import (
    CalendarFormalPublicationAuditPort,
)
from core.exceptions import DataFetchError

from .formal_exchange_calendar_publication_reader import (
    _FormalExchangeCalendarPublicationReader,
)
from .formal_exchange_calendar_publication_support import _CATALOG_MODELS as _CATALOG_MODELS
from .formal_exchange_calendar_publication_support import _DEFAULT_ALIAS as _DEFAULT_ALIAS
from .formal_exchange_calendar_publication_support import _LOCK_TIMEOUT_MS as _LOCK_TIMEOUT_MS
from .formal_exchange_calendar_publication_support import _LOCK_TIMEOUT_RE as _LOCK_TIMEOUT_RE
from .formal_exchange_calendar_publication_support import (
    _LOCK_TIMEOUT_SECONDS as _LOCK_TIMEOUT_SECONDS,
)
from .formal_exchange_calendar_publication_support import _PUBLICATION_MODELS as _PUBLICATION_MODELS
from .formal_exchange_calendar_publication_support import _SQLITE_FENCE_MODEL as _SQLITE_FENCE_MODEL
from .formal_exchange_calendar_publication_support import (
    _bounded_pg_lock_timeout_ms as _bounded_pg_lock_timeout_ms,
)
from .formal_exchange_calendar_publication_support import _is_utc_datetime as _is_utc_datetime
from .formal_exchange_calendar_publication_support import (
    _parse_pg_lock_timeout_ms as _parse_pg_lock_timeout_ms,
)
from .formal_exchange_calendar_publication_support import _parse_uuid as _parse_uuid
from .formal_exchange_calendar_publication_support import (
    _read_pg_lock_timeout as _read_pg_lock_timeout,
)
from .formal_exchange_calendar_publication_support import (
    _set_pg_lock_timeout as _set_pg_lock_timeout,
)
from .formal_exchange_calendar_publication_writer import (
    _FormalExchangeCalendarPublicationWriter,
)


class DjangoFormalExchangeCalendarPublicationRepository(
    _FormalExchangeCalendarPublicationWriter,
    _FormalExchangeCalendarPublicationReader,
):
    """Write and read exact calendar publications using existing DC storage."""

    def __init__(
        self,
        *,
        audit_port: CalendarFormalPublicationAuditPort,
        using: str = _DEFAULT_ALIAS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind one explicit database alias, Audit port, and UTC clock source."""

        if type(using) is not str or not using or using.strip() != using:
            raise DataFetchError(
                "Formal calendar repository requires an explicit database alias",
                code="CALENDAR_FORMAL_DATABASE_ALIAS_INVALID",
            )
        self._using = using
        self._audit_port = audit_port
        self._clock = clock or timezone.now


__all__ = ["DjangoFormalExchangeCalendarPublicationRepository"]
