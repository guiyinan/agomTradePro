"""Pure Application tests for exact/current Evidence scope source reads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.research.application.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1Corruption,
    GetCurrentEvidenceScopeSourceV1,
    GetCurrentEvidenceScopeSourceV1Command,
    GetExactEvidenceScopeSourceV1,
    GetExactEvidenceScopeSourceV1Command,
)
from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.domain.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1,
    root_claim_hash_for_evidence_scope_source_v1,
)

AS_OF = datetime(2026, 8, 15, 10, tzinfo=UTC)


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        owner="research",
        artifact_type="evidence_operator_spec",
        artifact_id="operator-1",
        artifact_version="v1",
        content_hash="a" * 64,
    )


def _root(**changes: object) -> EvidenceScopeSourceV1:
    values: dict[str, object] = {
        "source_id": "scope-source-1",
        "source_version": "v1",
        "owner_id": "owner-1",
        "tenant_id": "tenant-1",
        "account_id": "account-1",
        "actor_id": "actor-1",
        "artifact": _artifact(),
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


def _successor(previous: EvidenceScopeSourceV1, **changes: object) -> EvidenceScopeSourceV1:
    values: dict[str, object] = {
        "source_id": previous.source_id,
        "source_version": "v2",
        "owner_id": previous.owner_id,
        "tenant_id": previous.tenant_id,
        "account_id": previous.account_id,
        "actor_id": previous.actor_id,
        "artifact": previous.artifact,
        "status": "active",
        "recorded_at": previous.recorded_at + timedelta(minutes=1),
        "valid_until": previous.valid_until + timedelta(minutes=1),
        "root_claim_hash": None,
        "supersedes_content_hash": previous.content_hash,
        "identity_hash": "",
        "content_hash": "",
    }
    values.update(changes)
    return EvidenceScopeSourceV1(**values)  # type: ignore[arg-type]


class _Repository:
    def __init__(self, exact: EvidenceScopeSourceV1 | None) -> None:
        self.exact = exact
        self.head = exact
        self.exact_calls = 0
        self.head_calls = 0

    def get_exact(self, **kwargs: object) -> EvidenceScopeSourceV1 | None:
        del kwargs
        self.exact_calls += 1
        return self.exact

    def get_current_head(self, **kwargs: object) -> EvidenceScopeSourceV1 | None:
        del kwargs
        self.head_calls += 1
        return self.head


def _exact_command(source: EvidenceScopeSourceV1) -> GetExactEvidenceScopeSourceV1Command:
    return GetExactEvidenceScopeSourceV1Command(
        source_id=source.source_id,
        source_version=source.source_version,
        expected_content_hash=source.content_hash,
        as_of=AS_OF,
    )


def _current_command(source: EvidenceScopeSourceV1) -> GetCurrentEvidenceScopeSourceV1Command:
    return GetCurrentEvidenceScopeSourceV1Command(
        source_id=source.source_id,
        source_version=source.source_version,
        expected_content_hash=source.content_hash,
        as_of=AS_OF,
    )


def test_exact_is_historical_and_does_not_apply_validity_window() -> None:
    source = _root(valid_until=AS_OF - timedelta(seconds=30))
    repository = _Repository(source)

    result = GetExactEvidenceScopeSourceV1(repository).execute(_exact_command(source))

    assert result == source
    assert repository.exact_calls == 1


def test_exact_missing_returns_none() -> None:
    repository = _Repository(None)
    source = _root()

    assert GetExactEvidenceScopeSourceV1(repository).execute(_exact_command(source)) is None


def test_current_requires_final_head_and_does_not_fallback() -> None:
    source = _root()
    successor = _successor(source)
    repository = _Repository(source)
    repository.head = successor

    assert GetCurrentEvidenceScopeSourceV1(repository).execute(_current_command(source)) is None
    assert repository.head_calls == 1


@pytest.mark.parametrize(
    "source_changes",
    [
        {"status": "revoked"},
        {"valid_until": AS_OF - timedelta(seconds=30)},
    ],
)
def test_current_returns_none_for_terminal_or_expired_source(
    source_changes: dict[str, object],
) -> None:
    source = _root(**source_changes)
    repository = _Repository(source)

    assert GetCurrentEvidenceScopeSourceV1(repository).execute(_current_command(source)) is None
    assert repository.head_calls == 0


def test_current_happy_path_returns_exact_final_head() -> None:
    source = _root()
    repository = _Repository(source)

    assert GetCurrentEvidenceScopeSourceV1(repository).execute(_current_command(source)) == source
    assert repository.exact_calls == 1
    assert repository.head_calls == 1


@pytest.mark.parametrize("attribute", ["content_hash", "tenant_id", "artifact"])
def test_repository_substitution_is_corruption(attribute: str) -> None:
    source = _root()
    repository = _Repository(source)
    replacement = _root()
    object.__setattr__(replacement, attribute, "b" * 64 if attribute == "content_hash" else "bad")
    repository.exact = replacement

    with pytest.raises(EvidenceScopeSourceV1Corruption):
        GetExactEvidenceScopeSourceV1(repository).execute(_exact_command(source))


def test_future_repository_row_is_corruption() -> None:
    source = _root(recorded_at=AS_OF + timedelta(minutes=1))
    repository = _Repository(source)
    command = GetExactEvidenceScopeSourceV1Command(
        source_id=source.source_id,
        source_version=source.source_version,
        expected_content_hash=source.content_hash,
        as_of=AS_OF,
    )

    with pytest.raises(EvidenceScopeSourceV1Corruption):
        GetExactEvidenceScopeSourceV1(repository).execute(command)
