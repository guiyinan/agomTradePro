"""Input-boundary regressions for the Qlib data management command."""

from io import StringIO

import pytest
from django.core.management.base import CommandError

from apps.alpha.management.commands import build_qlib_data


def _valid_options() -> dict[str, object]:
    return {
        "provider_uri": "C:/qlib/data",
        "region": "CN",
        "target_date": "2026-07-28",
        "max_staleness_days": 5,
        "check_only": True,
        "universes": "csi300,csi500",
        "lookback_days": 400,
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"provider_uri": 42}, "provider_uri 必须是字符串"),
        ({"provider_uri": "bad\npath"}, "provider_uri 不能包含控制字符"),
        ({"region": {"bad": "shape"}}, "region 必须是字符串"),
        ({"region": "CN/../../US"}, "region 必须是"),
        ({"target_date": "2026-02-30"}, "target_date 必须是"),
        ({"target_date": True}, "target_date 必须是"),
        ({"max_staleness_days": -1}, "max_staleness_days 必须位于"),
        ({"max_staleness_days": True}, "max_staleness_days 必须是整数"),
        ({"lookback_days": 0}, "lookback_days 必须位于"),
        ({"lookback_days": 2_001}, "lookback_days 必须位于"),
        ({"universes": ["csi300"]}, "universes 必须是逗号分隔字符串"),
        ({"universes": "csi300,../../etc"}, "universe 必须是"),
        ({"universes": " , "}, "至少需要一个 universe"),
        ({"check_only": 1}, "check_only 必须是布尔值"),
    ],
)
def test_invalid_options_fail_before_token_or_local_data_io(
    monkeypatch,
    overrides: dict[str, object],
    message: str,
) -> None:
    monkeypatch.setattr(build_qlib_data, "get_runtime_qlib_config", lambda: {})
    monkeypatch.setattr(
        build_qlib_data,
        "_resolve_tushare_token",
        lambda: pytest.fail("invalid options must fail before secret lookup"),
    )
    monkeypatch.setattr(
        build_qlib_data,
        "_inspect_latest_trade_date",
        lambda *_args: pytest.fail("invalid options must fail before local data inspection"),
    )
    options = _valid_options() | overrides

    with pytest.raises(CommandError, match=message):
        build_qlib_data.Command(stdout=StringIO()).handle(**options)


def test_runtime_provider_config_is_validated_before_io(monkeypatch) -> None:
    monkeypatch.setattr(
        build_qlib_data,
        "get_runtime_qlib_config",
        lambda: {"provider_uri": {"unexpected": "mapping"}, "region": "CN"},
    )
    monkeypatch.setattr(
        build_qlib_data,
        "_resolve_tushare_token",
        lambda: pytest.fail("invalid runtime config must fail before secret lookup"),
    )

    options = _valid_options() | {"provider_uri": None, "region": None}

    with pytest.raises(CommandError, match="provider_uri 必须是字符串"):
        build_qlib_data.Command(stdout=StringIO()).handle(**options)


def test_option_parser_normalizes_and_deduplicates_universes() -> None:
    options = _valid_options() | {"universes": " CSI300, custom_index, csi300 "}

    parsed = build_qlib_data._parse_command_options(options, {})

    assert parsed.region == "cn"
    assert parsed.universes == ("csi300", "custom_index")
    assert parsed.lookback_days == 400


@pytest.mark.parametrize("token", [None, "", "   ", 42, {"token": "secret"}])
def test_tushare_token_resolver_rejects_non_string_or_blank_values(
    monkeypatch,
    token: object,
) -> None:
    monkeypatch.setattr("shared.config.secrets.get_tushare_token", lambda: token)

    assert build_qlib_data._resolve_tushare_token() is None
