"""
Market Data 模块 - Interface 层视图

只做输入验证和输出格式化，禁止业务逻辑。
"""

import logging
from datetime import time

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.market_data.application.cross_validator import validate_and_select
from apps.market_data.application.registry_factory import get_registry
from apps.market_data.application.use_cases import (
    IngestStockNewsRequest,
    IngestStockNewsUseCase,
    SyncCapitalFlowRequest,
    SyncCapitalFlowUseCase,
)
from apps.market_data.domain.enums import DataCapability
from apps.market_data.interface.serializers import (
    CapitalFlowSnapshotSerializer,
    IngestStockNewsResponseSerializer,
    ProviderStatusSerializer,
    QuoteSnapshotSerializer,
    StockNewsItemSerializer,
    SyncCapitalFlowResponseSerializer,
)
from shared.config.secrets import get_secrets

logger = logging.getLogger(__name__)


def _is_cn_a_share_market_closed(now) -> bool:
    """粗略判断 A 股是否处于收盘时段。"""
    local_now = timezone.localtime(now)
    if local_now.weekday() >= 5:
        return True

    current = local_now.time()
    morning_open = time(9, 30)
    morning_close = time(11, 30)
    afternoon_open = time(13, 0)
    afternoon_close = time(15, 0)

    in_morning = morning_open <= current <= morning_close
    in_afternoon = afternoon_open <= current <= afternoon_close
    return not (in_morning or in_afternoon)


def _parse_positive_int(raw_value, field_name: str, default: int) -> int:
    """解析正整数参数，非法时抛出 ValueError。"""
    if raw_value in (None, ""):
        return default

    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是整数") from exc

    if value <= 0:
        raise ValueError(f"{field_name} 必须大于 0")

    return value


