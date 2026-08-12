"""Pure contract tests for Evidence operator spec approval and activation."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Iterator

import pytest

from apps.research.application.evidence_operator_spec_lifecycle import (
    ActivateEvidenceOperatorSpec,
    ActivateEvidenceOperatorSpecCommand,
    EvidenceOperatorSpecConflict,
    EvidenceOperatorSpecCorruption,
    EvidenceOperatorSpecOwnerApproval,
    EvidenceOperatorSpecUnavailable,
)
from apps.research.domain.evidence_contracts import (
    ClaimKind,
    DecisionPermission,
    DependencyFlag,
    EvidenceOperatorSpec,
    MethodKind,
)
from apps.research.domain.evidence_operator_spec_lifecycle import (
    ActivatedEvidenceOperatorSpec,
    EvidenceOperatorSpecDefinition,
)
from apps.research.infrastructure.evidence_operator_spec_lifecycle_codec import (
    EvidenceOperatorSpecLifecycleCodecError,
    decode_activated_operator_spec,
    encode_activated_operator_spec,
)

NOW = datetime(2026, 8, 12, 8, tzinfo=UTC)


def _definition(
    *,
    version: str = "v1",
    supersedes: str | None = None,
) -> EvidenceOperatorSpecDefinition:
    spec = EvidenceOperatorSpec.create(
        operator_id="scenario-probability",
        operator_version=version,
        research_family="r7",
        output_artifact_type="scenario_probability",
        claim_kind=ClaimKind.FORECAST,
        method_kind=MethodKind.STATISTICAL,
        required_input_roles=("calibration", "sample_policy"),
        dependency_flags=frozenset({DependencyFlag.ESTIMATED_INPUT}),
        maximum_permission=DecisionPermission.ADVISORY,
        requires_track_record=True,
        activated_at=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(days=30),
    )
    return EvidenceOperatorSpecDefinition.create(
        operator_spec=spec,
        supersedes_activation_hash=supersedes,
    )


def _approval(
    definition: EvidenceOperatorSpecDefinition,
    *,
    version: str = "v1",
) -> EvidenceOperatorSpecOwnerApproval:
    spec = definition.operator_spec
    return EvidenceOperatorSpecOwnerApproval(
        approval_id=f"approval-{version}",
        approval_version=version,
        owner_record_id=f"risk-record-{version}",
        owner_record_version=version,
        owner_record_hash="a" * 64,
        operator_id=spec.operator_id,
        operator_version=spec.operator_version,
        definition_hash=definition.content_hash,
        supersedes_activation_hash=definition.supersedes_activation_hash,
        approved_by="risk-owner",
        issued_at=NOW - timedelta(hours=2),
        valid_until=NOW + timedelta(days=10),
    )


class _DefinitionProvider:
    def __init__(self, values: list[EvidenceOperatorSpecDefinition | None]) -> None:
        self.values = values
        self.calls = 0

    def get_exact(
        self,
        *,
        operator_id: str,
        operator_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecDefinition | None:
        del operator_id, operator_version, as_of
        index = min(self.calls, len(self.values) - 1)
        self.calls += 1
        return self.values[index]


class _ApprovalQuery:
    def __init__(self, values: list[EvidenceOperatorSpecOwnerApproval | None]) -> None:
        self.values = values
        self.calls = 0
        self.requested_definition_hashes: list[str] = []

    def get_exact(
        self,
        *,
        approval_id: str,
        approval_version: str,
        operator_id: str,
        operator_version: str,
        definition_hash: str,
        supersedes_activation_hash: str | None,
        as_of: datetime,
    ) -> EvidenceOperatorSpecOwnerApproval | None:
        del (
            approval_id,
            approval_version,
            operator_id,
            operator_version,
            supersedes_activation_hash,
            as_of,
        )
        self.requested_definition_hashes.append(definition_hash)
        index = min(self.calls, len(self.values) - 1)
        self.calls += 1
        return self.values[index]


class _Store:
    def __init__(
        self,
        records: list[ActivatedEvidenceOperatorSpec] | None = None,
        now: datetime = NOW,
    ) -> None:
        self.records = records or []
        self.clock = now
        self.atomic_entries = 0
        self.append_calls = 0

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.atomic_entries += 1
        yield

    def now(self) -> datetime:
        return self.clock

    def get_exact(
        self,
        *,
        operator_id: str,
        operator_version: str,
        as_of: datetime,
    ) -> ActivatedEvidenceOperatorSpec | None:
        return next(
            (
                record
                for record in self.records
                if record.operator_spec.operator_id == operator_id
                and record.operator_spec.operator_version == operator_version
                and record.recorded_at <= as_of
            ),
            None,
        )

    def get_head(
        self,
        *,
        operator_id: str,
        as_of: datetime,
    ) -> ActivatedEvidenceOperatorSpec | None:
        candidates = [
            record
            for record in self.records
            if record.operator_spec.operator_id == operator_id and record.recorded_at <= as_of
        ]
        return candidates[-1] if candidates else None

    def append_graph(
        self,
        record: ActivatedEvidenceOperatorSpec,
    ) -> ActivatedEvidenceOperatorSpec:
        self.append_calls += 1
        self.records.append(record)
        return record


def _command(*, version: str = "v1") -> ActivateEvidenceOperatorSpecCommand:
    return ActivateEvidenceOperatorSpecCommand(
        operator_id="scenario-probability",
        operator_version=version,
        approval_id=f"approval-{version}",
        approval_version=version,
        as_of=NOW,
    )


def _service(
    definition_provider: _DefinitionProvider,
    approval_query: _ApprovalQuery,
    store: _Store,
) -> ActivateEvidenceOperatorSpec:
    return ActivateEvidenceOperatorSpec(
        definition_provider=definition_provider,
        approval_query=approval_query,
        store=store,
    )


def test_activation_rereads_trusted_definition_and_owner_then_appends_atomically() -> None:
    definition = _definition()
    approval = _approval(definition)
    definitions = _DefinitionProvider([definition])
    approvals = _ApprovalQuery([approval])
    store = _Store()

    record = _service(definitions, approvals, store).execute(_command())

    assert record.operator_spec == definition.operator_spec
    assert record.approval.approved_by == "risk-owner"
    assert record.definition.supersedes_activation_hash is None
    assert definitions.calls == 2
    assert approvals.calls == 2
    assert approvals.requested_definition_hashes == [
        definition.content_hash,
        definition.content_hash,
    ]
    assert store.atomic_entries == 1
    assert store.append_calls == 1


def test_activation_is_idempotent_only_for_the_complete_existing_graph() -> None:
    definition = _definition()
    approval = _approval(definition)
    existing = ActivatedEvidenceOperatorSpec.create(
        definition=definition,
        approval=approval.to_receipt(),
        recorded_at=NOW,
    )
    store = _Store([existing])

    winner = _service(
        _DefinitionProvider([definition]),
        _ApprovalQuery([approval]),
        store,
    ).execute(_command())

    assert winner == existing
    assert store.append_calls == 0


def test_activation_rejects_missing_external_owner_approval() -> None:
    definition = _definition()
    service = _service(
        _DefinitionProvider([definition]),
        _ApprovalQuery([None]),
        _Store(),
    )

    with pytest.raises(EvidenceOperatorSpecUnavailable, match="external-owner"):
        service.execute(_command())


def test_activation_rejects_owner_or_definition_drift_before_append() -> None:
    definition = _definition()
    changed = _definition(version="v2")
    approval = _approval(definition)
    service = _service(
        _DefinitionProvider([definition, changed]),
        _ApprovalQuery([approval]),
        _Store(),
    )

    with pytest.raises(EvidenceOperatorSpecCorruption, match="identity"):
        service.execute(_command())


def test_activation_rejects_external_projection_that_does_not_match_query() -> None:
    definition = _definition()
    forged = replace(_approval(definition), operator_version="v-forged")
    service = _service(
        _DefinitionProvider([definition]),
        _ApprovalQuery([forged]),
        _Store(),
    )

    with pytest.raises(EvidenceOperatorSpecCorruption, match="approval identity"):
        service.execute(_command())


def test_successor_must_supersede_the_exact_current_activation_hash() -> None:
    first_definition = _definition()
    first = ActivatedEvidenceOperatorSpec.create(
        definition=first_definition,
        approval=_approval(first_definition).to_receipt(),
        recorded_at=NOW,
    )
    second_definition = _definition(version="v2", supersedes="b" * 64)
    service = _service(
        _DefinitionProvider([second_definition]),
        _ApprovalQuery([_approval(second_definition, version="v2")]),
        _Store([first], now=NOW + timedelta(seconds=1)),
    )

    with pytest.raises(EvidenceOperatorSpecConflict, match="exact current head"):
        service.execute(replace(_command(version="v2"), as_of=NOW + timedelta(seconds=1)))


def test_first_version_cannot_claim_a_missing_predecessor() -> None:
    definition = _definition(supersedes="b" * 64)
    service = _service(
        _DefinitionProvider([definition]),
        _ApprovalQuery([_approval(definition)]),
        _Store(),
    )

    with pytest.raises(EvidenceOperatorSpecConflict, match="predecessor is missing"):
        service.execute(_command())


def test_future_cutoff_is_rejected_before_any_append() -> None:
    definition = _definition()
    store = _Store()
    service = _service(
        _DefinitionProvider([definition]),
        _ApprovalQuery([_approval(definition)]),
        store,
    )

    with pytest.raises(EvidenceOperatorSpecUnavailable, match="future as_of"):
        service.execute(replace(_command(), as_of=NOW + timedelta(seconds=1)))
    assert store.append_calls == 0


def test_lifecycle_codec_round_trip_recomputes_nested_hashes() -> None:
    definition = _definition()
    record = ActivatedEvidenceOperatorSpec.create(
        definition=definition,
        approval=_approval(definition).to_receipt(),
        recorded_at=NOW,
    )

    payload = encode_activated_operator_spec(record)
    assert decode_activated_operator_spec(payload) == record

    tampered = dict(payload)
    tampered_definition = dict(tampered["definition"])  # type: ignore[arg-type]
    tampered_definition["supersedes_activation_hash"] = "c" * 64
    tampered["definition"] = tampered_definition
    with pytest.raises(EvidenceOperatorSpecLifecycleCodecError):
        decode_activated_operator_spec(tampered)


def test_activated_record_rejects_hash_and_clock_tampering() -> None:
    definition = _definition()
    record = ActivatedEvidenceOperatorSpec.create(
        definition=definition,
        approval=_approval(definition).to_receipt(),
        recorded_at=NOW,
    )

    with pytest.raises(ValueError, match="content_hash"):
        replace(record, content_hash="f" * 64)
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(record, recorded_at=NOW.replace(tzinfo=None))
