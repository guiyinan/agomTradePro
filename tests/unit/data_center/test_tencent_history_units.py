import pytest

from apps.data_center.infrastructure import tencent_history_units as units
from core.exceptions import ConfigurationError


@pytest.mark.parametrize(
    "raw", [None, "bad", {}, {"*": True}, {"*": 0}, {"*": 100, "bad": 1}, {"*": float("nan")}]
)
def test_missing_or_invalid_unit_rules_fail_closed(raw):
    with pytest.raises(ConfigurationError):
        units.parse_history_volume_rules(raw)


def test_longest_configured_prefix_and_exchange_match(monkeypatch):
    monkeypatch.setattr(
        units, "get_runtime_config_value", lambda key: {"*": 100, "68.SH": 1, "688012.SH": 2}
    )
    assert units.history_volume_multiplier("688012.SH") == 2
    assert units.history_volume_multiplier("689009.SH") == 1
    assert units.history_volume_multiplier("688012.SZ") == 100
    assert units.history_volume_multiplier("000001.SZ") == 100


def test_configuration_command_dry_run_then_audited_activation(tmp_path, monkeypatch):
    from django.core.management import call_command

    from apps.data_center.management.commands import configure_tencent_history_units as command

    rules = tmp_path / "units.json"
    rules.write_text('{"*":100,"688.SH":1}')
    calls = []
    monkeypatch.setattr(command, "register_runtime_definitions", lambda specs: calls.append(specs))
    monkeypatch.setattr(
        command,
        "activate_runtime_profile_patch",
        lambda **kwargs: (calls.append(kwargs) or {"profile_id": "new"}),
    )
    kwargs = {
        "rules": str(rules),
        "environment": "production",
        "actor": "test",
        "reason": "verified units",
    }
    call_command("configure_tencent_history_units", **kwargs)
    assert calls == []
    call_command("configure_tencent_history_units", apply=True, **kwargs)
    assert len(calls) == 2
    assert set(calls[1]["patch"]) == {units.TENCENT_HISTORY_VOLUME_KEY}
    assert calls[1]["reason"] == "verified units"
