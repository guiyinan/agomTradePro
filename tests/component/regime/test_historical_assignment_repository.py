"""Component coverage for the Regime historical assignment owner ledger."""

from __future__ import annotations

import pytest

from apps.regime.historical_assignment_composition import (
    _build_historical_regime_assignment_runtime_for_test,
    build_historical_regime_assignment_runtime,
)
from apps.regime.infrastructure.historical_assignment_models import (
    HistoricalRegimeAssignmentDefinitionModel,
    HistoricalRegimeAssignmentReceiptModel,
)
from tests.unit.regime.test_historical_assignment import (
    _artifact,
    _ArtifactProvider,
    _Clock,
    _definition,
    _DefinitionOwner,
    _FactProvider,
    _facts,
    _materialize_command,
    _register_command,
)


@pytest.mark.django_db
def test_definition_and_receipt_round_trip_and_exact_replay() -> None:
    """Private owner registration produces one exact immutable winner graph."""

    runtime = _build_historical_regime_assignment_runtime_for_test(
        definition_provider=_DefinitionOwner((_definition(),) * 8),
        artifact_provider=_ArtifactProvider((_artifact(),) * 8),
        fact_provider=_FactProvider((_facts(),) * 8),
        clock=_Clock(),
    )
    definition = runtime.register_definition.execute(_register_command())
    receipt = runtime.materialize.execute(_materialize_command())

    assert runtime.register_definition.execute(_register_command()) == definition
    assert runtime.materialize.execute(_materialize_command()) == receipt
    assert (
        runtime.repository.get_exact_definition(
            definition_id=definition.definition.definition_id,
            definition_version=definition.definition.definition_version,
            expected_content_hash=definition.definition.content_hash,
            as_of=receipt.pit_as_of,
        )
        == definition
    )
    assert (
        runtime.repository.get_exact_receipt(
            artifact_id=receipt.artifact_id,
            expected_artifact_hash=receipt.artifact_hash,
            as_of=receipt.recorded_at,
        )
        == receipt
    )
    assert HistoricalRegimeAssignmentDefinitionModel._default_manager.count() == 1
    assert HistoricalRegimeAssignmentReceiptModel._default_manager.count() == 1


@pytest.mark.django_db
def test_public_runtime_is_read_only_and_zero_write() -> None:
    """Production exposes no owner provider, clock, store, token, or mutation path."""

    runtime = build_historical_regime_assignment_runtime()
    assert not hasattr(runtime.repository, "append_definition")
    assert not hasattr(runtime.repository, "append_receipt")
    assert not hasattr(runtime.repository, "_repository")
    assert runtime.repository.__slots__ == ("_using",)
    with pytest.raises(Exception, match="unavailable"):
        runtime.mutation.register_definition(_register_command())
    with pytest.raises(Exception, match="unavailable"):
        runtime.mutation.materialize(_materialize_command())
    assert HistoricalRegimeAssignmentDefinitionModel._default_manager.count() == 0
    assert HistoricalRegimeAssignmentReceiptModel._default_manager.count() == 0
