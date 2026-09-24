"""Safe public explanations for the global decision-runtime gate."""

from __future__ import annotations

PUBLIC_DECISION_RUNTIME_BLOCK_DETAILS = {
    "maintenance": (
        "系统正在维护决策数据，当前结果不可用于投资决策。请等待维护完成后重试。",
        "等待系统维护完成后重试",
        "系统运维",
    ),
    "validating": (
        "系统正在校验最新数据，当前结果不可用于投资决策。请等待校验完成后重试。",
        "等待数据校验完成后重试",
        "数据运维",
    ),
    "blocked": (
        "系统决策链路当前被安全阻断，结果不可用于投资决策。请等待管理员完成核查。",
        "等待管理员核查并恢复决策服务",
        "系统管理员",
    ),
}


def get_public_decision_runtime_block_details(status: str) -> tuple[str, str, str]:
    """Return stable public guidance without exposing internal audit diagnostics."""

    return PUBLIC_DECISION_RUNTIME_BLOCK_DETAILS.get(
        status,
        (
            "系统决策状态异常，当前结果不可用于投资决策。请等待管理员完成核查。",
            "等待管理员核查系统状态",
            "系统管理员",
        ),
    )
