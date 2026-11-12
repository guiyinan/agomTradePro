"""Safe user-facing projection for ordinary-owner simulated action consent."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import TypedDict, TypeGuard, cast

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA as _V1_GRANT_SCHEMA,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA as _V2_GRANT_SCHEMA,
)

CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY = "simulated-trading.corporate-action-consent-prepare"
CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY = "simulated-trading.corporate-action-consent-confirm"
CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY = (
    "simulated-trading.corporate-action-consent-withdraw-prepare"
)
CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY = "simulated-trading.corporate-action-consent-withdraw"

_ACTION_TITLES: dict[str, str] = {
    CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY: "模拟公司行为授权确认资料",
    CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY: "模拟公司行为授权结果",
    CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY: "模拟授权撤回确认资料",
    CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY: "模拟公司行为授权撤回结果",
}
_ACCOUNT_ID_PATTERN = re.compile(r"[1-9][0-9]*\Z")
_TIMESTAMP_SUFFIX_PATTERN = re.compile(r"(?:Z|[+-][0-9]{2}:[0-9]{2})\Z")
_RESPONSE_FIELDS = frozenset(
    {
        "account_id",
        "outcome",
        "consent_status",
        "summary",
        "blocking_reason",
        "source_observed_at",
        "source_valid_until",
        "consent_valid_until",
        "consent_token",
        "withdrawal_token",
        "grant_id",
        "grant_version",
        "grant_content_hash",
        "must_not_execute",
    }
)
_VERSIONED_RESPONSE_FIELDS = _RESPONSE_FIELDS | frozenset(
    {
        "grant_schema",
        "selected_capabilities",
        "capability_labels",
        "terms_version",
        "terms_sha256",
        "terms_text",
    }
)
_CAPABILITY_CODES = tuple(
    sorted(
        (
            SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE.value,
            SimulatedCorporateActionWriteCapability.TAX_ASSESS.value,
            SimulatedCorporateActionWriteCapability.TAX_WITHHOLD.value,
        )
    )
)
_TERMS_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,191}\Z")
_TERMS_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_SIMULATION_NOTICE = (
    "现金分红模拟权益和支付日模拟到账均为模拟结果。此操作只保存或撤回授权，"
    "不会实际入账，也不证明银行已经到账。"
)
_V2_SIMULATION_NOTICE = (
    "现金分红模拟权益和支付日模拟到账均为模拟结果。本次操作只保存或撤回所选授权；"
    "现在不会评估税额、扣缴模拟资金、模拟入账或下单，也不证明银行已经到账。"
)
_OUTCOME_TEXT: dict[str, str] = {"success": "已完成", "noop": "无需变更", "blocked": "当前受阻"}
_CONSENT_STATUS_TEXT: dict[str, str] = {
    "not_consented": "尚未授权",
    "awaiting_confirmation": "等待本人明确同意",
    "active": "授权有效",
    "already_current": "已有有效授权",
    "expired": "授权已过期，仍可撤回记录",
    "stored": "保留的历史授权，可撤回",
    "revoked": "授权已撤回",
}
_REASON_TEXT: dict[str, str] = {
    "simulated_action_account_mapping_unavailable": "账户来源资料缺失或不唯一，请重新核对。",
    "simulated_action_account_mapping_changed": "账户与来源资料的对应关系已变化，请重新核对。",
    "simulated_action_trading_role_required": "当前角色不能新增授权，仍可撤回已有授权。",
    "simulated_action_account_source_refresh_required": "账户来源资料已过期或与当前状态不符，请刷新后重试。",
    "simulated_action_source_expired": "来源资料已过期，请重新读取核对。",
    "simulated_action_consent_basis_changed": "授权依据已变化，请重新读取后再单独确认。",
    "simulated_action_service_policy_unavailable": "模拟授权服务尚未启用或暂不可用。已有授权仍可撤回。",
    "simulated_action_consent_request_unavailable": "授权服务暂不可用，请稍后重新读取。",
}


def _reason_text(reason: str) -> str:
    """Keep stable diagnostic codes outside ordinary account copy."""
    return _REASON_TEXT.get(reason, "授权资料未通过核对，请重新读取后重试。")


class _ConsentResponse(TypedDict):
    """Normalized exact JSON fields returned by the consent owner composition."""

    account_id: int
    outcome: str
    consent_status: str
    summary: str
    blocking_reason: str | None
    source_observed_at: str | None
    source_valid_until: str | None
    consent_valid_until: str | None
    consent_token: str | None
    withdrawal_token: str | None
    grant_id: str | None
    grant_version: str | None
    grant_content_hash: str | None
    grant_schema: str | None
    selected_capabilities: list[str]
    capability_labels: list[str]
    terms_version: str | None
    terms_sha256: str | None
    terms_text: str
    must_not_execute: bool


def _is_string_keyed_object(value: object) -> TypeGuard[dict[str, object]]:
    """Narrow one exact JSON object without accepting mapping-like substitutes."""

    return type(value) is dict and all(
        type(key) is str for key in cast(dict[object, object], value)
    )


def _bounded_text(value: object, *, maximum: int) -> str | None:
    """Accept bounded, trimmed display text without control characters."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 and character not in "\n\t" for character in value)
    ):
        return None
    return value


