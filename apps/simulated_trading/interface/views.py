"""模拟盘交易模块 Interface 层视图兼容导出面。

遵循四层架构规范：
- Interface 层只做输入验证和输出格式化
- 禁止业务逻辑
- 包含 API 视图（DRF）

账户生命周期 API 和共享输入/输出辅助函数分别由同层私有模块负责；本
模块保留原有页面、API 类和辅助函数的稳定导入路径。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, TypeVar, cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application import interface_services as simulated_interface_services
from apps.simulated_trading.application.use_cases import (
    ExecuteBuyOrderUseCase,
    ExecuteSellOrderUseCase,
    ListAccountsUseCase,
)
from apps.simulated_trading.domain.entities import AccountType
from core.exceptions import (
    DataFetchError,
    DataValidationError,
    DuplicateResourceError,
    ExternalServiceError,
    InvalidInputError,
)
from core.integration.authenticated_canonical_account_creation import (
    create_authenticated_canonical_account,
)

from ._account_views import (
    AccountBatchDeleteAPIView,
    AccountDetailAPIView,
)
from ._fee_config_views import FeeConfigListAPIView
from ._portfolio_views import (
    PerformanceAPIView,
    PositionListAPIView,
    TradeListAPIView,
)
from ._view_helpers import (
    AccountModelProtocol,
    _account_payload,
    _authenticated_user_id,
    _delete_account_with_summary,
    _get_owned_account_or_response,
    _parse_iso_date,
    _parse_positive_int,
)
from .serializers import (
    AccountCreateResponseSerializer,
    AccountCreationKeySerializer,
    AccountListResponseSerializer,
    AutoTradingRunRequestSerializer,
    AutoTradingRunResponseSerializer,
    CreateAccountRequestSerializer,
    DailyInspectionReportListResponseSerializer,
    DailyInspectionRunRequestSerializer,
    EquityCurveResponseSerializer,
    ManualTradeRequestSerializer,
    ManualTradeResponseSerializer,
)

ViewMethodT = TypeVar("ViewMethodT", bound=Callable[..., Any])


class ExtendSchemaProtocol(Protocol):
    """Typed façade for drf-spectacular's decorator factory."""

    def __call__(self, *args: Any, **kwargs: Any) -> Callable[[ViewMethodT], ViewMethodT]: ...


typed_extend_schema = cast(ExtendSchemaProtocol, extend_schema)


__all__ = [
    "AccountModelProtocol",
    "AccountBatchDeleteAPIView",
    "AccountDetailAPIView",
    "AccountListAPIView",
    "AutoTradingAPIView",
    "DailyInspectionReportListAPIView",
    "DailyInspectionRunAPIView",
    "EquityCurveAPIView",
    "FeeConfigListAPIView",
    "ManualTradeAPIView",
    "PerformanceAPIView",
    "PositionListAPIView",
    "TradeListAPIView",
    "account_detail_page",
    "dashboard_page",
    "my_account_detail_page",
    "my_accounts_page",
    "my_inspection_notify_page",
    "my_positions_page",
    "my_trades_page",
    "_account_payload",
    "_authenticated_user_id",
    "_delete_account_with_summary",
    "_get_owned_account_or_response",
    "_parse_iso_date",
    "_parse_positive_int",
]


# ============================================================================
# 页面视图（前端）
# ============================================================================


@require_http_methods(["GET"])
@login_required
def dashboard_page(request: HttpRequest) -> HttpResponse:
    """
    模拟盘仪表盘页面

    GET /simulated-trading/dashboard/
    """
    return render(request, "simulated_trading/dashboard.html")


@require_http_methods(["GET"])
@login_required
def account_detail_page(request: HttpRequest, account_id: int) -> HttpResponse:
    """
    账户详情页面

    GET /simulated-trading/accounts/{id}/
    """
    context = {"account_id": account_id}
    return render(request, "simulated_trading/account_detail.html", context)


# ============================================================================
# 用户专属投资组合视图
# ============================================================================