def _build_market_data_unavailable_hint(market_closed: bool) -> str:
    """构造更可执行的不可用提示。"""
    hint_parts = []
    if market_closed:
        hint_parts.append("当前已收盘，正常应优先展示最近一个交易日收盘价。")
    else:
        hint_parts.append("当前应优先展示盘中实时行情。")

    try:
        secrets = get_secrets().data_sources
    except OSError:
        hint_parts.append("检测到未配置 Tushare Token，收盘价备用源当前不可用。")
    else:
        if secrets.tushare_http_url:
            hint_parts.append("Tushare 备用源当前使用自定义 HTTP URL。")

    hint_parts.append("请检查东方财富连接状态，或在数据源中台补齐 Tushare Token/HTTP URL。")
    return " ".join(hint_parts)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_realtime_quotes(request: Request) -> Response:
    """获取实时行情快照

    Query params:
        codes: 逗号分隔的股票代码（Tushare 格式）
    """
    codes_param = request.query_params.get("codes", "")
    if not codes_param:
        return Response(
            {"error": "缺少 codes 参数"}, status=status.HTTP_400_BAD_REQUEST
        )

    stock_codes = [c.strip() for c in codes_param.split(",") if c.strip()]
    if not stock_codes:
        return Response(
            {"error": "codes 参数为空"}, status=status.HTTP_400_BAD_REQUEST
        )

    registry = get_registry()
    now = timezone.now()
    market_closed = _is_cn_a_share_market_closed(now)
    snapshots = registry.call_with_failover(
        DataCapability.REALTIME_QUOTE,
        lambda p: p.get_quote_snapshots(stock_codes),
    )
    if snapshots is None:
        message = "所有实时行情 provider 均不可用"
        if market_closed:
            message = "当前已收盘，实时行情不可用，且收盘价备用源也不可用"
        return Response(
            {
                "error": message,
                "market_closed": market_closed,
                "fallback_mode": "unavailable",
                "hint": _build_market_data_unavailable_hint(market_closed),
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    fallback_mode = (
        "close_fallback"
        if snapshots and all((s.source or "").lower() == "tushare" for s in snapshots)
        else "realtime"
    )
    message = None
    if fallback_mode == "close_fallback":
        message = "当前展示的是最近一个交易日收盘价，非盘中实时行情"

    serializer = QuoteSnapshotSerializer(
        [s.to_dict() for s in snapshots], many=True
    )
    return Response(
        {
            "data": serializer.data,
            "market_closed": market_closed,
            "fallback_mode": fallback_mode,
            "message": message,
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_capital_flows(request: Request) -> Response:
    """获取个股资金流向

    Query params:
        code: 股票代码
        period: 时间范围（默认 5d）
    """
    stock_code = request.query_params.get("code", "")
    if not stock_code:
        return Response(
            {"error": "缺少 code 参数"}, status=status.HTTP_400_BAD_REQUEST
        )

    period = request.query_params.get("period", "5d")
    registry = get_registry()
    flows = registry.call_with_failover(
        DataCapability.CAPITAL_FLOW,
        lambda p: p.get_capital_flows(stock_code, period=period),
    )
    if flows is None:
        return Response(
            {"error": "所有资金流向 provider 均不可用"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    serializer = CapitalFlowSnapshotSerializer(
        [f.to_dict() for f in flows], many=True
    )
    return Response({"data": serializer.data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_stock_news(request: Request) -> Response:
    """获取个股新闻

    Query params:
        code: 股票代码
        limit: 最多返回条数（默认 20）
    """
    stock_code = request.query_params.get("code", "")
    if not stock_code:
        return Response(
            {"error": "缺少 code 参数"}, status=status.HTTP_400_BAD_REQUEST
        )

    try:
        limit = _parse_positive_int(
            request.query_params.get("limit", "20"),
            field_name="limit",
            default=20,
        )
    except ValueError as exc:
        return Response(
            {"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST
        )
    registry = get_registry()
    items = registry.call_with_failover(
        DataCapability.STOCK_NEWS,
        lambda p: p.get_stock_news(stock_code, limit=limit),
    )
    if items is None:
        return Response(
            {"error": "所有股票新闻 provider 均不可用"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    serializer = StockNewsItemSerializer(
        [i.to_dict() for i in items], many=True
    )
    return Response({"data": serializer.data})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sync_capital_flow(request: Request) -> Response:
    """同步个股资金流向到数据库

    Body:
        stock_code: 股票代码
        period: 时间范围（默认 5d）
    """
    stock_code = request.data.get("stock_code", "")
    if not stock_code:
        return Response(
            {"error": "缺少 stock_code"}, status=status.HTTP_400_BAD_REQUEST
        )

    period = request.data.get("period", "5d")
    registry = get_registry()
    use_case = SyncCapitalFlowUseCase(registry)
    result = use_case.execute(
        SyncCapitalFlowRequest(stock_code=stock_code, period=period)
    )

    serializer = SyncCapitalFlowResponseSerializer(
        {
            "stock_code": result.stock_code,
            "synced_count": result.synced_count,
            "success": result.success,
            "error_message": result.error_message,
        }
    )
    resp_status = status.HTTP_200_OK if result.success else status.HTTP_503_SERVICE_UNAVAILABLE
    return Response(serializer.data, status=resp_status)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ingest_stock_news(request: Request) -> Response:
    """采集个股新闻到数据库

    Body:
        stock_code: 股票代码
        limit: 最多采集条数（默认 20）
    """
    stock_code = request.data.get("stock_code", "")
    if not stock_code:
        return Response(
            {"error": "缺少 stock_code"}, status=status.HTTP_400_BAD_REQUEST
        )

    try:
        limit = _parse_positive_int(
            request.data.get("limit", 20),
            field_name="limit",
            default=20,
        )
    except ValueError as exc:
        return Response(
            {"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST
        )
    registry = get_registry()
    use_case = IngestStockNewsUseCase(registry)
    result = use_case.execute(
        IngestStockNewsRequest(stock_code=stock_code, limit=limit)
    )

    serializer = IngestStockNewsResponseSerializer(
        {
            "stock_code": result.stock_code,
            "fetched_count": result.fetched_count,
            "new_count": result.new_count,
            "data_sufficient": result.data_sufficient,
            "success": result.success,
            "error_message": result.error_message,
        }
    )
    resp_status = status.HTTP_200_OK if result.success else status.HTTP_503_SERVICE_UNAVAILABLE
    return Response(serializer.data, status=resp_status)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def provider_health(request: Request) -> Response:
    """获取所有 provider 健康状态"""
    registry = get_registry()
    statuses = registry.get_all_statuses()
    serializer = ProviderStatusSerializer(
        [s.to_dict() for s in statuses], many=True
    )
    return Response({"data": serializer.data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cross_validate(request: Request) -> Response:
    """交叉校验多数据源行情

    对指定股票代码，从所有可用 provider 获取行情并比对偏差。

    Query params:
        codes: 逗号分隔的股票代码
    """
    codes_param = request.query_params.get("codes", "")
    if not codes_param:
        return Response(
            {"error": "缺少 codes 参数"}, status=status.HTTP_400_BAD_REQUEST
        )

    stock_codes = [c.strip() for c in codes_param.split(",") if c.strip()]
    if not stock_codes:
        return Response(
            {"error": "codes 参数为空"}, status=status.HTTP_400_BAD_REQUEST
        )

    registry = get_registry()
    quotes, validation = validate_and_select(registry, stock_codes)

    result = {
        "quotes_count": len(quotes),
        "validation": validation.to_dict() if validation else None,
    }
    return Response({"data": result})
