"""Human-readable projections for the owner fee-correction workflow."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

_POLICY_ACTION = "simulated-trading.fee-correction-policy"
_POLICY_SAVE_ACTION = "simulated-trading.fee-correction-policy-save"
_POLICY_DISABLE_ACTION = "simulated-trading.fee-correction-policy-disable"
_PREVIEW_ACTION = "simulated-trading.fee-correction-preview"
_CONFIRM_ACTION = "simulated-trading.fee-correction-confirm"
_HEAD_ACTION = "simulated-trading.fee-correction-head"
_RECOVER_ACTION = "simulated-trading.fee-correction-recover"
_ASSURANCE_CLASS = "operator_attested_upload"
_ASSURANCE_NOTICE = "费用材料由账户所有者声明，不代表券商或发行方认证。"
_MAX_VISIBLE_MESSAGE_LENGTH = 240


def project_fee_correction_result(
    action_key: str,
    payload: object,
    *,
    http_status: int,
    requested_params: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Project owner policy, preview, confirmation, or readback without private tokens."""

    if type(http_status) is not int or not 100 <= http_status <= 599:
        return _blocked("费用更正", "响应状态无法核对；请重新读取本人账户的费用更正状态。")
    if action_key in {_POLICY_ACTION, _POLICY_SAVE_ACTION, _POLICY_DISABLE_ACTION}:
        return _project_policy(
            action_key,
            payload,
            http_status=http_status,
            requested_params=requested_params,
        )
    if action_key == _PREVIEW_ACTION:
        return _project_preview(payload, http_status=http_status, requested_params=requested_params)
    if action_key == _CONFIRM_ACTION:
        return _project_confirmation(
            payload,
            http_status=http_status,
            requested_params=requested_params,
        )
    if action_key == _RECOVER_ACTION:
        if (
            requested_params is None
            or _source_locator(requested_params.get("source_locator")) is None
        ):
            return _blocked("费用更正结果", "请输入原预览中保存的费用材料编号。")
        return _project_head(payload, http_status=http_status, requested_params=requested_params)
    if action_key == _HEAD_ACTION:
        return _project_head(payload, http_status=http_status, requested_params=requested_params)
    return _blocked("费用更正", "无法识别这项费用更正操作。")


