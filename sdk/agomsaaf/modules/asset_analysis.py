"""AgomSAAF SDK - Asset Analysis 模块。"""

from typing import Any

from .base import BaseModule


class AssetAnalysisModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/asset-analysis")

    def multidim_screen(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("multidim-screen/", json=payload)

    def get_weight_configs(self) -> dict[str, Any]:
        return self._get("weight-configs/")

    def get_current_weight(self) -> dict[str, Any]:
        return self._get("current-weight/")

    def screen_asset_pool(self, asset_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if payload:
            return self._post(f"screen/{asset_type}/", json=payload)
        return self._get(f"screen/{asset_type}/")

    def pool_summary(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._get("pool-summary/", params=payload)
