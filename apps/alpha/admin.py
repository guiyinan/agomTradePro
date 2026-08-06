from __future__ import annotations

import hashlib
import importlib
import json
import pickle
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypedDict, cast

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.urls.resolvers import URLPattern
from django.utils import timezone

from apps.alpha.application.tasks import _execute_qlib_prediction
from apps.alpha.models import (
    AlphaAlertModel,
    AlphaScoreCacheModel,
    QlibModelRegistryModel,
)
from apps.config_center.application.use_cases import (
    ConflictError,
    QlibAccessDeniedError,
    TriggerQlibTrainingUseCase,
    ValidationFailureError,
)
from core.integration import runtime_settings
from shared.infrastructure.django_admin import TypedModelAdmin

_SAFE_MODEL_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
_ARTIFACT_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class ModelValidationCheck(TypedDict):
    """One stable model-validation check for the Admin template."""

    label: str
    ok: bool
    detail: str


class ModelValidationResult(TypedDict):
    """Typed result returned by the Qlib model validation workflow."""

    passed: bool
    checks: list[ModelValidationCheck]
    sample_scores: list[dict[str, object]]
    activation_message: str


def _validate_model_name(value: object) -> str:
    """Return a path-safe model identifier or raise form validation error."""

    if not isinstance(value, str) or _SAFE_MODEL_NAME_PATTERN.fullmatch(value) is None:
        raise ValidationError("模型名称仅允许字母、数字、点、下划线和连字符。")
    if value in {".", ".."} or value.endswith("."):
        raise ValidationError("模型名称不能是相对目录标记或以点结尾。")
    if value.split(".", maxsplit=1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        raise ValidationError("模型名称不能使用系统保留名称。")
    return value


def _parse_json_object(value: object, *, label: str) -> dict[str, object]:
    """Parse a form JSON object and narrow it at the dynamic JSON boundary."""

    if not isinstance(value, str):
        raise ValidationError(f"{label}必须是 JSON object。")
    raw = value.strip()
    if not raw:
        return {}
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{label} JSON 解析失败。") from exc
    if not isinstance(parsed, dict):
        raise ValidationError(f"{label}必须是 JSON object。")
    return cast(dict[str, object], parsed)


def _qlib_settings_mapping() -> Mapping[str, object]:
    """Return Qlib settings through a typed dynamic-settings boundary."""

    raw_settings: object = getattr(settings, "QLIB_SETTINGS", {})
    if not isinstance(raw_settings, Mapping):
        return {}
    return cast(Mapping[str, object], raw_settings)


class QlibModelImportForm(forms.Form):
    model_file = forms.FileField(
        label="Qlib 模型文件",
        help_text="上传训练好的 model.pkl 文件。",
    )
    model_name = forms.CharField(max_length=100, label="模型名称")
    model_type = forms.ChoiceField(
        choices=QlibModelRegistryModel.MODEL_TYPE_CHOICES,
        label="模型类型",
    )
    universe = forms.CharField(max_length=20, initial="csi300", label="股票池")
    feature_set_id = forms.CharField(max_length=50, initial="v1", label="特征集标识")
    label_id = forms.CharField(max_length=50, initial="return_5d", label="标签标识")
    data_version = forms.CharField(
        max_length=50,
        initial=timezone.now().strftime("%Y-%m-%d"),
        label="数据版本",
    )
    ic = forms.DecimalField(required=False, max_digits=10, decimal_places=6, label="IC")
    icir = forms.DecimalField(required=False, max_digits=10, decimal_places=6, label="ICIR")
    rank_ic = forms.DecimalField(required=False, max_digits=10, decimal_places=6, label="Rank IC")
    train_config = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 8, "cols": 100}),
        initial='{"source": "admin_import"}',
        label="训练配置 JSON",
        help_text="可选。用于记录模型来源、训练参数等。",
    )

    def clean_model_file(self) -> UploadedFile:
        """Accept only a Django uploaded pickle artifact."""

        uploaded: object = self.cleaned_data.get("model_file")
        if not isinstance(uploaded, UploadedFile):
            raise ValidationError("请选择有效的模型文件。")
        filename = uploaded.name or ""
        if not filename.lower().endswith(".pkl"):
            raise ValidationError("只支持上传 .pkl 模型文件。")
        return uploaded

    def clean_model_name(self) -> str:
        """Reject path separators and traversal markers in model names."""

        return _validate_model_name(self.cleaned_data.get("model_name"))

    def clean_train_config(self) -> dict[str, object]:
        """Return the imported model metadata as a JSON object."""

        return _parse_json_object(self.cleaned_data.get("train_config", ""), label="训练配置")


