from apps.alpha.application.tasks import (
    _normalize_qlib_instrument_code,
    _normalize_qlib_instrument_list,
)


def test_normalize_qlib_instrument_code_converts_ts_code_to_qlib_code():
    assert _normalize_qlib_instrument_code("000001.SZ") == "SZ000001"
    assert _normalize_qlib_instrument_code("600000.SH") == "SH600000"
    assert _normalize_qlib_instrument_code("sh600015") == "SH600015"


def test_normalize_qlib_instrument_list_deduplicates_and_preserves_order():
    assert _normalize_qlib_instrument_list(
        ["000001.SZ", "SZ000001", "600000.SH", "sh600000", ""]
    ) == [
        "SZ000001",
        "SH600000",
    ]
