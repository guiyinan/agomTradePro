"""Runtime TUI metadata for Agent Runtime operator workflows."""

from __future__ import annotations

from typing import Any

from apps.agent_runtime.domain.entities import (
    ApprovalStatus,
    ProposalStatus,
    RiskLevel,
    TaskDomain,
    TaskStatus,
)

_SCREEN = "ai-ops.agent-runtime"
_MODULE = "research-tools"
_SOURCE = "approved:runtime-agent-runtime-operator"


def _path_id(key: str, label: str) -> dict[str, Any]:
    """Build one positive integer path parameter."""

    return {
        "key": key,
        "label": label,
        "binding": "path",
        "input_type": "number",
        "value_type": "integer",
        "required": True,
        "min": 1,
    }


def _proposal_action(
    key: str,
    label: str,
    suffix: str,
    *,
    sequence: int,
    reason_required: bool = False,
) -> dict[str, Any]:
    """Build one confirmed and audited proposal lifecycle action."""

    fields = [_path_id("proposal_id", "提案 ID")]
    if suffix in {"approve", "reject"}:
        fields.append(
            {
                "key": "reason",
                "label": "处理原因",
                "binding": "body",
                "input_type": "textarea",
                "value_type": "string",
                "required": reason_required,
                "max": 1000,
            }
        )
    return {
        "key": key,
        "label": label,
        "endpoint": f"/api/agent-runtime/proposals/<int:proposal_id>/{suffix}/",
        "method": "POST",
        "intent": key.replace("-", "_").replace(".", "_"),
        "risk": "write",
        "audience": "authenticated",
        "effect": "execute",
        "confirmation_required": True,
        "audit_required": True,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": f"{label}，由运行时状态机、权限与 guardrail 再次校验。",
        "source": _SOURCE,
        "task_group": "03 提案审批与执行",
        "sequence": sequence,
        "task_tier": "operation",
        "fields": fields,
        "view_model": {"kind": "detail", "title_path": "proposal.request_id"},
    }


RUNTIME_AGENT_RUNTIME_OPERATOR_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "agent-runtime.operator-summary",
        "label": "智能任务治理总览",
        "endpoint": "/api/agent-runtime/dashboard/summary/",
        "method": "GET",
        "intent": "read_agent_runtime_operator_summary",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "查看任务、提案与待人工处理数量。",
        "source": _SOURCE,
        "task_group": "01 智能任务治理",
        "sequence": 520,
        "task_tier": "support",
        "fields": [],
        "view_model": {"kind": "detail"},
    },
    {
        "key": "agent-runtime.operator-task-list",
        "label": "智能任务队列",
        "endpoint": "/api/agent-runtime/operator/tasks/",
        "method": "GET",
        "intent": "list_agent_runtime_operator_tasks",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "按状态、任务域、搜索词与人工关注标记筛选智能任务。",
        "source": _SOURCE,
        "task_group": "02 任务调查",
        "sequence": 530,
        "task_tier": "operation",
        "fields": [
            {
                "key": "status",
                "label": "任务状态",
                "binding": "query",
                "input_type": "select",
                "value_type": "string",
                "required": False,
                "options": [item.value for item in TaskStatus],
            },
            {
                "key": "task_domain",
                "label": "任务域",
                "binding": "query",
                "input_type": "select",
                "value_type": "string",
                "required": False,
                "options": [item.value for item in TaskDomain],
            },
            {
                "key": "search",
                "label": "搜索",
                "binding": "query",
                "input_type": "text",
                "value_type": "string",
                "required": False,
                "max": 100,
            },
            {
                "key": "attention",
                "label": "仅待人工处理",
                "binding": "query",
                "input_type": "checkbox",
                "value_type": "boolean",
                "required": False,
                "default": False,
            },
        ],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "tasks",
            "columns": [
                {"key": "request_id", "label": "请求编号"},
                {"key": "task_domain", "label": "任务域"},
                {"key": "task_type", "label": "任务类型"},
                {"key": "status", "label": "状态"},
                {"key": "current_step", "label": "当前步骤"},
                {"key": "requires_human", "label": "需要人工"},
                {"key": "updated_at", "label": "更新时间"},
            ],
        },
    },
    {
        "key": "agent-runtime.operator-task-detail",
        "label": "智能任务调查详情",
        "endpoint": "/api/agent-runtime/dashboard/task/<int:task_id>/",
        "method": "GET",
        "intent": "read_agent_runtime_operator_task_detail",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "查看任务、时间线、提案、guardrail 和执行记录。",
        "source": _SOURCE,
        "task_group": "02 任务调查",
        "sequence": 540,
        "task_tier": "operation",
        "fields": [_path_id("task_id", "任务 ID")],
        "view_model": {"kind": "detail", "title_path": "task.request_id"},
    },
    {
        "key": "agent-runtime.operator-proposal-list",
        "label": "提案审批队列",
        "endpoint": "/api/agent-runtime/operator/proposals/",
        "method": "GET",
        "intent": "list_agent_runtime_operator_proposals",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "按状态、审批状态、风险和搜索词筛选提案。",
        "source": _SOURCE,
        "task_group": "03 提案审批与执行",
        "sequence": 550,
        "task_tier": "operation",
        "fields": [
            {
                "key": "status",
                "label": "提案状态",
                "binding": "query",
                "input_type": "select",
                "value_type": "string",
                "required": False,
                "options": [item.value for item in ProposalStatus],
            },
            {
                "key": "approval_status",
                "label": "审批状态",
                "binding": "query",
                "input_type": "select",
                "value_type": "string",
                "required": False,
                "options": [item.value for item in ApprovalStatus],
            },
            {
                "key": "risk_level",
                "label": "风险级别",
                "binding": "query",
                "input_type": "select",
                "value_type": "string",
                "required": False,
                "options": [item.value for item in RiskLevel],
            },
            {
                "key": "search",
                "label": "搜索",
                "binding": "query",
                "input_type": "text",
                "value_type": "string",
                "required": False,
                "max": 100,
            },
        ],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "proposals",
            "columns": [
                {"key": "request_id", "label": "请求编号"},
                {"key": "task", "label": "任务"},
                {"key": "proposal_type", "label": "提案类型"},
                {"key": "status", "label": "状态"},
                {"key": "approval_status", "label": "审批状态"},
                {"key": "risk_level", "label": "风险级别"},
                {"key": "updated_at", "label": "更新时间"},
            ],
        },
    },
    {
        "key": "agent-runtime.operator-proposal-detail",
        "label": "提案与执行证据",
        "endpoint": "/api/agent-runtime/operator/proposals/<int:proposal_id>/",
        "method": "GET",
        "intent": "read_agent_runtime_operator_proposal_detail",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "查看提案正文、guardrail、执行记录和关联任务时间线。",
        "source": _SOURCE,
        "task_group": "03 提案审批与执行",
        "sequence": 560,
        "task_tier": "operation",
        "fields": [_path_id("proposal_id", "提案 ID")],
        "view_model": {"kind": "detail", "title_path": "proposal.request_id"},
    },
    _proposal_action(
        "agent-runtime.operator-submit-proposal",
        "提交提案审批",
        "submit-approval",
        sequence=570,
    ),
    _proposal_action(
        "agent-runtime.operator-approve-proposal",
        "批准提案",
        "approve",
        sequence=580,
    ),
    _proposal_action(
        "agent-runtime.operator-reject-proposal",
        "拒绝提案",
        "reject",
        sequence=590,
        reason_required=True,
    ),
    _proposal_action(
        "agent-runtime.operator-execute-proposal",
        "执行已批准提案",
        "execute",
        sequence=600,
    ),
)