class QlibModelTrainForm(forms.Form):
    model_name = forms.CharField(max_length=100, label="模型名称", initial="lgb_csi300")
    model_type = forms.ChoiceField(
        choices=QlibModelRegistryModel.MODEL_TYPE_CHOICES,
        label="模型类型",
        initial=QlibModelRegistryModel.MODEL_LGB,
    )
    universe = forms.CharField(max_length=20, initial="csi300", label="股票池")
    start_date = forms.DateField(label="训练开始日期", initial="2020-01-01")
    end_date = forms.DateField(label="训练结束日期", initial=timezone.now().date())
    feature_set_id = forms.CharField(max_length=50, initial="v1", label="特征集标识")
    label_id = forms.CharField(max_length=50, initial="return_5d", label="标签标识")
    learning_rate = forms.FloatField(initial=0.01, label="学习率")
    epochs = forms.IntegerField(initial=100, min_value=1, label="训练轮数")
    model_params = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 8, "cols": 100}),
        initial='{"loss": "mse", "col_sample_bytree": 0.8}',
        label="模型参数 JSON",
    )
    extra_train_config = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 8, "cols": 100}),
        initial='{"source": "admin_train"}',
        label="附加训练配置 JSON",
    )
    activate_now = forms.BooleanField(required=False, initial=False, label="训练完成后自动激活")

    def clean_model_name(self) -> str:
        """Apply the same stable identifier contract used by model import."""

        return _validate_model_name(self.cleaned_data.get("model_name"))

    def clean_model_params(self) -> dict[str, object]:
        """Return training model parameters as a JSON object."""

        return _parse_json_object(self.cleaned_data.get("model_params", ""), label="模型参数")

    def clean_extra_train_config(self) -> dict[str, object]:
        """Return additional training metadata as a JSON object."""

        return _parse_json_object(
            self.cleaned_data.get("extra_train_config", ""),
            label="附加训练配置",
        )