def _project_policy(
    action_key: str,
    payload: object,
    *,
    http_status: int,
    requested_params: Mapping[str, object] | None,
) -> dict[str, object]:
    """Display validated policy state and build exact versioned follow-up inputs."""

    if not 200 <= http_status < 300:
        return _transport_failure("费用材料策略", http_status, write=action_key != _POLICY_ACTION)
    response = _as_mapping(payload)
    policy = _as_mapping(response.get("policy")) if response is not None else None
    if response is None or response.get("success") is not True or policy is None:
        return _blocked("费用材料策略", "未取得完整的本人费用材料策略状态。")

    account_id = _positive_int(policy.get("account_id"))
    version = _nonnegative_int(policy.get("version"))
    enabled = policy.get("enabled")
    allows_attested = policy.get("allow_operator_attested_upload")
    currency = policy.get("ledger_currency")
    valid_from_valid, valid_from = _optional_aware_timestamp(policy, "valid_from")
    valid_until_valid, valid_until = _optional_aware_timestamp(policy, "valid_until")
    if (
        account_id is None
        or version is None
        or type(enabled) is not bool
        or type(allows_attested) is not bool
        or not isinstance(currency, str)
        or policy.get("assurance_class") != _ASSURANCE_CLASS
        or not valid_from_valid
        or not valid_until_valid
        or (enabled or allows_attested)
        and not currency
        or not _requested_scope_matches(requested_params, "account_id", account_id)
    ):
        return _blocked("费用材料策略", "策略状态或其有效期无法核对。")

    status = "材料策略已启用" if enabled else "材料策略已停用"
    fields = [
        _field("account_id", "账户编号", str(account_id)),
        _field("policy_status", "费用材料", status),
        _field(
            "operator_attested_upload",
            "所有者声明材料",
            "允许" if allows_attested else "不允许",
        ),
        _field(
            "ledger_currency",
            "账本币种",
            currency if currency else "未设置（停用状态可为空）",
        ),
        _field("assurance", "材料来源声明", "账户所有者声明；未经券商或发行方认证。"),
    ]
    if valid_from is not None:
        fields.append(_field("valid_from", "开始时间", valid_from))
    if valid_until is not None:
        fields.append(_field("valid_until", "结束时间", valid_until))

    next_steps: list[dict[str, object]] = []
    if action_key == _POLICY_ACTION:
        next_steps.append(
            {
                "label": "设置费用材料策略",
                "action_key": _POLICY_SAVE_ACTION,
                "params": {
                    "account_id": account_id,
                    "expected_version": version,
                    "ledger_currency": currency,
                    "valid_from": valid_from,
                    "valid_until": valid_until,
                },
                "hint": "启用和材料许可须明确选择；启用时填写已有账本币种并确认材料声明。",
            }
        )
        if enabled or allows_attested:
            next_steps.append(
                {
                    "label": "停用费用材料策略",
                    "action_key": _POLICY_DISABLE_ACTION,
                    "params": {
                        "account_id": account_id,
                        "expected_version": version,
                        "enabled": False,
                        "allow_operator_attested_upload": False,
                        "ledger_currency": currency,
                        "valid_from": valid_from,
                        "valid_until": valid_until,
                        "attestation_acknowledged": False,
                    },
                    "hint": "停用会保留当前账本币种和有效期，并在提交前再次确认。",
                }
            )
    elif action_key in {_POLICY_SAVE_ACTION, _POLICY_DISABLE_ACTION}:
        next_steps.append(
            {
                "label": "重新读取费用材料策略",
                "action_key": _POLICY_ACTION,
                "params": {"account_id": account_id},
                "hint": "确认保存后的策略和有效期。",
            }
        )

    if not enabled:
        summary = "材料策略已停用；费用更正不会被允许。"
    elif not allows_attested:
        summary = "材料策略已启用，但尚未允许所有者声明材料；当前不能进行费用更正。"
    else:
        summary = "材料策略已启用；所有者声明材料仍须逐笔核对并二次确认。"
    return {
        "kind": "detail",
        "title": "费用材料策略",
        "status": status,
        "outcome": "success",
        "fields": fields,
        "nested": [],
        "business_summary": summary,
        "blocking_reason": "",
        "next_steps": next_steps,
        "assurance_notice": _ASSURANCE_NOTICE,
    }


