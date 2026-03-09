"""
原始 Payload 仓储

负责持久化外部源的原始响应，便于后续排查字段变更。
"""

import logging
from typing import Dict

from apps.market_data.infrastructure.models import RawPayloadModel

logger = logging.getLogger(__name__)


class RawPayloadRepository:
    """原始 payload 持久化仓储"""

    def save(
        self,
        request_type: str,
        stock_code: str,
        provider_name: str,
        payload: Dict,
        parse_status: str = "success",
        error_message: str = "",
    ) -> None:
        """保存一条原始 payload"""
        try:
            RawPayloadModel.objects.create(
                request_type=request_type,
                stock_code=stock_code,
                provider_name=provider_name,
                payload=payload,
                parse_status=parse_status,
                error_message=error_message,
            )
        except Exception:
            logger.exception(
                "保存原始 payload 失败: %s %s %s",
                request_type,
                stock_code,
                provider_name,
            )
