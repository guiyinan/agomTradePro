"""Session discovery selects once, then verifies only that exact original."""

from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.data_center import retained_historical_price_source_composition as source
from apps.data_center.application.retained_historical_price_source import (
    RetainedHistoricalPriceSourceResult,
)

_AS_OF = datetime(2026, 11, 15, 8, tzinfo=UTC)
_DAY = date(2026, 11, 13)
_ID = "38d57a89-5621-4f4a-8990-ebeb5ee3eec0"


@pytest.fixture
def selector(monkeypatch):
    repository = SimpleNamespace(select_retained_publication_for_session=Mock(return_value=_ID))
    connection = SimpleNamespace(in_atomic_block=False, atomic_blocks=[])

    @contextmanager
    def atomic(**kwargs):
        assert kwargs == {"using": "default"}
        connection.in_atomic_block = True
        connection.atomic_blocks.append(object())
        try:
            yield
        finally:
            connection.atomic_blocks.pop()
            connection.in_atomic_block = False

    def stabilize(dataset):
        assert dataset == "equity.price.bar" and len(connection.atomic_blocks) == 1

    monkeypatch.setattr(source, "connections", {"default": connection})
    monkeypatch.setattr(source, "transaction", SimpleNamespace(atomic=atomic))
    monkeypatch.setattr(source, "stabilize_caller_owned_publication_read", stabilize)
    monkeypatch.setattr(source.timezone, "now", lambda: _AS_OF)
    monkeypatch.setattr(source, "DjangoPublishedPriceSourceRepository", lambda: repository)
    read = Mock(return_value=RetainedHistoricalPriceSourceResult(None, "original-body-corrupt"))
    monkeypatch.setattr(source, "_read_retained_source_snapshot", read)
    return repository, read


def _read(**overrides):
    values = {
        "asset_code": "001211.SZ",
        "trade_date": _DAY,
        "expected_publication_key": "m1-rebalance-reference",
        "knowledge_cutoff": _AS_OF,
        "environment": "test",
    }
    values.update(overrides)
    return source.read_retained_historical_price_for_session(**values)


def test_selected_invalid_original_never_falls_back_to_another_publication(selector):
    repository, read = selector
    result = _read()
    assert result.evidence is None and result.blocked_reason == "original-body-corrupt"
    assert result.must_not_use_for_decision is True
    repository.select_retained_publication_for_session.assert_called_once_with(
        asset_code="001211.SZ", trade_date=_DAY, knowledge_cutoff=_AS_OF
    )
    read.assert_called_once()
    request = read.call_args.args[0]
    assert (
        request.publication_id == _ID
        and request.trade_date == _DAY
        and request.knowledge_cutoff == _AS_OF
    )


def test_missing_session_publication_does_not_substitute_current_pointer(selector):
    repository, read = selector
    repository.select_retained_publication_for_session.return_value = None
    result = _read()
    assert (
        result.evidence is None
        and result.blocked_reason == "retained_price_session_publication_missing"
    )
    read.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"asset_code": "001211.sz"},
        {"trade_date": _AS_OF},
        {"expected_publication_key": "current"},
        {"environment": " test"},
        {"using": "other"},
    ],
)
def test_invalid_session_scope_is_rejected_before_selection(selector, changes):
    repository, read = selector
    result = _read(**changes)
    assert result.evidence is None and result.must_not_use_for_decision is True
    repository.select_retained_publication_for_session.assert_not_called()
    read.assert_not_called()
