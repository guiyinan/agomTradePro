"""Physical source discovery preserves final chain state and mapping ambiguity."""

from types import SimpleNamespace

import pytest

from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    PersistedSimulatedAccountRowSourceV2,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Corruption,
    DjangoSimulatedAccountRowSourceV2Repository,
)
from tests.unit.simulated_trading.test_simulated_account_row_source_v2 import (
    _at,
    _raw,
    _source,
)


def _repository(monkeypatch, sources):
    repository = DjangoSimulatedAccountRowSourceV2Repository(
        clock=SimpleNamespace(now=lambda: _at(30))
    )
    records = tuple(PersistedSimulatedAccountRowSourceV2(source) for source in sources)
    monkeypatch.setattr(type(repository), "_visible_records", lambda self, **kwargs: records)
    return repository


def test_expired_head_remains_discoverable_without_current_permission(monkeypatch):
    source = _source()
    repository = _repository(monkeypatch, (source,))
    heads = repository.get_physical_account_heads(underlying_unified_account_id=7, as_of=_at(20))
    assert tuple(record.source for record in heads) == (source,)
    assert not heads[0].source.is_current_at(_at(20))


def test_conflicting_canonical_mappings_are_not_filtered_away(monkeypatch):
    one = _source()
    two = _source(raw=_raw(observation_id="other-mapping"), account_id="0008")
    repository = _repository(monkeypatch, (one, two))
    heads = repository.get_physical_account_heads(underlying_unified_account_id=7, as_of=_at(6))
    assert {record.source.account_id for record in heads} == {"0007", "0008"}


def test_missing_chain_root_is_rejected_instead_of_selected_as_latest(monkeypatch):
    source = _source(supersedes_content_hash="f" * 64)
    repository = _repository(monkeypatch, (source,))
    with pytest.raises(DjangoSimulatedAccountRowSourceV2Corruption):
        repository.get_physical_account_heads(underlying_unified_account_id=7, as_of=_at(6))


def test_another_physical_row_cannot_appear_in_discovered_scope(monkeypatch):
    repository = _repository(monkeypatch, (_source(),))
    assert (
        repository.get_physical_account_heads(underlying_unified_account_id=8, as_of=_at(6)) == ()
    )


def test_expired_origin_metadata_does_not_weaken_the_existing_exact_freshness_gate(monkeypatch):
    source = _source()
    repository = _repository(monkeypatch, (source,))
    selector = {
        "source_id": source.source_id,
        "source_version": source.source_version,
        "expected_content_hash": source.content_hash,
        "as_of": _at(20),
    }
    assert repository.get_exact_by_hash(**selector) is None
    historical = repository.get_historical_exact_metadata(**selector)
    assert historical is not None and historical.source == source
    assert not isinstance(historical, PersistedSimulatedAccountRowSourceV2)
    assert not historical.source.is_current_at(_at(20))
