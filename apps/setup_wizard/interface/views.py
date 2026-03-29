"""
Interface Views for Setup Wizard.

处理 HTTP 请求，协调 Application 层用例。
"""

import logging

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import View

from apps.setup_wizard.application.use_cases import (
    CheckSetupStatusUseCase,
    CompleteSetupUseCase,
    EnsureSecurityKeysUseCase,
    GetNextStepUseCase,
    SetupAdminUseCase,
    SetupAIProviderUseCase,
    SetupDataSourceUseCase,
    VerifyAdminAuthUseCase,
)
from apps.setup_wizard.domain.entities import (
    AdminConfig,
    AIProviderConfigDTO,
    DataSourceConfigDTO,
    WizardStep,
)

logger = logging.getLogger(__name__)


class SetupWizardView(View):
    """安装向导主视图"""

    template_name = "setup_wizard/wizard.html"
    auth_template_name = "setup_wizard/auth.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        """处理 GET 请求"""
        use_case = CheckSetupStatusUseCase()
        result = use_case.execute()

        if result.is_first_time:
            session_data = request.session.get("setup_wizard", {})
            current_step = session_data.get("current_step", "welcome")

            if request.session.get("setup_wizard_authenticated"):
                return self._render_wizard(request, current_step, result.state)

            return self._render_wizard(request, current_step, result.state)

        if result.requires_auth:
            if not request.session.get("setup_wizard_authenticated"):
                return render(request, self.auth_template_name)

            session_data = request.session.get("setup_wizard", {})
            current_step = session_data.get("current_step", "welcome")
            return self._render_wizard(request, current_step, result.state)

        return redirect("/")

    def _render_wizard(
        self,
        request: HttpRequest,
        current_step: str,
        state,
    ) -> HttpResponse:
        """渲染向导页面"""
        try:
            step = WizardStep(current_step)
        except ValueError:
            step = WizardStep.WELCOME

        next_step_use_case = GetNextStepUseCase()
        next_step = next_step_use_case.execute(step)

        context = {
            "current_step": step.value,
            "next_step": next_step.value if next_step else None,
            "state": state,
            "progress_percentage": self._calculate_progress(step),
            "step_number": self._get_step_number(step),
            "total_steps": 5,
        }

        return render(request, self.template_name, context)

    def _calculate_progress(self, step: WizardStep) -> int:
        """计算进度百分比"""
        step_progress = {
            WizardStep.WELCOME: 0,
            WizardStep.ADMIN_PASSWORD: 20,
            WizardStep.AI_PROVIDER: 40,
            WizardStep.DATA_SOURCE: 60,
            WizardStep.COMPLETE: 100,
        }
        return step_progress.get(step, 0)

    def _get_step_number(self, step: WizardStep) -> int:
        """获取步骤编号"""
        step_numbers = {
            WizardStep.WELCOME: 1,
            WizardStep.ADMIN_PASSWORD: 2,
            WizardStep.AI_PROVIDER: 3,
            WizardStep.DATA_SOURCE: 4,
            WizardStep.COMPLETE: 5,
        }
        return step_numbers.get(step, 1)


class SetupAuthView(View):
    """安装向导认证视图"""

    template_name = "setup_wizard/auth.html"

    def post(self, request: HttpRequest) -> HttpResponse:
        """处理认证请求"""
        password = request.POST.get("password", "")

        use_case = VerifyAdminAuthUseCase()
        if use_case.execute(password):
            request.session["setup_wizard_authenticated"] = True
            request.session["setup_wizard"] = {"current_step": "welcome"}
            return redirect("/setup/")
        else:
            messages.error(request, "密码错误，请重试")
            return render(request, self.template_name, {"error": "密码错误"})


class SetupStepView(View):
    """处理各步骤的 POST 请求"""

    def post(self, request: HttpRequest, step: str) -> HttpResponse:
        """处理步骤提交"""
        try:
            current_step = WizardStep(step)
        except ValueError:
            return JsonResponse({"error": "无效的步骤"}, status=400)

        handler = getattr(self, f"_handle_{current_step.value}", None)
        if handler:
            return handler(request)

        return JsonResponse({"error": "未知的步骤"}, status=400)

    def _handle_welcome(self, request: HttpRequest) -> HttpResponse:
        """处理欢迎页"""
        setup_status = CheckSetupStatusUseCase().execute()
        allow_key_generation = setup_status.is_first_time

        # Auto-generate security keys (SECRET_KEY / AGOMTRADEPRO_ENCRYPTION_KEY)
        # only during first-time setup to avoid runtime key rotation.
        use_case = EnsureSecurityKeysUseCase()
        result = use_case.execute(
            generate_secret_key=allow_key_generation,
            generate_encryption_key=allow_key_generation,
        )

        generated = []
        if result.get("secret_key_generated"):
            generated.append("Django SECRET_KEY")
        if result.get("encryption_key_generated"):
            generated.append("数据加密密钥")
        if generated:
            messages.info(
                request,
                f"已自动生成 {'、'.join(generated)} 并写入 .env 文件，请妥善保管。",
            )
        elif not allow_key_generation:
            warnings = []
            if not result.get("secret_key_configured"):
                warnings.append(
                    "检测到当前 SECRET_KEY 仍为占位值。为避免运行中轮换密钥，已安装系统不会在向导中自动改写，请通过部署环境离线更新。"
                )
            if not result.get("encryption_key_configured"):
                warnings.append(
                    "检测到当前数据加密密钥缺失。为避免影响现有加密数据，已安装系统不会在向导中自动补写，请通过部署环境离线配置。"
                )
            for warning_message in warnings:
                messages.warning(request, warning_message)

        request.session.setdefault("setup_wizard", {})["current_step"] = "admin_password"
        request.session.modified = True
        return redirect("/setup/")

    def _handle_admin_password(self, request: HttpRequest) -> HttpResponse:
        """处理管理员密码设置"""
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        confirm_password = request.POST.get("confirm_password", "")
        email = request.POST.get("email", "").strip()

        if password != confirm_password:
            messages.error(request, "两次输入的密码不一致")
            return redirect("/setup/")

        config = AdminConfig(
            username=username,
            password=password,
            email=email or None,
        )

        use_case = SetupAdminUseCase()
        result = use_case.execute(config)

        if result.success:
            messages.success(request, result.message)
            request.session.setdefault("setup_wizard", {})["current_step"] = "ai_provider"
            request.session.modified = True
        else:
            messages.error(request, result.message)

        return redirect("/setup/")

    def _handle_ai_provider(self, request: HttpRequest) -> HttpResponse:
        """处理 AI Provider 设置"""
        skip = request.POST.get("skip") == "true"

        if skip:
            use_case = SetupAIProviderUseCase()
            use_case.execute(None)
            request.session.setdefault("setup_wizard", {})["current_step"] = "data_source"
            request.session.modified = True
            return redirect("/setup/")

        name = request.POST.get("name", "").strip()
        provider_type = request.POST.get("provider_type", "openai")
        base_url = request.POST.get("base_url", "").strip()
        api_key = request.POST.get("api_key", "").strip()
        default_model = request.POST.get("default_model", "gpt-3.5-turbo").strip()

        config = AIProviderConfigDTO(
            name=name or provider_type,
            provider_type=provider_type,
            base_url=base_url,
            api_key=api_key,
            default_model=default_model,
            is_active=True,
            priority=10,
        )

        use_case = SetupAIProviderUseCase()
        result = use_case.execute(config)

        if result.success:
            messages.success(request, result.message)
            request.session.setdefault("setup_wizard", {})["current_step"] = "data_source"
            request.session.modified = True
        else:
            messages.error(request, result.message)

        return redirect("/setup/")

    def _handle_data_source(self, request: HttpRequest) -> HttpResponse:
        """处理数据源设置"""
        skip = request.POST.get("skip") == "true"

        if skip:
            use_case = SetupDataSourceUseCase()
            use_case.execute(None)
            request.session.setdefault("setup_wizard", {})["current_step"] = "complete"
            request.session.modified = True
            return redirect("/setup/")

        tushare_token = request.POST.get("tushare_token", "").strip()
        tushare_http_url = request.POST.get("tushare_http_url", "").strip()
        fred_api_key = request.POST.get("fred_api_key", "").strip()
        akshare_enabled = request.POST.get("akshare_enabled") == "on"

        config = DataSourceConfigDTO(
            tushare_token=tushare_token or None,
            tushare_http_url=tushare_http_url or None,
            fred_api_key=fred_api_key or None,
            akshare_enabled=akshare_enabled,
        )

        use_case = SetupDataSourceUseCase()
        result = use_case.execute(config)

        if result.success:
            messages.success(request, result.message)

            complete_use_case = CompleteSetupUseCase()
            complete_use_case.execute()

            request.session.setdefault("setup_wizard", {})["current_step"] = "complete"
            request.session.modified = True
        else:
            messages.error(request, result.message)

        return redirect("/setup/")


@require_POST
def setup_logout(request: HttpRequest) -> HttpResponse:
    """退出安装向导"""
    if "setup_wizard_authenticated" in request.session:
        del request.session["setup_wizard_authenticated"]
    if "setup_wizard" in request.session:
        del request.session["setup_wizard"]
    return redirect("/")


@require_GET
def check_password_strength(request: HttpRequest) -> JsonResponse:
    """检查密码强度 API"""
    from apps.setup_wizard.domain.services import PasswordStrengthChecker

    password = request.GET.get("password", "")
    score, level, suggestions = PasswordStrengthChecker.check_strength(password)

    return JsonResponse(
        {
            "score": score,
            "level": level,
            "suggestions": suggestions,
        }
    )
