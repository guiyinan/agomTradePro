"""Pure tests for the dormant Evidence scope-source provider adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.research.application.evidence_scope import (
    EvidenceScopeCorruption,
    EvidenceScopeUnavailable,
    evidence_scope_grant_hash,
)
from apps.research.application.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1Corruption,
    EvidenceScopeSourceV1Unavailable,
    GetCurrentEvidenceScopeSourceV1Command,
)
from apps.research.application.evidence_scope_source_v1_provider import (
    EvidenceScopeSourceV1Provider,
    EvidenceScopeSourceV1Selector,
)
from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.domain.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1,
    root_claim_hash_for_evidence_scope_source_v1,
)

AS_OF = datetime(2026, 8, 15, 10, tzinfo=UTC)


def _artifact(*, artifact_id: str = "operator-1") -> ArtifactRef:
    return ArtifactRef(
        owner="research",
        artifact_type="evidence_operator_spec",
        artifact_id=artifact_id,
        artifact_version="v1",
        content_hash="a" * 64,
    )


def _source(artifact: ArtifactRef | None = None, **changes: object) -> EvidenceScopeSourceV1:
    values: dict[str, object] = {
        "source_id": "scope-source-1",
        "source_version": "v1",
        "owner_id": "owner-1",
        "tenant_id": "tenant-1",
        "account_id": "account-1",
        "actor_id": "actor-1",
        "artifact": artifact or _artifact(),
        "status": "active",
        "recorded_at": AS_OF - timedelta(minutes=1),
        "valid_until": AS_OF + timedelta(hours=1),
        "root_claim_hash": "",
        "supersedes_content_hash": None,
        "identity_hash": "",
        "content_hash": "",
    }
    values.update(changes)
    if values["root_claim_hash"] == "":
        values["root_claim_hash"] = root_claim_hash_for_evidence_scope_source_v1(
            source_id=values["source_id"],
            owner_id=values["owner_id"],
            tenant_id=values["tenant_id"],
            account_id=values["account_id"],
            actor_id=values["actor_id"],
            artifact=values["artifact"],
        )
    return EvidenceScopeSourceV1(**values)  # type: ignore[arg-type]


def _selector(source: EvidenceScopeSourceV1) -> EvidenceScopeSourceV1Selector:
    return EvidenceScopeSourceV1Selector(
        source_id=source.source_id,
        source_version=source.source_version,
        expected_content_hash=source.content_hash,
    )


class _Selectors:
    def __init__(self, selector: EvidenceScopeSourceV1Selector | None) -> None:
        self.selector = selector
        self.calls: list[tuple[ArtifactRef, datetime]] = []

    def get_selector(
        self,
        *,
        artifact: ArtifactRef,
        as_of: datetime,
    ) -> EvidenceScopeSourceV1Selector | None:
        self.calls.append((artifact, as_of))
        return self.selector


class _Reader:
    def __init__(self, source: EvidenceScopeSourceV1 | None = None) -> None:
        self.source = source
        self.calls: list[GetCurrentEvidenceScopeSourceV1Command] = []
        self.error: RuntimeError | None = None

    def execute(
        self, command: GetCurrentEvidenceScopeSourceV1Command
    ) -> EvidenceScopeSourceV1 | None:
        self.calls.append(command)
        if self.error is not None:
            raise self.error
        return self.source


def test_provider_maps_exact_current_source_to_scope_grant() -> None:
    source = _source()
    selectors = _Selectors(_selector(source))
    reader = _Reader(source)

    grant = EvidenceScopeSourceV1Provider(reader=reader, selectors=selectors).get_current_scope(
        artifact=source.artifact,
        as_of=AS_OF,
    )

    assert grant is not None
    assert grant.scope_id == source.source_id
    assert grant.scope_version == source.source_version
    assert grant.actor_id == source.actor_id
    assert grant.tenant_id == source.tenant_id
    assert grant.account_id == source.account_id
    assert grant.artifact == source.artifact
    assert grant.status == source.status
    assert grant.permission == source.permission
    assert grant.recorded_at == source.recorded_at
    assert grant.valid_until == source.valid_until
    assert grant.content_hash == evidence_scope_grant_hash(grant)
    assert len(reader.calls) == 1
    assert reader.calls[0].expected_content_hash == source.content_hash


def test_missing_selector_is_unavailable_without_reading_source() -> None:
    selectors = _Selectors(None)
    reader = _Reader()

    result = EvidenceScopeSourceV1Provider(reader=reader, selectors=selectors).get_current_scope(
        artifact=_artifact(),
        as_of=AS_OF,
    )

    assert result is None
    assert reader.calls == []


@pytest.mark.parametrize(
    "source_changes",
    [
        {"status": "revoked"},
        {"valid_until": AS_OF - timedelta(seconds=1)},
    ],
)
def test_terminal_or_expired_source_returns_none_without_scope_grant(
    source_changes: dict[str, object],
) -> None:
    source = _source(**source_changes)

    result = EvidenceScopeSourceV1Provider(
        reader=_Reader(source),
        selectors=_Selectors(_selector(source)),
    ).get_current_scope(artifact=source.artifact, as_of=AS_OF)

    assert result is None


def test_reader_missing_source_returns_none() -> None:
    source = _source()

    result = EvidenceScopeSourceV1Provider(
        reader=_Reader(None),
        selectors=_Selectors(_selector(source)),
    ).get_current_scope(artifact=source.artifact, as_of=AS_OF)

    assert result is None


@pytest.mark.parametrize(
    "replacement",
    [
        _source(artifact=_artifact(artifact_id="different")),
        _source(tenant_id="different-tenant"),
    ],
)
def test_reader_substitution_is_scope_corruption(
    replacement: EvidenceScopeSourceV1,
) -> None:
    expected = _source()

    with pytest.raises(EvidenceScopeCorruption):
        EvidenceScopeSourceV1Provider(
            reader=_Reader(replacement),
            selectors=_Selectors(_selector(expected)),
        ).get_current_scope(artifact=expected.artifact, as_of=AS_OF)


def test_selector_provider_invalid_data_is_scope_corruption() -> None:
    class _BadSelectors:
        def get_selector(
            self, *, artifact: ArtifactRef, as_of: datetime
        ) -> EvidenceScopeSourceV1Selector:
            del artifact, as_of
            return object()  # type: ignore[return-value]

    with pytest.raises(EvidenceScopeCorruption):
        EvidenceScopeSourceV1Provider(
            reader=_Reader(),
            selectors=_BadSelectors(),
        ).get_current_scope(artifact=_artifact(), as_of=AS_OF)


@pytest.mark.parametrize(
    "error, expected",
    [
        (EvidenceScopeSourceV1Unavailable("missing selector"), EvidenceScopeUnavailable),
        (EvidenceScopeSourceV1Corruption("bad selector"), EvidenceScopeCorruption),
    ],
)
def test_selector_provider_errors_map_to_scope_taxonomy(
    error: RuntimeError,
    expected: type[RuntimeError],
) -> None:
    class _FailingSelectors:
        def get_selector(
            self, *, artifact: ArtifactRef, as_of: datetime
        ) -> EvidenceScopeSourceV1Selector | None:
            del artifact, as_of
            raise error

    with pytest.raises(expected):
        EvidenceScopeSourceV1Provider(
            reader=_Reader(),
            selectors=_FailingSelectors(),
        ).get_current_scope(artifact=_artifact(), as_of=AS_OF)


@pytest.mark.parametrize(
    "error, expected",
    [
        (EvidenceScopeSourceV1Unavailable("missing"), EvidenceScopeUnavailable),
        (EvidenceScopeSourceV1Corruption("bad"), EvidenceScopeCorruption),
        (RuntimeError("tenant database secret"), EvidenceScopeUnavailable),
    ],
)
def test_reader_errors_map_to_scope_taxonomy(
    error: RuntimeError,
    expected: type[RuntimeError],
) -> None:
    source = _source()
    reader = _Reader(source)
    reader.error = error

    with pytest.raises(expected):
        EvidenceScopeSourceV1Provider(
            reader=reader,
            selectors=_Selectors(_selector(source)),
        ).get_current_scope(artifact=source.artifact, as_of=AS_OF)


def test_unexpected_reader_failure_is_sanitized() -> None:
    source = _source()
    reader = _Reader(source)
    reader.error = RuntimeError("database password must not escape")

    with pytest.raises(EvidenceScopeUnavailable, match="scope source is unavailable") as exc:
        EvidenceScopeSourceV1Provider(
            reader=reader,
            selectors=_Selectors(_selector(source)),
        ).get_current_scope(artifact=source.artifact, as_of=AS_OF)

    assert "database password" not in str(exc.value)


def test_source_hash_tamper_is_scope_corruption() -> None:
    source = _source()
    object.__setattr__(source, "tenant_id", "tampered-tenant")

    with pytest.raises(EvidenceScopeCorruption):
        EvidenceScopeSourceV1Provider(
            reader=_Reader(source),
            selectors=_Selectors(_selector(source)),
        ).get_current_scope(artifact=source.artifact, as_of=AS_OF)


@pytest.mark.parametrize(
    "artifact, as_of",
    [
        (object(), AS_OF),
        (_artifact(), datetime(2026, 8, 15, 10)),
    ],
)
def test_provider_rejects_invalid_request_boundary(
    artifact: object,
    as_of: datetime,
) -> None:
    with pytest.raises(TypeError if not isinstance(artifact, ArtifactRef) else ValueError):
        EvidenceScopeSourceV1Provider(
            reader=_Reader(),
            selectors=_Selectors(None),
        ).get_current_scope(
            artifact=artifact, as_of=as_of
        )  # type: ignore[arg-type]