def _project_preview(
    payload: object,
    *,
    http_status: int,
    requested_params: Mapping[str, object] | None,
) -> dict[str, object]:
    """Display exact preview amounts and source clocks, never its private handoff."""

    if not 200 <= http_status < 300:
        return _transport_failure("费用更正预览", http_status, write=True)
    response = _as_mapping(payload)
    if response is None or response.get("success") is not True:
        return _blocked("费用更正预览", "没有取得可核对的费用预览。")

    status = response.get("status")
    outcome = response.get("outcome")
    if status == "already_applied":
        receipt = _validated_receipt(
            response.get("receipt"),
            requested_params=requested_params,
            require_replay=True,
        )
        if outcome != "noop" or response.get("preview") is not None or receipt is None:
            return _blocked("费用更正预览", "原请求回执与已入账状态无法核对。")
        return {
            "kind": "detail",
            "title": "费用更正结果",
            "status": "已入账；无需再次确认",
            "outcome": "noop",
            "fields": [
                _field("account_id", "账户编号", str(receipt["account_id"])),
                _field("trade_id", "成交编号", str(receipt["trade_id"])),
                _field("posting", "处理状态", "原请求已入账，无需重复提交。"),
            ],
            "nested": [],
            "business_summary": "原费用更正已入账，不会再次执行。",
            "blocking_reason": "",
            "next_steps": [],
        }

    if status != "preview" or outcome != "success" or response.get("receipt") is not None:
        return _blocked("费用更正预览", "本次响应既不属于待确认预览，也没有可核对的原回执。")
    preview = _as_mapping(response.get("preview"))
    if preview is None:
        return _blocked("费用更正预览", "费用明细不完整，未提供可核对的预览。")
    account_id = _positive_int(preview.get("account_id"))
    trade_id = _positive_int(preview.get("trade_id"))
    asset_code = _nonempty_text(preview.get("asset_code"))
    currency = _nonempty_text(preview.get("ledger_currency"))
    source_locator = _source_locator(preview.get("source_locator"))
    if (
        account_id is None
        or trade_id is None
        or asset_code is None
        or currency is None
        or source_locator is None
        or preview.get("assurance_class") != _ASSURANCE_CLASS
        or not _requested_scope_matches(requested_params, "account_id", account_id)
        or not _requested_scope_matches(requested_params, "trade_id", trade_id)
        or _nonnegative_int(preview.get("expected_revision")) is None
        or not _optional_positive_int(preview.get("expected_predecessor_id"))
        or not all(
            _nonempty_text(preview.get(key)) is not None
            for key in ("source_locator", "content_sha256", "payload_sha256")
        )
    ):
        return _blocked("费用更正预览", "账户、成交、材料来源或版本状态无法核对。")

    source_time = _aware_timestamp(preview.get("source_observed_at"))
    verified_at = _aware_timestamp(preview.get("verified_at"))
    stored_at = _aware_timestamp(preview.get("stored_at"))
    as_of = _aware_timestamp(preview.get("as_of"))
    previous = _fee_components(preview.get("previous_fee_components"))
    revised = _fee_components(preview.get("revised_fee_components"))
    delta = _fee_delta(preview.get("delta"))
    if any(
        value is None
        for value in (source_time, verified_at, stored_at, as_of, previous, revised, delta)
    ):
        return _blocked("费用更正预览", "费用金额或原始时间信息不完整，尚不能确认。")

    previous_values = previous or {}
    revised_values = revised or {}
    delta_values = delta or {}
    fields = [
        _field("account_id", "账户编号", str(account_id)),
        _field("trade_id", "成交编号", str(trade_id)),
        {
            **_field("source_locator", "费用材料编号（请保存）", source_locator),
            "presentation": "copyable",
        },
        _field("asset_code", "证券", asset_code),
        _field("ledger_currency", "账本币种", currency),
        _field("previous_commission", "原佣金", previous_values["commission"]),
        _field("revised_commission", "调整后佣金", revised_values["commission"]),
        _field("previous_transfer_fee", "原过户费", previous_values["transfer_fee"]),
        _field("revised_transfer_fee", "调整后过户费", revised_values["transfer_fee"]),
        _field("previous_stamp_duty", "原印花税", previous_values["stamp_duty"]),
        _field("revised_stamp_duty", "调整后印花税", revised_values["stamp_duty"]),
        _field("total_fee_delta", "费用合计差额", delta_values["total_fee_delta"]),
        _field("cash_delta", "现金变化", delta_values["cash_delta"]),
        _field("source_observed_at", "来源观测时间", source_time or ""),
        _field("verified_at", "核验时间", verified_at or ""),
        _field("stored_at", "材料保存时间", stored_at or ""),
        _field("as_of", "本次核对时间", as_of or ""),
        _field("assurance", "材料来源声明", "账户所有者声明；未经券商或发行方认证。"),
    ]
    return {
        "kind": "detail",
        "title": "费用更正预览",
        "status": "预览完成；尚未入账",
        "outcome": "success",
        "fields": fields,
        "nested": [],
        "business_summary": (
            "费用材料已保存并核对，尚未改变成交费用或现金。请核对原费用、调整后费用、"
            "现金变化及材料声明，再使用本次预览提供的确认操作。"
            "请复制保存费用材料编号；刷新或重开页面后，可凭编号找回原请求结果。"
        ),
        "blocking_reason": "",
        "next_steps": [],
        "assurance_notice": _ASSURANCE_NOTICE,
    }


