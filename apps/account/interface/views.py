"""
Account Interface Views

用户认证、注册、登录、登出等视图。
"""

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.db import models
from rest_framework.authtoken.models import Token
from decimal import Decimal

from apps.account.infrastructure.models import AccountProfileModel, PortfolioModel, CapitalFlowModel
from apps.account.infrastructure.repositories import (
    AccountRepository,
    PortfolioRepository,
    PositionRepository,
    AssetMetadataRepository,
)
from apps.account.application.use_cases import CreatePositionFromBacktestUseCase, CreatePositionFromBacktestInput


@require_http_methods(["GET", "POST"])
def register_view(request):
    """
    用户注册视图

    GET: 显示注册表单
    POST: 处理注册请求
    """
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        password_confirm = request.POST.get("password_confirm")
        display_name = request.POST.get("display_name", username)

        # 验证
        if not username or not password:
            messages.error(request, "用户名和密码不能为空")
            return render(request, "account/register.html")

        if password != password_confirm:
            messages.error(request, "两次输入的密码不一致")
            return render(request, "account/register.html")

        if User.objects.filter(username=username).exists():
            messages.error(request, "用户名已存在")
            return render(request, "account/register.html")

        # 创建用户
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )

            # 创建账户配置
            AccountProfileModel.objects.create(
                user=user,
                display_name=display_name,
                initial_capital=Decimal("1000000.00"),
                risk_tolerance="moderate"
            )

            # 创建默认投资组合
            PortfolioModel.objects.create(
                user=user,
                name="默认组合",
                is_active=True
            )

            # 创建API Token
            Token.objects.create(user=user)

            # 自动登录
            login(request, user)

            messages.success(request, f"欢迎加入 AgomSAAF，{display_name}！")
            return redirect("/dashboard/")

        except Exception as e:
            messages.error(request, f"注册失败：{str(e)}")
            return render(request, "account/register.html")

    return render(request, "account/register.html")


@require_http_methods(["GET", "POST"])
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
    profile = request.user.account_profile
    portfolios = request.user.portfolios.all()

    context = {
        "user": request.user,
        "profile": profile,
        "portfolios": portfolios,
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

        profile.save()
        messages.success(request, "设置已保存")
        return redirect("/account/settings/")

    # 计算资金流水汇总
    if portfolio:
        capital_flows = CapitalFlowModel.objects.filter(
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

    context = {
        "user": request.user,
        "profile": profile,
        "capital_flows": capital_flows,
        "total_deposit": total_deposit,
        "total_withdraw": total_withdraw,
        "net_capital": net_capital,
    }
    return render(request, "account/settings.html", context)


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
            portfolio = PortfolioModel.objects.create(
                user=request.user,
                name="默认组合",
                is_active=True
            )

        # 创建资金流水记录
        CapitalFlowModel.objects.create(
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
            backtest = BacktestResultModel.objects.get(id=backtest_id)
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
