from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.agent_runtime.application.interface_services import (
    get_operator_proposal_detail_context,
    get_operator_proposal_list_context,
    get_operator_task_detail_context,
    get_operator_task_list_context,
)
from apps.agent_runtime.application.proposal_use_cases import (
    ApproveProposalUseCase,
    ExecuteProposalUseCase,
    GuardrailBlockedError,
    InvalidProposalTransitionError,
    RejectProposalUseCase,
    SubmitProposalForApprovalUseCase,
)


def _ensure_operator_access(request: HttpRequest) -> None:
    user = request.user
    if not user.is_authenticated:
        raise PermissionDenied
    if user.is_staff:
        return
    if user.groups.filter(name="operator").exists():
        return
    raise PermissionDenied


def _build_actor(request: HttpRequest) -> dict[str, Any]:
    return {
        "user_id": request.user.id,
        "is_staff": request.user.is_staff,
        "roles": list(request.user.groups.values_list("name", flat=True)),
    }


@require_http_methods(["GET"])
def operator_task_list_view(request: HttpRequest) -> HttpResponse:
    _ensure_operator_access(request)

    status_filter = (request.GET.get("status") or "").strip()
    domain_filter = (request.GET.get("task_domain") or "").strip()
    search = (request.GET.get("search") or "").strip()
    attention_only = request.GET.get("attention") == "1"

    context = get_operator_task_list_context(
        status_filter=status_filter,
        domain_filter=domain_filter,
        search=search,
        attention_only=attention_only,
    )
    return render(request, "agent_runtime/operator_task_list.html", context)


@require_http_methods(["GET"])
def operator_task_detail_view(request: HttpRequest, task_id: int) -> HttpResponse:
    _ensure_operator_access(request)

    context = get_operator_task_detail_context(task_id=task_id)
    if context is None:
        raise Http404
    return render(request, "agent_runtime/operator_task_detail.html", context)


@require_http_methods(["GET"])
def operator_proposal_list_view(request: HttpRequest) -> HttpResponse:
    _ensure_operator_access(request)

    status_filter = (request.GET.get("status") or "").strip()
    approval_filter = (request.GET.get("approval_status") or "").strip()
    risk_filter = (request.GET.get("risk_level") or "").strip()
    search = (request.GET.get("search") or "").strip()

    context = get_operator_proposal_list_context(
        status_filter=status_filter,
        approval_filter=approval_filter,
        risk_filter=risk_filter,
        search=search,
    )
    return render(request, "agent_runtime/operator_proposal_list.html", context)


@require_http_methods(["GET", "POST"])
def operator_proposal_detail_view(request: HttpRequest, proposal_id: int) -> HttpResponse:
    _ensure_operator_access(request)

    context = get_operator_proposal_detail_context(proposal_id=proposal_id)
    if context is None:
        raise Http404
    proposal = context["proposal"]

    if request.method == "POST":
        action_name = (request.POST.get("action") or "").strip()
        reason = (request.POST.get("reason") or "").strip() or None
        actor = _build_actor(request)
        try:
            if action_name == "submit":
                SubmitProposalForApprovalUseCase().execute(proposal_id=proposal.id, actor=actor)
                messages.success(request, "Proposal 已提交审批。")
            elif action_name == "approve":
                ApproveProposalUseCase().execute(proposal_id=proposal.id, reason=reason, actor=actor)
                messages.success(request, "Proposal 已批准。")
            elif action_name == "reject":
                RejectProposalUseCase().execute(proposal_id=proposal.id, reason=reason, actor=actor)
                messages.success(request, "Proposal 已拒绝。")
            elif action_name == "execute":
                output = ExecuteProposalUseCase().execute(proposal_id=proposal.id, actor=actor)
                messages.success(request, f"Proposal 已执行，execution_record_id={output.execution_record_id}。")
            else:
                messages.error(request, "不支持的 proposal 动作。")
        except InvalidProposalTransitionError as exc:
            messages.error(request, exc.message)
        except GuardrailBlockedError as exc:
            messages.error(request, f"Guardrail blocked: {exc.guardrail_message}")
        return redirect(reverse("agent_runtime_pages:proposal_detail", args=[proposal.id]))
    return render(request, "agent_runtime/operator_proposal_detail.html", context)
