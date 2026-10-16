from __future__ import annotations

import pytest

from apps.audit.calendar_publication_composition import (
    build_calendar_publication_audit_coordinator,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from core.exceptions import InvalidInputError


def test_public_calendar_composition_returns_exact_coordinator_for_alias() -> None:
    """The public composition factory binds the canonical coordinator to its alias."""

    coordinator = build_calendar_publication_audit_coordinator(using="default")

    assert type(coordinator) is DjangoSystemAuditEventOutboxCoordinator
    assert coordinator.database_alias == "default"


@pytest.mark.parametrize("using", ["", "   "])
def test_public_calendar_composition_rejects_empty_alias_with_typed_error(
    using: str,
) -> None:
    """An omitted or whitespace-only alias cannot choose a transaction target."""

    with pytest.raises(InvalidInputError) as error:
        build_calendar_publication_audit_coordinator(using=using)

    assert error.value.code == "CALENDAR_PUBLICATION_AUDIT_ALIAS_INVALID"