def _valid_optional_timestamp(value: object) -> bool:
    """Require an explicit timezone-aware ISO timestamp or null."""

    if value is None:
        return True
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or _TIMESTAMP_SUFFIX_PATTERN.search(value) is None
    ):
        return False
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _narrow_response(
    value: object, *, allow_unavailable_withdrawal_terms: bool = False
) -> _ConsentResponse | None:
    """Validate either exact legacy or expanded payload without exposing credentials."""

    if not _is_string_keyed_object(value):
        return None
    response_fields = frozenset(value)
    if response_fields not in {_RESPONSE_FIELDS, _VERSIONED_RESPONSE_FIELDS}:
        return None
    account_id = value["account_id"]
    outcome = value["outcome"]
    consent_status = value["consent_status"]
    summary = value["summary"]
    blocking_reason = value["blocking_reason"]
    source_observed_at = value["source_observed_at"]
    source_valid_until = value["source_valid_until"]
    consent_valid_until = value["consent_valid_until"]
    grant_id = value["grant_id"]
    grant_version = value["grant_version"]
    grant_content_hash = value["grant_content_hash"]

    if (
        type(account_id) is not int
        or account_id <= 0
        or type(outcome) is not str
        or outcome not in {"success", "noop", "blocked"}
        or _bounded_text(consent_status, maximum=96) is None
        or _bounded_text(summary, maximum=1000) is None
        or (blocking_reason is not None and _bounded_text(blocking_reason, maximum=160) is None)
        or not _valid_optional_timestamp(source_observed_at)
        or not _valid_optional_timestamp(source_valid_until)
        or not _valid_optional_timestamp(consent_valid_until)
        or any(
            field is not None and _bounded_text(field, maximum=192) is None
            for field in (grant_id, grant_version, grant_content_hash)
        )
        or value["consent_token"] is not None
        or value["withdrawal_token"] is not None
        or type(value["must_not_execute"]) is not bool
        or value["must_not_execute"] is not True
        or (outcome == "blocked") != (blocking_reason is not None)
    ):
        return None
    normalized = dict(value)
    if response_fields == _RESPONSE_FIELDS:
        normalized.update(
            {
                "grant_schema": None,
                "selected_capabilities": [],
                "capability_labels": [],
                "terms_version": None,
                "terms_sha256": None,
                "terms_text": "",
            }
        )
    if not _valid_capability_terms_fields(
        normalized, allow_unavailable_withdrawal_terms=allow_unavailable_withdrawal_terms
    ):
        return None
    return cast(_ConsentResponse, normalized)


def _valid_capability_terms_fields(
    value: dict[str, object], *, allow_unavailable_withdrawal_terms: bool
) -> bool:
    """Require known ordered capability codes and a safe schema-specific terms shape."""
    grant_schema = value["grant_schema"]
    selected = value["selected_capabilities"]
    labels = value["capability_labels"]
    version = value["terms_version"]
    digest = value["terms_sha256"]
    text = value["terms_text"]
    if (
        (
            grant_schema is not None
            and (
                type(grant_schema) is not str
                or grant_schema not in {_V1_GRANT_SCHEMA, _V2_GRANT_SCHEMA}
            )
        )
        or type(selected) is not list
        or type(labels) is not list
        or type(text) is not str
        or len(text) > 10000
        or (text and _bounded_text(text, maximum=10000) is None)
    ):
        return False
    selected_values = cast(list[object], selected)
    label_values = cast(list[object], labels)
    if any(type(item) is not str or item not in _CAPABILITY_CODES for item in selected_values):
        return False
    selected_codes = tuple(cast(str, item) for item in selected_values)
    if selected_codes != tuple(sorted(set(selected_codes))):
        return False
    if grant_schema in {None, _V1_GRANT_SCHEMA}:
        return (
            not selected_codes
            and not label_values
            and version is None
            and digest is None
            and text == ""
        )
    if not selected_codes:
        return False
    incomplete_blocked_terms = (
        (
            value["outcome"] == "blocked"
            or (
                allow_unavailable_withdrawal_terms
                and value["consent_status"] in {"stored", "expired", "revoked"}
            )
        )
        and not label_values
        and version is None
        and digest is None
        and text == ""
    )
    if incomplete_blocked_terms:
        return True
    if len(label_values) != len(selected_codes) or any(
        _bounded_text(item, maximum=160) is None for item in label_values
    ):
        return False
    return (
        type(version) is str
        and _TERMS_VERSION_PATTERN.fullmatch(version) is not None
        and type(digest) is str
        and _TERMS_SHA256_PATTERN.fullmatch(digest) is not None
        and _bounded_text(text, maximum=10000) is not None
    )


