"""
Account Interface Views

用户认证、注册、登录、登出等视图。
"""

import json
import logging
from decimal import Decimal
from urllib.parse import urlparse

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from apps.account.application import interface_services
from apps.account.application.rbac import is_system_admin

logger = logging.getLogger(__name__)


def is_admin_user(user):
    """检查用户是否是管理员"""
    return is_system_admin(user)


def _build_token_payload(*, username: str, token_name: str, token_value: str):
    return interface_services.build_token_payload(
        username=username,
        token_name=token_name,
        token_value=token_value,
        access_level=interface_services.TOKEN_ACCESS_LEVEL_READ_WRITE,
    )


def _get_token_name_from_request(request, default_prefix: str = "token") -> str:
    raw_name = (request.POST.get("token_name") or "").strip()
    if raw_name:
        return raw_name
    return f"{default_prefix}-{timezone.now().strftime('%Y%m%d%H%M%S')}"


def _get_token_access_level_from_request(request) -> str:
    raw_value = request.POST.get("access_level")
    return interface_services.normalize_token_access_level(raw_value)


def _add_flash_message(request, level: str, message: str) -> None:
    """Emit a Django flash message from a service outcome."""

    getattr(messages, level)(request, message)


def _get_safe_next_path(request, *, default_path: str) -> str:
    """Return a local redirect path from form data when valid."""

    candidate = (request.POST.get("next") or "").strip()
    if not candidate:
        return default_path

    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return default_path
    if not candidate.startswith("/"):
        return default_path
    return candidate


@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def register_view(request):
    """
    用户注册视图

    GET: 显示注册表单
    POST: 处理注册请求
    """
    system_settings = interface_services.get_system_settings()

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
            return render(
                request,
                "account/register.html",
                {
                    "system_settings": system_settings,
                },
            )

        if password != password_confirm:
            messages.error(request, "两次输入的密码不一致")
            return render(
                request,
                "account/register.html",
                {
                    "system_settings": system_settings,
                },
            )

        if interface_services.username_exists(username):
            messages.error(request, "用户名已存在")
            return render(
                request,
                "account/register.html",
                {
                    "system_settings": system_settings,
                },
            )

        # 验证用户协议和风险提示
        if not user_agreement:
            messages.error(request, "请阅读并同意用户协议")
            return render(
                request,
                "account/register.html",
                {
                    "system_settings": system_settings,
                },
            )

        if not risk_warning:
            messages.error(request, "请确认已阅读风险提示")
            return render(
                request,
                "account/register.html",
                {
                    "system_settings": system_settings,
                },
            )

        # 创建用户
        try:
            registration = interface_services.register_user(
                username=username,
                email=email,
                password=password,
                display_name=display_name,
                client_ip=get_client_ip(request),
            )
            user = registration.user
            approval_status = registration.approval_status

            # 根据审批状态显示不同消息
            if approval_status == "pending":
                messages.info(request, "注册成功！您的账户正在等待管理员审批，审批通过后即可登录。")
                return redirect("/account/login/")
            else:
                # 自动登录
                login(request, user)

                admin_msg = " 您已成为系统管理员。" if user.is_superuser else ""
                messages.success(
                    request,
                    f"欢迎加入 AgomTradePro，{registration.display_name}！{admin_msg}",
                )
                return redirect("/dashboard/")

        except IntegrityError:
            messages.error(request, "注册失败：用户名或账户资料已存在")
            return render(
                request,
                "account/register.html",
                {
                    "system_settings": system_settings,
                },
            )
        except Exception:
            logger.exception("User registration failed for username=%s", username)
            messages.error(request, "注册失败：系统忙，请稍后重试")
            return render(
                request,
                "account/register.html",
                {
                    "system_settings": system_settings,
                },
            )

    return render(
        request,
        "account/register.html",
        {
            "system_settings": system_settings,
        },
    )


def get_client_ip(request):
    """获取客户端IP地址"""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
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

            next_page = request.GET.get("next", "/dashboard/")
            return redirect(next_page)
        else:
            messages.error(request, "用户名或密码错误")

    return render(
        request,
        "account/login.html",
        interface_services.build_login_context(),
    )


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
    context = interface_services.build_profile_context(request.user.id)
    return render(request, "account/profile.html", context)


