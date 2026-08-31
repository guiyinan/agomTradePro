from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.audit.application.system_audit_archive import (
    BuildSystemAuditArchiveCommand,
    BuildSystemAuditArchiveUseCase,
    RestoreSystemAuditArchiveCommand,
    RestoreSystemAuditArchiveUseCase,
    SystemAuditArchiveCandidate,
    SystemAuditArchiveCandidateProvider,
    SystemAuditArchiveCorruption,
    SystemAuditArchiveUnavailable,
)
from apps.audit.application.system_audit_query import SystemAuditReaderContext
from apps.audit.domain.system_audit_event import AuditScopeRef, SystemAuditEvent
from apps.audit.infrastructure.system_audit_archive_codec import (
    AppendOnlySystemAuditArchiveStore,
    CanonicalSystemAuditArchiveCodec,
    SystemAuditArchiveStoreError,
)
from tests.unit.audit.test_system_audit_event import make_event

NOW = datetime(2026, 8, 31, 2, 0, tzinfo=UTC)
SCOPE = AuditScopeRef("tenant:primary", "owner:research")
OTHER_SCOPE = AuditScopeRef("tenant:other", "owner:research")
CANDIDATE = SystemAuditArchiveCandidate(
    commit="8" * 40,
    version="20260830215638",
    oci_revision=f"sha256:{'c' * 64}",
    matrix_sha256="a" * 64,
)


def _reader(*, staff: bool = True, scope: AuditScopeRef = SCOPE) -> SystemAuditReaderContext:
    return SystemAuditReaderContext._from_authority(
        authority_source_id="authority:archive-test",
        authority_source_version="v1",
        actor_id="django-user:7",
        user_id=7,
        tenant_id=scope.tenant_id,
        owner_id=scope.owner_id,
        authority_content_hash="b" * 64,
        is_authenticated=True,
        is_staff=staff,
        role="operations",
        authority_state="active",
        authority_recorded_at=NOW - timedelta(hours=1),
        authority_valid_until=NOW + timedelta(days=1),
    )


def _event(
    *,
    stream_id: str,
    sequence_no: int,
    recorded_at: datetime,
    predecessor_hash: str | None,
    scope: AuditScopeRef = SCOPE,
) -> SystemAuditEvent:
    base = make_event(scope=scope)
    return SystemAuditEvent.create(
        event_id=f"{stream_id}:event:{sequence_no}",
        event_version="1",
        schema_version=base.schema_version,
        category=base.category,
        event_type=base.event_type,
        owner=base.owner,
        write_policy=base.write_policy,
        outcome=base.outcome,
        severity=base.severity,
        reason_codes=base.reason_codes,
        occurred_at=recorded_at,
        recorded_at=recorded_at,
        observed_at=recorded_at,
        actor=base.actor,
        source_app=base.source_app,
        source_component=base.source_component,
        source_surface=base.source_surface,
        correlations=base.correlations,
        resource=base.resource,
        dataset_key=base.dataset_key,
        provider_key=base.provider_key,
        capability=base.capability,
        publication_id=base.publication_id,
        evidence_refs=base.evidence_refs,
        detail_schema=base.detail_schema,
        detail={"rows": sequence_no, "source_status": "valid"},
        stream_id=stream_id,
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=f"archive:{stream_id}:{sequence_no}",
        scope=scope,
    )


def _events() -> tuple[SystemAuditEvent, ...]:
    alpha_root = _event(
        stream_id="stream:alpha",
        sequence_no=1,
        recorded_at=NOW,
        predecessor_hash=None,
    )
    beta_root = _event(
        stream_id="stream:beta",
        sequence_no=1,
        recorded_at=NOW + timedelta(seconds=1),
        predecessor_hash=None,
    )
    alpha_successor = _event(
        stream_id="stream:alpha",
        sequence_no=2,
        recorded_at=NOW + timedelta(seconds=2),
        predecessor_hash=alpha_root.content_hash,
    )
    return alpha_root, beta_root, alpha_successor


