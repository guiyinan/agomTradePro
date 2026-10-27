"""Bind account-preview price presentation to its requested reference basis."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from uuid import UUID

_PublicationIdentity = tuple[
    str,
    str,
    str,
    str,
    str,
    datetime,
    datetime,
    datetime,
    date,
    datetime,
    str,
]
_PUBLICATION_HASH = re.compile(r"^[0-9a-f]{64}$")
_CLOSE_BLOCK_REASONS = frozenset(
    {
        "M1_REFERENCE_CLOSE_CALENDAR_UNAVAILABLE",
        "M1_REFERENCE_PUBLICATION_BLOCKED",
        "M1_REFERENCE_PUBLICATION_SCOPE_INVALID",
        "M1_REFERENCE_CLOSE_ROW_INVALID",
        "M1_REFERENCE_CLOSE_DATE_NOT_CURRENT",
        "M1_REFERENCE_PUBLICATION_MIXED",
        "M1_REFERENCE_CLOSE_READER_UNAVAILABLE",
        "M1_REFERENCE_CLOSE_RESULT_INVALID",
        "M1_REFERENCE_PRICE_BASIS_INVALID",
    }
)
_BASIS_LABELS = {
    "market": "当前市场参考价（仅本次只读预览）",
    "published_close": "已核验日终收盘价（仅本次只读预览）",
}
_FRESHNESS_LABELS = {
    "fresh": "已核验",
    "latest_completed_session": "最近已完成交易时段",
}


def project_reference_price_context(
    view_model: dict[str, object],
    payload: object,
    request_params: Mapping[str, object] | None,
) -> dict[str, object]:
    """Show the chosen price basis only when it matches the owner response."""

    requested_basis = _requested_basis(request_params)
    if requested_basis is None:
        return _blocked_price_basis()
    if view_model.get("kind") != "detail":
        return view_model

    plan = _preview_plan(payload)
    if plan is None:
        return view_model if view_model.get("outcome") == "blocked" else _blocked_price_basis()
    response_basis = plan.get("reference_price_basis", "market")
    if type(response_basis) is not str or response_basis != requested_basis:
        return _blocked_price_basis()

    raw_items = plan.get("asset_items")
    if not isinstance(raw_items, list):
        return _blocked_price_basis()

    price_rows: list[dict[str, object]] = []
    has_unverified_close = False
    publication_identity: _PublicationIdentity | None = None
    if requested_basis == "market":
        if any(
            isinstance(item, Mapping) and item.get("price_publication") is not None
            for item in raw_items
        ):
            return _blocked_price_basis()
    else:
        plan_as_of = _aware_timestamp(plan.get("as_of"))
        if plan_as_of is None:
            return _blocked_price_basis()
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping) or raw_item.get("scope") != "asset":
                return _blocked_price_basis()
            if "price_publication" not in raw_item:
                return _blocked_price_basis()
            raw_publication = raw_item.get("price_publication")
            has_unverified_close = has_unverified_close or raw_publication is None
            row = _published_close_row(
                raw_item,
                raw_publication,
                plan_as_of=plan_as_of,
                plan_status=plan.get("status"),
            )
            if row is None:
                return _blocked_price_basis()
            if isinstance(raw_publication, Mapping):
                row_identity = _publication_identity(raw_publication)
                if row_identity is None:
                    return _blocked_price_basis()
                if publication_identity is not None and row_identity != publication_identity:
                    return _blocked_price_basis()
                publication_identity = row_identity
            price_rows.append(row)

    updated = dict(view_model)
    basis_value = _BASIS_LABELS[requested_basis]
    if requested_basis == "published_close" and (has_unverified_close or not price_rows):
        suffix = "个别标的未核验" if has_unverified_close else "本次没有单标的来源项"
        basis_value = f"已选择日终收盘价（仅本次只读预览）；{suffix}"

    fields = updated.get("fields")
    normalized_fields = (
        [field for field in fields if isinstance(field, dict)] if isinstance(fields, list) else []
    )
    normalized_fields = [
        field for field in normalized_fields if field.get("key") != "reference_price_basis"
    ]
    normalized_fields.insert(
        0,
        {
            "key": "reference_price_basis",
            "label": "参考价格口径",
            "value": basis_value,
        },
    )
    updated["fields"] = normalized_fields

    sections = updated.get("sections")
    section_rows = list(sections) if isinstance(sections, list) else []
    section_rows = [
        section
        for section in section_rows
        if not isinstance(section, Mapping) or section.get("key") != "reference_price_context"
    ]
    if requested_basis == "published_close":
        section_rows.append(
            {
                "key": "reference_price_context",
                "title": "日终收盘参考与来源时点",
                "rows": price_rows,
                "body": [
                    "日终收盘价仅用于本次只读预览；未核验的标的不会显示为已核验收盘参考。",
                    "日期与来源时点用于核对本次采用的参考价格，不代表未来报价或可成交价格。",
                    *(["本次没有单标的日终参考价格。"] if not price_rows else []),
                ],
            }
        )
    updated["sections"] = section_rows
    summary = updated.get("business_summary")
    if type(summary) is str and summary:
        updated["business_summary"] = f"参考价格口径：{basis_value}。{summary}"
    return updated


def _requested_basis(request_params: Mapping[str, object] | None) -> str | None:
    if request_params is None or "reference_price_basis" not in request_params:
        return "market"
    value = request_params.get("reference_price_basis")
    return value if type(value) is str and value in _BASIS_LABELS else None


def _preview_plan(payload: object) -> Mapping[str, object] | None:
    if not isinstance(payload, Mapping) or payload.get("success") is not True:
        return None
    reports = payload.get("reports")
    if type(payload.get("count")) is not int or payload.get("count") != 1:
        return None
    if not isinstance(reports, list) or len(reports) != 1:
        return None
    report = reports[0]
    if not isinstance(report, Mapping):
        return None
    plan = report.get("plan")
    return plan if isinstance(plan, Mapping) else None


def _published_close_row(
    item: Mapping[str, object],
    publication: object,
    *,
    plan_as_of: datetime,
    plan_status: object,
) -> dict[str, object] | None:
    asset_code = item.get("asset_code")
    if type(asset_code) is not str or not asset_code.strip() or len(asset_code) > 48:
        return None
    if publication is None:
        reasons = item.get("reason_codes")
        if (
            not isinstance(reasons, list)
            or not any(type(reason) is str and reason in _CLOSE_BLOCK_REASONS for reason in reasons)
            or type(plan_status) is not str
            or plan_status not in {"blocked", "partial"}
            or item.get("status") != "blocked"
            or item.get("actionable_quantity") is not None
            or item.get("reference_price") is not None
        ):
            return None
        return {
            "fields": [
                _field("asset", "標的", asset_code),
                _field("verification", "收盘参考状态", "未核验；本项预览受限"),
                _field("bar_date", "收盘数据基准日", "未提供"),
                _field("source_observed_at", "来源观测时间", "未提供"),
            ]
        }
    if not isinstance(publication, Mapping):
        return None

    dataset_key = _bounded_text(publication.get("dataset_key"), limit=64)
    publication_key = _bounded_text(publication.get("publication_key"), limit=64)
    publication_id = _bounded_text(publication.get("publication_id"), limit=160)
    publication_hash = publication.get("publication_hash")
    run_id = _bounded_text(publication.get("publication_run_id"), limit=36)
    published_at = _aware_timestamp(publication.get("published_at"))
    publication_as_of = _aware_timestamp(publication.get("publication_as_of"))
    knowledge_cutoff = _aware_timestamp(publication.get("knowledge_cutoff"))
    bar_date = _iso_date(publication.get("bar_date"))
    source_observed_at = _aware_timestamp(publication.get("source_observed_at"))
    freshness = publication.get("freshness_status")
    item_date = _iso_date(item.get("price_as_of"))
    item_observed_at = _aware_timestamp(item.get("price_observed_at"))

    if (
        dataset_key != "equity.price.bar"
        or publication_key != "m1-rebalance-reference"
        or publication_id is None
        or not isinstance(publication_hash, str)
        or _PUBLICATION_HASH.fullmatch(publication_hash) is None
        or run_id is None
        or not _canonical_uuid(run_id)
        or published_at is None
        or publication_as_of is None
        or knowledge_cutoff is None
        or bar_date is None
        or source_observed_at is None
        or type(freshness) is not str
        or freshness not in _FRESHNESS_LABELS
        or item_date != bar_date
        or item_observed_at != source_observed_at
        or knowledge_cutoff != plan_as_of
        or source_observed_at > publication_as_of
        or publication_as_of > published_at
        or published_at > knowledge_cutoff
    ):
        return None

    return {
        "fields": [
            _field("asset", "標的", asset_code),
            _field("verification", "收盘参考状态", _FRESHNESS_LABELS[freshness]),
            _field("bar_date", "收盘数据基准日", bar_date),
            _field("source_observed_at", "来源观测时间", _timestamp_text(source_observed_at)),
            _field("publication_as_of", "发布数据基准时点", _timestamp_text(publication_as_of)),
            _field("published_at", "发布时间", _timestamp_text(published_at)),
            _field("knowledge_cutoff", "本次核对截至", _timestamp_text(knowledge_cutoff)),
        ]
    }


def _publication_identity(
    publication: Mapping[str, object],
) -> _PublicationIdentity | None:
    """Return a complete publication identity for cross-asset consistency checks."""

    dataset_key = _bounded_text(publication.get("dataset_key"), limit=64)
    publication_key = _bounded_text(publication.get("publication_key"), limit=64)
    publication_id = _bounded_text(publication.get("publication_id"), limit=160)
    publication_hash = publication.get("publication_hash")
    run_id = _bounded_text(publication.get("publication_run_id"), limit=36)
    published_at = _aware_timestamp(publication.get("published_at"))
    publication_as_of = _aware_timestamp(publication.get("publication_as_of"))
    knowledge_cutoff = _aware_timestamp(publication.get("knowledge_cutoff"))
    bar_date = _iso_date(publication.get("bar_date"))
    source_observed_at = _aware_timestamp(publication.get("source_observed_at"))
    freshness = publication.get("freshness_status")
    if (
        dataset_key is None
        or publication_key is None
        or publication_id is None
        or not isinstance(publication_hash, str)
        or _PUBLICATION_HASH.fullmatch(publication_hash) is None
        or run_id is None
        or not _canonical_uuid(run_id)
        or published_at is None
        or publication_as_of is None
        or knowledge_cutoff is None
        or bar_date is None
        or source_observed_at is None
        or type(freshness) is not str
        or freshness not in _FRESHNESS_LABELS
    ):
        return None
    return (
        dataset_key,
        publication_key,
        publication_id,
        publication_hash,
        run_id,
        published_at,
        publication_as_of,
        knowledge_cutoff,
        date.fromisoformat(bar_date),
        source_observed_at,
        freshness,
    )


def _blocked_price_basis() -> dict[str, object]:
    message = "所选价格口径与预览结果不一致；本次计划明细未展示。请重新生成预览。"
    return {
        "kind": "detail",
        "title": "账户调仓预览",
        "status": "价格口径未核实",
        "outcome": "blocked",
        "business_summary": message,
        "blocking_reason": message,
        "fields": [],
        "sections": [{"key": "blocked", "title": "处理提示", "body": [message]}],
        "next_steps": [],
    }


def _bounded_text(value: object, *, limit: int) -> str | None:
    if type(value) is not str or not value.strip() or len(value) > limit:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return None
    return value


def _canonical_uuid(value: str | None) -> bool:
    if value is None:
        return False
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return str(parsed) == value


def _iso_date(value: object) -> str | None:
    if type(value) is not str:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed.isoformat() == value else None


def _aware_timestamp(value: object) -> datetime | None:
    if type(value) is not str or len(value) > 80:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _timestamp_text(value: datetime) -> str:
    return value.isoformat()


def _field(key: str, label: str, value: str) -> dict[str, str]:
    return {"key": key, "label": label, "value": value}


__all__ = ["project_reference_price_context"]