def _project_confirmation(
    payload: object,
    *,
    http_status: int,
    requested_params: Mapping[str, object] | None,
) -> dict[str, object]:
    """Show posting completion only when the returned receipt matches the target trade."""

    if not 200 <= http_status < 300:
        return _transport_failure("费用更正确认", http_status, write=True)
    response = _as_mapping(payload)
    if response is None or response.get("success") is not True:
        return _blocked("费用更正确认", "没有取得可核对的费用更正回执。")
    receipt = _validated_receipt(response.get("receipt"), requested_params=requested_params)
    if receipt is None:
        return _blocked("费用更正确认", "费用更正回执与所选账户或成交不一致。")
    replayed = receipt["replayed"]
    return {
        "kind": "detail",
        "title": "费用更正结果",
        "status": "原请求已核对" if replayed else "费用更正已入账",
        "outcome": "success",
        "fields": [
            _field("account_id", "账户编号", str(receipt["account_id"])),
            _field("trade_id", "成交编号", str(receipt["trade_id"])),
            _field(
                "posting", "处理状态", "原请求已入账，无需重复提交。" if replayed else "已入账。"
            ),
        ],
        "nested": [],
        "business_summary": (
            "费用更正已按原预览入账；没有重复修改成交。" if replayed else "费用更正已入账。"
        ),
        "blocking_reason": "",
        "next_steps": [],
    }


def _project_head(
    payload: object,
    *,
    http_status: int,
    requested_params: Mapping[str, object] | None,
) -> dict[str, object]:
    """Distinguish an unresolved keyed readback from a matching posted receipt."""

    if not 200 <= http_status < 300:
        return _transport_failure("费用更正结果", http_status)
    response = _as_mapping(payload)
    head = _as_mapping(response.get("head")) if response is not None else None
    if (
        response is None
        or response.get("success") is not True
        or response.get("outcome") not in {"success", "partial"}
        or head is None
    ):
        return _blocked("费用更正结果", "没有取得可核对的费用更正状态。")

    account_id = _positive_int(head.get("account_id"))
    trade_id = _positive_int(head.get("trade_id"))
    as_of = _aware_timestamp(head.get("as_of"))
    revision = _nonnegative_int(head.get("revision"))
    predecessor = _optional_positive_int(head.get("expected_predecessor_id"))
    if (
        account_id is None
        or trade_id is None
        or as_of is None
        or revision is None
        or not predecessor
        or (revision == 0) != (head.get("expected_predecessor_id") is None)
        or not _requested_scope_matches(requested_params, "account_id", account_id)
        or not _requested_scope_matches(requested_params, "trade_id", trade_id)
    ):
        return _blocked("费用更正结果", "账户、成交或读取时间无法核对。")

    receipt_value = head.get("request_receipt")
    if response.get("outcome") == "partial":
        if receipt_value is not None:
            return _blocked("费用更正结果", "待核对状态包含了不一致的回执。")
        return {
            "kind": "message",
            "title": "费用更正结果",
            "status": "结果仍待核对",
            "outcome": "partial",
            "message": "尚未找到原请求回执；结果仍未确认，请保留原请求，不要另建请求重复提交。",
            "fields": [
                _field("account_id", "账户编号", str(account_id)),
                _field("trade_id", "成交编号", str(trade_id)),
                _field("as_of", "读取时间", as_of),
            ],
            "nested": [],
            "business_summary": "本次查询尚未确认原请求结果。",
            "blocking_reason": "原请求仍未得到可核对回执；请使用原请求继续读取结果。",
            "next_steps": [],
        }

    if receipt_value is None:
        if requested_params is not None and requested_params.get("source_locator") is not None:
            return _blocked("费用更正结果", "尚未取得原材料对应的入账回执；不要重复提交。")
        return {
            "kind": "detail",
            "title": "费用更正状态",
            "status": "已读取当前费用更正状态",
            "outcome": "success",
            "fields": [
                _field("account_id", "账户编号", str(account_id)),
                _field("trade_id", "成交编号", str(trade_id)),
                _field("as_of", "读取时间", as_of),
            ],
            "nested": [],
            "business_summary": "已读取本人账户中所选成交的费用更正状态。",
            "blocking_reason": "",
            "next_steps": [],
        }

    receipt = _validated_receipt(
        receipt_value,
        requested_params=requested_params,
        require_replay=requested_params is not None
        and requested_params.get("source_locator") is not None,
    )
    if receipt is None or receipt["account_id"] != account_id or receipt["trade_id"] != trade_id:
        return _blocked("费用更正结果", "读取到的回执与本人所选成交不一致。")
    return {
        "kind": "detail",
        "title": "费用更正结果",
        "status": "已核对原请求",
        "outcome": "success",
        "fields": [
            _field("account_id", "账户编号", str(account_id)),
            _field("trade_id", "成交编号", str(trade_id)),
            _field("posting", "处理状态", "原请求已入账，无需重复提交。"),
            _field("as_of", "读取时间", as_of),
        ],
        "nested": [],
        "business_summary": "已找到原请求对应的入账回执。",
        "blocking_reason": "",
        "next_steps": [],
    }