class _CandidateProvider:
    def __init__(self, candidate: SystemAuditArchiveCandidate | None = CANDIDATE) -> None:
        self.candidate = candidate
        self.calls = 0

    def get_current_candidate(self, *, as_of: datetime) -> SystemAuditArchiveCandidate | None:
        self.calls += 1
        return self.candidate


class _DriftingCandidateProvider:
    def __init__(self) -> None:
        self.calls = 0

    def get_current_candidate(self, *, as_of: datetime) -> SystemAuditArchiveCandidate | None:
        self.calls += 1
        if self.calls == 1:
            return CANDIDATE
        return replace(CANDIDATE, commit="9" * 40, oci_revision=f"sha256:{'d' * 64}")


class _Source:
    def __init__(self, events: tuple[SystemAuditEvent, ...]) -> None:
        self.events = events
        self.calls = 0
        self.requested_limit: int | None = None

    def list_archive_window(
        self,
        *,
        window_started_at: datetime,
        window_ended_at: datetime,
        as_of: datetime,
        scope: AuditScopeRef,
        limit: int,
    ) -> tuple[SystemAuditEvent, ...]:
        self.calls += 1
        self.requested_limit = limit
        return self.events


def _build(
    events: tuple[SystemAuditEvent, ...] | None = None,
    *,
    source: _Source | None = None,
    provider: SystemAuditArchiveCandidateProvider | None = None,
    reader: SystemAuditReaderContext | None = None,
    max_members: int = 100,
):
    actual_source = source or _Source(events or _events())
    actual_provider = provider or _CandidateProvider()
    result = BuildSystemAuditArchiveUseCase(
        source=actual_source,
        candidate_provider=actual_provider,
    ).execute(
        BuildSystemAuditArchiveCommand(
            expected_candidate=CANDIDATE,
            window_started_at=NOW,
            window_ended_at=NOW + timedelta(minutes=1),
            as_of=NOW + timedelta(minutes=2),
            reader=reader or _reader(),
            max_members=max_members,
        )
    )
    return result, actual_source, actual_provider


def test_build_is_candidate_bound_deterministic_and_anchors_each_stream() -> None:
    bundle, source, provider = _build()
    repeated, _, _ = _build()

    assert bundle == repeated
    assert bundle.manifest.candidate == CANDIDATE
    assert bundle.manifest.scope == SCOPE
    assert bundle.manifest.member_count == 3
    assert len(bundle.manifest.source_sha256) == 64
    assert len(bundle.manifest.manifest_sha256) == 64
    assert bundle.manifest.archive_id == f"audit-archive:{bundle.manifest.manifest_sha256}"
    assert tuple(anchor.stream_id for anchor in bundle.manifest.streams) == (
        "stream:alpha",
        "stream:beta",
    )
    assert bundle.manifest.streams[0].member_count == 2
    assert bundle.manifest.streams[0].first_predecessor_hash is None
    assert bundle.manifest.streams[0].last_content_hash == _events()[2].content_hash
    assert source.requested_limit == 101
    assert provider.calls == 2


def test_mid_stream_window_retains_external_predecessor_anchor() -> None:
    root, _, successor = _events()
    bundle, _, _ = _build((successor,))

    anchor = bundle.manifest.streams[0]
    assert anchor.first_sequence_no == 2
    assert anchor.first_predecessor_hash == root.content_hash
    assert anchor.last_sequence_no == 2
    assert anchor.member_count == 1


def test_unauthorized_or_drifted_candidate_never_reads_the_ledger() -> None:
    unauthorized_source = _Source(_events())
    unauthorized_provider = _CandidateProvider()
    with pytest.raises(SystemAuditArchiveUnavailable, match="authority_unavailable"):
        _build(
            source=unauthorized_source,
            provider=unauthorized_provider,
            reader=_reader(staff=False),
        )
    assert unauthorized_provider.calls == 0
    assert unauthorized_source.calls == 0

    drifted_source = _Source(_events())
    drifted_provider = _CandidateProvider(
        replace(CANDIDATE, commit="9" * 40, oci_revision=f"sha256:{'d' * 64}")
    )
    with pytest.raises(SystemAuditArchiveUnavailable, match="candidate_drift"):
        _build(source=drifted_source, provider=drifted_provider)
    assert drifted_provider.calls == 1
    assert drifted_source.calls == 0


