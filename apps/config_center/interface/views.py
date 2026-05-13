"""Interface views for config center pages."""

from __future__ import annotations

import json
from typing import Any

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render

from apps.config_center.application.use_cases import (
    ConflictError,
    CreateOrUpdateQlibTrainingProfileUseCase,
    GetQlibRuntimeConfigUseCase,
    GetQlibTrainingRunDetailUseCase,
    ListQlibTrainingProfilesUseCase,
    ListQlibTrainingRunsUseCase,
    QlibAccessDeniedError,
    TriggerQlibTrainingUseCase,
    UpdateQlibRuntimeConfigUseCase,
    ValidationFailureError,
)


class QlibRuntimeConfigForm(forms.Form):
    enabled = forms.BooleanField(required=False, label="启用 Qlib")
    provider_uri = forms.CharField(max_length=500, label="Qlib 数据目录")
    region = forms.CharField(max_length=10, label="Qlib 区域")
    model_root = forms.CharField(max_length=500, label="Qlib 模型目录")
    default_universe = forms.CharField(max_length=50, label="默认股票池")
    default_feature_set_id = forms.CharField(max_length=50, label="默认特征集")
    default_label_id = forms.CharField(max_length=50, label="默认标签")
    train_queue_name = forms.CharField(max_length=64, label="训练队列")
    infer_queue_name = forms.CharField(max_length=64, label="推理队列")
    allow_auto_activate = forms.BooleanField(required=False, label="允许训练后自动激活")
    alpha_fixed_provider = forms.CharField(required=False, max_length=20, label="固定 Alpha Provider")
    alpha_pool_mode = forms.ChoiceField(
        choices=[
            ("strict_valuation", "严格估值覆盖池"),
            ("market", "市场可交易池"),
            ("price_covered", "价格覆盖池"),
        ],
        label="Alpha 默认股票池模式",
    )


class QlibTrainingProfileForm(forms.Form):
    profile_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    profile_key = forms.CharField(max_length=64, label="模板键")
    name = forms.CharField(max_length=120, label="模板名称")
    model_name = forms.CharField(max_length=100, label="模型名称")
    model_type = forms.CharField(max_length=50, label="模型类型")
    universe = forms.CharField(max_length=50, required=False, label="股票池")
    start_date = forms.DateField(required=False, label="训练开始日期")
    end_date = forms.DateField(required=False, label="训练结束日期")
    feature_set_id = forms.CharField(max_length=50, required=False, label="特征集标识")
    label_id = forms.CharField(max_length=50, required=False, label="标签标识")
    learning_rate = forms.FloatField(required=False, label="学习率")
    epochs = forms.IntegerField(required=False, min_value=1, label="训练轮数")
    model_params = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        label="模型参数 JSON",
    )
    extra_train_config = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        label="附加训练配置 JSON",
    )
    activate_after_train = forms.BooleanField(required=False, label="训练完成后自动激活")
    is_active = forms.BooleanField(required=False, initial=True, label="模板启用")
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), label="备注")

    def clean_model_params(self) -> dict[str, Any]:
        return _parse_json_object(self.cleaned_data.get("model_params", ""), field_name="模型参数")

    def clean_extra_train_config(self) -> dict[str, Any]:
        return _parse_json_object(
            self.cleaned_data.get("extra_train_config", ""),
            field_name="附加训练配置",
        )


