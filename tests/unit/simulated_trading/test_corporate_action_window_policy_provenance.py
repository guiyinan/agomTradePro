"""A same-value Config Center replacement must still invalidate financial entry proof."""

from dataclasses import replace
from typing import cast

import pytest

from apps.simulated_trading import corporate_action_window_audit_composition as audit
from apps.simulated_trading.application.corporate_action_current_official_window import (
    CorporateActionCurrentOfficialWindowReader,
)
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
)
from tests.unit.simulated_trading.test_corporate_action_current_official_window import (
    _NOW,
    _Clock,
    _policy,
    _reader,
    _request,
)


@pytest.mark.parametrize(
    "change",
    [{"profile_id": "new-profile"}, {"snapshot_id": "new-snapshot"}, {"profile_version": 2}],
)
def test_equal_policy_values_do_not_hide_replaced_profile_or_snapshot(monkeypatch, change):
    first_reader, _, _ = _reader(policies=(_policy(),), clock=_Clock((_NOW,)))
    second_reader, _, _ = _reader(policies=(replace(_policy(), **change),), clock=_Clock((_NOW,)))
    proofs = iter(
        (
            first_reader.read_current(_request(), as_of=_NOW),
            second_reader.read_current(_request(), as_of=_NOW),
        )
    )

    class Reader:
        def read_current(self, request, *, as_of):
            return next(proofs)

    monkeypatch.setattr(audit.timezone, "now", lambda: _NOW)
    gate = audit.CorporateActionWindowAuditGate(
        cast(CorporateActionCurrentOfficialWindowReader, Reader())
    )
    original = gate.read_entry_evidence(_request())
    with pytest.raises(CorporateActionPostingBlockedError):
        gate.assert_unchanged(_request(), original)


def test_original_financial_window_retains_the_exact_actual_profile_and_snapshot():
    reader, _, _ = _reader(clock=_Clock((_NOW,)))
    evidence = reader.read_current(_request(), as_of=_NOW)
    assert evidence.policy_provenance.profile_id == _policy().profile_id
    assert evidence.policy_provenance.snapshot_id == _policy().snapshot_id
    payload = audit.corporate_action_window_audit_payload(evidence, _request(), recorded_at=_NOW)
    restored = audit.restore_corporate_action_window_audit_evidence(
        payload, _request(), recorded_at=_NOW
    )
    assert restored.policy_provenance == evidence.policy_provenance