def _validated_receipt(
    value: object,
    *,
    requested_params: Mapping[str, object] | None,
    require_replay: bool = False,
) -> dict[str, int | bool] | None:
    """Narrow a receipt to the minimum safe account, trade and replay facts."""

    receipt = _as_mapping(value)
    if receipt is None:
        return None
    event_id = _positive_int(receipt.get("event_id"))
    account_id = _positive_int(receipt.get("account_id"))
    trade_id = _positive_int(receipt.get("trade_id"))
    revision = _positive_int(receipt.get("revision"))
    payload_hash = _nonempty_text(receipt.get("payload_hash"))
    replayed = receipt.get("replayed")
    if (
        event_id is None
        or account_id is None
        or trade_id is None
        or revision is None
        or payload_hash is None
        or type(replayed) is not bool
        or require_replay
        and replayed is not True
        or not _requested_scope_matches(requested_params, "account_id", account_id)
        or not _requested_scope_matches(requested_params, "trade_id", trade_id)
    ):
        return None
    return {
        "event_id": event_id,
        "account_id": account_id,
        "trade_id": trade_id,
        "replayed": replayed,
    }


def _fee_components(value: object) -> dict[str, str] | None:
    """Validate three API decimal strings without converting them to floats."""

    source = _as_mapping(value)
    if source is None:
        return None
    fields: dict[str, str] = {}
    for key in ("commission", "transfer_fee", "stamp_duty"):
        text = _decimal_text(source.get(key))
        if text is None:
            return None
        fields[key] = text
    return fields


def _fee_delta(value: object) -> dict[str, str] | None:
    """Validate fee deltas and preserve the owner's exact decimal strings."""

    source = _as_mapping(value)
    if source is None:
        return None
    fields: dict[str, str] = {}
    for key in (
        "commission",
        "transfer_fee",
        "stamp_duty",
        "total_fee_delta",
        "cash_delta",
    ):
        text = _decimal_text(source.get(key))
        if text is None:
            return None
        fields[key] = text
    return fields


def _decimal_text(value: object) -> str | None:
    """Accept finite decimal text while retaining its exact wire representation."""

    if not isinstance(value, str) or not value or value != value.strip():
        return None
    try:
        decimal_value = Decimal(value)
    except InvalidOperation:
        return None
    return value if decimal_value.is_finite() else None


def _optional_aware_timestamp(mapping: Mapping[str, object], key: str) -> tuple[bool, str | None]:
    """Preserve explicit null policy dates and reject missing or naive timestamps."""

    if key not in mapping:
        return False, None
    value = mapping[key]
    if value is None:
        return True, None
    timestamp = _aware_timestamp(value)
    if timestamp is None:
        return False, None
    return True, timestamp