class QlibTrainingTriggerForm(forms.Form):
    profile_key = forms.CharField(required=False, max_length=64, label="训练模板键")
    model_name = forms.CharField(max_length=100, label="模型名称")
    model_type = forms.CharField(max_length=50, label="模型类型")
    universe = forms.CharField(required=False, max_length=50, label="股票池")
    start_date = forms.DateField(required=False, label="训练开始日期")
    end_date = forms.DateField(required=False, label="训练结束日期")
    feature_set_id = forms.CharField(required=False, max_length=50, label="特征集标识")
    label_id = forms.CharField(required=False, max_length=50, label="标签标识")
    learning_rate = forms.FloatField(required=False, label="学习率")
    epochs = forms.IntegerField(required=False, min_value=1, label="训练轮数")
    model_params = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        label="模型参数 JSON",
    )
    extra_train_config = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        label="附加训练配置 JSON",
    )
    activate = forms.BooleanField(required=False, label="训练完成后自动激活")

    def clean_model_params(self) -> dict[str, Any]:
        return _parse_json_object(self.cleaned_data.get("model_params", ""), field_name="模型参数")

    def clean_extra_train_config(self) -> dict[str, Any]:
        return _parse_json_object(
            self.cleaned_data.get("extra_train_config", ""),
            field_name="附加训练配置",
        )