@login_required
@require_http_methods(["GET", "POST"])
def my_accounts_page(request: HttpRequest) -> HttpResponse:
    """
    我的账户页面

    显示当前用户的所有账户，account_type 仅作为账户属性展示。
    支持创建新账户。

    GET /simulated-trading/my-accounts/
    POST /simulated-trading/my-accounts/
    """
    from django.contrib import messages

    if request.method == "POST":
        # 创建新账户
        account_type = request.POST.get("account_type")
        account_name = request.POST.get("account_name")
        try:
            initial_capital = Decimal(request.POST.get("initial_capital", "100000"))
        except (InvalidOperation, ValueError):
            messages.error(request, "初始资金必须是有效数字")
            return redirect("/simulated-trading/my-accounts/")

        # 验证
        if account_type not in ["real", "simulated"]:
            messages.error(request, "无效的账户类型")
            return redirect("/simulated-trading/my-accounts/")

        if not account_name:
            messages.error(request, "请输入账户名称")
            return redirect("/simulated-trading/my-accounts/")

        if not initial_capital.is_finite() or initial_capital <= 0:
            messages.error(request, "初始资金必须大于0")
            return redirect("/simulated-trading/my-accounts/")

        # 创建账户
        simulated_interface_services.create_account_for_user(
            user=request.user,
            account_name=account_name,
            account_type=account_type,
            initial_capital=initial_capital,
        )

        type_label = "真实账户" if account_type == "real" else "模拟账户"
        messages.success(request, f"{type_label}创建成功！")
        return redirect("/simulated-trading/my-accounts/")

    # GET 请求：显示用户账户列表
    context = simulated_interface_services.build_my_accounts_context(request.user)
    return render(request, "simulated_trading/my_accounts.html", context)


@login_required
@require_http_methods(["GET"])
def my_account_detail_page(request: HttpRequest, account_id: int) -> HttpResponse:
    """
    我的账户详情页面

    显示指定账户的详细信息、持仓和交易记录
    GET /simulated-trading/my-accounts/{id}/
    """
    context = simulated_interface_services.build_my_account_detail_context(request.user, account_id)
    if context is None:
        raise Http404("账户不存在")
    return render(request, "simulated_trading/my_account_detail.html", context)


@login_required
@require_http_methods(["GET"])
def my_positions_page(request: HttpRequest, account_id: int) -> HttpResponse:
    """
    我的持仓页面

    显示指定账户的所有持仓
    GET /simulated-trading/my-accounts/{id}/positions/
    """
    context = simulated_interface_services.build_my_positions_context(request.user, account_id)
    if context is None:
        raise Http404("账户不存在")
    return render(request, "simulated_trading/my_positions.html", context)