def _requested_account_id(requested_params: Mapping[str, object] | None) -> int | None:
    """Accept one exact positive account path value from this request."""

    if requested_params is None:
        return None
    value = requested_params.get("account_id")
    if type(value) is int and value > 0:
        return value
    if type(value) is str and _ACCOUNT_ID_PATTERN.fullmatch(value) is not None:
        return int(value)
    return None


def _field(key: str, label: str, value: str) -> dict[str, str]:
    """Build one ordinary non-copyable detail field."""

    return {"key": key, "label": label, "value": value}


def _blocked(title: str, reason: str) -> dict[str, object]:
    """Return a bounded failure result with no raw response or credential values."""

    fields = [_field("blocking_reason", "处理说明", _reason_text(reason))]
    return {
        "kind": "detail",
        "title": title,
        "status": "资料未通过核对",
        "outcome": "blocked",
        "fields": fields,
        "nested": [],
        "business_summary": _SIMULATION_NOTICE,
        "blocking_reason": reason,
        "next_steps": [],
    }


def _action_status(action_key: str, outcome: str) -> str:
    """Return a bounded display status for one consent operation."""

    if outcome == "blocked":
        return "当前受阻"
    if outcome == "noop":
        if action_key == CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY:
            return "已有有效授权，无需重复同意"
        if action_key == CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY:
            return "没有待撤回授权"
        if action_key == CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY:
            return "授权已存在，无需重复保存"
        return "没有待撤回授权"
    if action_key == CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY:
        return "资料已准备，等待单独确认"
    if action_key == CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY:
        return "授权记录已保存"
    if action_key == CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY:
        return "撤回资料已准备，等待单独确认"
    return "授权撤回已保存"


def project_simulated_corporate_action_consent_result(
    action_key: str,
    payload: object,
    *,
    http_status: int,
    requested_params: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Project consent results after exact account, clock, and token checks."""

    title = _ACTION_TITLES.get(action_key)
    if title is None:
        return _blocked("模拟公司行为授权", "simulated_action_consent_action_unknown")
    if type(http_status) is not int or not 100 <= http_status <= 599:
        return _blocked(title, "simulated_action_consent_http_status_invalid")
    if not 200 <= http_status < 300:
        return _blocked(
            title,
            "simulated_action_consent_request_unavailable",
        )

    response = _narrow_response(
        payload,
        allow_unavailable_withdrawal_terms=action_key
        in {
            CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY,
            CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY,
        },
    )
    request_account_id = _requested_account_id(requested_params)
    if response is None:
        return _blocked(title, "simulated_action_consent_response_invalid")
    if request_account_id is None or response["account_id"] != request_account_id:
        return _blocked(title, "simulated_action_consent_account_scope_mismatch")

    source_observed_at = response["source_observed_at"] or "未知"
    source_valid_until = response["source_valid_until"] or "未知"
    consent_valid_until = response["consent_valid_until"] or "未建立或未提供"
    blocking_reason = (
        _reason_text(response["blocking_reason"]) if response["blocking_reason"] else "无"
    )
    fields = [
        _field("account_id", "账户编号", str(response["account_id"])),
        _field("outcome", "处理结果", _OUTCOME_TEXT[response["outcome"]]),
        _field(
            "consent_status",
            "当前授权状态",
            _CONSENT_STATUS_TEXT.get(response["consent_status"], "待核对"),
        ),
        _field("summary", "处理摘要", response["summary"]),
        _field("source_observed_at", "来源观测时间", source_observed_at),
        _field("source_valid_until", "来源有效期", source_valid_until),
        _field("consent_valid_until", "同意期限", consent_valid_until),
        _field("blocking_reason", "阻断原因", blocking_reason),
    ]
    business_notice = _SIMULATION_NOTICE
    if response["grant_schema"] == _V2_GRANT_SCHEMA:
        business_notice = _V2_SIMULATION_NOTICE
        labels = response["capability_labels"]
        if labels:
            fields.append(_field("selected_capabilities", "所选模拟能力", "、".join(labels)))
        elif response["selected_capabilities"]:
            fields.append(
                _field(
                    "selected_capabilities",
                    "授权范围核对",
                    "现有授权范围暂无法核对；本结果不表示授权当前可用。",
                )
            )
        if response["terms_text"]:
            fields.append(_field("terms_text", "完整授权条款", response["terms_text"]))
    return {
        "kind": "detail",
        "title": title,
        "status": _action_status(action_key, response["outcome"]),
        "outcome": response["outcome"],
        "fields": fields,
        "nested": [],
        "business_summary": f"{response['summary']} {business_notice}",
        "blocking_reason": response["blocking_reason"] or "",
        "next_steps": [],
    }


__all__: tuple[str, ...] = (
    "CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY",
    "CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY",
    "CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY",
    "CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY",
    "project_simulated_corporate_action_consent_result",
)
