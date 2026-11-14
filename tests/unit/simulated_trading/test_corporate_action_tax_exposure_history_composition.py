"""Stable exposure source epochs retain full configuration metadata, not query clocks."""

from dataclasses import replace
from datetime import timedelta

import pytest

from apps.simulated_trading.corporate_action_tax_exposure_history_composition import (
    _policy_epoch,
    _same_policy,
)
from tests.unit.simulated_trading.test_corporate_action_tax_statutory_qualification import _inputs


def test_new_read_cutoff_does_not_invent_a_changed_tax_model(monkeypatch):
    original, _ = _inputs(monkeypatch)
    current = replace(original, as_of=original.as_of + timedelta(seconds=1))
    assert _same_policy(original, current)
    assert _policy_epoch(original) == _policy_epoch(current)


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile_id", "different-profile"),
        ("profile_key", "different-key"),
        ("profile_version", 2),
        ("snapshot_id", "different-snapshot"),
        ("snapshot_hash", "b" * 64),
    ],
)
def test_same_value_tax_policy_metadata_swap_cannot_clear_cash_coverage(monkeypatch, field, value):
    original, _ = _inputs(monkeypatch)
    current = replace(original, **{field: value})
    assert not _same_policy(original, current)
    assert _policy_epoch(original) != _policy_epoch(current)
