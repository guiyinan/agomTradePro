"""Typed TUI presentation for an Equity research snapshot.

The owner supplies the evidence and execution outcome. This helper only
projects bounded presentation fields and curated evidence sections.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, NotRequired, TypedDict, TypeGuard, cast

SourceKind = Literal[
    "observation",
    "availability",
    "fetch",
    "period",
    "publication",
]
SourceOrigin = Literal[
    "section",
    "wrapper",
    "data",
    "publication",
    "record",
    "record.source_evidence",
]


class TuiResearchField(TypedDict):
    key: str
    label: str
    value: str


class TuiResearchNested(TypedDict):
    key: str
    label: str
    count: int


class TuiResearchColumn(TypedDict):
    key: str
    label: str


class TuiResearchRow(TypedDict):
    fields: list[TuiResearchField]


class TuiResearchSourceTime(TypedDict):
    kind: SourceKind
    field: str
    origin: SourceOrigin
    label: str
    value: str


class TuiResearchSection(TypedDict, total=False):
    key: str
    label: str
    owner_status: str
    required: bool
    must_not_use_for_decision: bool
    owner_flags: dict[str, bool]
    owner_reason: str
    restriction_message: str
    block_reason_code: str
    upstream_status: str
    upstream_freshness_status: str
    upstream_reliability: dict[str, object]
    columns: list[TuiResearchColumn]
    rows: list[TuiResearchRow]
    item_count: int
    truncated: bool
    truncation_note: str
    source_times: list[TuiResearchSourceTime]


class TuiResearchParams(TypedDict):
    stock_code: str


class TuiResearchProfessionalTarget(TypedDict, total=False):
    """Caller-filtered target metadata for one optional professional link."""

    screen_key: Literal["research.asset-lab"]
    action_key: Literal["equity.valuation-overview"]
    label: str


class TuiResearchNextStep(TypedDict):
    label: str
    screen_key: Literal["research.asset-lab"]
    action_key: Literal["equity.valuation-overview"]
    params: TuiResearchParams


class TuiResearchSnapshotView(TypedDict):
    kind: Literal["detail"]
    title: str
    status: str
    owner_status: str
    fields: list[TuiResearchField]
    nested: list[TuiResearchNested]
    business_summary: str
    blocking_reason: str
    next_steps: list[TuiResearchNextStep]
    debug_hidden_fields: list[str]
    sections: list[TuiResearchSection]
    owner_reliability: dict[str, object]
    outcome: NotRequired[str]
    must_not_use_for_decision: NotRequired[bool]


_MAX_ROWS = 6

_SECTION_ORDER: tuple[str, ...] = (
    "latest_quote",
    "price_history",
    "valuation",
    "financials",
    "news",
    "capital_flows",
)

_SECTION_LABELS: dict[str, str] = {
    "latest_quote": "行情",
    "price_history": "价格历史",
    "valuation": "估值",
    "financials": "财务",
    "news": "新闻",
    "capital_flows": "资金流",
}

_SECTION_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "latest_quote": (
        ("asset_code", "证券代码"),
        ("current_price", "现价"),
        ("open", "开盘"),
        ("high", "最高"),
        ("low", "最低"),
        ("prev_close", "昨收"),
        ("volume", "成交量"),
        ("amount", "成交额"),
        ("currency", "币种"),
        ("source", "来源"),
        ("snapshot_at", "观测时间"),
        ("fetched_at", "抓取时间"),
    ),
    "price_history": (
        ("asset_code", "证券代码"),
        ("bar_date", "行情日期"),
        ("freq", "频率"),
        ("adjustment", "复权"),
        ("open", "开盘"),
        ("high", "最高"),
        ("low", "最低"),
        ("close", "收盘"),
        ("volume", "成交量"),
        ("amount", "成交额"),
        ("source", "来源"),
        ("fetched_at", "抓取时间"),
    ),
    "valuation": (
        ("asset_code", "证券代码"),
        ("unit", "单位"),
        ("pe_ttm", "PE(TTM)"),
        ("pe_static", "PE(静态)"),
        ("pb", "PB"),
        ("ps_ttm", "PS(TTM)"),
        ("market_cap", "总市值"),
        ("float_market_cap", "流通市值"),
        ("dv_ratio", "股息率"),
        ("source", "来源"),
        ("val_date", "估值日期"),
        ("observed_at", "观测时间"),
        ("available_at", "可用时间"),
        ("fetched_at", "抓取时间"),
    ),
    "financials": (
        ("announced_at", "公告时间"),
        ("asset_code", "证券代码"),
        ("metric_code", "指标"),
        ("value", "数值"),
        ("unit", "单位"),
        ("period_end", "报告期末"),
        ("period_type", "报告期类型"),
        ("source", "来源"),
        ("report_date", "报告日期"),
        ("available_at", "可用时间"),
        ("fetched_at", "抓取时间"),
    ),
    "news": (
        ("asset_code", "证券代码"),
        ("title", "标题"),
        ("published_at", "发布时间"),
        ("source", "来源"),
        ("fetched_at", "抓取时间"),
    ),
    "capital_flows": (
        ("asset_code", "证券代码"),
        ("flow_date", "资金流日期"),
        ("main_net", "主力净流入"),
        ("retail_net", "散户净流入"),
        ("super_large_net", "超大单净流入"),
        ("large_net", "大单净流入"),
        ("medium_net", "中单净流入"),
        ("small_net", "小单净流入"),
        ("unit", "单位"),
        ("source", "来源"),
        ("fetched_at", "抓取时间"),
    ),
}

_UNIT_SECTIONS = {"valuation", "financials", "capital_flows"}
_UNIT_VALUE_KEYS: dict[str, tuple[str, ...]] = {
    "valuation": (
        "pe_ttm",
        "pe_static",
        "pb",
        "ps_ttm",
        "market_cap",
        "float_market_cap",
        "dv_ratio",
    ),
    "financials": ("value",),
    "capital_flows": (
        "main_net",
        "retail_net",
        "super_large_net",
        "large_net",
        "medium_net",
        "small_net",
    ),
}

_ROW_KEYS: tuple[str, ...] = (
    "rows",
    "results",
    "items",
    "records",
    "data",
    "bars",
    "financials",
    "valuations",
    "news",
    "flows",
)

_TIME_SPECS: dict[str, tuple[SourceKind, str]] = {
    "snapshot_at": ("observation", "观测时间"),
    "bar_date": ("observation", "行情日期"),
    "flow_date": ("observation", "资金流日期"),
    "val_date": ("observation", "估值日期"),
    "period_end": ("period", "报告期末"),
    "report_date": ("publication", "报告日期"),
    "announced_at": ("publication", "公告时间"),
    "observed_at": ("observation", "观测时间"),
    "source_observed_at": ("observation", "来源观测时间"),
    "available_at": ("availability", "可用时间"),
    "source_available_at": ("availability", "来源可用时间"),
    "published_at": ("publication", "来源发布时间"),
    "source_published_at": ("publication", "来源发布时间"),
    "fetched_at": ("fetch", "抓取时间"),
}

_STATUS_LABELS: dict[str, str] = {
    "fresh": "已返回",
    "partial": "部分返回",
    "blocked": "已阻断",
    "missing": "未找到",
    "failed": "读取失败",
    "stale": "数据过期",
    "error": "读取错误",
    "unavailable": "暂不可用",
}

_REASON_LABELS: dict[str, str] = {
    "publication_member_fact_changed": "数据与发布记录不一致，请重新读取；持续受限时请联系管理员更新数据。",
    "publication_member_evidence_missing": "来源时间或校验证据缺失，请稍后重新读取；持续受限时请联系管理员补齐数据。",
    "publication_stale": "数据已超过允许的新鲜度，请等待新资料后重新读取。",
    "canonical_publication_missing": "当前没有可用的发布数据，请稍后重新读取。",
    "equity_identity_unresolved": "无法唯一确认标的，请使用完整证券代码或唯一名称。",
    "identity_missing": "标的信息缺失",
    "source_unavailable": "数据源不可用",
    "source_stale": "数据源已过期",
    "not_supported": "该分区暂不支持",
    "decision_restricted": "结果被标记为不可用于决策",
}


def build_tui_research_snapshot_view(
    snapshot: Mapping[str, object],
    professional_target: TuiResearchProfessionalTarget | None = None,
) -> TuiResearchSnapshotView:
    """Project owner evidence without inferring financial usability."""

    owner_status = _required_text(snapshot, "status")
    identity = _as_mapping(snapshot.get("identity"))
    identity_data = _as_mapping(_value(identity, "data"))
    code = _first_text(
        snapshot.get("stock_code"),
        _value(identity_data, "code"),
        _value(identity, "code"),
    )
    name = _first_text(
        _value(identity_data, "name"),
        _value(identity_data, "short_name"),
        _value(identity, "name"),
    )
    currency = _first_text(
        _value(identity_data, "currency"),
        _value(identity, "currency"),
    )
    section_payloads = _as_mapping(snapshot.get("sections"))
    sections = _build_sections(section_payloads, currency)
    reliability = _as_mapping(snapshot.get("reliability"))
    gaps = _gaps_text(snapshot, sections, reliability)
    location = name or code or "该标的"
    section_facts = "；".join(
        f"{section.get('label', section.get('key', '分区'))}："
        f"{_status_label(str(section['owner_status']))}"
        for section in sections
        if section.get("owner_status")
    )
    summary = f"{location}研究快照。"
    summary += f"分区状态：{section_facts}。" if section_facts else "未返回研究分区。"
    if gaps:
        summary += f"已报告缺口：{gaps}。"
    summary += "本快照仅汇总事实，未自动生成投资结论、反向论证或可直接验证的证伪条件。"

    result: TuiResearchSnapshotView = {
        "kind": "detail",
        "title": "单标的研究快照",
        "status": _status_label(owner_status),
        "owner_status": owner_status,
        "fields": _top_fields(
            snapshot,
            code,
            name,
            identity_data,
            sections,
            reliability,
        ),
        "nested": [
            {
                "key": str(item.get("key", "")),
                "label": str(item.get("label", "")),
                "count": int(item.get("item_count", 0)),
            }
            for item in sections
        ],
        "business_summary": summary,
        "blocking_reason": _blocking_reason(sections, reliability),
        "next_steps": _next_steps(code, professional_target),
        "debug_hidden_fields": [],
        "sections": sections,
        "owner_reliability": dict(reliability) if reliability is not None else {},
    }

    # outcome belongs to the owner use case.  This helper copies it and
    # deliberately does not derive a second financial readiness state.
    outcome = _optional_text(snapshot.get("outcome"))
    if outcome is not None:
        result["outcome"] = outcome
    must_not = _optional_bool(snapshot.get("must_not_use_for_decision"))
    if must_not is not None:
        result["must_not_use_for_decision"] = must_not
    return result


def project_tui_research_snapshot_result(
    payload: object,
    status_code: int,
    professional_target: object = None,
) -> TuiResearchSnapshotView | None:
    """Project only a successful, owner-shaped transport payload."""

    if not 200 <= status_code < 300 or not isinstance(payload, Mapping):
        return None
    if not (
        isinstance(payload.get("status"), str)
        and bool(str(payload.get("status") or "").strip())
        and isinstance(payload.get("outcome"), str)
        and bool(str(payload.get("outcome") or "").strip())
        and "stock_code" in payload
        and (payload["stock_code"] is None or isinstance(payload["stock_code"], str))
        and _is_owner_section(payload.get("identity"))
        and isinstance(payload.get("sections"), Mapping)
        and isinstance(payload.get("must_not_use_for_decision"), bool)
    ):
        return None
    sections = cast(Mapping[str, object], payload["sections"])
    if payload["stock_code"] is not None and not _SECTION_LABELS.keys() <= sections.keys():
        return None
    if not all(_is_owner_section(section) for section in sections.values()):
        return None
    target = _professional_target(professional_target)
    return build_tui_research_snapshot_view(cast(Mapping[str, object], payload), target)


def _is_owner_section(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("status"), str)
        and bool(value["status"].strip())
        and isinstance(value.get("required"), bool)
        and "data" in value
        and isinstance(value.get("must_not_use_for_decision"), bool)
        and isinstance(value.get("block_reason_code"), str)
    )


def _professional_target(value: object) -> TuiResearchProfessionalTarget | None:
    if not isinstance(value, Mapping):
        return None
    if (
        value.get("screen_key") != "research.asset-lab"
        or value.get("action_key") != "equity.valuation-overview"
    ):
        return None
    target: TuiResearchProfessionalTarget = {
        "screen_key": "research.asset-lab",
        "action_key": "equity.valuation-overview",
    }
    label = value.get("label")
    if isinstance(label, str) and label.strip():
        target["label"] = label.strip()
    return target


def _build_sections(
    payloads: Mapping[str, object] | None,
    quote_currency: str | None,
) -> list[TuiResearchSection]:
    if payloads is None:
        return []

    sections: list[TuiResearchSection] = []
    for key in _SECTION_ORDER:
        payload = _as_mapping(payloads.get(key))
        if payload is None:
            continue
        data = payload.get("data")
        if data is None:
            data = payload
        data_mapping = _as_mapping(data)
        records = _records(data, key)
        rows = _curated_rows(key, records, quote_currency)
        section: TuiResearchSection = {
            "key": key,
            "label": _SECTION_LABELS[key],
            "columns": _columns(key, rows),
            "rows": rows,
            "item_count": len(records),
            "truncated": len(records) > _MAX_ROWS,
        }

        status = _optional_text(payload.get("status"))
        if status is not None:
            section["owner_status"] = status
        required = payload.get("required")
        if isinstance(required, bool):
            section["required"] = required
        must_not = payload.get("must_not_use_for_decision")
        if isinstance(must_not, bool):
            section["must_not_use_for_decision"] = must_not
        flags = _bool_flags(payload.get("flags"))
        if flags:
            section["owner_flags"] = flags
        owner_reason = _owner_reason(payload)
        if owner_reason is None and data_mapping is not None:
            owner_reason = _owner_reason(data_mapping)
        if owner_reason is not None:
            section["owner_reason"] = owner_reason
        reason_code = _optional_text(payload.get("block_reason_code"))
        if reason_code is not None:
            section["block_reason_code"] = reason_code
        friendly_reason = _friendly_reason(section)
        if friendly_reason:
            section["restriction_message"] = friendly_reason
        if key == "financials":
            notice = _financial_coverage_notice(data_mapping)
            if notice is not None:
                current = section.get("restriction_message")
                section["restriction_message"] = f"{current}；{notice}" if current else notice
        if data_mapping is not None:
            upstream_status = _mapping_text(data_mapping, "status")
            if upstream_status is not None:
                section["upstream_status"] = upstream_status
            upstream_freshness = _mapping_text(
                data_mapping,
                "freshness_status",
            )
            if upstream_freshness is not None:
                section["upstream_freshness_status"] = upstream_freshness
            upstream_reliability = _as_mapping(data_mapping.get("reliability"))
            if upstream_reliability is not None:
                section["upstream_reliability"] = dict(upstream_reliability)

        if section["truncated"]:
            section["truncation_note"] = (
                f"仅展示前 {_MAX_ROWS} 条{_SECTION_LABELS[key]}证据；"
                f"该分区实际返回 {len(records)} 条，其余未在此视图展开。"
            )
        times = _source_times(key, payload, data, records)
        if times:
            section["source_times"] = times
        sections.append(section)
    return sections


def _financial_coverage_notice(
    data: Mapping[str, object] | None,
) -> str | None:
    """Describe the current financial publication scope when it is partial."""
    if data is None or data.get("publication_outcome") != "partial":
        return None
    fields = (
        ("coverage_requested_count", "请求"),
        ("coverage_eligible_count", "符合条件"),
        ("coverage_selected_count", "已选入"),
        ("coverage_missing_count", "缺失"),
    )
    counts: list[str] = []
    for key, label in fields:
        value = data.get(key)
        count = str(value) if type(value) is int and value >= 0 else "未提供"
        counts.append(f"{label}：{count}")
    return f"本次财务发布范围：部分返回；{'；'.join(counts)}。"


def _curated_rows(
    section_key: str,
    records: list[Mapping[str, object]],
    quote_currency: str | None,
) -> list[TuiResearchRow]:
    rows: list[TuiResearchRow] = []
    for record in records[:_MAX_ROWS]:
        fields: list[TuiResearchField] = []
        for key, label in _SECTION_COLUMNS.get(section_key, ()):
            value = _record_value(section_key, key, record, quote_currency)
            if value is not None:
                fields.append({"key": key, "label": label, "value": value})
        if fields:
            rows.append({"fields": fields})
    return rows


def _record_value(
    section_key: str,
    key: str,
    record: Mapping[str, object],
    quote_currency: str | None,
) -> str | None:
    if section_key == "latest_quote" and key == "currency":
        # A quote may carry a provider currency field, but this view only uses
        # the identity currency supplied by the owner snapshot.
        return _display_scalar(quote_currency)
    if section_key == "financials" and key == "announced_at":
        evidence = _as_mapping(record.get("source_evidence"))
        return _display_scalar(_value(evidence, "announced_at"))
    value = _display_scalar(record.get(key))
    if key == "unit" and value is None and _needs_unit_marker(section_key, record):
        return "单位未提供"
    return value


def _needs_unit_marker(
    section_key: str,
    record: Mapping[str, object],
) -> bool:
    if section_key not in _UNIT_SECTIONS:
        return False
    return any(
        key in record and _display_scalar(record.get(key)) is not None
        for key in _UNIT_VALUE_KEYS.get(section_key, ())
    )


def _columns(
    section_key: str,
    rows: list[TuiResearchRow],
) -> list[TuiResearchColumn]:
    present = {cell["key"] for row in rows for cell in row["fields"]}
    return [
        {"key": key, "label": label}
        for key, label in _SECTION_COLUMNS.get(section_key, ())
        if key in present
    ]


def _source_times(
    section_key: str,
    section: Mapping[str, object],
    data: object,
    records: list[Mapping[str, object]],
) -> list[TuiResearchSourceTime]:
    sources: list[tuple[SourceOrigin, Mapping[str, object]]] = [("section", section)]
    mapping = _as_mapping(data)
    if mapping is not None:
        wrapped = _as_mapping(mapping.get(section_key))
        if wrapped is not None:
            sources.append(("wrapper", wrapped))
        sources.append(("data", mapping))
        publication = _as_mapping(mapping.get("publication"))
        if publication is not None:
            sources.append(("publication", publication))
    if records:
        record = records[0]
        sources.append(("record", record))
        source_evidence = _as_mapping(record.get("source_evidence"))
        if source_evidence is not None:
            sources.append(("record.source_evidence", source_evidence))

    result: list[TuiResearchSourceTime] = []
    seen: set[tuple[str, str, str, str]] = set()
    for origin, source in sources:
        for field, (kind, label) in _TIME_SPECS.items():
            value = _display_scalar(source.get(field))
            if value is None:
                continue
            marker = (field, origin, kind, value)
            if marker in seen:
                continue
            seen.add(marker)
            result.append(
                {
                    "kind": kind,
                    "field": field,
                    "origin": origin,
                    "label": _source_time_label(
                        section_key,
                        origin,
                        field,
                        label,
                    ),
                    "value": value,
                }
            )

    for item in _declared_source_times(section):
        marker = (
            item["field"],
            item["origin"],
            item["kind"],
            item["value"],
        )
        if marker not in seen:
            seen.add(marker)
            result.append(item)
    return result


def _source_time_label(
    section_key: str,
    origin: SourceOrigin,
    field: str,
    label: str,
) -> str:
    section_label = _SECTION_LABELS[section_key]
    if field == "published_at":
        if origin == "record" and section_key == "news":
            return "新闻发布时间"
        return f"{section_label}数据发布记录时间"
    return f"{section_label}{label}"


def _declared_source_times(
    section: Mapping[str, object],
) -> list[TuiResearchSourceTime]:
    declared = section.get("source_times")
    if not isinstance(declared, list):
        return []
    result: list[TuiResearchSourceTime] = []
    for item in declared:
        mapping = _as_mapping(item)
        if mapping is None:
            continue
        kind = _source_kind(mapping.get("kind"))
        origin = _source_origin(mapping.get("origin"))
        field = _optional_text(mapping.get("field"))
        value = _display_scalar(mapping.get("value"))
        if kind is None or origin is None or field is None or value is None:
            continue
        label = _optional_text(mapping.get("label")) or field
        result.append(
            {
                "kind": kind,
                "field": field,
                "origin": origin,
                "label": label,
                "value": value,
            }
        )
    return result


def _source_kind(value: object) -> SourceKind | None:
    if not isinstance(value, str):
        return None
    if value in {
        "observation",
        "availability",
        "fetch",
        "period",
        "publication",
    }:
        return cast(SourceKind, value)
    return None


def _source_origin(value: object) -> SourceOrigin | None:
    if not isinstance(value, str):
        return None
    if value in {
        "section",
        "wrapper",
        "data",
        "publication",
        "record",
        "record.source_evidence",
    }:
        return cast(SourceOrigin, value)
    return None


def _records(
    data: object,
    section_key: str,
) -> list[Mapping[str, object]]:
    if isinstance(data, list):
        return [row for item in data if (row := _as_mapping(item)) is not None]

    mapping = _as_mapping(data)
    if mapping is None:
        return []

    wrapped = mapping.get(section_key)
    if wrapped is not None and wrapped is not data:
        nested_records = _records(wrapped, section_key)
        if nested_records:
            return nested_records

    for key in _ROW_KEYS:
        nested = mapping.get(key)
        if isinstance(nested, list):
            return [row for item in nested if (row := _as_mapping(item)) is not None]
        nested_mapping = _as_mapping(nested)
        if nested_mapping is not None and _has_section_value(
            nested_mapping,
            section_key,
        ):
            return [nested_mapping]
    return [mapping] if _has_section_value(mapping, section_key) else []


def _has_section_value(
    mapping: Mapping[str, object],
    section_key: str,
) -> bool:
    return any(key in mapping for key, _ in _SECTION_COLUMNS.get(section_key, ()))


def _top_fields(
    snapshot: Mapping[str, object],
    code: str | None,
    name: str | None,
    identity: Mapping[str, object] | None,
    sections: list[TuiResearchSection],
    reliability: Mapping[str, object] | None,
) -> list[TuiResearchField]:
    fields: list[TuiResearchField] = []
    _add(
        fields,
        "status",
        "研究状态",
        _status_label(_required_text(snapshot, "status")),
    )
    security = "；".join(
        x
        for x in (
            f"代码：{code}" if code else "",
            f"名称：{name}" if name else "",
        )
        if x
    )
    _add(fields, "security", "证券", security)
    _add(fields, "asset_type", "资产类型", _mapping_text(identity, "asset_type"))

    must_not = _optional_bool(snapshot.get("must_not_use_for_decision"))
    if must_not is True:
        restriction = "禁止用于决策"
    elif must_not is False:
        restriction = "未标记阻断；限制信息仍需按原始快照核对"
    else:
        restriction = "限制信息缺失"
    _add(fields, "decision_restriction", "决策限制", restriction)

    _add(
        fields,
        "latest_quote",
        "最新行情",
        _section_fact(
            sections,
            "latest_quote",
            (
                ("current_price", "价格"),
                ("currency", "币种"),
                ("snapshot_at", "观测时间"),
                ("source", "来源"),
            ),
        ),
    )
    _add(
        fields,
        "valuation",
        "估值",
        _section_fact(
            sections,
            "valuation",
            (
                ("unit", "单位"),
                ("pe_ttm", "PE(TTM)"),
                ("pe_static", "PE(静态)"),
                ("pb", "PB"),
                ("ps_ttm", "PS(TTM)"),
                ("market_cap", "总市值"),
                ("val_date", "估值日期"),
            ),
        ),
    )
    _add(
        fields,
        "financials",
        "财务值",
        _section_fact(
            sections,
            "financials",
            (
                ("metric_code", "指标"),
                ("value", "数值"),
                ("unit", "单位"),
                ("period_end", "报告期末"),
                ("report_date", "报告日期"),
            ),
        ),
    )
    _add(fields, "evidence_time", "证据时间", _time_fact(sections))
    _add(fields, "reliability", "可靠性", _reliability_fact(reliability))
    _add(
        fields,
        "evidence_gaps",
        "证据缺口",
        _gaps_text(snapshot, sections, reliability),
    )
    return fields[:10]


def _section_fact(
    sections: list[TuiResearchSection],
    section_key: str,
    wanted: tuple[tuple[str, str], ...],
) -> str | None:
    section = next(
        (item for item in sections if item.get("key") == section_key),
        None,
    )
    rows = section.get("rows") if section is not None else None
    if not rows:
        return None
    values = {cell["key"]: cell["value"] for cell in rows[0]["fields"]}
    facts = [f"{label}：{values[key]}" for key, label in wanted if key in values]
    return "；".join(facts) or None


def _time_fact(sections: list[TuiResearchSection]) -> str | None:
    parts: list[str] = []
    seen: set[tuple[str, str]] = set()
    for section in sections:
        for item in section.get("source_times", []):
            marker = (item["label"], item["value"])
            if marker in seen:
                continue
            seen.add(marker)
            parts.append(f"{item['label']}：{item['value']}")
    if not parts:
        return None
    bounded = parts[:8]
    if len(parts) > len(bounded):
        bounded.append("其余时间见分区")
    return "；".join(bounded)


def _reliability_fact(
    reliability: Mapping[str, object] | None,
) -> str | None:
    if reliability is None:
        return None
    parts: list[str] = []
    source = _mapping_text(reliability, "source")
    value = _display_scalar(reliability.get("reliability"))
    status = _mapping_text(reliability, "status")
    if source:
        parts.append(f"来源：{_reliability_source_label(source)}")
    if value:
        parts.append(f"可靠性值：{value}")
    if status:
        parts.append(f"状态：{_status_label(status)}")
    return "；".join(parts) or None


def _blocking_reason(
    sections: list[TuiResearchSection],
    reliability: Mapping[str, object] | None,
) -> str:
    if reliability is not None:
        reason = _friendly_reason(reliability)
        if reason:
            return reason
    for section in sections:
        reason = _friendly_reason(section)
        if reason:
            return reason
    return ""


def _gaps_text(
    snapshot: Mapping[str, object],
    sections: list[TuiResearchSection],
    reliability: Mapping[str, object] | None,
) -> str | None:
    parts: list[str] = []
    missing = snapshot.get("missing_optional_sections")
    if isinstance(missing, list):
        for item in missing:
            if isinstance(item, str) and item:
                parts.append(_SECTION_LABELS.get(item, "其他研究分区"))
    for section in sections:
        label = str(section.get("label", section.get("key", "分区")))
        if section.get("must_not_use_for_decision") is True:
            parts.append(f"{label}：已标记为不可用于决策")
        upstream_freshness = _optional_text(section.get("upstream_freshness_status"))
        if upstream_freshness is not None and upstream_freshness != "fresh":
            parts.append(f"{label}：上游{_status_label(upstream_freshness)}")
        if section.get("key") == "financials":
            reason = _optional_text(section.get("restriction_message"))
        else:
            reason = _friendly_reason(section)
        if reason:
            parts.append(f"{label}：{reason}")
    if reliability is not None:
        reason = _friendly_reason(reliability)
        if reason:
            parts.append(reason)
    return "；".join(dict.fromkeys(parts)) or None


def _friendly_reason(mapping: Mapping[str, object]) -> str | None:
    raw = _first_text(
        mapping.get("owner_reason"),
        mapping.get("block_reason"),
        mapping.get("blocked_reason"),
        mapping.get("reason"),
        mapping.get("restriction_reason"),
    )
    code = _first_text(mapping.get("block_reason_code"))
    candidate = raw or code
    if candidate is None:
        return None
    if any("一" <= character <= "鿿" for character in candidate):
        return candidate
    return _REASON_LABELS.get(candidate, "数据暂时受限，请稍后重新读取；持续受限时请联系管理员。")


def _owner_reason(mapping: Mapping[str, object]) -> str | None:
    sources: list[Mapping[str, object]] = [mapping]
    reliability = _as_mapping(mapping.get("reliability"))
    if reliability is not None:
        sources.append(reliability)
    for source in sources:
        reason = _first_text(
            source.get("owner_reason"),
            source.get("block_reason"),
            source.get("blocked_reason"),
            source.get("reason"),
            source.get("restriction_reason"),
        )
        if reason is not None:
            return reason
    return None


def _reliability_source_label(source: str) -> str:
    if source == "agomtradepro_api":
        return "系统研究汇总"
    return source


def _next_steps(
    code: str | None,
    target: TuiResearchProfessionalTarget | None,
) -> list[TuiResearchNextStep]:
    if not _is_canonical_stock_code(code) or target is None:
        return []
    screen_key = target.get("screen_key")
    action_key = target.get("action_key")
    if screen_key != "research.asset-lab" or action_key != "equity.valuation-overview":
        return []
    label = _optional_text(target.get("label")) or "打开资产研究"
    params: TuiResearchParams = {"stock_code": code}
    return [
        {
            "label": label,
            "screen_key": screen_key,
            "action_key": action_key,
            "params": params,
        }
    ]


def _is_canonical_stock_code(value: object) -> TypeGuard[str]:
    """Return whether an owner code is safe to copy into a path parameter."""

    if not isinstance(value, str) or not value or len(value) > 32 or value != value.strip():
        return False
    if value in {".", ".."}:
        return False
    if any(
        character.isspace() or ord(character) < 32 or character in "/\\?#" for character in value
    ):
        return False
    return all(character.isalnum() or character in "._*+-" for character in value)


def _bool_flags(value: object) -> dict[str, bool]:
    mapping = _as_mapping(value)
    if mapping is None:
        return {}
    return {
        key: flag
        for key, value in mapping.items()
        if isinstance(key, str) and isinstance(flag := value, bool)
    }


def _add(
    fields: list[TuiResearchField],
    key: str,
    label: str,
    value: str | None,
) -> None:
    if value:
        fields.append({"key": key, "label": label, "value": value})


def _value(
    mapping: Mapping[str, object] | None,
    key: str,
) -> object | None:
    return mapping.get(key) if mapping is not None else None


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    return cast(Mapping[str, object], value)


def _required_text(mapping: Mapping[str, object], key: str) -> str:
    value = _optional_text(mapping.get(key))
    if value is None:
        raise ValueError(f"research snapshot requires {key}")
    return value


def _first_text(*values: object) -> str | None:
    for value in values:
        text = _optional_text(value)
        if text is not None:
            return text
    return None


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _mapping_text(
    mapping: Mapping[str, object] | None,
    key: str,
) -> str | None:
    return _optional_text(_value(mapping, key))


def _display_scalar(value: object) -> str | None:
    if value is None or isinstance(value, Mapping | list | tuple | set):
        return None
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, int | float):
        return str(value)
    return None


def _status_label(owner_status: str) -> str:
    return _STATUS_LABELS.get(owner_status, "状态待确认")


__all__ = [
    "TuiResearchProfessionalTarget",
    "TuiResearchSnapshotView",
    "build_tui_research_snapshot_view",
    "project_tui_research_snapshot_result",
]