def _aware_timestamp(value: object) -> str | None:
    """Return an aware ISO timestamp without inventing a timezone or current time."""

    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return value


def _requested_scope_matches(
    requested_params: Mapping[str, object] | None,
    key: str,
    value: int,
) -> bool:
    """Check a returned identity against any explicitly supplied path parameter."""

    if requested_params is None or key not in requested_params:
        return True
    requested = _positive_int(requested_params[key])
    return requested is not None and requested == value


def _as_mapping(value: object) -> Mapping[str, object] | None:
    """Narrow one decoded JSON object without assuming a mutable dict."""

    if not isinstance(value, Mapping):
        return None
    return value


def _positive_int(value: object) -> int | None:
    """Accept a positive JSON integer or an ASCII path integer, but not bools."""

    if type(value) is int:
        return value if value > 0 else None
    if type(value) is str and value.isascii() and value.isdigit():
        try:
            parsed = int(value)
        except (ValueError, OverflowError):
            return None
        return parsed if parsed > 0 else None
    return None


def _nonnegative_int(value: object) -> int | None:
    """Accept a non-negative JSON integer and reject booleans and decimal strings."""

    return value if type(value) is int and value >= 0 else None


def _optional_positive_int(value: object) -> bool:
    """Validate an explicitly nullable predecessor ID without treating it as a default."""

    return value is None or _positive_int(value) is not None


def _nonempty_text(value: object) -> str | None:
    """Return nonempty trimmed text only when the original string has no padding."""

    if not isinstance(value, str) or not value or value != value.strip():
        return None
    return value


def _source_locator(value: object) -> str | None:
    """Accept only the canonical public material identifier, never a private handoff."""

    if type(value) is not str:
        return None
    try:
        return value if str(UUID(value)) == value else None
    except ValueError:
        return None


def _field(key: str, label: str, value: str) -> dict[str, str]:
    """Build one display-only field from already validated text."""

    return {"key": key, "label": label, "value": value}


def _transport_failure(
    kind: str,
    http_status: int,
    *,
    write: bool = False,
) -> dict[str, object]:
    """Translate transport failures into bounded owner-facing status copy."""

    if http_status in {401, 403}:
        return _blocked(kind, "当前登录用户没有访问此账户费用记录的权限。")
    if http_status == 404:
        return _blocked(kind, "本人账户或所选成交不存在或当前不可用。")
    if http_status >= 500:
        message = (
            "提交结果暂不能确认。请保留原请求，先读取费用材料策略或按原请求核对结果；"
            "不要另建请求重复提交。"
            if write
            else "当前无法读取费用更正状态；请稍后重新读取。"
        )
        reason = "提交结果尚未确认。" if write else "读取操作未取得可核对结果。"
        return {
            "kind": "message",
            "title": kind,
            "status": "结果待核对",
            "outcome": "failed",
            "message": message,
            "business_summary": "当前没有新的可核对结果。",
            "blocking_reason": reason,
            "fields": [],
            "nested": [],
            "next_steps": [],
            "debug_hidden_fields": [],
        }
    return _blocked(kind, "本次请求未完成；请核对账户和成交后重新读取。")


def _blocked(title: str, message: str) -> dict[str, object]:
    """Return a generic bounded result that never copies raw API details."""

    safe_message = message[:_MAX_VISIBLE_MESSAGE_LENGTH]
    return {
        "kind": "message",
        "title": title,
        "status": "结果待核对",
        "outcome": "blocked",
        "message": safe_message,
        "business_summary": safe_message,
        "blocking_reason": "没有取得完整、可核对的费用更正结果。",
        "fields": [],
        "nested": [],
        "next_steps": [],
        "debug_hidden_fields": [],
    }


__all__: tuple[str, ...] = ("project_fee_correction_result",)