def test_candidate_is_revalidated_after_the_ledger_read() -> None:
    source = _Source(_events())
    provider = _DriftingCandidateProvider()

    with pytest.raises(SystemAuditArchiveUnavailable, match="candidate_drift"):
        _build(source=source, provider=provider)

    assert source.calls == 1
    assert provider.calls == 2


@pytest.mark.parametrize(
    ("events", "reason"),
    [
        ((_events()[2], _events()[0]), "archive_source_order_invalid"),
        ((_events()[0], replace(_events()[1], scope=OTHER_SCOPE)), "archive_scope_substitution"),
        (
            (
                _event(
                    stream_id="stream:outside",
                    sequence_no=1,
                    recorded_at=NOW - timedelta(seconds=1),
                    predecessor_hash=None,
                ),
            ),
            "archive_window_substitution",
        ),
    ],
)
def test_source_substitution_or_stream_gap_fails_closed(
    events: tuple[SystemAuditEvent, ...], reason: str
) -> None:
    with pytest.raises(SystemAuditArchiveCorruption, match=reason):
        _build(events)


def test_member_bound_refuses_truncation_instead_of_claiming_complete_archive() -> None:
    with pytest.raises(SystemAuditArchiveUnavailable, match="member_limit_exceeded"):
        _build(max_members=2)


@pytest.mark.parametrize(
    ("events", "reason"),
    [
        (
            (
                _events()[0],
                _event(
                    stream_id="stream:alpha",
                    sequence_no=3,
                    recorded_at=NOW + timedelta(seconds=1),
                    predecessor_hash="e" * 64,
                ),
            ),
            "archive_stream_sequence_gap",
        ),
        (
            (
                _events()[0],
                _event(
                    stream_id="stream:alpha",
                    sequence_no=2,
                    recorded_at=NOW + timedelta(seconds=1),
                    predecessor_hash="e" * 64,
                ),
            ),
            "archive_stream_predecessor_mismatch",
        ),
        ((_events()[0], _events()[0]), "archive_duplicate_event"),
    ],
)
def test_archive_rejects_loss_fork_and_duplicate_members(
    events: tuple[SystemAuditEvent, ...], reason: str
) -> None:
    with pytest.raises(SystemAuditArchiveCorruption, match=reason):
        _build(events)


def test_codec_roundtrip_is_exact_and_rejects_unknown_or_tampered_bytes() -> None:
    bundle, _, _ = _build()
    codec = CanonicalSystemAuditArchiveCodec()
    payload = codec.encode(bundle)

    assert codec.decode(payload) == bundle
    assert codec.encode(codec.decode(payload)) == payload

    decoded = json.loads(payload)
    decoded["unknown"] = True
    with pytest.raises(SystemAuditArchiveCorruption, match="unknown_or_missing_keys"):
        codec.decode(json.dumps(decoded, sort_keys=True, separators=(",", ":")).encode())

    decoded = json.loads(payload)
    decoded["events"][0]["detail"]["rows"] = 999
    with pytest.raises(SystemAuditArchiveCorruption, match="event_invalid"):
        codec.decode(json.dumps(decoded, sort_keys=True, separators=(",", ":")).encode())

    with pytest.raises(SystemAuditArchiveCorruption, match="not_canonical"):
        codec.decode(payload + b"\n")


def test_codec_rejects_duplicate_json_keys() -> None:
    codec = CanonicalSystemAuditArchiveCodec()
    with pytest.raises(SystemAuditArchiveCorruption, match="duplicate_json_key"):
        codec.decode(b'{"events":[],"events":[],"manifest":{},"schema_version":"x"}')


