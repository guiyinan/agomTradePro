"""Strict codec tests for R2 Phase-B ledger evidence."""

from __future__ import annotations

from copy import deepcopy

import pytest

from apps.research.infrastructure.r2_market_structure_trial_monitoring_codec import (
    R2TrialMonitoringCodecError,
    decode_r2_monitoring_evidence,
    decode_r2_trial_evidence,
    encode_r2_monitoring_evidence,
    encode_r2_trial_evidence,
)
from tests.unit.research.test_r2_market_structure_trial_monitoring_persistence import (
    _monitoring_evidence,
    _trial_evidence,
)


def test_trial_and_monitoring_evidence_round_trip_exactly() -> None:
    trial = _trial_evidence()
    monitoring = _monitoring_evidence()

    assert decode_r2_trial_evidence(encode_r2_trial_evidence(trial)) == trial
    assert decode_r2_monitoring_evidence(encode_r2_monitoring_evidence(monitoring)) == monitoring


def test_codec_rejects_extra_keys_and_nested_live_seal_changes() -> None:
    trial_payload = encode_r2_trial_evidence(_trial_evidence())
    changed_envelope = deepcopy(trial_payload)
    changed_envelope["extra"] = True
    with pytest.raises(R2TrialMonitoringCodecError, match="missing or extra"):
        decode_r2_trial_evidence(changed_envelope)

    monitoring = _monitoring_evidence()
    object.__setattr__(monitoring.facts[-1], "source_owner", "substituted-owner")
    with pytest.raises(R2TrialMonitoringCodecError):
        decode_r2_monitoring_evidence(encode_r2_monitoring_evidence(monitoring))
