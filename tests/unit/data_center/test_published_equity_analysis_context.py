from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from apps.data_center import publication_read_composition
from apps.data_center.application import published_equity_context


def test_equity_analysis_context_enters_all_dataset_snapshots_before_read(monkeypatch):
    events: list[tuple[str, str]] = []
    deadlines: list[float] = []

    @contextmanager
    def snapshot(dataset_key: str, *, lock_deadline: float | None = None) -> Iterator[None]:
        assert lock_deadline is not None
        deadlines.append(lock_deadline)
        events.append(("enter", dataset_key))
        yield
        events.append(("exit", dataset_key))

    def read_context(
        asset_codes: list[str],
        *,
        publication_key: str,
        include_price: bool,
        include_financial: bool,
        include_valuation: bool,
        valuation_limit: int,
    ) -> dict[str, dict[str, dict[str, object]]]:
        events.append(("read", str(valuation_limit)))
        assert asset_codes == ["600000.SH"]
        assert publication_key == "release-1"
        assert include_price and include_financial and include_valuation
        return {}

    monkeypatch.setattr(publication_read_composition, "consistent_publication_read", snapshot)
    monkeypatch.setattr(
        published_equity_context, "get_published_equity_context_payloads", read_context
    )

    result = published_equity_context.get_published_equity_analysis_context_payloads(
        ["600000.SH"], publication_key="release-1", valuation_limit=5000
    )

    assert result == {}
    assert len(deadlines) == 3
    assert len(set(deadlines)) == 1
    assert events == [
        ("enter", "equity.financial.fact"),
        ("enter", "equity.price.bar"),
        ("enter", "equity.valuation.fact"),
        ("read", "5000"),
        ("exit", "equity.valuation.fact"),
        ("exit", "equity.price.bar"),
        ("exit", "equity.financial.fact"),
    ]


def test_equity_analysis_context_propagates_snapshot_timeout(monkeypatch):
    events: list[tuple[str, str]] = []

    @contextmanager
    def snapshot(dataset_key: str, *, lock_deadline: float | None = None) -> Iterator[None]:
        assert lock_deadline is not None
        events.append(("enter", dataset_key))
        if dataset_key == "equity.price.bar":
            raise TimeoutError("snapshot lock timeout")
        try:
            yield
        finally:
            events.append(("exit", dataset_key))

    monkeypatch.setattr(publication_read_composition, "consistent_publication_read", snapshot)
    monkeypatch.setattr(
        published_equity_context,
        "get_published_equity_context_payloads",
        lambda *_args, **_kwargs: pytest.fail("read must not run after snapshot timeout"),
    )

    with pytest.raises(TimeoutError, match="snapshot lock timeout"):
        published_equity_context.get_published_equity_analysis_context_payloads(["600000.SH"])

    assert events == [
        ("enter", "equity.financial.fact"),
        ("enter", "equity.price.bar"),
        ("exit", "equity.financial.fact"),
    ]


def test_equity_analysis_context_returns_early_for_empty_asset_codes(monkeypatch):
    monkeypatch.setattr(
        publication_read_composition,
        "consistent_publication_read",
        lambda *_args, **_kwargs: pytest.fail("empty reads must not open a snapshot"),
    )

    assert published_equity_context.get_published_equity_analysis_context_payloads([" "]) == {}


def test_pool_equity_context_keeps_valuation_limit_default_one(monkeypatch):
    calls: list[tuple[str, int]] = []

    def read_dataset(
        dataset_key: str,
        asset_codes: list[str],
        publication_key: str,
        valuation_limit: int = 1,
    ) -> dict[str, dict[str, object]]:
        calls.append((dataset_key, valuation_limit))
        return {asset_codes[0]: {"rows": [], "publication_key": publication_key}}

    monkeypatch.setattr(published_equity_context, "_dataset_payloads", read_dataset)

    published_equity_context.get_published_equity_context_payloads(
        ["600000.SH"], include_price=False, include_financial=False
    )

    assert calls == [("equity.valuation.fact", 1)]


@pytest.mark.parametrize("invalid_limit", [0, -1, True, 5001])
def test_equity_context_rejects_invalid_valuation_limits_before_read(
    monkeypatch,
    invalid_limit: int,
):
    read_called = False

    def read_dataset(*_args, **_kwargs):
        nonlocal read_called
        read_called = True
        return {}

    monkeypatch.setattr(published_equity_context, "_dataset_payloads", read_dataset)

    with pytest.raises(ValueError, match="valuation_limit"):
        published_equity_context.get_published_equity_context_payloads(
            ["600000.SH"], valuation_limit=invalid_limit
        )

    assert not read_called
