"""Component proof for the identity-only trusted operator-spec definition provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

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
from apps.research.infrastructure.evidence_operator_spec_definition_provider import (
    DjangoEvidenceOperatorSpecDefinitionProvider,
)
from apps.research.infrastructure.evidence_repository import _build_evidence_store

NOW = datetime(2026, 8, 13, 8, tzinfo=UTC)


@dataclass
class FixedClock:
    value: datetime = NOW

    def now(self) -> datetime:
        return self.value


class EmptyLifecycle:
    def __init__(self) -> None:
        self.exact_calls: list[tuple[str, str, datetime]] = []
        self.head_calls: list[tuple[str, datetime]] = []

    def get_exact(
        self,
        *,
        operator_id: str,
        operator_version: str,
        as_of: datetime,
    ) -> ActivatedEvidenceOperatorSpec | None:
        self.exact_calls.append((operator_id, operator_version, as_of))
        return None

    def get_head(
        self,
        *,
        operator_id: str,
        as_of: datetime,
    ) -> ActivatedEvidenceOperatorSpec | None:
        self.head_calls.append((operator_id, as_of))
        return None


def _spec() -> EvidenceOperatorSpec:
    return EvidenceOperatorSpec.create(
        operator_id="sector-score",
        operator_version="1",
        research_family="sector",
        output_artifact_type="sector_score",
        claim_kind=ClaimKind.DERIVED,
        method_kind=MethodKind.DETERMINISTIC,
        required_input_roles=("sector_observations",),
        dependency_flags=frozenset({DependencyFlag.ESTIMATED_INPUT}),
        maximum_permission=DecisionPermission.DISPLAY_ONLY,
        requires_track_record=False,
        activated_at=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=30),
    )


@pytest.mark.django_db
def test_provider_resolves_canonical_definition_from_ids_without_caller_hash() -> None:
    spec = _spec()
    store = _build_evidence_store()
    with store.atomic():
        store.append_operator_spec(spec, recorded_at=NOW)
    lifecycle = EmptyLifecycle()
    provider = DjangoEvidenceOperatorSpecDefinitionProvider(
        clock=FixedClock(),
        lifecycle=lifecycle,
    )

    definition = provider.get_exact(
        operator_id=spec.operator_id,
        operator_version=spec.operator_version,
        as_of=NOW,
    )

    assert definition == EvidenceOperatorSpecDefinition.create(
        operator_spec=spec,
        supersedes_activation_hash=None,
    )
    assert lifecycle.exact_calls == [
        (spec.operator_id, spec.operator_version, NOW),
        (spec.operator_id, spec.operator_version, NOW),
    ]
    assert lifecycle.head_calls == [(spec.operator_id, NOW)]


@pytest.mark.django_db
def test_provider_fails_closed_before_canonical_knowledge_or_outside_validity() -> None:
    spec = _spec()
    store = _build_evidence_store()
    with store.atomic():
        store.append_operator_spec(spec, recorded_at=NOW)
    provider = DjangoEvidenceOperatorSpecDefinitionProvider(
        clock=FixedClock(NOW + timedelta(days=40)),
        lifecycle=EmptyLifecycle(),
    )

    assert (
        provider.get_exact(
            operator_id=spec.operator_id,
            operator_version=spec.operator_version,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )
    assert (
        provider.get_exact(
            operator_id=spec.operator_id,
            operator_version=spec.operator_version,
            as_of=spec.valid_until,
        )
        is None
    )
