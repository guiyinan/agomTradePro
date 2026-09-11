"""Fee configuration API views for simulated trading."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar, cast

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application import interface_services as simulated_interface_services

from .serializers import FeeConfigListResponseSerializer

ViewMethodT = TypeVar("ViewMethodT", bound=Callable[..., Any])


class ExtendSchemaProtocol(Protocol):
    """Typed façade for drf-spectacular's decorator factory."""

    def __call__(self, *args: Any, **kwargs: Any) -> Callable[[ViewMethodT], ViewMethodT]: ...


typed_extend_schema = cast(ExtendSchemaProtocol, extend_schema)


class FeeConfigListAPIView(APIView):
    """费率配置列表 API。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.fee_config_repo = simulated_interface_services.get_fee_config_repository()

    @typed_extend_schema(
        summary="获取费率配置列表",
        description="获取所有费率配置",
        responses={200: FeeConfigListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        """Return all configured fee schedules."""

        configs = self.fee_config_repo.get_all_configs()
        config_list = [
            {
                "config_id": config.config_id,
                "config_name": config.config_name,
                "asset_type": config.asset_type,
                "commission_rate_buy": config.commission_rate_buy,
                "commission_rate_sell": config.commission_rate_sell,
                "min_commission": config.min_commission,
                "stamp_duty_rate": config.stamp_duty_rate,
                "transfer_fee_rate": config.transfer_fee_rate,
                "min_transfer_fee": config.min_transfer_fee,
                "slippage_rate": config.slippage_rate,
                "description": config.description,
            }
            for config in configs
        ]
        return Response({"success": True, "count": len(config_list), "configs": config_list})


__all__ = ["FeeConfigListAPIView"]
