"""Shared configuration contract for Tushare request transports."""

from typing import Literal

TUSHARE_REQUEST_MODE_SDK_PATH: Literal["sdk_path"] = "sdk_path"
TUSHARE_REQUEST_MODE_UNIFIED_RELAY: Literal["unified_relay"] = "unified_relay"
TushareRequestMode = Literal["sdk_path", "unified_relay"]
TUSHARE_REQUEST_MODE_VALUES: tuple[TushareRequestMode, ...] = (
    TUSHARE_REQUEST_MODE_SDK_PATH,
    TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
)
