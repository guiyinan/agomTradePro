"""Pure contracts for the Research-owned R3 runner-spec ledger."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

import pytest

from apps.research.application.r3_macro_factor_runner_spec import (
    RegisterMacroFactorRunnerSpecCommand,
)
from apps.research.domain.r3_macro_factor_runner_spec import (
    PersistedMacroFactorRunnerSpecRecord,
)
from apps.research.infrastructure.r3_macro_factor_runner_spec_codec import (
    R3MacroFactorRunnerSpecCodecError,
    decode_persisted_macro_factor_runner_spec,
    encode_persisted_macro_factor_runner_spec,
)
from tests.unit.macro_factor.runner_factories import runner_spec


def _record() -> PersistedMacroFactorRunnerSpecRecord:
    return PersistedMacroFactorRunnerSpecRecord.create(
        spec=runner_spec(),
        ledger_recorded_at=datetime(2015, 1, 1, tzinfo=UTC),
    )


def test_registration_command_is_identity_and_cutoff_only() -> None:
    command = RegisterMacroFactorRunnerSpecCommand(
        spec_id="growth-fmp-research",
        spec_version=1,
        as_of=datetime(2015, 1, 1, tzinfo=UTC),
    )

    assert tuple(item.name for item in fields(command)) == (
        "spec_id",
        "spec_version",
        "as_of",
    )


def test_strict_codec_round_trips_the_complete_validated_spec() -> None:
    record = _record()

    restored = decode_persisted_macro_factor_runner_spec(
        encode_persisted_macro_factor_runner_spec(record)
    )

    assert restored == record
    assert restored.spec.validated_copy() == runner_spec()


def test_strict_codec_rejects_unknown_keys() -> None:
    payload = encode_persisted_macro_factor_runner_spec(_record())
    payload["unexpected"] = True

    with pytest.raises(R3MacroFactorRunnerSpecCodecError, match="exact keys"):
        decode_persisted_macro_factor_runner_spec(payload)


def test_record_rejects_retroactive_registration_after_selection() -> None:
    spec = runner_spec()
    first_selection = min(fold.selection_as_of for fold in spec.plan.outer_folds)

    with pytest.raises(ValueError, match="before nested-CV selection"):
        PersistedMacroFactorRunnerSpecRecord.create(
            spec=spec,
            ledger_recorded_at=first_selection,
        )
