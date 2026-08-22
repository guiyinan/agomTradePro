"""Composition tests for the fail-closed Research evidence read root."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType

from apps.research.application.evidence_reads import ScopedEvidenceReadFacade
from apps.research.application.evidence_scope_source_v1_provider import (
    EvidenceScopeSourceV1Selector,
)
from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.domain.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1,
    root_claim_hash_for_evidence_scope_source_v1,
)
from apps.research.evidence_composition import (
    make_authorized_evidence_read_facade,
    make_evidence_read_facade,
)


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
    module.DjangoEvidenceRepository = lambda **_: repository
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


class _AuthorizedEvidenceRepository(_Repository):
    """Evidence repository sentinel reached only after a valid scope grant."""

    def get_operator_spec(self, **_: object) -> None:
        self.calls += 1
        return None


class _EvidenceRepositoryFactory:
    """Capture the alias used to construct the evidence repository."""

    def __init__(self, repository: _AuthorizedEvidenceRepository) -> None:
        self.repository = repository
        self.aliases: list[str] = []

    def __call__(self, *, using: str = "default") -> _AuthorizedEvidenceRepository:
        self.aliases.append(using)
        return self.repository


class _SelectorProvider:
    def __init__(
        self,
        selector: EvidenceScopeSourceV1Selector | None,
        artifact: ArtifactRef,
    ) -> None:
        self.selector = selector
        self.selector_artifact = artifact

    def get_selector(
        self,
        *,
        artifact: ArtifactRef,
        as_of: datetime,
    ) -> EvidenceScopeSourceV1Selector | None:
        assert artifact == self.selector_artifact
        assert as_of == AS_OF
        return self.selector


class _ScopeRepository:
    aliases: list[str] = []

    def __init__(self, *, using: str = "default") -> None:
        self.aliases.append(using)


class _ScopeReader:
    def __init__(self, source: EvidenceScopeSourceV1) -> None:
        self.source = source

    def execute(self, command: object) -> EvidenceScopeSourceV1:
        del command
        return self.source


AS_OF = datetime(2026, 1, 1, tzinfo=UTC)
selector_artifact = ArtifactRef(
    owner="research",
    artifact_type="evidence_operator_spec",
    artifact_id="operator-1",
    artifact_version="v1",
    content_hash="b" * 64,
)


def _scope_source() -> EvidenceScopeSourceV1:
    root_claim_hash = root_claim_hash_for_evidence_scope_source_v1(
        source_id="scope-1",
        owner_id="owner-1",
        tenant_id="tenant-1",
        account_id="account-1",
        actor_id="actor-1",
        artifact=selector_artifact,
    )
    return EvidenceScopeSourceV1(
        source_id="scope-1",
        source_version="v1",
        owner_id="owner-1",
        tenant_id="tenant-1",
        account_id="account-1",
        actor_id="actor-1",
        artifact=selector_artifact,
        status="active",
        recorded_at=AS_OF - timedelta(minutes=1),
        valid_until=AS_OF + timedelta(minutes=5),
        root_claim_hash=root_claim_hash,
    )


def test_authorized_composition_keeps_scope_and_evidence_on_one_alias(monkeypatch) -> None:
    """Injected selectors wire both ledgers without inventing authority facts."""

    evidence_repository = _AuthorizedEvidenceRepository()
    evidence_factory = _EvidenceRepositoryFactory(evidence_repository)
    _ScopeRepository.aliases = []
    evidence_module = ModuleType("apps.research.infrastructure.evidence_repository")
    evidence_module.DjangoEvidenceRepository = evidence_factory
    scope_module = ModuleType("apps.research.infrastructure.evidence_scope_source_v1_repository")
    scope_module.DjangoEvidenceScopeSourceV1Repository = _ScopeRepository
    monkeypatch.setitem(sys.modules, evidence_module.__name__, evidence_module)
    monkeypatch.setitem(sys.modules, scope_module.__name__, scope_module)
    source = _scope_source()
    monkeypatch.setattr(
        "apps.research.evidence_composition.GetCurrentEvidenceScopeSourceV1",
        lambda repository: _ScopeReader(source),
    )
    selector = EvidenceScopeSourceV1Selector(
        source_id=source.source_id,
        source_version=source.source_version,
        expected_content_hash=source.content_hash,
        owner_id=source.owner_id,
        tenant_id=source.tenant_id,
        account_id=source.account_id,
        actor_id=source.actor_id,
    )
    provider = _SelectorProvider(selector, selector_artifact)

    facade = make_authorized_evidence_read_facade(
        selector_provider=provider,
        using="audit",
    )

    assert type(facade) is ScopedEvidenceReadFacade
    assert _ScopeRepository.aliases == ["audit"]
    assert evidence_factory.aliases == ["audit"]
    assert (
        facade.get_operator_spec(
            operator_id=selector_artifact.artifact_id,
            operator_version=selector_artifact.artifact_version,
            expected_content_hash=selector_artifact.content_hash,
            as_of=AS_OF,
        )
        is None
    )
    assert evidence_repository.calls == 1


def test_authorized_composition_missing_selector_stops_before_evidence_repository(
    monkeypatch,
) -> None:
    """A missing server-issued selector cannot reach the evidence repository."""

    evidence_repository = _AuthorizedEvidenceRepository()
    evidence_factory = _EvidenceRepositoryFactory(evidence_repository)
    _ScopeRepository.aliases = []
    evidence_module = ModuleType("apps.research.infrastructure.evidence_repository")
    evidence_module.DjangoEvidenceRepository = evidence_factory
    scope_module = ModuleType("apps.research.infrastructure.evidence_scope_source_v1_repository")
    scope_module.DjangoEvidenceScopeSourceV1Repository = _ScopeRepository
    monkeypatch.setitem(sys.modules, evidence_module.__name__, evidence_module)
    monkeypatch.setitem(sys.modules, scope_module.__name__, scope_module)
    source = _scope_source()
    monkeypatch.setattr(
        "apps.research.evidence_composition.GetCurrentEvidenceScopeSourceV1",
        lambda repository: _ScopeReader(source),
    )

    facade = make_authorized_evidence_read_facade(
        selector_provider=_SelectorProvider(None, selector_artifact),
        using="audit",
    )

    assert (
        facade.get_operator_spec(
            operator_id=selector_artifact.artifact_id,
            operator_version=selector_artifact.artifact_version,
            expected_content_hash=selector_artifact.content_hash,
            as_of=AS_OF,
        )
        is None
    )
    assert _ScopeRepository.aliases == ["audit"]
    assert evidence_factory.aliases == ["audit"]
    assert evidence_repository.calls == 0
