"""Pure tests for the dormant Evidence owner/tenant scope boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.research.application.evidence_reads import (
    EvidenceReadFacade,
    ScopedEvidenceReadFacade,
)
from apps.research.application.evidence_scope import (
    EvidenceScopeAuthorizer,
    EvidenceScopeCorruption,
    EvidenceScopeGrant,
    EvidenceScopeUnavailable,
)
from apps.research.domain.evidence_contracts import ArtifactRef

AS_OF = datetime(2026, 8, 15, 9, tzinfo=UTC)


def _artifact(*, owner: str = "research", content_hash: str = "a" * 64) -> ArtifactRef:
    return ArtifactRef(
        owner=owner,
        artifact_type="evidence_operator_spec",
        artifact_id="operator-1",
        artifact_version="v1",
        content_hash=content_hash,
    )


def _grant(artifact: ArtifactRef | None = None, **changes: object) -> EvidenceScopeGrant:
    values: dict[str, object] = {
        "scope_id": "scope-1",
        "scope_version": "v1",
        "actor_id": "actor-1",
        "tenant_id": "tenant-1",
        "account_id": "account-1",
        "artifact": artifact or _artifact(),
        "status": "active",
        "permission": "read_only",
        "recorded_at": AS_OF - timedelta(minutes=1),
        "valid_until": AS_OF + timedelta(hours=1),
        "content_hash": "",
    }
    values.update(changes)
    return EvidenceScopeGrant(**values)  # type: ignore[arg-type]


class _Provider:
    def __init__(self, grant: EvidenceScopeGrant | None) -> None:
        self.grant = grant
        self.calls: list[tuple[ArtifactRef, datetime]] = []

    def get_current_scope(
        self,
        *,
        artifact: ArtifactRef,
        as_of: datetime,
    ) -> EvidenceScopeGrant | None:
        self.calls.append((artifact, as_of))
        return self.grant


class _EchoProvider:
    def get_current_scope(
        self,
        *,
        artifact: ArtifactRef,
        as_of: datetime,
    ) -> EvidenceScopeGrant:
        del as_of
        return _grant(artifact)


class _ExplodingProvider:
    def get_current_scope(
        self,
        *,
        artifact: ArtifactRef,
        as_of: datetime,
    ) -> EvidenceScopeGrant:
        del artifact, as_of
        raise RuntimeError("database credentials must not escape")


class _Reads:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_operator_spec(self, **kwargs: object) -> None:
        self.calls.append("operator")
        return None

    def get_track_record(self, **kwargs: object) -> None:
        self.calls.append("track")
        return None

    def get_envelope(self, **kwargs: object) -> None:
        self.calls.append("envelope")
        return None


def test_authorizer_requires_exact_active_artifact_scope() -> None:
    provider = _Provider(_grant())

    result = EvidenceScopeAuthorizer(provider).require(
        artifact=_artifact(),
        as_of=AS_OF,
    )

    assert result.scope_id == "scope-1"
    assert provider.calls == [(_artifact(), AS_OF)]


@pytest.mark.parametrize(
    "grant, error",
    [
        (None, EvidenceScopeUnavailable),
        (_grant(status="revoked"), EvidenceScopeUnavailable),
        (_grant(recorded_at=AS_OF + timedelta(minutes=1)), EvidenceScopeUnavailable),
        (_grant(valid_until=AS_OF), EvidenceScopeUnavailable),
        (_grant(_artifact(owner="other")), EvidenceScopeCorruption),
    ],
)
def test_authorizer_fail_closed_for_missing_stale_or_substituted_scope(
    grant: EvidenceScopeGrant | None,
    error: type[RuntimeError],
) -> None:
    with pytest.raises(error):
        EvidenceScopeAuthorizer(_Provider(grant)).require(
            artifact=_artifact(),
            as_of=AS_OF,
        )


def test_scope_hash_tamper_is_corruption() -> None:
    grant = _grant()
    object.__setattr__(grant, "tenant_id", "tenant-tampered")

    with pytest.raises(EvidenceScopeCorruption):
        EvidenceScopeAuthorizer(_Provider(grant)).require(
            artifact=_artifact(),
            as_of=AS_OF,
        )


def test_authorizer_sanitizes_unexpected_provider_failures() -> None:
    with pytest.raises(
        EvidenceScopeUnavailable,
        match="current evidence scope is unavailable",
    ) as exc:
        EvidenceScopeAuthorizer(_ExplodingProvider()).require(
            artifact=_artifact(),
            as_of=AS_OF,
        )

    assert "database credentials" not in str(exc.value)


def test_scoped_facade_authorizes_all_three_reads_before_repository_calls() -> None:
    reads = _Reads()
    artifact = _artifact()
    facade = EvidenceReadFacade(
        reads,
        scope_authorizer=EvidenceScopeAuthorizer(_EchoProvider()),
    )

    facade.get_operator_spec(
        operator_id=artifact.artifact_id,
        operator_version=artifact.artifact_version,
        expected_content_hash=artifact.content_hash,
        as_of=AS_OF,
    )
    facade.get_track_record(
        snapshot_id=artifact.artifact_id,
        snapshot_version=artifact.artifact_version,
        expected_content_hash=artifact.content_hash,
        as_of=AS_OF,
    )
    facade.get_envelope(
        output_owner=artifact.owner,
        output_artifact_type=artifact.artifact_type,
        output_artifact_id=artifact.artifact_id,
        output_artifact_version=artifact.artifact_version,
        expected_content_hash=artifact.content_hash,
        as_of=AS_OF,
    )

    assert reads.calls == ["operator", "track", "envelope"]


def test_scoped_facade_does_not_touch_repository_when_scope_is_missing() -> None:
    reads = _Reads()
    facade = EvidenceReadFacade(
        reads,
        scope_authorizer=EvidenceScopeAuthorizer(_Provider(None)),
    )

    assert (
        facade.get_operator_spec(
            operator_id="operator-1",
            operator_version="v1",
            expected_content_hash="a" * 64,
            as_of=AS_OF,
        )
        is None
    )

    assert reads.calls == []


def test_scoped_facade_requires_authorizer_at_construction() -> None:
    reads = _Reads()

    with pytest.raises(TypeError):
        ScopedEvidenceReadFacade(reads, scope_authorizer=object())  # type: ignore[arg-type]

    facade = ScopedEvidenceReadFacade(
        reads,
        scope_authorizer=EvidenceScopeAuthorizer(_Provider(None)),
    )
    assert (
        facade.get_operator_spec(
            operator_id="operator-1",
            operator_version="v1",
            expected_content_hash="a" * 64,
            as_of=AS_OF,
        )
        is None
    )
    assert reads.calls == []