@login_required
@require_http_methods(["GET"])
def my_trades_page(request: HttpRequest, account_id: int) -> HttpResponse:
    """
    我的交易记录页面

    显示指定账户的所有交易记录
    GET /simulated-trading/my-accounts/{id}/trades/
    """
    context = simulated_interface_services.build_my_trades_context(request.user, account_id)
    if context is None:
        raise Http404("账户不存在")
    return render(request, "simulated_trading/my_trades.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def my_inspection_notify_page(request: HttpRequest, account_id: int) -> HttpResponse:
    """
    巡检邮件通知配置页面

    GET/POST /simulated-trading/my-accounts/{id}/inspection-notify/
    """
    from django.contrib import messages

    context = simulated_interface_services.build_inspection_notify_context(request.user, account_id)
    if context is None:
        raise Http404("账户不存在")

    if request.method == "POST":
        is_enabled = request.POST.get("is_enabled") == "on"
        include_owner_email = request.POST.get("include_owner_email") == "on"
        notify_on = request.POST.get("notify_on", "warning_error")
        if notify_on not in {"warning_error", "all"}:
            notify_on = "warning_error"

        raw_emails = request.POST.get("recipient_emails", "")
        emails: list[str] = []
        invalid: list[str] = []
        for chunk in raw_emails.replace(";", ",").replace("\n", ",").split(","):
            email = chunk.strip()
            if not email:
                continue
            try:
                validate_email(email)
                emails.append(email)
            except DjangoValidationError:
                invalid.append(email)

        if invalid:
            messages.error(request, f"以下邮箱格式无效: {', '.join(invalid)}")
        else:
            simulated_interface_services.save_inspection_notification_config(
                account_id=account_id,
                is_enabled=is_enabled,
                include_owner_email=include_owner_email,
                notify_on=notify_on,
                recipient_emails=emails,
            )
            messages.success(request, "巡检邮件通知配置已保存")
            return redirect(f"/simulated-trading/my-accounts/{account_id}/inspection-notify/")
    return render(request, "simulated_trading/inspection_notify.html", context)


# ============================================================================
# API 视图
# ============================================================================


class AccountListAPIView(APIView):
    """账户列表 API"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.account_repo = simulated_interface_services.get_account_repository()

    @typed_extend_schema(
        summary="获取统一账户列表",
        description="获取当前用户的账户列表，支持按 active_only 和 account_type 过滤。",
        parameters=[
            OpenApiParameter(
                name="active_only",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description="是否只返回活跃账户（默认 true）",
            ),
            OpenApiParameter(
                name="account_type",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="账户类型过滤：real 或 simulated",
            ),
        ],
        responses={200: AccountListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        """Return the authenticated user's accounts with optional filters."""

        if not request.user or not request.user.is_authenticated:
            return Response(
                {"success": False, "error": "请先登录后再查看账户列表"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        active_only = request.query_params.get("active_only", "true").lower() == "true"
        raw_account_type = request.query_params.get("account_type")
        account_type = None
        if raw_account_type:
            if raw_account_type not in {"real", "simulated"}:
                return Response(
                    {"success": False, "error": "account_type 必须是 real 或 simulated"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            account_type = AccountType(raw_account_type)

        use_case = ListAccountsUseCase(self.account_repo)
        accounts = use_case.execute(
            active_only=active_only,
            user_id=_authenticated_user_id(request),
            account_type=account_type,
        )
        if account_type is not None:
            accounts = [account for account in accounts if account.account_type == account_type]

        account_list = [_account_payload(account) for account in accounts]
        return Response({"success": True, "count": len(account_list), "accounts": account_list})

    @typed_extend_schema(
        summary="创建账户",
        description="创建新的统一账户，账户类型通过 account_type 指定。",
        request=CreateAccountRequestSerializer,
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description="同一次创建及网络重试复用此键；新的创建使用新键。",
            )
        ],
        responses={200: AccountCreateResponseSerializer, 201: AccountCreateResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        """Create an account through the authenticated canonical creation bridge."""

        serializer = CreateAccountRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key_serializer = AccountCreationKeySerializer(
            data={"request_key": request.headers.get("Idempotency-Key", "")}
        )
        key_serializer.is_valid(raise_exception=True)

        try:
            result = create_authenticated_canonical_account(
                request=request,
                parameters=serializer.to_creation_input(
                    request_key=cast(str, key_serializer.validated_data["request_key"])
                ),
            )
            response_data = _account_payload(result.account, newly_created=not result.replayed)
            return Response(
                {"success": True, "account": response_data, "replayed": result.replayed},
                status=status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED,
            )
        except DuplicateResourceError:
            return Response(
                {"success": False, "error": "创建请求与现有账户或已提交请求冲突。"},
                status=status.HTTP_409_CONFLICT,
            )
        except InvalidInputError:
            return Response(
                {"success": False, "error": "创建账户的输入无效。"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (DataValidationError, ExternalServiceError):
            return Response(
                {"success": False, "error": "账户创建暂不可用，请稍后重试本次提交。"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class ManualTradeAPIView(APIView):
    """手动交易 API"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.account_repo = simulated_interface_services.get_account_repository()
        self.position_repo = simulated_interface_services.get_position_repository()
        self.trade_repo = simulated_interface_services.get_trade_repository()

    @typed_extend_schema(
        summary="手动交易",
        description="执行手动买入或卖出订单",
        request=ManualTradeRequestSerializer,
        responses={200: ManualTradeResponseSerializer},
    )
    def post(self, request: Request, account_id: int) -> Response:
        """
        POST /api/simulated-trading/accounts/{id}/trade/

        手动交易

        Request Body:
        {
            "asset_code": "000001.SZ",
            "asset_name": "平安银行",
            "asset_type": "equity",
            "action": "buy",
            "quantity": 1000,
            "price": 12.50,
            "reason": "测试买入"
        }

        Response:
        {
            "success": true,
            "message": "买入成功",
            "trade": {...}
        }
        """
        account_model = _get_owned_account_or_response(request, account_id, action="操作")
        if isinstance(account_model, Response):
            return account_model

        # 1. 验证请求
        serializer = ManualTradeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            # 2. 根据动作执行不同用例
            if data["action"] == "buy":
                signal_repo = simulated_interface_services.get_trading_signal_repository()
                buy_use_case = ExecuteBuyOrderUseCase(
                    self.account_repo,
                    self.position_repo,
                    self.trade_repo,
                    simulated_interface_services.get_fee_config_repository(),
                    signal_repo=signal_repo,
                )
                trade = buy_use_case.execute(
                    account_id=account_id,
                    asset_code=data["asset_code"],
                    asset_name=data["asset_name"],
                    asset_type=data["asset_type"],
                    quantity=data["quantity"],
                    price=float(data["price"]),
                    reason=data.get("reason"),
                    signal_id=data.get("signal_id"),
                )
                message = f"买入成功: {data['asset_name']} x{data['quantity']} @ {data['price']}"

            else:  # sell
                sell_use_case = ExecuteSellOrderUseCase(
                    self.account_repo,
                    self.position_repo,
                    self.trade_repo,
                    simulated_interface_services.get_fee_config_repository(),
                )
                trade = sell_use_case.execute(
                    account_id=account_id,
                    asset_code=data["asset_code"],
                    quantity=data["quantity"],
                    price=float(data["price"]),
                    reason=data.get("reason"),
                )
                message = f"卖出成功: {data['asset_name']} x{data['quantity']} @ {data['price']}"

            # 3. 序列化交易记录
            trade_data = {
                "trade_id": trade.trade_id,
                "account_id": trade.account_id,
                "asset_code": trade.asset_code,
                "asset_name": trade.asset_name,
                "asset_type": trade.asset_type,
                "action": trade.action.value,
                "quantity": trade.quantity,
                "price": str(trade.price),
                "amount": str(trade.amount),
                "commission": str(trade.commission),
                "slippage": str(trade.slippage),
                "total_cost": str(trade.total_cost),
                "realized_pnl": (
                    str(trade.realized_pnl) if trade.realized_pnl is not None else None
                ),
                "realized_pnl_pct": trade.realized_pnl_pct,
                "reason": trade.reason,
                "signal_id": trade.signal_id,
                "order_date": trade.order_date.isoformat(),
                "execution_date": trade.execution_date.isoformat(),
                "execution_time": trade.execution_time.isoformat(),
                "status": trade.status.value,
            }

            return Response({"success": True, "message": message, "trade": trade_data})

        except ValueError as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class EquityCurveAPIView(APIView):
    """净值曲线 API"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.account_repo = simulated_interface_services.get_account_repository()
        self.trade_repo = simulated_interface_services.get_trade_repository()
        self.performance_calculator = simulated_interface_services.get_performance_calculator()

    @typed_extend_schema(
        summary="获取净值曲线",
        description="获取账户的净值曲线数据（用于图表）",
        parameters=[
            OpenApiParameter(
                name="start_date", type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                name="end_date", type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY
            ),
        ],
        responses={200: EquityCurveResponseSerializer},
    )
    def get(self, request: Request, account_id: int) -> Response:
        """
        GET /api/simulated-trading/accounts/{id}/equity-curve/

        获取净值曲线

        Query Parameters:
        - start_date: 开始日期（可选）
        - end_date: 结束日期（可选）

        Response:
        {
            "success": true,
            "account_id": 1,
            "account_name": "测试账户1",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "data_points": [
                {
                    "date": "2024-01-01",
                    "net_value": 100000.00,
                    "trades_count": 2,
                    "daily_pnl": -500.00
                },
                ...
            ]
        }
        """
        account_model = _get_owned_account_or_response(request, account_id, action="查看")
        if isinstance(account_model, Response):
            return account_model

        account = self.account_repo.get_by_id(account_id)
        if not account:
            return Response(
                {"success": False, "error": f"账户不存在: {account_id}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 获取日期范围
        raw_start_date = request.query_params.get("start_date")
        raw_end_date = request.query_params.get("end_date")

        try:
            if not raw_start_date:
                start_date = account.start_date
            else:
                start_date = _parse_iso_date(raw_start_date, field_name="start_date")

            if not raw_end_date:
                end_date = date.today()
            else:
                end_date = _parse_iso_date(raw_end_date, field_name="end_date")
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if start_date > end_date:
            return Response(
                {"success": False, "error": "start_date 不能晚于 end_date"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 获取净值曲线
        try:
            data_points = self.performance_calculator.get_equity_curve(
                account_id=account_id, start_date=start_date, end_date=end_date
            )
        except DataFetchError as exc:
            return Response(
                {
                    "success": False,
                    "error": str(exc),
                    "code": exc.code,
                    "details": exc.details,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "success": True,
                "account_id": account_id,
                "account_name": account.account_name,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "data_points": data_points,
            }
        )


class AutoTradingAPIView(APIView):
    """自动交易 API"""

    @typed_extend_schema(
        summary="执行自动交易",
        description="手动触发自动交易引擎（用于测试或补跑）",
        request=AutoTradingRunRequestSerializer,
        responses={200: AutoTradingRunResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        """
        POST /api/simulated-trading/auto-trading/run/

        执行自动交易

        Request Body:
        {
            "trade_date": "2024-01-15",
            "account_ids": [1, 2]  // 可选，空则全部活跃账户
        }

        Response:
        {
            "success": true,
            "trade_date": "2024-01-15",
            "total_accounts": 2,
            "results": {
                "1": {"buy_count": 3, "sell_count": 1},
                "2": {"buy_count": 2, "sell_count": 0}
            },
            "summary": {
                "total_buy_count": 5,
                "total_sell_count": 1
            }
        }
        """
        # 1. 验证请求
        serializer = AutoTradingRunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        trade_date = data.get("trade_date") or date.today()
        account_ids = data.get("account_ids")

        # 2. 初始化引擎
        engine = simulated_interface_services.build_auto_trading_engine()

        # 3. 执行自动交易
        try:
            results = engine.run_daily_trading(trade_date, account_ids=account_ids)

            # 汇总统计
            total_buy_count = sum(r["buy_count"] for r in results.values())
            total_sell_count = sum(r["sell_count"] for r in results.values())

            return Response(
                {
                    "success": True,
                    "trade_date": trade_date.isoformat(),
                    "total_accounts": len(results),
                    "results": results,
                    "summary": {
                        "total_buy_count": total_buy_count,
                        "total_sell_count": total_sell_count,
                    },
                }
            )

        except Exception as e:
            return Response(
                {"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DailyInspectionRunAPIView(APIView):
    """手动触发日更巡检 API"""

    @typed_extend_schema(
        summary="执行账户日更巡检",
        description="对指定账户执行一轮日更巡检并写入数据库",
        request=DailyInspectionRunRequestSerializer,
        responses={200: DailyInspectionReportListResponseSerializer},
    )
    def post(self, request: Request, account_id: int) -> Response:
        account_model = _get_owned_account_or_response(request, account_id, action="执行")
        if isinstance(account_model, Response):
            return account_model

        serializer = DailyInspectionRunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            result = simulated_interface_services.run_daily_inspection(
                account_id=account_id,
                inspection_date=data.get("inspection_date") or date.today(),
                strategy_id=data.get("strategy_id"),
                auto_create_proposal=data.get("auto_create_proposal", False),
            )
            return Response(
                {
                    "success": True,
                    "count": 1,
                    "reports": [result],
                }
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DailyInspectionReportListAPIView(APIView):
    """账户日更巡检历史 API"""

    @typed_extend_schema(
        summary="获取账户日更巡检历史",
        description="按账户查询日更巡检报告列表",
        parameters=[
            OpenApiParameter(name="limit", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY),
            OpenApiParameter(
                name="inspection_date", type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY
            ),
        ],
        responses={200: DailyInspectionReportListResponseSerializer},
    )
    def get(self, request: Request, account_id: int) -> Response:
        account_model = _get_owned_account_or_response(request, account_id, action="查看")
        if isinstance(account_model, Response):
            return account_model

        try:
            limit = _parse_positive_int(
                request.query_params.get("limit", 20),
                field_name="limit",
                default=20,
            )
            raw_inspection_date = request.query_params.get("inspection_date")
            inspection_date = (
                _parse_iso_date(raw_inspection_date, field_name="inspection_date")
                if raw_inspection_date
                else None
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = simulated_interface_services.list_daily_inspection_report_payloads(
            account_id=account_id,
            limit=limit,
            inspection_date=inspection_date,
        )

        return Response(
            {
                "success": True,
                "count": len(payload),
                "reports": payload,
            }
        )