@login_required
def settings_view(request):
    """
    账户设置视图

    编辑风险偏好等配置，管理资金流水。
    """
    if request.method == "POST":
        context = interface_services.build_settings_context(request.user.id)
        portfolio = context["portfolio"]
        if portfolio and request.POST.get("save_trading_cost"):
            try:
                outcome = interface_services.save_trading_cost_config(
                    request.user.id,
                    commission_rate=request.POST.get("commission_rate", "0.00025"),
                    min_commission=request.POST.get("min_commission", "5.0"),
                    stamp_duty_rate=request.POST.get("stamp_duty_rate", "0.001"),
                    transfer_fee_rate=request.POST.get("transfer_fee_rate", "0.00002"),
                )
            except Exception as exc:
                outcome = interface_services.FlashOutcome(
                    level="error",
                    message=f"费率保存失败：{exc}",
                    redirect_to="/account/settings/",
                )
        else:
            outcome = interface_services.update_account_settings(
                request.user.id,
                display_name=request.POST.get("display_name", request.user.username),
                risk_tolerance=request.POST.get(
                    "risk_tolerance",
                    context["profile"].risk_tolerance,
                ),
                email=request.POST.get("email", ""),
                new_password=request.POST.get("new_password", ""),
            )
        _add_flash_message(request, outcome.level, outcome.message)
        return redirect(outcome.redirect_to or "/account/settings/")

    context = interface_services.build_settings_context(request.user.id)
    context["new_token_payload"] = request.session.pop("self_new_token_payload", None)
    context["token_access_level_choices"] = interface_services.get_token_access_level_choices()
    context["default_token_access_level"] = interface_services.TOKEN_ACCESS_LEVEL_READ_ONLY
    return render(request, "account/settings.html", context)


@login_required
def mcp_guide_view(request):
    """MCP/SDK integration guide for the current user."""

    base_url = request.build_absolute_uri("/").rstrip("/")
    context = interface_services.build_mcp_guide_context(request.user.id, base_url=base_url)
    context["new_token_payload"] = request.session.pop("self_new_token_payload", None)
    context["token_access_level_choices"] = interface_services.get_token_access_level_choices()
    context["default_token_access_level"] = interface_services.TOKEN_ACCESS_LEVEL_READ_ONLY
    return render(request, "account/mcp_guide.html", context)


@login_required
@require_http_methods(["POST"])
def create_self_token_view(request):
    """用户创建自己的 MCP/SDK Token。"""
    redirect_path = _get_safe_next_path(request, default_path="/account/settings/")
    try:
        token_name = _get_token_name_from_request(request, default_prefix="self")
        outcome = interface_services.create_self_token(
            request.user.id,
            token_name=token_name,
            access_level=_get_token_access_level_from_request(request),
        )
        if outcome.payload:
            request.session["self_new_token_payload"] = outcome.payload
        _add_flash_message(request, outcome.level, outcome.message)
    except Exception as e:
        messages.error(request, f"创建 Token 失败：{str(e)}")

    return redirect(redirect_path)


@login_required
@require_http_methods(["POST"])
def revoke_self_token_view(request, token_id):
    """用户撤销自己的 Token。"""
    redirect_path = _get_safe_next_path(request, default_path="/account/settings/")
    try:
        outcome = interface_services.revoke_self_token(request.user.id, token_id)
        _add_flash_message(request, outcome.level, outcome.message)
    except LookupError as exc:
        messages.error(request, str(exc))
    except Exception as e:
        messages.error(request, f"撤销 Token 失败：{str(e)}")
    return redirect(redirect_path)