def test_isolated_restore_replays_exact_stream_without_production_claim() -> None:
    bundle, _, _ = _build()
    codec = CanonicalSystemAuditArchiveCodec()
    payload = codec.encode(bundle)
    result = RestoreSystemAuditArchiveUseCase(
        codec=codec,
        candidate_provider=_CandidateProvider(),
    ).execute(
        RestoreSystemAuditArchiveCommand(
            payload=payload,
            expected_candidate=CANDIDATE,
            reader=_reader(),
            as_of=NOW + timedelta(minutes=3),
            replay_stream_id="stream:alpha",
        )
    )

    assert result.outcome == "success"
    assert result.isolation_mode == "memory_only"
    assert result.production_claim is False
    assert result.production_ready is False
    assert result.source_sha256 == result.restored_sha256
    assert result.manifest_sha256 == bundle.manifest.manifest_sha256
    assert result.member_count == 3
    assert result.replay_member_count == 2
    assert len(result.replay_sha256) == 64
    assert result.artifact_sha256 == hashlib.sha256(payload).hexdigest()
    with pytest.raises(SystemAuditArchiveCorruption, match="claim_invalid"):
        replace(result, production_claim=True)


def test_restore_rejects_scope_candidate_and_replay_substitution() -> None:
    bundle, _, _ = _build()
    codec = CanonicalSystemAuditArchiveCodec()
    payload = codec.encode(bundle)
    use_case = RestoreSystemAuditArchiveUseCase(
        codec=codec,
        candidate_provider=_CandidateProvider(),
    )

    with pytest.raises(SystemAuditArchiveUnavailable, match="scope_substitution"):
        use_case.execute(
            RestoreSystemAuditArchiveCommand(
                payload=payload,
                expected_candidate=CANDIDATE,
                reader=_reader(scope=OTHER_SCOPE),
                as_of=NOW + timedelta(minutes=3),
                replay_stream_id="stream:alpha",
            )
        )
    with pytest.raises(SystemAuditArchiveUnavailable, match="replay_stream_unavailable"):
        use_case.execute(
            RestoreSystemAuditArchiveCommand(
                payload=payload,
                expected_candidate=CANDIDATE,
                reader=_reader(),
                as_of=NOW + timedelta(minutes=3),
                replay_stream_id="stream:missing",
            )
        )


def test_append_only_store_roundtrip_is_idempotent_and_sidecar_bound(tmp_path: Path) -> None:
    bundle, _, _ = _build()
    store = AppendOnlySystemAuditArchiveStore(root=tmp_path / "audit-archives")

    first = store.write(bundle)
    repeated = store.write(bundle)

    assert repeated == first
    assert first.path.read_bytes() == CanonicalSystemAuditArchiveCodec().encode(bundle)
    assert first.sidecar_path.read_text(encoding="ascii") == (
        f"{first.artifact_sha256}  {first.path.name}\n"
    )
    assert store.read(first.artifact_sha256) == bundle


def test_append_only_store_fails_closed_on_artifact_or_sidecar_tamper(tmp_path: Path) -> None:
    bundle, _, _ = _build()
    store = AppendOnlySystemAuditArchiveStore(root=tmp_path / "audit-archives")
    artifact = store.write(bundle)

    artifact.path.write_bytes(b"tampered")
    with pytest.raises(SystemAuditArchiveStoreError, match="artifact_hash_mismatch"):
        store.read(artifact.artifact_sha256)

    clean_root = tmp_path / "clean-audit-archives"
    clean_store = AppendOnlySystemAuditArchiveStore(root=clean_root)
    clean = clean_store.write(bundle)
    clean.sidecar_path.write_text("tampered\n", encoding="ascii")
    with pytest.raises(SystemAuditArchiveStoreError, match="sidecar_mismatch"):
        clean_store.read(clean.artifact_sha256)


@pytest.mark.parametrize("root", [Path("relative"), Path("/")])
def test_store_requires_a_bounded_absolute_non_root_directory(root: Path) -> None:
    with pytest.raises(ValueError, match="bounded absolute directory"):
        AppendOnlySystemAuditArchiveStore(root=root)
