"""Composition tests for the fail-closed Research evidence read root."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import ModuleType

from apps.research.application.evidence_reads import ScopedEvidenceReadFacade
from apps.research.evidence_composition import make_evidence_read_facade


class _Repository:
    """Repository sentinel; the scope gate must stop every call before it."""

    def __init__(self) -> None:
        self.calls = 0

    def get_operator_spec(self, **_: object) -> None:
        self.calls += 1
        return None

    def get_track_record(self, **_: object) -> None:
        self.calls += 1
        return None

    def get_envelope(self, **_: object) -> None:
        self.calls += 1
        return None


def test_default_composition_is_scoped_and_unwired(monkeypatch) -> None:
    """An absent owner/tenant provider cannot fall back to staff-only reads."""

    repository = _Repository()
    module = ModuleType("apps.research.infrastructure.evidence_repository")
    module.DjangoEvidenceRepository = lambda: repository
    monkeypatch.setitem(sys.modules, module.__name__, module)

    facade = make_evidence_read_facade()

    assert type(facade) is ScopedEvidenceReadFacade
    assert (
        facade.get_operator_spec(
            operator_id="operator-1",
            operator_version="v1",
            expected_content_hash="a" * 64,
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
        )
        is None
    )
    assert repository.calls == 0