@login_required
@require_http_methods(["POST"])
def capital_flow_view(request):
    """
    资金流水视图

    处理入金/出金操作。
    """
    from datetime import datetime

    try:
        flow_type = request.POST.get("flow_type")
        amount = Decimal(request.POST.get("amount", "0"))
        flow_date_str = request.POST.get("flow_date")
        notes = request.POST.get("notes", "")

        if flow_type not in ["deposit", "withdraw"]:
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

        outcome = interface_services.create_capital_flow(
            request.user.id,
            flow_type=flow_type,
            amount=amount,
            flow_date=flow_date,
            notes=notes,
        )
        _add_flash_message(request, outcome.level, outcome.message)
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
    try:
        data = json.loads(request.body) if request.body else {}
        scale_factor = float(data.get("scale_factor", 1.0))
        result = interface_services.apply_backtest_results(
            request.user.id,
            backtest_id=backtest_id,
            scale_factor=scale_factor,
        )

        return JsonResponse(
            {
                "success": True,
                "message": f"成功应用回测结果「{result['backtest_name']}」",
                "data": result,
            }
        )

    except ValueError as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"success": False, "error": f"应用失败：{str(e)}"}, status=500)


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
        portfolio = interface_services.get_active_portfolio_for_user(request.user.id)

        if not portfolio:
            return JsonResponse({"success": False, "error": "暂无投资组合"}, status=404)

        # 执行波动率分析
        use_case = VolatilityAnalysisUseCase()
        analysis = use_case.analyze_portfolio_volatility(
            portfolio_id=portfolio.id,
            user_id=request.user.id,
        )

        # 转换历史数据为图表格式
        history_data = []
        for metric in analysis.volatility_history:
            history_data.append(
                {
                    "date": metric.date.strftime("%Y-%m-%d") if metric.date else None,
                    "daily_volatility": metric.daily_volatility,
                    "rolling_volatility_30d": metric.rolling_volatility_30d,
                    "annualized_volatility": metric.annualized_volatility,
                }
            )

        return JsonResponse(
            {
                "success": True,
                "data": {
                    "portfolio_id": analysis.portfolio_id,
                    "current": {
                        "volatility_30d": analysis.current_volatility_30d,
                        "volatility_60d": analysis.current_volatility_60d,
                        "volatility_90d": analysis.current_volatility_90d,
                        "target": analysis.target_volatility,
                    },
                    "adjustment": (
                        {
                            "should_reduce": analysis.adjustment_result.should_reduce,
                            "reduction_reason": analysis.adjustment_result.reduction_reason,
                            "suggested_multiplier": analysis.adjustment_result.suggested_position_multiplier,
                        }
                        if analysis.adjustment_result
                        else None
                    ),
                    "history": history_data,
                },
            }
        )

    except ValueError as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse(
            {"success": False, "error": f"获取波动率数据失败：{str(e)}"}, status=500
        )


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
    status_filter = request.GET.get("status", "")
    search_query = request.GET.get("q", "")
    context = interface_services.build_user_management_context(status_filter, search_query)
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
    context = interface_services.build_token_management_context(search_query, only_without_token)
    context["new_token_payload"] = request.session.pop("new_token_payload", None)
    context["token_access_level_choices"] = interface_services.get_token_access_level_choices()
    context["default_token_access_level"] = interface_services.TOKEN_ACCESS_LEVEL_READ_ONLY
    return render(request, "account/token_management.html", context)


@login_required
@user_passes_test(is_admin_user)
@require_http_methods(["POST"])
def rotate_user_token_view(request, user_id):
    """
    为指定用户创建新 Token（仅管理员可用）。
    """
    try:
        token_name = _get_token_name_from_request(request, default_prefix="admin")
        outcome = interface_services.rotate_user_token(
            actor_user_id=request.user.id,
            target_user_id=user_id,
            token_name=token_name,
            access_level=_get_token_access_level_from_request(request),
        )
        if outcome.payload:
            request.session["new_token_payload"] = outcome.payload
        _add_flash_message(request, outcome.level, outcome.message)
        logger.info(
            "admin_action=create_token actor=%s target=%s token_name=%s result=success",
            request.user.username,
            outcome.username,
            outcome.token_name,
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
        outcome = interface_services.revoke_user_tokens(user_id)
        _add_flash_message(request, outcome["level"], outcome["message"])
        logger.info(
            "admin_action=revoke_all_tokens actor=%s target=%s deleted_count=%s",
            request.user.username,
            outcome["username"],
            outcome["deleted_count"],
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
        outcome = interface_services.revoke_access_token(token_id)
        _add_flash_message(request, outcome.level, outcome.message)
    except LookupError as exc:
        messages.error(request, str(exc))
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
        outcome = interface_services.toggle_user_mcp(user_id)
        _add_flash_message(request, outcome.level, outcome.message)
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
        outcome = interface_services.approve_user(
            actor_user_id=request.user.id,
            target_user_id=user_id,
        )
        _add_flash_message(request, outcome.level, outcome.message)
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
        outcome = interface_services.reject_user(
            actor_user_id=request.user.id,
            target_user_id=user_id,
            rejection_reason=request.POST.get("rejection_reason", ""),
        )
        _add_flash_message(request, outcome.level, outcome.message)
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
        raw_role = (request.POST.get("rbac_role") or "").strip()
        outcome = interface_services.set_user_role(
            target_user_id=user_id,
            raw_role=raw_role,
        )
        _add_flash_message(request, outcome.level, outcome.message)
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
        outcome = interface_services.reset_user_status(
            actor_user_id=request.user.id,
            target_user_id=user_id,
        )
        _add_flash_message(request, outcome.level, outcome.message)
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
    if request.method == "POST":
        try:
            outcome = interface_services.update_system_settings(request.POST)
            _add_flash_message(request, outcome.level, outcome.message)
            return redirect(outcome.redirect_to or "/account/admin/settings/")
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            messages.error(request, f"系统配置未保存：{exc}")

    context = interface_services.build_system_settings_context()
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
    context = {
        "user": request.user,
        **interface_services.build_collaboration_context(request.user.id),
    }
    return render(request, "account/collaboration.html", context)


@login_required
@require_http_methods(["GET"])
def observer_portal_view(request):
    """
    观察员门户视图

    显示当前用户有权限观察的账户列表。
    """
    context = {
        "user": request.user,
        **interface_services.build_observer_portal_context(request.user.id),
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
