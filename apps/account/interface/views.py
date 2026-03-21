"""
Account Interface Views

用户认证、注册、登录、登出等视图。
"""

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse
from django.db import models, transaction
from django.utils import timezone
from decimal import Decimal
import json
import logging

from apps.account.infrastructure.models import (
    AccountProfileModel,
    PortfolioModel,
    CapitalFlowModel,
    SystemSettingsModel,
    UserAccessTokenModel,
    TradingCostConfigModel,
)
from apps.account.infrastructure.repositories import (
    AccountRepository,
    PortfolioRepository,
    PositionRepository,
    AssetMetadataRepository,
)
from apps.account.application.use_cases import CreatePositionFromBacktestUseCase, CreatePositionFromBacktestInput
from apps.account.application.rbac import ROLE_CHOICES, is_system_admin
from apps.account.interface.serializers import TradingCostConfigCreateSerializer

logger = logging.getLogger(__name__)


def is_admin_user(user):
    """检查用户是否是管理员"""
    return is_system_admin(user)


def _build_token_payload(*, username: str, token_name: str, token_value: str):
    settings_obj = SystemSettingsModel.get_settings()
    if not settings_obj.allow_token_plaintext_view:
        return None
    return {
        "username": username,
        "token_name": token_name,
        "token": token_value,
        "generated_at": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _get_token_name_from_request(request, default_prefix: str = "token") -> str:
    raw_name = (request.POST.get("token_name") or "").strip()
    if raw_name:
        return raw_name
    return f"{default_prefix}-{timezone.now().strftime('%Y%m%d%H%M%S')}"


@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def register_view(request):
    """
    用户注册视图

    GET: 显示注册表单
    POST: 处理注册请求
    """
    # 获取系统配置
    system_settings = SystemSettingsModel.get_settings()

    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        password_confirm = request.POST.get("password_confirm")
        display_name = request.POST.get("display_name", username)

        # 用户协议和风险提示确认
        user_agreement = request.POST.get("user_agreement") == "on"
        risk_warning = request.POST.get("risk_warning") == "on"

        # 验证
        if not username or not password:
            messages.error(request, "用户名和密码不能为空")
            return render(request, "account/register.html", {
                "system_settings": system_settings,
            })

        if password != password_confirm:
            messages.error(request, "两次输入的密码不一致")
            return render(request, "account/register.html", {
                "system_settings": system_settings,
            })

        if User._default_manager.filter(username=username).exists():
            messages.error(request, "用户名已存在")
            return render(request, "account/register.html", {
                "system_settings": system_settings,
            })

        # 验证用户协议和风险提示
        if not user_agreement:
            messages.error(request, "请阅读并同意用户协议")
            return render(request, "account/register.html", {
                "system_settings": system_settings,
            })

        if not risk_warning:
            messages.error(request, "请确认已阅读风险提示")
            return render(request, "account/register.html", {
                "system_settings": system_settings,
            })

        # 创建用户
        try:
            user = User._default_manager.create_user(
                username=username,
                email=email,
                password=password
            )
            user.is_active = False  # 初始设为未激活，等待审批（或自动批准）

            # 确定审批状态
            from django.db.models import Q
            has_admin = User._default_manager.filter(Q(is_superuser=True) | Q(is_staff=True)).exists()

            if not system_settings.require_user_approval:
                # 审批已关闭，自动批准
                approval_status = "auto_approved"
                user.is_active = True
                rbac_role = "owner"
            elif not has_admin and system_settings.auto_approve_first_admin:
                # 系统无管理员，自动成为管理员并获得批准
                user.is_superuser = True
                user.is_staff = True
                user.is_active = True
                approval_status = "auto_approved"
                rbac_role = "admin"
            else:
                # 需要管理员审批
                approval_status = "pending"
                rbac_role = "owner"

            user.save()

            # 获取客户端IP
            client_ip = get_client_ip(request)

            # 创建账户配置
            AccountProfileModel._default_manager.create(
                user=user,
                display_name=display_name,
                initial_capital=Decimal("1000000.00"),
                risk_tolerance="moderate",
                mcp_enabled=system_settings.default_mcp_enabled,
                user_agreement_accepted=True,
                risk_warning_acknowledged=True,
                agreement_accepted_at=timezone.now(),
                agreement_ip_address=client_ip,
                approval_status=approval_status,
                rbac_role=rbac_role,
            )

            # 创建默认投资组合
            PortfolioModel._default_manager.create(
                user=user,
                name="默认组合",
                is_active=True
            )

            # 根据审批状态显示不同消息
            if approval_status == "pending":
                messages.info(
                    request,
                    f"注册成功！您的账户正在等待管理员审批，审批通过后即可登录。"
                )
                return redirect("/account/login/")
            else:
                # 自动登录
                login(request, user)

                admin_msg = " 您已成为系统管理员。" if user.is_superuser else ""
                messages.success(request, f"欢迎加入 AgomTradePro，{display_name}！{admin_msg}")
                return redirect("/dashboard/")

        except Exception as e:
            messages.error(request, f"注册失败：{str(e)}")
            return render(request, "account/register.html", {
                "system_settings": system_settings,
            })

    return render(request, "account/register.html", {
        "system_settings": system_settings,
    })


def get_client_ip(request):
    """获取客户端IP地址"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def login_view(request):
    """
    用户登录视图

    GET: 显示登录表单
    POST: 处理登录请求
    """
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            messages.success(request, f"欢迎回来，{user.username}！")

            # 重定向到之前访问的页面或首页
            next_page = request.GET.get("next", "/dashboard/")
            return redirect(next_page)
        else:
            messages.error(request, "用户名或密码错误")

    return render(request, "account/login.html")


@login_required
def logout_view(request):
    """用户登出视图"""
    logout(request)
    messages.success(request, "您已成功登出")
    return redirect("/account/login/")


@login_required
def profile_view(request):
    """
    用户资料视图

    显示和编辑用户账户配置。
    """
    from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

    profile = request.user.account_profile
    portfolios = request.user.portfolios.all()

    # ⭐ 重构：直接从 SimulatedAccountModel 获取用户的投资组合
    investment_accounts = SimulatedAccountModel._default_manager.filter(
        user=request.user
    )

    # 计算当前总资产（优先从投资组合获取）
    total_assets = 0.0

    # 优先使用投资组合的资产
    if investment_accounts.exists():
        for account in investment_accounts:
            total_assets += float(account.total_value)
    else:
        # 如果没有投资组合，使用Portfolio系统（向后兼容）
        from apps.account.infrastructure.repositories import PortfolioRepository
        portfolio_repo = PortfolioRepository()
        for portfolio in portfolios.filter(is_active=True):
            snapshot = portfolio_repo.get_portfolio_snapshot(portfolio.id)
            if snapshot:
                total_assets += float(snapshot.total_value)

    context = {
        "user": request.user,
        "profile": profile,
        "portfolios": portfolios,
        "investment_accounts": investment_accounts,
        "total_assets": total_assets,
    }
    return render(request, "account/profile.html", context)


@login_required
def settings_view(request):
    """
    账户设置视图

    编辑风险偏好等配置，管理资金流水。
    """
    profile = request.user.account_profile
    portfolio = request.user.portfolios.filter(is_active=True).first()
    system_settings = SystemSettingsModel.get_settings()

    if request.method == "POST":
        # 更新配置
        profile.display_name = request.POST.get("display_name", profile.user.username)
        profile.risk_tolerance = request.POST.get("risk_tolerance", profile.risk_tolerance)

        # 更新邮箱
        email = request.POST.get("email", "")
        if email:
            request.user.email = email
            request.user.save()

        # 如果提供了新密码
        new_password = request.POST.get("new_password")
        if new_password:
            request.user.set_password(new_password)
            request.user.save()
            messages.success(request, "密码已修改，请重新登录")
            return redirect("/account/login/")

        # 保存交易费率配置
        if portfolio and request.POST.get("save_trading_cost"):
            try:
                trading_cost_config = portfolio.trading_cost_config
            except TradingCostConfigModel.DoesNotExist:
                trading_cost_config = None
            serializer = TradingCostConfigCreateSerializer(
                instance=trading_cost_config,
                data={
                    "portfolio": portfolio.id,
                    "commission_rate": request.POST.get("commission_rate", 0.00025),
                    "min_commission": request.POST.get("min_commission", 5.0),
                    "stamp_duty_rate": request.POST.get("stamp_duty_rate", 0.001),
                    "transfer_fee_rate": request.POST.get("transfer_fee_rate", 0.00002),
                    "is_active": trading_cost_config.is_active if trading_cost_config else True,
                },
            )
            if serializer.is_valid():
                serializer.save()
                messages.success(request, "交易费率已保存")
            else:
                first_error = next(iter(serializer.errors.values()))
                if isinstance(first_error, (list, tuple)):
                    error_message = first_error[0]
                else:
                    error_message = first_error
                messages.error(request, f"费率保存失败：{error_message}")
            return redirect("/account/settings/")

        profile.save()
        messages.success(request, "设置已保存")
        return redirect("/account/settings/")

    # 计算资金流水汇总
    if portfolio:
        capital_flows = CapitalFlowModel._default_manager.filter(
            portfolio=portfolio
        ).order_by('-flow_date', '-created_at')

        total_deposit = capital_flows.filter(flow_type='deposit').aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0')

        total_withdraw = capital_flows.filter(flow_type='withdraw').aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0')

        net_capital = total_deposit - total_withdraw
    else:
        capital_flows = []
        total_deposit = Decimal('0')
        total_withdraw = Decimal('0')
        net_capital = Decimal('0')

    # 交易费率配置
    trading_cost_config = None
    if portfolio:
        try:
            trading_cost_config = portfolio.trading_cost_config
        except TradingCostConfigModel.DoesNotExist:
            pass

    context = {
        "user": request.user,
        "profile": profile,
        "portfolio": portfolio,
        "capital_flows": capital_flows,
        "total_deposit": total_deposit,
        "total_withdraw": total_withdraw,
        "net_capital": net_capital,
        "trading_cost_config": trading_cost_config,
        "system_settings": system_settings,
        "access_tokens": request.user.access_tokens.filter(is_active=True).order_by("-created_at"),
        "new_token_payload": request.session.pop("self_new_token_payload", None),
    }
    return render(request, "account/settings.html", context)


@login_required
@require_http_methods(["POST"])
def create_self_token_view(request):
    """用户创建自己的 MCP/SDK Token。"""
    profile = request.user.account_profile
    if not profile.mcp_enabled:
        messages.error(request, "管理员已关闭您的 MCP/SDK 权限，暂时不能创建 Token")
        return redirect("/account/settings/")

    try:
        token_name = _get_token_name_from_request(request, default_prefix="self")
        token, raw_key = UserAccessTokenModel.create_token(
            user=request.user,
            name=token_name,
            created_by=request.user,
        )
        payload = _build_token_payload(
            username=request.user.username,
            token_name=token.name,
            token_value=raw_key,
        )
        if payload:
            request.session["self_new_token_payload"] = payload
            messages.success(request, f"已创建 Token：{token.name}")
        else:
            messages.success(request, f"已创建 Token：{token.name}。当前系统禁止查看明文，请自行妥善管理。")
    except Exception as e:
        messages.error(request, f"创建 Token 失败：{str(e)}")

    return redirect("/account/settings/")


@login_required
@require_http_methods(["POST"])
def revoke_self_token_view(request, token_id):
    """用户撤销自己的 Token。"""
    try:
        token = UserAccessTokenModel._default_manager.get(
            id=token_id,
            user=request.user,
            is_active=True,
        )
        token.revoke()
        messages.success(request, f"已撤销 Token：{token.name}")
    except UserAccessTokenModel.DoesNotExist:
        messages.error(request, "Token 不存在或已失效")
    except Exception as e:
        messages.error(request, f"撤销 Token 失败：{str(e)}")
    return redirect("/account/settings/")


@login_required
@require_http_methods(["POST"])
def capital_flow_view(request):
    """
    资金流水视图

    处理入金/出金操作。
    """
    from datetime import datetime

    try:
        # 获取参数
        flow_type = request.POST.get("flow_type")
        amount = Decimal(request.POST.get("amount", "0"))
        flow_date_str = request.POST.get("flow_date")
        notes = request.POST.get("notes", "")

        # 验证
        if flow_type not in ['deposit', 'withdraw']:
            messages.error(request, "无效的流水类型")
            return redirect("/account/settings/")

        if amount <= 0:
            messages.error(request, "金额必须大于0")
            return redirect("/account/settings/")

        if not flow_date_str:
            messages.error(request, "请选择日期")
            return redirect("/account/settings/")

        # 解析日期
        try:
            flow_date = datetime.strptime(flow_date_str, "%Y-%m-%d").date()
        except ValueError:
            messages.error(request, "日期格式错误")
            return redirect("/account/settings/")

        # 获取或创建默认组合
        portfolio = request.user.portfolios.filter(is_active=True).first()
        if not portfolio:
            portfolio = PortfolioModel._default_manager.create(
                user=request.user,
                name="默认组合",
                is_active=True
            )

        # 创建资金流水记录
        CapitalFlowModel._default_manager.create(
            user=request.user,
            portfolio=portfolio,
            flow_type=flow_type,
            amount=amount,
            flow_date=flow_date,
            notes=notes
        )

        action_text = "入金" if flow_type == "deposit" else "出金"
        messages.success(request, f"{action_text}记录已添加：¥{amount:.2f}")

    except Exception as e:
        messages.error(request, f"操作失败：{str(e)}")

    return redirect("/account/settings/")


@login_required
@require_http_methods(["POST"])
def apply_backtest_results_view(request, backtest_id):
    """
    应用回测结果到实际持仓

    Args:
        backtest_id: 回测结果ID
    """
    from apps.backtest.infrastructure.models import BacktestResultModel
    import json

    try:
        # 获取参数
        data = json.loads(request.body) if request.body else {}
        scale_factor = float(data.get('scale_factor', 1.0))

        # 验证回测归属
        try:
            backtest = BacktestResultModel._default_manager.get(id=backtest_id)
        except BacktestResultModel.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': '回测不存在'
            }, status=404)

        if backtest.user_id != request.user.id:
            return JsonResponse({
                'success': False,
                'error': '无权限访问此回测'
            }, status=403)

        if backtest.status != 'completed':
            return JsonResponse({
                'success': False,
                'error': f'回测状态为 {backtest.status}，无法应用'
            }, status=400)

        # 创建用例并执行
        use_case = CreatePositionFromBacktestUseCase(
            position_repo=PositionRepository(),
            account_repo=AccountRepository(),
            asset_meta_repo=AssetMetadataRepository(),
        )

        input_dto = CreatePositionFromBacktestInput(
            user_id=request.user.id,
            backtest_id=backtest_id,
            scale_factor=scale_factor,
        )

        result = use_case.execute(input_dto)

        return JsonResponse({
            'success': True,
            'message': f'成功应用回测结果「{result.backtest_name}」',
            'data': {
                'total_positions': result.total_positions,
                'total_value': result.total_value,
                'backtest_name': result.backtest_name,
            }
        })

    except ValueError as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'应用失败：{str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def portfolio_volatility_api_view(request):
    """
    投资组合波动率API

    返回30/60/90天滚动波动率数据（用于图表展示）
    """
    from apps.account.application.volatility_use_cases import VolatilityAnalysisUseCase

    try:
        # 获取投资组合ID（默认活跃组合）
        portfolio = request.user.portfolios.filter(is_active=True).first()

        if not portfolio:
            return JsonResponse({
                'success': False,
                'error': '暂无投资组合'
            }, status=404)

        # 执行波动率分析
        use_case = VolatilityAnalysisUseCase()
        analysis = use_case.analyze_portfolio_volatility(
            portfolio_id=portfolio.id,
            user_id=request.user.id,
        )

        # 转换历史数据为图表格式
        history_data = []
        for metric in analysis.volatility_history:
            history_data.append({
                'date': metric.date.strftime('%Y-%m-%d') if metric.date else None,
                'daily_volatility': metric.daily_volatility,
                'rolling_volatility_30d': metric.rolling_volatility_30d,
                'annualized_volatility': metric.annualized_volatility,
            })

        return JsonResponse({
            'success': True,
            'data': {
                'portfolio_id': analysis.portfolio_id,
                'current': {
                    'volatility_30d': analysis.current_volatility_30d,
                    'volatility_60d': analysis.current_volatility_60d,
                    'volatility_90d': analysis.current_volatility_90d,
                    'target': analysis.target_volatility,
                },
                'adjustment': {
                    'should_reduce': analysis.adjustment_result.should_reduce,
                    'reduction_reason': analysis.adjustment_result.reduction_reason,
                    'suggested_multiplier': analysis.adjustment_result.suggested_position_multiplier,
                } if analysis.adjustment_result else None,
                'history': history_data,
            }
        })

    except ValueError as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'获取波动率数据失败：{str(e)}'
        }, status=500)


# ============================================================
# 用户管理视图（仅管理员）
# ============================================================

@login_required
@user_passes_test(is_admin_user)
@require_http_methods(["GET", "POST"])
def user_management_view(request):
    """
    用户管理视图（仅管理员可用）

    显示所有用户列表，支持审批操作。
    """
    system_settings = SystemSettingsModel.get_settings()

    # 获取过滤参数
    status_filter = request.GET.get("status", "")
    search_query = request.GET.get("q", "")

    # 构建查询
    profiles = AccountProfileModel._default_manager.select_related('user', 'approved_by').all()

    if status_filter:
        profiles = profiles.filter(approval_status=status_filter)

    if search_query:
        profiles = profiles.filter(
            models.Q(user__username__icontains=search_query) |
            models.Q(user__email__icontains=search_query) |
            models.Q(display_name__icontains=search_query)
        )

    # 排序
    profiles = profiles.order_by('-created_at')

    # 统计信息
    total_count = profiles.count()
    pending_count = profiles.filter(approval_status='pending').count()
    approved_count = profiles.filter(approval_status__in=['approved', 'auto_approved']).count()
    rejected_count = profiles.filter(approval_status='rejected').count()

    context = {
        "profiles": profiles,
        "role_choices": ROLE_CHOICES,
        "system_settings": system_settings,
        "status_filter": status_filter,
        "search_query": search_query,
        "total_count": total_count,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
    }
    return render(request, "account/user_management.html", context)


@login_required
@user_passes_test(is_admin_user)
@require_http_methods(["GET"])
def token_management_view(request):
    """
    MCP/SDK Token 管理页面（仅管理员可用）

    管理 DRF Token：查看、生成/重置、撤销。
    """
    search_query = request.GET.get("q", "").strip()
    only_without_token = request.GET.get("without_token") == "1"
    system_settings = SystemSettingsModel.get_settings()

    users = User._default_manager.select_related("account_profile").all().order_by("-date_joined")
    if search_query:
        users = users.filter(
            models.Q(username__icontains=search_query) |
            models.Q(email__icontains=search_query)
        )

    tokens = UserAccessTokenModel._default_manager.select_related("created_by").filter(
        is_active=True
    ).order_by("-created_at")
    token_map = {}
    for token in tokens:
        token_map.setdefault(token.user_id, []).append(token)

    rows = []
    for user in users:
        user_tokens = token_map.get(user.id, [])
        if only_without_token and user_tokens:
            continue

        rows.append({
            "user": user,
            "profile": getattr(user, "account_profile", None),
            "tokens": user_tokens,
            "has_token": bool(user_tokens),
            "token_count": len(user_tokens),
        })

    new_token_payload = request.session.pop("new_token_payload", None)

    context = {
        "rows": rows,
        "search_query": search_query,
        "only_without_token": only_without_token,
        "total_users": len(rows),
        "with_token_count": sum(1 for r in rows if r["has_token"]),
        "without_token_count": sum(1 for r in rows if not r["has_token"]),
        "total_token_count": sum(r["token_count"] for r in rows),
        "new_token_payload": new_token_payload,
        "system_settings": system_settings,
    }
    return render(request, "account/token_management.html", context)


@login_required
@user_passes_test(is_admin_user)
@require_http_methods(["POST"])
def rotate_user_token_view(request, user_id):
    """
    为指定用户创建新 Token（仅管理员可用）。
    """
    try:
        target_user = User._default_manager.select_related("account_profile").get(id=user_id)
        if not target_user.account_profile.mcp_enabled:
            messages.error(request, f"用户 {target_user.username} 的 MCP/SDK 权限已关闭，请先开启")
            return redirect("/account/admin/tokens/")

        token_name = _get_token_name_from_request(request, default_prefix="admin")
        token, raw_key = UserAccessTokenModel.create_token(
            user=target_user,
            name=token_name,
            created_by=request.user,
        )
        payload = _build_token_payload(
            username=target_user.username,
            token_name=token.name,
            token_value=raw_key,
        )
        if payload:
            request.session["new_token_payload"] = payload
            messages.success(request, f"已为用户 {target_user.username} 创建 Token：{token.name}")
        else:
            messages.success(request, f"已为用户 {target_user.username} 创建 Token：{token.name}。当前系统禁止查看明文。")
        logger.info(
            "admin_action=create_token actor=%s target=%s token_name=%s result=success",
            request.user.username,
            target_user.username,
            token.name,
        )
    except User.DoesNotExist:
        messages.error(request, "用户不存在")
    except Exception as e:
        messages.error(request, f"创建 Token 失败：{str(e)}")
        logger.exception(
            "admin_action=create_token actor=%s target_user_id=%s result=failed",
            request.user.username,
            user_id,
        )

    return redirect("/account/admin/tokens/")


@login_required
@user_passes_test(is_admin_user)
@require_http_methods(["POST"])
def revoke_user_token_view(request, user_id):
    """
    撤销指定用户全部 Token（兼容旧入口，仅管理员可用）。
    """
    try:
        target_user = User._default_manager.get(id=user_id)
        active_tokens = list(UserAccessTokenModel._default_manager.filter(user=target_user, is_active=True))
        for token in active_tokens:
            token.revoke()
        deleted_count = len(active_tokens)
        if deleted_count > 0:
            messages.success(request, f"已撤销用户 {target_user.username} 的全部 Token")
        else:
            messages.warning(request, f"用户 {target_user.username} 当前没有可撤销的 Token")
        logger.info(
            "admin_action=revoke_all_tokens actor=%s target=%s deleted_count=%s",
            request.user.username,
            target_user.username,
            deleted_count,
        )
    except User.DoesNotExist:
        messages.error(request, "用户不存在")
    except Exception as e:
        messages.error(request, f"撤销 Token 失败：{str(e)}")
        logger.exception(
            "admin_action=revoke_token actor=%s target_user_id=%s result=failed",
            request.user.username,
            user_id,
        )

    return redirect("/account/admin/tokens/")


@login_required
@user_passes_test(is_admin_user)
@require_http_methods(["POST"])
def revoke_access_token_view(request, token_id):
    """撤销单个 Token。"""
    try:
        token = UserAccessTokenModel._default_manager.select_related("user").get(id=token_id, is_active=True)
        token.revoke()
        messages.success(request, f"已撤销 {token.user.username} 的 Token：{token.name}")
    except UserAccessTokenModel.DoesNotExist:
        messages.error(request, "Token 不存在或已失效")
    except Exception as e:
        messages.error(request, f"撤销 Token 失败：{str(e)}")
        logger.exception(
            "admin_action=revoke_token actor=%s token_id=%s result=failed",
            request.user.username,
            token_id,
        )
    return redirect("/account/admin/tokens/")


@login_required
@user_passes_test(is_admin_user)
@require_http_methods(["POST"])
def toggle_user_mcp_view(request, user_id):
    """管理员切换用户 MCP 权限。"""
    try:
        settings_obj = SystemSettingsModel.get_settings()
        target_user = User._default_manager.select_related("account_profile").get(id=user_id)
        profile = target_user.account_profile
        profile.mcp_enabled = not profile.mcp_enabled
        profile.save(update_fields=["mcp_enabled", "updated_at"])

        if not profile.mcp_enabled:
            for token in UserAccessTokenModel._default_manager.filter(user=target_user, is_active=True):
                token.revoke()

        state = "开启" if profile.mcp_enabled else "关闭"
        messages.success(
            request,
            f"已{state}用户 {target_user.username} 的 MCP/SDK 权限（系统默认：{'开启' if settings_obj.default_mcp_enabled else '关闭'}）"
        )
    except User.DoesNotExist:
        messages.error(request, "用户不存在")
    except Exception as e:
        messages.error(request, f"MCP 权限切换失败：{str(e)}")
    return redirect("/account/admin/tokens/")


@login_required
@user_passes_test(is_admin_user)
@require_http_methods(["POST"])
def approve_user_view(request, user_id):
    """
    批准用户视图（仅管理员可用）
    """
    try:
        with transaction.atomic():
            target_user = User._default_manager.get(id=user_id)
            profile = target_user.account_profile

            if profile.approval_status == 'approved':
                messages.warning(request, f"用户 {target_user.username} 已经被批准过了")
            elif profile.approval_status == 'rejected':
                messages.error(request, f"用户 {target_user.username} 已被拒绝，请先取消拒绝状态")
            elif profile.approval_status != 'pending':
                messages.error(request, f"用户 {target_user.username} 当前状态不允许批准")
            else:
                # 激活用户
                target_user.is_active = True
                target_user.save(update_fields=["is_active"])

                # 更新审批状态
                profile.approval_status = 'approved'
                profile.approved_at = timezone.now()
                profile.approved_by = request.user
                profile.mcp_enabled = SystemSettingsModel.get_settings().default_mcp_enabled
                profile.rejection_reason = ""
                profile.save(update_fields=["approval_status", "approved_at", "approved_by", "mcp_enabled", "rejection_reason", "updated_at"])

                messages.success(request, f"已批准用户 {target_user.username}")
                logger.info(
                    "admin_action=approve_user actor=%s target=%s",
                    request.user.username,
                    target_user.username,
                )

    except User.DoesNotExist:
        messages.error(request, "用户不存在")
    except Exception as e:
        messages.error(request, f"批准失败：{str(e)}")
        logger.exception(
            "admin_action=approve_user actor=%s target_user_id=%s result=failed",
            request.user.username,
            user_id,
        )

    return redirect("/account/admin/users/")


@login_required
@user_passes_test(is_admin_user)
@require_http_methods(["POST"])
def reject_user_view(request, user_id):
    """
    拒绝用户视图（仅管理员可用）
    """
    try:
        with transaction.atomic():
            target_user = User._default_manager.get(id=user_id)
            profile = target_user.account_profile

            # 确保不拒绝自己
            if target_user.id == request.user.id:
                messages.error(request, "不能拒绝自己")
                return redirect("/account/admin/users/")

            if profile.approval_status != "pending":
                messages.error(request, f"用户 {target_user.username} 当前状态不允许拒绝")
                return redirect("/account/admin/users/")

            rejection_reason = request.POST.get("rejection_reason", "")

            # 更新审批状态并强制停用/撤销Token
            profile.approval_status = 'rejected'
            profile.rejection_reason = rejection_reason
            profile.approved_at = None
            profile.approved_by = None
            profile.save(update_fields=["approval_status", "rejection_reason", "approved_at", "approved_by", "updated_at"])

            target_user.is_active = False
            target_user.save(update_fields=["is_active"])
            for token in UserAccessTokenModel._default_manager.filter(user=target_user, is_active=True):
                token.revoke()

            messages.success(request, f"已拒绝用户 {target_user.username}")
            logger.info(
                "admin_action=reject_user actor=%s target=%s",
                request.user.username,
                target_user.username,
            )

    except User.DoesNotExist:
        messages.error(request, "用户不存在")
    except Exception as e:
        messages.error(request, f"拒绝失败：{str(e)}")
        logger.exception(
            "admin_action=reject_user actor=%s target_user_id=%s result=failed",
            request.user.username,
            user_id,
        )

    return redirect("/account/admin/users/")


@login_required
@user_passes_test(is_admin_user)
@require_http_methods(["POST"])
def set_user_role_view(request, user_id):
    """
    设置用户 RBAC 角色（仅管理员可用）
    """
    try:
        target_user = User._default_manager.get(id=user_id)
        profile = target_user.account_profile
        raw_role = (request.POST.get("rbac_role") or "").strip()
        valid_values = {value for value, _ in ROLE_CHOICES}
        if raw_role not in valid_values:
            messages.error(request, "无效的角色")
            return redirect("/account/admin/users/")

        profile.rbac_role = raw_role
        profile.save(update_fields=["rbac_role", "updated_at"])
        messages.success(request, f"已将用户 {target_user.username} 角色更新为 {raw_role}")
    except User.DoesNotExist:
        messages.error(request, "用户不存在")
    except Exception as e:
        messages.error(request, f"角色更新失败：{str(e)}")
        logger.exception(
            "admin_action=set_user_role actor=%s target_user_id=%s result=failed",
            request.user.username,
            user_id,
        )
    return redirect("/account/admin/users/")


@login_required
@user_passes_test(is_admin_user)
@require_http_methods(["POST"])
def reset_user_status_view(request, user_id):
    """
    重置用户状态视图（仅管理员可用）

    将用户状态重置为待审批，允许重新审批。
    """
    try:
        with transaction.atomic():
            target_user = User._default_manager.get(id=user_id)
            profile = target_user.account_profile

            # 防止管理员误锁自己
            if target_user.id == request.user.id:
                messages.error(request, "不能重置自己")
                return redirect("/account/admin/users/")

            # 重置审批状态
            profile.approval_status = 'pending'
            profile.approved_at = None
            profile.approved_by = None
            profile.rejection_reason = ""
            profile.save(update_fields=["approval_status", "approved_at", "approved_by", "rejection_reason", "updated_at"])

            # 停用用户
            target_user.is_active = False
            target_user.save(update_fields=["is_active"])

            for token in UserAccessTokenModel._default_manager.filter(user=target_user, is_active=True):
                token.revoke()

            messages.success(request, f"已重置用户 {target_user.username} 的状态")
            logger.info(
                "admin_action=reset_user_status actor=%s target=%s",
                request.user.username,
                target_user.username,
            )

    except User.DoesNotExist:
        messages.error(request, "用户不存在")
    except Exception as e:
        messages.error(request, f"重置失败：{str(e)}")
        logger.exception(
            "admin_action=reset_user_status actor=%s target_user_id=%s result=failed",
            request.user.username,
            user_id,
        )

    return redirect("/account/admin/users/")


@login_required
@user_passes_test(is_admin_user)
@require_http_methods(["GET", "POST"])
def system_settings_view(request):
    """
    系统配置视图（仅管理员可用）

    管理系统配置，如审批开关、协议内容等。
    """
    system_settings = SystemSettingsModel.get_settings()

    if request.method == "POST":
        try:
            benchmark_code_map = json.loads(request.POST.get("benchmark_code_map", "{}") or "{}")
            asset_proxy_code_map = json.loads(request.POST.get("asset_proxy_code_map", "{}") or "{}")
            macro_index_catalog = json.loads(request.POST.get("macro_index_catalog", "[]") or "[]")

            if not isinstance(benchmark_code_map, dict):
                raise ValueError("基准代码映射必须是 JSON 对象")
            if not isinstance(asset_proxy_code_map, dict):
                raise ValueError("资产代理代码映射必须是 JSON 对象")
            if not isinstance(macro_index_catalog, list):
                raise ValueError("宏观指数目录必须是 JSON 数组")

            system_settings.require_user_approval = request.POST.get("require_user_approval") == "on"
            system_settings.auto_approve_first_admin = request.POST.get("auto_approve_first_admin") == "on"
            system_settings.default_mcp_enabled = request.POST.get("default_mcp_enabled") == "on"
            system_settings.allow_token_plaintext_view = request.POST.get("allow_token_plaintext_view") == "on"
            system_settings.user_agreement_content = request.POST.get("user_agreement_content", "")
            system_settings.risk_warning_content = request.POST.get("risk_warning_content", "")
            system_settings.notes = request.POST.get("notes", "")
            system_settings.benchmark_code_map = benchmark_code_map
            system_settings.asset_proxy_code_map = asset_proxy_code_map
            system_settings.macro_index_catalog = macro_index_catalog
            system_settings.save()

            messages.success(request, "系统配置已更新")
            return redirect("/account/admin/settings/")
        except (json.JSONDecodeError, ValueError) as exc:
            messages.error(request, f"系统配置未保存：{exc}")

    context = {
        "system_settings": system_settings,
        "benchmark_code_map_json": json.dumps(system_settings.benchmark_code_map or {}, ensure_ascii=False, indent=2),
        "asset_proxy_code_map_json": json.dumps(system_settings.asset_proxy_code_map or {}, ensure_ascii=False, indent=2),
        "macro_index_catalog_json": json.dumps(system_settings.macro_index_catalog or [], ensure_ascii=False, indent=2),
    }
    return render(request, "account/system_settings.html", context)


# ============================================================
# 账户协作视图
# ============================================================

@login_required
@require_http_methods(["GET"])
def collaboration_view(request):
    """
    账户协作管理视图

    显示和授权观察员。
    """
    from apps.account.infrastructure.models import PortfolioObserverGrantModel

    # 获取当前用户的授权统计
    grant_count = PortfolioObserverGrantModel._default_manager.filter(
        owner_user_id=request.user,
        status='active'
    ).count()

    context = {
        "user": request.user,
        "grant_count": grant_count,
        "max_grants": 10,
    }
    return render(request, "account/collaboration.html", context)


@login_required
@require_http_methods(["GET"])
def observer_portal_view(request):
    """
    观察员门户视图

    显示当前用户有权限观察的账户列表。
    """
    from apps.account.infrastructure.models import PortfolioObserverGrantModel

    # 获取当前用户作为观察员的授权数量
    observable_count = PortfolioObserverGrantModel._default_manager.filter(
        observer_user_id=request.user,
        status='active'
    ).count()

    context = {
        "user": request.user,
        "observable_count": observable_count,
    }
    return render(request, "account/observer_portal.html", context)


# ============================================================
# 注释：创建实仓和模拟仓视图已移除
# ============================================================
#
# ⭐ 重构说明（2026-01-04）：
# create_simulated_account_view 已删除
#
# 新架构下：
# - 用户可以创建多个投资组合（实仓/模拟仓）
# - 创建功能移至 simulated_trading 模块的 my_accounts_page
# - 访问路径：/simulated-trading/my-accounts/
#
