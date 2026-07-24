"""Pulse weight management command contracts."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

from apps.pulse.management.commands import (
    init_pulse_weights,
    set_pulse_weight,
    show_pulse_config,
)


def test_initialize_pulse_weights_activates_one_config_and_seeds_indicators(monkeypatch) -> None:
    """Initialization activates its config and idempotently seeds every indicator."""
    config = SimpleNamespace(id=1, is_active=False, save=lambda: None)
    excluded: list[dict[str, object]] = []
    indicators: list[str] = []
    config_manager = SimpleNamespace(
        get_or_create=lambda **kwargs: (config, True),
        exclude=lambda **kwargs: SimpleNamespace(update=lambda **updates: excluded.append(updates)),
    )
    indicator_manager = SimpleNamespace(
        get_or_create=lambda **kwargs: indicators.append(str(kwargs["indicator_code"]))
        or (object(), True)
    )
    monkeypatch.setattr(
        init_pulse_weights,
        "PulseWeightConfig",
        SimpleNamespace(objects=config_manager),
    )
    monkeypatch.setattr(
        init_pulse_weights,
        "PulseIndicatorWeight",
        SimpleNamespace(objects=indicator_manager),
    )
    monkeypatch.setattr(
        init_pulse_weights,
        "DEFAULT_PULSE_INDICATORS",
        [
            SimpleNamespace(code="breadth", dimension="market"),
            SimpleNamespace(code="credit", dimension="macro"),
        ],
    )
    output = StringIO()
    init_pulse_weights.Command(stdout=output).handle()
    assert config.is_active is True
    assert indicators == ["breadth", "credit"]
    assert excluded == [{"is_active": False}]
    assert "初始化完成" in output.getvalue()

    config_manager.get_or_create = lambda **kwargs: (config, False)
    existing_output = StringIO()
    init_pulse_weights.Command(stdout=existing_output).handle()
    assert "已存在" in existing_output.getvalue()


def test_set_and_show_pulse_weights_cover_missing_and_success_paths(monkeypatch) -> None:
    """Operators receive clear output for missing config, missing indicator, and updates."""
    no_config = SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(first=lambda: None))
    monkeypatch.setattr(
        set_pulse_weight,
        "PulseWeightConfig",
        SimpleNamespace(objects=no_config),
    )
    output = StringIO()
    set_pulse_weight.Command(stdout=output).handle(indicator="breadth", weight=2.0)
    assert "没有找到" in output.getvalue()

    weight = SimpleNamespace(weight=1.0, save=lambda: None)
    config = SimpleNamespace(
        name="default",
        weights=SimpleNamespace(
            filter=lambda **kwargs: [
                SimpleNamespace(dimension="market", indicator_code="breadth", weight=2.0)
            ]
        ),
    )
    active = SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(first=lambda: config))
    monkeypatch.setattr(
        set_pulse_weight,
        "PulseWeightConfig",
        SimpleNamespace(objects=active),
    )
    monkeypatch.setattr(
        set_pulse_weight,
        "PulseIndicatorWeight",
        SimpleNamespace(
            objects=SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(first=lambda: weight))
        ),
    )
    output = StringIO()
    set_pulse_weight.Command(stdout=output).handle(indicator="breadth", weight=2.0)
    assert weight.weight == 2.0
    assert "更新为 2.0" in output.getvalue()

    monkeypatch.setattr(
        set_pulse_weight,
        "PulseIndicatorWeight",
        SimpleNamespace(
            objects=SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(first=lambda: None))
        ),
    )
    missing = StringIO()
    set_pulse_weight.Command(stdout=missing).handle(indicator="missing", weight=1.0)
    assert "未在配置中找到" in missing.getvalue()

    monkeypatch.setattr(
        show_pulse_config,
        "PulseWeightConfig",
        SimpleNamespace(objects=active),
    )
    shown = StringIO()
    show_pulse_config.Command(stdout=shown).handle()
    assert "当前激活配置: default" in shown.getvalue()
    assert "[market] breadth = 2.0" in shown.getvalue()

    monkeypatch.setattr(
        show_pulse_config,
        "PulseWeightConfig",
        SimpleNamespace(objects=no_config),
    )
    absent = StringIO()
    show_pulse_config.Command(stdout=absent).handle()
    assert "没有找到激活" in absent.getvalue()
