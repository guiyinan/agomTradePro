"""Hedge initialization command contracts."""

from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management.base import CommandError

from apps.hedge.management.commands import init_hedge


def test_init_hedge_rejects_non_boolean_reset() -> None:
    with pytest.raises(CommandError, match="--reset must be boolean"):
        init_hedge.Command(stdout=StringIO()).handle(reset="yes")


def test_init_hedge_publishes_bounded_unique_seed_pairs(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    class _Manager:
        def get_or_create(self, *, name: str, defaults: dict[str, object]):
            captured.append(dict(defaults))
            return (
                SimpleNamespace(
                    name=name,
                    long_asset=defaults["long_asset"],
                    hedge_asset=defaults["hedge_asset"],
                ),
                True,
            )

    monkeypatch.setattr(
        init_hedge,
        "HedgePairModel",
        SimpleNamespace(_default_manager=_Manager()),
    )
    output = StringIO()

    init_hedge.Command(stdout=output).handle(reset=False)

    assert len(captured) == 10
    assert len({str(item["name"]) for item in captured}) == 10
    assert all(
        float(item["target_long_weight"]) + float(item["target_hedge_weight"]) == pytest.approx(1.0)
        for item in captured
    )
    assert "已初始化 10 个对冲对配置" in output.getvalue()