def _parse_json_object(raw: str, *, field_name: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise forms.ValidationError(f"{field_name} JSON 解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise forms.ValidationError(f"{field_name} 必须是 JSON object。")
    return payload


def _pretty_json(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "{}"
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _runtime_form_initial(runtime_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": runtime_payload.get("enabled", False),
        "provider_uri": runtime_payload.get("provider_uri", ""),
        "region": runtime_payload.get("region", "CN"),
        "model_root": runtime_payload.get("model_root", ""),
        "default_universe": runtime_payload.get("default_universe", "csi300"),
        "default_feature_set_id": runtime_payload.get("default_feature_set_id", "v1"),
        "default_label_id": runtime_payload.get("default_label_id", "return_5d"),
        "train_queue_name": runtime_payload.get("train_queue_name", "qlib_train"),
        "infer_queue_name": runtime_payload.get("infer_queue_name", "qlib_infer"),
        "allow_auto_activate": runtime_payload.get("allow_auto_activate", False),
        "alpha_fixed_provider": runtime_payload.get("alpha_fixed_provider", ""),
        "alpha_pool_mode": runtime_payload.get("alpha_pool_mode", "strict_valuation"),
    }


def _profile_form_initial(profile) -> dict[str, Any]:
    if profile is None:
        return {
            "model_params": "{}",
            "extra_train_config": '{"source": "config_center_profile"}',
            "is_active": True,
        }
    return {
        "profile_id": profile.id,
        "profile_key": profile.profile_key,
        "name": profile.name,
        "model_name": profile.model_name,
        "model_type": profile.model_type,
        "universe": profile.universe,
        "start_date": profile.start_date,
        "end_date": profile.end_date,
        "feature_set_id": profile.feature_set_id,
        "label_id": profile.label_id,
        "learning_rate": profile.learning_rate,
        "epochs": profile.epochs,
        "model_params": _pretty_json(profile.model_params or {}),
        "extra_train_config": _pretty_json(profile.extra_train_config or {}),
        "activate_after_train": profile.activate_after_train,
        "is_active": profile.is_active,
        "notes": profile.notes,
    }


def _trigger_form_initial(runtime_payload: dict[str, Any], profile) -> dict[str, Any]:
    initial = {
        "profile_key": "",
        "model_name": "lgb_csi300",
        "model_type": "LGBModel",
        "universe": runtime_payload.get("default_universe", "csi300"),
        "feature_set_id": runtime_payload.get("default_feature_set_id", "v1"),
        "label_id": runtime_payload.get("default_label_id", "return_5d"),
        "model_params": "{}",
        "extra_train_config": '{"source": "config_center_page"}',
        "activate": runtime_payload.get("allow_auto_activate", False),
    }
    if profile is None:
        return initial
    initial.update(
        {
            "profile_key": profile.profile_key,
            "model_name": profile.model_name,
            "model_type": profile.model_type,
            "universe": profile.universe or initial["universe"],
            "start_date": profile.start_date,
            "end_date": profile.end_date,
            "feature_set_id": profile.feature_set_id or initial["feature_set_id"],
            "label_id": profile.label_id or initial["label_id"],
            "learning_rate": profile.learning_rate,
            "epochs": profile.epochs,
            "model_params": _pretty_json(profile.model_params or {}),
            "extra_train_config": _pretty_json(profile.extra_train_config or {}),
            "activate": profile.activate_after_train,
        }
    )
    return initial


def _resolve_selected_profile(profiles: list[Any], request: HttpRequest):
    selected_key = str(request.GET.get("profile", "") or request.POST.get("profile_key", "")).strip()
    if not selected_key:
        return None
    for profile in profiles:
        if profile.profile_key == selected_key:
            return profile
    return None


def _serialize_profiles(profiles: list[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for profile in profiles:
        serialized.append(
            {
                "id": profile.id,
                "profile_key": profile.profile_key,
                "name": profile.name,
                "model_name": profile.model_name,
                "model_type": profile.model_type,
                "universe": profile.universe,
                "feature_set_id": profile.feature_set_id,
                "label_id": profile.label_id,
                "is_active": profile.is_active,
                "activate_after_train": profile.activate_after_train,
                "updated_at": profile.updated_at,
            }
        )
    return serialized


def _serialize_runs(*, actor, runs: list[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for run in runs:
        detail = GetQlibTrainingRunDetailUseCase().execute(actor=actor, run_id=str(run.run_id))
        payload = detail or run
        serialized.append(
            {
                "run_id": str(payload.run_id),
                "status": payload.status,
                "model_name": payload.model_name,
                "model_type": payload.model_type,
                "requested_by": getattr(payload.requested_by, "username", None),
                "requested_at": payload.requested_at,
                "started_at": payload.started_at,
                "finished_at": payload.finished_at,
                "celery_task_id": payload.celery_task_id,
                "result_model_name": payload.result_model_name,
                "result_artifact_hash": payload.result_artifact_hash,
                "error_message": payload.error_message,
                "resolved_train_config_json": _pretty_json(payload.resolved_train_config or {}),
                "result_metrics_json": _pretty_json(payload.result_metrics or {}),
                "registry_result_json": _pretty_json(payload.registry_result or {}),
                "profile_name": getattr(getattr(payload, "profile", None), "name", ""),
            }
        )
    return serialized


@login_required
def qlib_config_center_view(request: HttpRequest) -> HttpResponse:
    try:
        runtime_payload = GetQlibRuntimeConfigUseCase().execute(actor=request.user)
        profiles = ListQlibTrainingProfilesUseCase().execute(actor=request.user)
        runs = ListQlibTrainingRunsUseCase().execute(actor=request.user, limit=20)
    except QlibAccessDeniedError as exc:
        return HttpResponseForbidden(str(exc))

    selected_profile = _resolve_selected_profile(profiles, request)

    runtime_form = QlibRuntimeConfigForm(initial=_runtime_form_initial(runtime_payload))
    profile_form = QlibTrainingProfileForm(initial=_profile_form_initial(selected_profile))
    trigger_form = QlibTrainingTriggerForm(initial=_trigger_form_initial(runtime_payload, selected_profile))

    if request.method == "POST":
        action = str(request.POST.get("action") or "").strip()
        if action == "update_runtime":
            runtime_form = QlibRuntimeConfigForm(request.POST)
            if runtime_form.is_valid():
                try:
                    UpdateQlibRuntimeConfigUseCase().execute(
                        actor=request.user,
                        payload=runtime_form.cleaned_data,
                    )
                except QlibAccessDeniedError as exc:
                    messages.error(request, str(exc))
                else:
                    messages.success(request, "Qlib Runtime 配置已更新。")
                    return redirect("config_center_pages:qlib-center")
        elif action == "save_profile":
            profile_form = QlibTrainingProfileForm(request.POST)
            if profile_form.is_valid():
                payload = {
                    "id": profile_form.cleaned_data.get("profile_id"),
                    "profile_key": profile_form.cleaned_data["profile_key"],
                    "name": profile_form.cleaned_data["name"],
                    "model_name": profile_form.cleaned_data["model_name"],
                    "model_type": profile_form.cleaned_data["model_type"],
                    "universe": profile_form.cleaned_data["universe"],
                    "start_date": profile_form.cleaned_data["start_date"],
                    "end_date": profile_form.cleaned_data["end_date"],
                    "feature_set_id": profile_form.cleaned_data["feature_set_id"],
                    "label_id": profile_form.cleaned_data["label_id"],
                    "learning_rate": profile_form.cleaned_data["learning_rate"],
                    "epochs": profile_form.cleaned_data["epochs"],
                    "model_params": profile_form.cleaned_data["model_params"],
                    "extra_train_config": profile_form.cleaned_data["extra_train_config"],
                    "activate_after_train": profile_form.cleaned_data["activate_after_train"],
                    "is_active": profile_form.cleaned_data["is_active"],
                    "notes": profile_form.cleaned_data["notes"],
                }
                try:
                    model = CreateOrUpdateQlibTrainingProfileUseCase().execute(
                        actor=request.user,
                        payload=payload,
                    )
                except QlibAccessDeniedError as exc:
                    messages.error(request, str(exc))
                else:
                    messages.success(request, f"训练模板已保存：{model.name}")
                    return redirect(f"{request.path}?profile={model.profile_key}")
        elif action == "trigger_training":
            trigger_form = QlibTrainingTriggerForm(request.POST)
            if trigger_form.is_valid():
                payload = {
                    "profile_key": trigger_form.cleaned_data["profile_key"],
                    "model_name": trigger_form.cleaned_data["model_name"],
                    "model_type": trigger_form.cleaned_data["model_type"],
                    "universe": trigger_form.cleaned_data["universe"],
                    "start_date": trigger_form.cleaned_data["start_date"],
                    "end_date": trigger_form.cleaned_data["end_date"],
                    "feature_set_id": trigger_form.cleaned_data["feature_set_id"],
                    "label_id": trigger_form.cleaned_data["label_id"],
                    "learning_rate": trigger_form.cleaned_data["learning_rate"],
                    "epochs": trigger_form.cleaned_data["epochs"],
                    "model_params": trigger_form.cleaned_data["model_params"],
                    "extra_train_config": trigger_form.cleaned_data["extra_train_config"],
                    "activate": trigger_form.cleaned_data["activate"],
                }
                try:
                    result = TriggerQlibTrainingUseCase().execute(actor=request.user, payload=payload)
                except QlibAccessDeniedError as exc:
                    trigger_form.add_error(None, str(exc))
                except ConflictError as exc:
                    trigger_form.add_error(None, str(exc))
                except ValidationFailureError as exc:
                    trigger_form.add_error(None, str(exc))
                else:
                    messages.success(
                        request,
                        f"训练任务已提交：run_id={result['run_id']} task_id={result['task_id']}",
                    )
                    return redirect(f"{request.path}?profile={payload.get('profile_key', '')}")

    context = {
        "page_title": "Qlib 配置与训练中心",
        "page_subtitle": "统一查看 Runtime 配置、训练模板、运行记录，并直接触发在线训练。",
        "runtime_payload": GetQlibRuntimeConfigUseCase().execute(actor=request.user),
        "runtime_form": runtime_form,
        "profile_form": profile_form,
        "trigger_form": trigger_form,
        "profiles": _serialize_profiles(ListQlibTrainingProfilesUseCase().execute(actor=request.user)),
        "runs": _serialize_runs(
            actor=request.user,
            runs=ListQlibTrainingRunsUseCase().execute(actor=request.user, limit=20),
        ),
        "selected_profile_key": getattr(selected_profile, "profile_key", ""),
        "can_write": request.user.is_superuser,
        "settings_center_url": "/settings/",
        "api_runtime_url": "/api/system/config-center/qlib/runtime/",
        "api_profiles_url": "/api/system/config-center/qlib/training-profiles/",
        "api_runs_url": "/api/system/config-center/qlib/training-runs/",
        "api_trigger_url": "/api/system/config-center/qlib/training-runs/trigger/",
    }
    return render(request, "config_center/qlib_center.html", context)
