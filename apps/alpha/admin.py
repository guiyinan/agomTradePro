from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.utils import timezone

from apps.alpha.application.tasks import _execute_qlib_prediction
from apps.alpha.infrastructure.models import (
    AlphaAlertModel,
    AlphaScoreCacheModel,
    QlibModelRegistryModel,
)


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
    activate_now = forms.BooleanField(
        required=False,
        initial=True,
        label="导入后立即激活",
    )

    def clean_model_file(self):
        uploaded = self.cleaned_data["model_file"]
        if not uploaded.name.lower().endswith(".pkl"):
            raise ValidationError("只支持上传 .pkl 模型文件。")
        return uploaded

    def clean_train_config(self):
        raw = self.cleaned_data.get("train_config", "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"训练配置 JSON 解析失败: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValidationError("训练配置必须是 JSON object。")
        return parsed


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

    def clean_model_params(self):
        raw = self.cleaned_data.get("model_params", "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"模型参数 JSON 解析失败: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValidationError("模型参数必须是 JSON object。")
        return parsed

    def clean_extra_train_config(self):
        raw = self.cleaned_data.get("extra_train_config", "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"附加训练配置 JSON 解析失败: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValidationError("附加训练配置必须是 JSON object。")
        return parsed


@admin.register(QlibModelRegistryModel)
class QlibModelRegistryAdmin(admin.ModelAdmin):
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

    def get_urls(self):
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

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["import_url"] = reverse("admin:alpha_qlibmodelregistry_import")
        extra_context["train_url"] = reverse("admin:alpha_qlibmodelregistry_train")
        return super().changelist_view(request, extra_context=extra_context)

    @admin.display(description="Hash")
    def artifact_hash_short(self, obj: QlibModelRegistryModel) -> str:
        return f"{obj.artifact_hash[:12]}..."

    @admin.action(description="激活选中的模型（最后一条生效）")
    def activate_selected_models(self, request, queryset):
        last_model = None
        for model in queryset.order_by("created_at"):
            model.activate(activated_by=f"admin:{request.user.username}")
            last_model = model
        if last_model is not None:
            self.message_user(
                request,
                f"已激活模型 {last_model.model_name}@{last_model.artifact_hash[:8]}。",
                level=messages.SUCCESS,
            )

    def import_model_view(self, request: HttpRequest):
        if not self.has_add_permission(request):
            self.message_user(request, "你没有导入模型的权限。", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:index"))

        form = QlibModelImportForm(request.POST or None, request.FILES or None)

        if request.method == "POST" and form.is_valid():
            uploaded = form.cleaned_data["model_file"]
            model_name = form.cleaned_data["model_name"]
            artifact_hash = self._hash_uploaded_file(uploaded)

            if QlibModelRegistryModel._default_manager.filter(artifact_hash=artifact_hash).exists():
                form.add_error("model_file", f"相同 artifact_hash 已存在: {artifact_hash}")
            else:
                model_file_path = self._store_uploaded_model(uploaded, model_name, artifact_hash)
                train_config = form.cleaned_data["train_config"]
                metrics_payload = {
                    "ic": float(form.cleaned_data["ic"]) if form.cleaned_data["ic"] is not None else None,
                    "icir": float(form.cleaned_data["icir"]) if form.cleaned_data["icir"] is not None else None,
                    "rank_ic": float(form.cleaned_data["rank_ic"]) if form.cleaned_data["rank_ic"] is not None else None,
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
                    f"{reverse('admin:alpha_qlibmodelregistry_validate', args=[model.artifact_hash])}"
                    f"?activate={'1' if form.cleaned_data['activate_now'] else '0'}"
                )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "导入 Qlib 模型",
            "form": form,
            "has_view_permission": self.has_view_permission(request),
        }
        return render(request, "admin/alpha/qlibmodelregistry/import_form.html", context)

    def validate_model_view(self, request: HttpRequest, artifact_hash: str):
        if not self.has_view_permission(request):
            self.message_user(request, "你没有查看模型验证结果的权限。", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:index"))

        try:
            model = QlibModelRegistryModel._default_manager.get(artifact_hash=artifact_hash)
        except QlibModelRegistryModel.DoesNotExist:
            self.message_user(request, f"模型不存在: {artifact_hash}", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:alpha_qlibmodelregistrymodel_changelist"))

        should_activate = request.GET.get("activate") == "1"
        result = self._run_validation(model)
        if should_activate and result["passed"] and not model.is_active:
            model.activate(activated_by=f"admin:{request.user.username}")
            result["activation_message"] = "验证通过，模型已自动激活。"
        elif should_activate and not result["passed"]:
            result["activation_message"] = "验证未通过，未执行自动激活。"

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Qlib 模型试跑验证",
            "model_obj": model,
            "validation": result,
            "change_url": reverse("admin:alpha_qlibmodelregistrymodel_change", args=[model.pk]),
            "list_url": reverse("admin:alpha_qlibmodelregistrymodel_changelist"),
        }
        return render(request, "admin/alpha/qlibmodelregistry/validation_result.html", context)

    def train_model_view(self, request: HttpRequest):
        if not self.has_add_permission(request):
            self.message_user(request, "你没有发起训练的权限。", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:index"))

        form = QlibModelTrainForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            from apps.alpha.application.tasks import qlib_train_model

            extra_train_config = form.cleaned_data["extra_train_config"]
            train_config = {
                **extra_train_config,
                "universe": form.cleaned_data["universe"],
                "start_date": form.cleaned_data["start_date"].isoformat(),
                "end_date": form.cleaned_data["end_date"].isoformat(),
                "learning_rate": form.cleaned_data["learning_rate"],
                "epochs": form.cleaned_data["epochs"],
                "model_params": form.cleaned_data["model_params"],
                "feature_set_id": form.cleaned_data["feature_set_id"],
                "label_id": form.cleaned_data["label_id"],
                "model_path": str(self._model_root()),
                "activate": form.cleaned_data["activate_now"],
            }

            task = qlib_train_model.delay(
                model_name=form.cleaned_data["model_name"],
                model_type=form.cleaned_data["model_type"],
                train_config=train_config,
            )

            context = {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "title": "Qlib 训练任务已提交",
                "task_id": task.id,
                "payload": {
                    "model_name": form.cleaned_data["model_name"],
                    "model_type": form.cleaned_data["model_type"],
                    "universe": form.cleaned_data["universe"],
                    "start_date": train_config["start_date"],
                    "end_date": train_config["end_date"],
                    "activate": train_config["activate"],
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
        qlib_settings = getattr(settings, "QLIB_SETTINGS", {}) or {}
        root = qlib_settings.get("model_path", "/models/qlib")
        return Path(root).expanduser()

    def _hash_uploaded_file(self, uploaded) -> str:
        sha256 = hashlib.sha256()
        for chunk in uploaded.chunks():
            sha256.update(chunk)
        uploaded.seek(0)
        return sha256.hexdigest()

    def _store_uploaded_model(self, uploaded, model_name: str, artifact_hash: str) -> Path:
        artifact_dir = self._model_root() / model_name / artifact_hash
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
        train_config: dict,
        metrics: dict,
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

    def _run_validation(self, model: QlibModelRegistryModel) -> dict:
        checks: list[dict] = []
        sample_scores = []
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
                        "detail": f"加载失败: {exc}",
                    }
                )
                passed = False

        qlib_import_ok = False
        qlib_data_ok = False
        qlib_data_path = ""
        try:
            import qlib  # noqa: F401

            qlib_import_ok = True
            checks.append({"label": "Qlib 依赖", "ok": True, "detail": "pyqlib 可导入"})
        except Exception as exc:
            checks.append({"label": "Qlib 依赖", "ok": False, "detail": f"pyqlib 不可用: {exc}"})
            passed = False

        qlib_settings = getattr(settings, "QLIB_SETTINGS", {}) or {}

        # 优先从数据库读取 Qlib 配置
        try:
            from apps.account.infrastructure.models import SystemSettingsModel
            qlib_runtime_config = SystemSettingsModel.get_runtime_qlib_config()
            qlib_data_path = qlib_runtime_config.get('provider_uri', '')
            qlib_enabled = qlib_runtime_config.get('enabled', False)
        except Exception:
            qlib_data_path = str(Path(qlib_settings.get("provider_uri", "~/.qlib/qlib_data/cn_data")).expanduser())
            qlib_enabled = False

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
                "detail": f"{qlib_data_path} ({status_text})" if qlib_data_ok else f"目录不存在: {qlib_data_path} ({status_text})",
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
                sample_scores = scores[:5]
                checks.append(
                    {
                        "label": "真实推理 smoke test",
                        "ok": bool(scores),
                        "detail": f"返回 {len(scores)} 条评分" if scores else "推理成功但返回空结果",
                    }
                )
                passed = passed and bool(scores)
            except Exception as exc:
                checks.append(
                    {
                        "label": "真实推理 smoke test",
                        "ok": False,
                        "detail": str(exc),
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
class AlphaScoreCacheAdmin(admin.ModelAdmin):
    list_display = ("universe_id", "intended_trade_date", "provider_source", "status", "created_at")
    list_filter = ("provider_source", "status", "universe_id")
    search_fields = ("universe_id", "model_id", "model_artifact_hash")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AlphaAlertModel)
class AlphaAlertAdmin(admin.ModelAdmin):
    list_display = ("title", "alert_type", "severity", "is_resolved", "created_at")
    list_filter = ("alert_type", "severity", "is_resolved")
    search_fields = ("title", "message")
    readonly_fields = ("created_at", "resolved_at")