@admin.register(QlibModelRegistryModel)
class QlibModelRegistryAdmin(TypedModelAdmin[QlibModelRegistryModel]):
    list_display = (
        "model_name",
        "artifact_hash_short",
        "model_type",
        "universe",
        "data_version",
        "ic",
        "icir",
        "is_active",
        "created_at",
    )
    list_filter = ("model_type", "universe", "is_active", "created_at")
    search_fields = ("model_name", "artifact_hash", "model_path", "feature_set_id", "label_id")
    readonly_fields = ("artifact_hash", "created_at", "activated_at", "activated_by")
    actions = ("activate_selected_models",)
    change_list_template = "admin/alpha/qlibmodelregistry/change_list.html"

    def get_urls(self) -> list[URLPattern]:
        """Publish superuser model import, validation, and training routes."""

        urls = super().get_urls()
        custom_urls = [
            path(
                "import-model/",
                self.admin_site.admin_view(self.import_model_view),
                name="alpha_qlibmodelregistry_import",
            ),
            path(
                "validate-model/<str:artifact_hash>/",
                self.admin_site.admin_view(self.validate_model_view),
                name="alpha_qlibmodelregistry_validate",
            ),
            path(
                "train-model/",
                self.admin_site.admin_view(self.train_model_view),
                name="alpha_qlibmodelregistry_train",
            ),
        ]
        return custom_urls + urls

    def changelist_view(
        self,
        request: HttpRequest,
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        """Add custom Qlib operation links to the registry changelist."""

        extra_context = extra_context or {}
        extra_context["import_url"] = reverse("admin:alpha_qlibmodelregistry_import")
        extra_context["train_url"] = reverse("admin:alpha_qlibmodelregistry_train")
        return super().changelist_view(request, extra_context=extra_context)

    @admin.display(description="Hash")
    def artifact_hash_short(self, obj: QlibModelRegistryModel) -> str:
        return f"{obj.artifact_hash[:12]}..."

    @admin.action(description="验证并激活选中的单个模型")
    def activate_selected_models(
        self,
        request: HttpRequest,
        queryset: QuerySet[QlibModelRegistryModel],
    ) -> None:
        """Validate and activate exactly one model under superuser control."""

        if not request.user.is_superuser:
            self.message_user(request, "只有超级用户可以激活模型。", level=messages.ERROR)
            return
        selected = list(queryset.order_by("created_at")[:2])
        if len(selected) != 1:
            self.message_user(request, "每次必须且只能选择一个模型。", level=messages.ERROR)
            return
        model = selected[0]
        validation = self._run_validation(model)
        if not validation["passed"]:
            self.message_user(request, "模型验证未通过，未执行激活。", level=messages.ERROR)
            return
        model.activate(activated_by=f"admin:{request.user.username}")
        self.message_user(
            request,
            f"已激活模型 {model.model_name}@{model.artifact_hash[:8]}。",
            level=messages.SUCCESS,
        )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Restrict pickle artifact import and direct registry creation to superusers."""

        return bool(request.user.is_superuser and super().has_add_permission(request))

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: QlibModelRegistryModel | None = None,
    ) -> bool:
        """Prevent delegated staff from changing artifact paths or model state."""

        return bool(request.user.is_superuser and super().has_change_permission(request, obj))

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: QlibModelRegistryModel | None = None,
    ) -> bool:
        """Restrict model registry deletion to superusers."""

        return bool(request.user.is_superuser and super().has_delete_permission(request, obj))

    def import_model_view(self, request: HttpRequest) -> HttpResponse:
        """Import a model artifact without activating it as a side effect."""

        if not self.has_add_permission(request):
            self.message_user(request, "你没有导入模型的权限。", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:index"))

        form = QlibModelImportForm(request.POST or None, request.FILES or None)

        if request.method == "POST" and form.is_valid():
            uploaded = cast(UploadedFile, form.cleaned_data["model_file"])
            model_name = cast(str, form.cleaned_data["model_name"])
            artifact_hash = self._hash_uploaded_file(uploaded)

            if QlibModelRegistryModel._default_manager.filter(artifact_hash=artifact_hash).exists():
                form.add_error("model_file", f"相同 artifact_hash 已存在: {artifact_hash}")
            else:
                model_file_path = self._store_uploaded_model(uploaded, model_name, artifact_hash)
                train_config = cast(dict[str, object], form.cleaned_data["train_config"])
                metrics_payload: dict[str, float | None] = {
                    "ic": (
                        float(form.cleaned_data["ic"])
                        if form.cleaned_data["ic"] is not None
                        else None
                    ),
                    "icir": (
                        float(form.cleaned_data["icir"])
                        if form.cleaned_data["icir"] is not None
                        else None
                    ),
                    "rank_ic": (
                        float(form.cleaned_data["rank_ic"])
                        if form.cleaned_data["rank_ic"] is not None
                        else None
                    ),
                }
                self._write_metadata_files(
                    model_file_path=model_file_path,
                    model_name=model_name,
                    artifact_hash=artifact_hash,
                    data_version=form.cleaned_data["data_version"],
                    train_config=train_config,
                    metrics=metrics_payload,
                )

                model = QlibModelRegistryModel._default_manager.create(
                    model_name=model_name,
                    artifact_hash=artifact_hash,
                    model_type=form.cleaned_data["model_type"],
                    universe=form.cleaned_data["universe"],
                    train_config=train_config,
                    feature_set_id=form.cleaned_data["feature_set_id"],
                    label_id=form.cleaned_data["label_id"],
                    data_version=form.cleaned_data["data_version"],
                    ic=form.cleaned_data["ic"],
                    icir=form.cleaned_data["icir"],
                    rank_ic=form.cleaned_data["rank_ic"],
                    model_path=str(model_file_path),
                    is_active=False,
                )

                return HttpResponseRedirect(
                    reverse(
                        "admin:alpha_qlibmodelregistry_validate",
                        args=[model.artifact_hash],
                    )
                )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "导入 Qlib 模型",
            "form": form,
            "has_view_permission": self.has_view_permission(request),
        }
        return render(request, "admin/alpha/qlibmodelregistry/import_form.html", context)

    def validate_model_view(self, request: HttpRequest, artifact_hash: str) -> HttpResponse:
        """Validate a model and activate it only through an explicit POST."""

        if not request.user.is_superuser or not self.has_view_permission(request):
            self.message_user(request, "你没有查看模型验证结果的权限。", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:index"))

        try:
            model = QlibModelRegistryModel._default_manager.get(artifact_hash=artifact_hash)
        except QlibModelRegistryModel.DoesNotExist:
            self.message_user(request, f"模型不存在: {artifact_hash}", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:alpha_qlibmodelregistrymodel_changelist"))

        result = self._run_validation(model)
        if request.method == "POST":
            if not self.has_change_permission(request, model):
                raise PermissionDenied("Model activation requires change permission")
            if request.POST.get("activate") != "1":
                return HttpResponseBadRequest("Unknown model validation action")
            if result["passed"] and not model.is_active:
                model.activate(activated_by=f"admin:{request.user.username}")
                result["activation_message"] = "验证通过，模型已激活。"
            elif not result["passed"]:
                result["activation_message"] = "验证未通过，未执行激活。"

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Qlib 模型试跑验证",
            "model_obj": model,
            "validation": result,
            "can_activate": result["passed"] and not model.is_active,
            "change_url": reverse("admin:alpha_qlibmodelregistrymodel_change", args=[model.pk]),
            "list_url": reverse("admin:alpha_qlibmodelregistrymodel_changelist"),
        }
        return render(request, "admin/alpha/qlibmodelregistry/validation_result.html", context)

    def train_model_view(self, request: HttpRequest) -> HttpResponse:
        """Validate and submit a Qlib training request for a superuser."""

        if not request.user.is_superuser:
            self.message_user(request, "你没有发起训练的权限。", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:index"))

        runtime_qlib = runtime_settings.get_runtime_qlib_config()
        initial = {
            "universe": runtime_qlib.get("default_universe", "csi300"),
            "feature_set_id": runtime_qlib.get("default_feature_set_id", "v1"),
            "label_id": runtime_qlib.get("default_label_id", "return_5d"),
            "activate_now": runtime_qlib.get("allow_auto_activate", False),
        }
        form = QlibModelTrainForm(request.POST or None, initial=initial)
        if request.method == "POST" and form.is_valid():
            try:
                trigger_result = TriggerQlibTrainingUseCase().execute(
                    actor=request.user,
                    payload={
                        "model_name": form.cleaned_data["model_name"],
                        "model_type": form.cleaned_data["model_type"],
                        "universe": form.cleaned_data["universe"],
                        "start_date": form.cleaned_data["start_date"],
                        "end_date": form.cleaned_data["end_date"],
                        "learning_rate": form.cleaned_data["learning_rate"],
                        "epochs": form.cleaned_data["epochs"],
                        "model_params": form.cleaned_data["model_params"],
                        "feature_set_id": form.cleaned_data["feature_set_id"],
                        "label_id": form.cleaned_data["label_id"],
                        "extra_train_config": form.cleaned_data["extra_train_config"],
                        "activate": form.cleaned_data["activate_now"],
                    },
                )
            except ConflictError as exc:
                form.add_error(None, str(exc))
            except QlibAccessDeniedError as exc:
                form.add_error(None, str(exc))
            except ValidationFailureError as exc:
                form.add_error(None, str(exc))
            else:
                resolved_config = trigger_result["resolved_train_config"]
                context = {
                    **self.admin_site.each_context(request),
                    "opts": self.model._meta,
                    "title": "Qlib 训练任务已提交",
                    "task_id": trigger_result["task_id"],
                    "run_id": trigger_result["run_id"],
                    "payload": {
                        "model_name": form.cleaned_data["model_name"],
                        "model_type": form.cleaned_data["model_type"],
                        "universe": resolved_config["universe"],
                        "start_date": resolved_config["start_date"],
                        "end_date": resolved_config["end_date"],
                        "activate": resolved_config["activate"],
                    },
                    "list_url": reverse("admin:alpha_qlibmodelregistrymodel_changelist"),
                }
                return render(request, "admin/alpha/qlibmodelregistry/train_queued.html", context)

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "发起 Qlib 训练",
            "form": form,
            "has_view_permission": self.has_view_permission(request),
        }
        return render(request, "admin/alpha/qlibmodelregistry/train_form.html", context)

    def _model_root(self) -> Path:
        qlib_settings = _qlib_settings_mapping()
        configured_root = qlib_settings.get("model_path", "/models/qlib")
        root = configured_root if isinstance(configured_root, str) else "/models/qlib"
        return Path(root).expanduser().resolve()

    def _hash_uploaded_file(self, uploaded: UploadedFile) -> str:
        sha256 = hashlib.sha256()
        for chunk in uploaded.chunks():
            sha256.update(chunk)
        uploaded.seek(0)
        return sha256.hexdigest()

    def _store_uploaded_model(
        self,
        uploaded: UploadedFile,
        model_name: str,
        artifact_hash: str,
    ) -> Path:
        try:
            safe_model_name = _validate_model_name(model_name)
        except ValidationError as exc:
            raise ValueError("model_name must be a safe identifier") from exc
        if _ARTIFACT_HASH_PATTERN.fullmatch(artifact_hash) is None:
            raise ValueError("artifact_hash must be a lowercase SHA-256 digest")
        model_root = self._model_root()
        artifact_dir = (model_root / safe_model_name / artifact_hash).resolve()
        if not artifact_dir.is_relative_to(model_root):
            raise ValueError("model artifact path escapes the configured root")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        model_file_path = artifact_dir / "model.pkl"
        with model_file_path.open("wb") as destination:
            for chunk in uploaded.chunks():
                destination.write(chunk)
        uploaded.seek(0)
        return model_file_path

    def _write_metadata_files(
        self,
        model_file_path: Path,
        model_name: str,
        artifact_hash: str,
        data_version: str,
        train_config: dict[str, object],
        metrics: dict[str, float | None],
    ) -> None:
        artifact_dir = model_file_path.parent
        with (artifact_dir / "config.json").open("w", encoding="utf-8") as fh:
            json.dump(
                {
                    "model_name": model_name,
                    "artifact_hash": artifact_hash,
                    "train_config": train_config,
                    "imported_at": timezone.now().isoformat(),
                    "source": "django_admin",
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )
        with (artifact_dir / "metrics.json").open("w", encoding="utf-8") as fh:
            json.dump(metrics, fh, ensure_ascii=False, indent=2)
        with (artifact_dir / "data_version.txt").open("w", encoding="utf-8") as fh:
            fh.write(data_version)

    def _run_validation(self, model: QlibModelRegistryModel) -> ModelValidationResult:
        checks: list[ModelValidationCheck] = []
        sample_scores: list[dict[str, object]] = []
        passed = True

        model_file = Path(model.model_path)
        file_exists = model_file.exists()
        checks.append(
            {
                "label": "模型文件存在",
                "ok": file_exists,
                "detail": str(model_file) if file_exists else f"文件不存在: {model_file}",
            }
        )
        passed = passed and file_exists

        pickle_ok = False
        if file_exists:
            try:
                with model_file.open("rb") as fh:
                    loaded = pickle.load(fh)
                pickle_ok = True
                checks.append(
                    {
                        "label": "pickle 加载",
                        "ok": True,
                        "detail": f"加载成功: {loaded.__class__.__name__}",
                    }
                )
            except Exception as exc:
                checks.append(
                    {
                        "label": "pickle 加载",
                        "ok": False,
                        "detail": f"加载失败: {type(exc).__name__}",
                    }
                )
                passed = False

        qlib_import_ok = False
        qlib_data_ok = False
        qlib_data_path = ""
        try:
            importlib.import_module("qlib")

            qlib_import_ok = True
            checks.append({"label": "Qlib 依赖", "ok": True, "detail": "pyqlib 可导入"})
        except Exception as exc:
            checks.append(
                {
                    "label": "Qlib 依赖",
                    "ok": False,
                    "detail": f"pyqlib 不可用: {type(exc).__name__}",
                }
            )
            passed = False

        # 优先从数据库读取 Qlib 配置
        try:
            qlib_runtime_config = runtime_settings.get_runtime_qlib_config()
            provider_uri = qlib_runtime_config.get("provider_uri", "")
            enabled = qlib_runtime_config.get("enabled", False)
            qlib_data_path = provider_uri if isinstance(provider_uri, str) else ""
            qlib_enabled = enabled if isinstance(enabled, bool) else False
        except Exception as exc:
            qlib_data_path = ""
            qlib_enabled = False
            checks.append(
                {
                    "label": "Qlib 运行配置",
                    "ok": False,
                    "detail": f"配置不可用: {type(exc).__name__}",
                }
            )
            passed = False

        if qlib_data_path:
            data_path_obj = Path(qlib_data_path).expanduser()
            qlib_data_ok = data_path_obj.exists()
        else:
            qlib_data_ok = False

        status_text = "启用" if qlib_enabled else "未启用"
        checks.append(
            {
                "label": "Qlib 数据目录",
                "ok": qlib_data_ok,
                "detail": (
                    f"{qlib_data_path} ({status_text})"
                    if qlib_data_ok
                    else f"目录不存在: {qlib_data_path} ({status_text})"
                ),
            }
        )
        passed = passed and qlib_data_ok and qlib_enabled

        if file_exists and pickle_ok and qlib_import_ok and qlib_data_ok:
            try:
                scores = _execute_qlib_prediction(
                    active_model=model,
                    universe_id=model.universe,
                    trade_date=timezone.now().date(),
                    top_n=5,
                )
                sample_scores = [
                    {str(key): value for key, value in score.items()} for score in scores[:5]
                ]
                checks.append(
                    {
                        "label": "真实推理 smoke test",
                        "ok": bool(scores),
                        "detail": (
                            f"返回 {len(scores)} 条评分" if scores else "推理成功但返回空结果"
                        ),
                    }
                )
                passed = passed and bool(scores)
            except Exception as exc:
                checks.append(
                    {
                        "label": "真实推理 smoke test",
                        "ok": False,
                        "detail": f"推理失败: {type(exc).__name__}",
                    }
                )
                passed = False

        return {
            "passed": passed,
            "checks": checks,
            "sample_scores": sample_scores,
            "activation_message": "",
        }


@admin.register(AlphaScoreCacheModel)
class AlphaScoreCacheAdmin(TypedModelAdmin[AlphaScoreCacheModel]):
    list_display = ("universe_id", "intended_trade_date", "provider_source", "status", "created_at")
    list_filter = ("provider_source", "status", "universe_id")
    search_fields = ("universe_id", "model_id", "model_artifact_hash")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AlphaAlertModel)
class AlphaAlertAdmin(TypedModelAdmin[AlphaAlertModel]):
    list_display = ("title", "alert_type", "severity", "is_resolved", "created_at")
    list_filter = ("alert_type", "severity", "is_resolved")
    search_fields = ("title", "message")
    readonly_fields = ("created_at", "resolved_at")
