/*
 * TUX-08 research evidence renderer.  It returns markup only; it does not
 * mutate the DOM, attach handlers, or infer a financial decision state.
 */

const RESEARCH_EVIDENCE_LIMITS = Object.freeze({
    sections: 6,
    columns: 16,
    rows: 6,
    fields: 12,
    times: 24,
    text: 1200,
});

const RESEARCH_EVIDENCE_STATUS_LABELS = Object.freeze({
    fresh: "已返回",
    partial: "部分返回",
    blocked: "已阻断",
    missing: "未找到",
    failed: "读取失败",
    stale: "数据过期",
    error: "读取错误",
    unavailable: "暂不可用",
});

const RESEARCH_EVIDENCE_OUTCOME_LABELS = Object.freeze({
    success: "读取完成",
    partial: "部分返回",
    noop: "无变更",
    blocked: "已阻断",
    failed: "读取失败",
});

const RESEARCH_EVIDENCE_REASON_LABELS = Object.freeze({
    canonical_publication_missing: "当前没有可用的发布记录。",
    decision_reliability_blocked: "结果被标记为不可用于决策。",
    decision_readiness_blocked: "决策准备条件未满足，结果受限。",
    equity_core_evidence_incomplete: "核心研究证据不完整，结果受限。",
    equity_identity_unresolved: "标的身份未能唯一确认。",
    publication_member_fact_changed: "发布记录中的成员事实发生变化，当前结果受限。",
    publication_member_evidence_missing: "发布记录缺少成员证据，当前结果受限。",
    publication_stale: "发布记录已超过可用时效，当前结果受限。",
    evidence_missing: "当前分区缺少必要证据。",
    section_evidence_missing: "当前分区缺少必要证据。",
    source_stale: "来源已超过可用时效，当前结果受限。",
    provider_specific_unknown: "数据源限制原因未提供。",
});

const RESEARCH_EVIDENCE_SECTION_KEYS = new Set([
    "latest_quote",
    "price_history",
    "valuation",
    "financials",
    "news",
    "capital_flows",
]);

function researchEvidenceOwnMapValue(map, key) {
    return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : "";
}

function researchEvidenceRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value)
        ? value
        : null;
}

function researchEvidenceText(value) {
    const displayed = String(displayValue(value) ?? "-");
    const clipped = displayed.length > RESEARCH_EVIDENCE_LIMITS.text
        ? `${displayed.slice(0, RESEARCH_EVIDENCE_LIMITS.text)}…`
        : displayed;
    return escapeHtml(clipped);
}

function researchEvidenceRawText(value) {
    if (value === null || value === undefined || value === "") {
        return "";
    }
    return String(displayValue(value) ?? "").trim();
}

function researchEvidenceList(value, limit) {
    return Array.isArray(value) ? value.slice(0, limit) : [];
}

function researchEvidenceStatus(value) {
    const raw = researchEvidenceRawText(value);
    const mapped = researchEvidenceOwnMapValue(
        RESEARCH_EVIDENCE_STATUS_LABELS,
        raw,
    );
    return {
        label: mapped || "状态未知",
        raw,
    };
}

function researchEvidenceReadableReason(value) {
    const raw = researchEvidenceRawText(value);
    if (!raw) {
        return "";
    }
    const mapped = researchEvidenceOwnMapValue(RESEARCH_EVIDENCE_REASON_LABELS, raw);
    if (mapped) {
        return mapped;
    }
    if (raw.includes("详情见研究快照") || /^[A-Za-z0-9_][A-Za-z0-9_.:-]{1,79}$/.test(raw)) {
        return "请稍后重新读取；如持续受限，请联系管理员。";
    }
    return raw;
}

function researchEvidenceRestriction(section) {
    if (section.must_not_use_for_decision === true) {
        return "限制：禁止用于决策";
    }
    if (section.must_not_use_for_decision === false) {
        return "限制：未标记阻断";
    }
    return "限制：限制信息缺失";
}

function researchEvidenceReason(section) {
    const code = researchEvidenceRawText(section.block_reason_code);
    const ownerReason = researchEvidenceRawText(section.owner_reason);
    const restrictionMessage = researchEvidenceRawText(section.restriction_message);
    const ownerReasonLooksLikeCode = /^[A-Za-z0-9_][A-Za-z0-9_.:-]{1,79}$/.test(
        ownerReason,
    );
    const reasonCode = code || (ownerReasonLooksLikeCode ? ownerReason : "");
    const mapped = researchEvidenceOwnMapValue(
        RESEARCH_EVIDENCE_REASON_LABELS,
        reasonCode,
    );
    const readable = restrictionMessage
        || (ownerReason && ownerReason !== code
        && !ownerReasonLooksLikeCode
            ? ownerReason
            : mapped || (reasonCode ? "请稍后重新读取；如持续受限，请联系管理员。" : ""));
    if (!readable && !reasonCode) {
        return "";
    }
    return `
        <p class="tui-research-evidence-reason"${reasonCode ? ` data-reason-code="${researchEvidenceText(reasonCode)}"` : ""}>
            <strong>限制原因：</strong>${researchEvidenceText(readable)}
        </p>
    `;
}

function researchEvidenceIsSnapshotViewModel(viewModel) {
    if (!viewModel || typeof viewModel !== "object" || viewModel.kind !== "detail") {
        return false;
    }
    const sections = Array.isArray(viewModel.sections) ? viewModel.sections : [];
    if (sections.length !== RESEARCH_EVIDENCE_SECTION_KEYS.size) {
        return false;
    }
    const seen = new Set();
    for (const section of sections) {
        if (!researchEvidenceRecord(section)) {
            return false;
        }
        const key = researchEvidenceRawText(section.key);
        if (!RESEARCH_EVIDENCE_SECTION_KEYS.has(key) || seen.has(key)) {
            return false;
        }
        if (!Array.isArray(section.columns) || !Array.isArray(section.rows)) {
            return false;
        }
        seen.add(key);
    }
    return seen.size === RESEARCH_EVIDENCE_SECTION_KEYS.size
        && ("owner_status" in viewModel || "outcome" in viewModel);
}

function researchEvidenceCount(section, rows) {
    const count = Number(section.item_count);
    return Number.isFinite(count) && count >= 0 ? count : rows.length;
}

function renderResearchEvidenceTimes(section) {
    const rawTimes = Array.isArray(section.source_times)
        ? section.source_times
        : [];
    const times = researchEvidenceList(
        rawTimes,
        RESEARCH_EVIDENCE_LIMITS.times,
    ).filter(researchEvidenceRecord);
    if (!times.length) {
        return "";
    }
    const overflow = rawTimes.length > times.length;
    return `
        <details class="tui-research-evidence-clocks">
            <summary>来源时间 ${researchEvidenceText(times.length)} 项</summary>
            <dl class="tui-research-evidence-source-times">
                ${times.map((time) => `
                    <div>
                        <dt>${researchEvidenceText(time.label || time.field || "来源时间")}</dt>
                        <dd>
                            ${researchEvidenceText(time.value)}
                            ${time.origin ? `<span class="tui-research-evidence-origin" data-source-origin="${researchEvidenceText(time.origin)}"></span>` : ""}
                        </dd>
                    </div>
                `).join("")}
            </dl>
            ${overflow ? `<p class="tui-research-evidence-truncation">来源时间过多，仅展示前 ${researchEvidenceText(times.length)} 项。</p>` : ""}
        </details>
    `;
}

function renderResearchEvidenceColumns(section) {
    const columns = researchEvidenceList(
        section.columns,
        RESEARCH_EVIDENCE_LIMITS.columns,
    ).filter(researchEvidenceRecord);
    if (!columns.length) {
        return "";
    }
    return `
        <p class="tui-research-evidence-columns">
            <strong>字段：</strong>
            ${columns.map((column) => researchEvidenceText(column.label || column.key || "字段")).join("、")}
        </p>
    `;
}

function renderResearchEvidenceRows(section) {
    const rawRows = Array.isArray(section.rows) ? section.rows : [];
    const rows = researchEvidenceList(
        rawRows,
        RESEARCH_EVIDENCE_LIMITS.rows,
    ).filter(researchEvidenceRecord);
    if (!rows.length) {
        return `<p class="tui-research-evidence-empty">当前没有可展开的证据行。</p>`;
    }
    return `
        <div class="tui-research-evidence-rows" role="list">
            ${rows.map((row, rowIndex) => {
                const fields = researchEvidenceList(
                    row.fields,
                    RESEARCH_EVIDENCE_LIMITS.fields,
                ).filter(researchEvidenceRecord);
                return `
                    <div class="tui-research-evidence-row" role="listitem">
                        <span class="tui-research-evidence-row-index">证据行 ${researchEvidenceText(rowIndex + 1)}</span>
                        ${fields.length ? `
                            <dl class="tui-research-evidence-fields">
                                ${fields.map((field) => `
                                    <div>
                                        <dt>${researchEvidenceText(field.label || field.key || "字段")}</dt>
                                        <dd>${researchEvidenceText(field.value)}</dd>
                                    </div>
                                `).join("")}
                            </dl>
                        ` : `<p class="tui-research-evidence-empty">该证据行没有可显示字段。</p>`}
                    </div>
                `;
            }).join("")}
        </div>
    `;
}

function renderResearchEvidenceSection(section) {
    const rows = researchEvidenceList(
        section.rows,
        RESEARCH_EVIDENCE_LIMITS.rows,
    ).filter(researchEvidenceRecord);
    const status = researchEvidenceStatus(section.owner_status);
    const upstream = researchEvidenceRawText(section.upstream_freshness_status);
    const upstreamLabel = upstream && upstream !== "fresh" ? researchEvidenceStatus(upstream).label : "";
    const statusAttribute = status.raw
        ? ` data-owner-status="${researchEvidenceText(status.raw)}"`
        : "";
    const required = section.required === true
        ? "必需分区"
        : section.required === false
            ? "可选分区"
            : "必需性未知";
    const count = researchEvidenceCount(section, rows);
    const truncated = section.truncated === true;
    const truncationNote = researchEvidenceRawText(section.truncation_note)
        || `当前仅展示前 ${rows.length} 行证据。`;
    return `
        <details class="tui-research-evidence-section">
            <summary class="tui-research-evidence-summary">
                <span class="tui-research-evidence-label">${researchEvidenceText(section.label || section.key || "证据分区")}</span>
                <span class="tui-research-evidence-status"${statusAttribute}>状态：${researchEvidenceText(status.label)}</span>
                ${upstreamLabel ? `<span class="tui-research-evidence-upstream">来源：${researchEvidenceText(upstreamLabel)}</span>` : ""}
                <span class="tui-research-evidence-restriction">${researchEvidenceText(researchEvidenceRestriction(section))}</span>
                <span class="tui-research-evidence-count">${researchEvidenceText(count)} 条</span>
            </summary>
            <div class="tui-research-evidence-body">
                <p class="tui-research-evidence-required">${researchEvidenceText(required)}</p>
                ${researchEvidenceReason(section)}
                ${renderResearchEvidenceColumns(section)}
                ${renderResearchEvidenceRows(section)}
                ${truncated ? `<p class="tui-research-evidence-truncation">${researchEvidenceText(truncationNote)}</p>` : ""}
                ${renderResearchEvidenceTimes(section)}
            </div>
        </details>
    `;
}

function researchEvidencePrimaryTime(section) {
    const times = Array.isArray(section.source_times)
        ? section.source_times.filter(researchEvidenceRecord)
        : [];
    if (!times.length) {
        return null;
    }
    const newsPublication = researchEvidenceRawText(section.key) === "news"
        ? times.find((time) => time.origin === "record" && time.field === "published_at")
        : null;
    if (newsPublication) return newsPublication;
    const announcement = times.find((time) => (
        [time.field, time.key].some((value) => (
            researchEvidenceRawText(value).toLowerCase() === "announced_at"
        ))
    ));
    if (announcement) {
        return announcement;
    }
    return times.find((time) => (
        researchEvidenceRawText(time.kind).toLowerCase() === "observation"
    )) || null;
}

function renderResearchEvidencePrimaryTimes(sections) {
    const primaryTimes = sections.map((section) => ({
        section,
        time: researchEvidencePrimaryTime(section),
    })).filter((item) => item.time);
    if (!primaryTimes.length) {
        return "";
    }
    return `
        <div class="tui-research-evidence-primary-times" data-research-primary-times>
            <strong>原始时间</strong>
            ${primaryTimes.map(({ section, time }) => `
                <span data-source-time-kind="${researchEvidenceText(time.kind || time.field || "source")}" data-source-time-section="${researchEvidenceText(section.key || "section")}">
                    ${researchEvidenceText(section.label || section.key || "证据分区")}：${researchEvidenceText(time.label || time.field || "观测时间")} ${researchEvidenceText(time.value)}
                </span>
            `).join("")}
        </div>
    `;
}

function renderResearchEvidenceCompactFacts(viewModel) {
    const compactKeys = new Set([
        "security",
        "latest_quote",
        "valuation",
        "financials",
        "evidence_gaps",
        "capabilities",
    ]);
    const fields = (Array.isArray(viewModel.fields) ? viewModel.fields : [])
        .filter(researchEvidenceRecord)
        .filter((field) => compactKeys.has(researchEvidenceRawText(field.key)));
    const identity = fields.find((field) => researchEvidenceRawText(field.key) === "security");
    const identityMarkup = identity
        ? `
            <div class="tui-research-evidence-fact tui-research-evidence-identity" data-research-identity>
                <dt>${researchEvidenceText(identity.label || "标的")}</dt>
                <dd>${researchEvidenceText(identity.value)}</dd>
            </div>
        `
        : `
            <div class="tui-research-evidence-fact tui-research-evidence-identity" data-research-identity>
                <dt>标的</dt>
                <dd>${researchEvidenceText(viewModel.title || "未提供")}</dd>
            </div>
        `;
    const factMarkup = fields
        .filter((field) => field !== identity)
        .map((field) => `
            <div class="tui-research-evidence-fact" data-research-fact-key="${researchEvidenceText(field.key)}">
                <dt>${researchEvidenceText(field.label || field.key || "事实")}</dt>
                <dd>${researchEvidenceText(field.value)}</dd>
            </div>
        `).join("");
    return `
        <dl class="tui-research-evidence-p0" data-research-p0>
            ${identityMarkup}
            ${factMarkup}
        </dl>
    `;
}

function researchEvidenceReliabilityText(viewModel) {
    const ownerReliability = researchEvidenceRecord(viewModel.owner_reliability);
    if (!ownerReliability) {
        return "未提供";
    }
    if (ownerReliability.reliability !== null && ownerReliability.reliability !== undefined) {
        return researchEvidenceRawText(ownerReliability.reliability);
    }
    const fields = Array.isArray(viewModel.fields) ? viewModel.fields : [];
    const declared = fields.find((field) => researchEvidenceRecord(field) && field.key === "reliability");
    return researchEvidenceRawText(declared?.value) || "未提供独立评分";
}

function renderResearchEvidenceSections(viewModel) {
    if (!researchEvidenceIsSnapshotViewModel(viewModel)) {
        return "";
    }
    const sections = researchEvidenceList(
        viewModel.sections,
        RESEARCH_EVIDENCE_LIMITS.sections,
    ).filter(researchEvidenceRecord);
    if (!sections.length) {
        return "";
    }
    const ownerStatus = researchEvidenceStatus(viewModel.owner_status || viewModel.status);
    const outcome = researchEvidenceRawText(viewModel.outcome);
    const outcomeLabel = researchEvidenceOwnMapValue(RESEARCH_EVIDENCE_OUTCOME_LABELS, outcome) || "状态未知";
    const blockingReason = researchEvidenceReadableReason(viewModel.blocking_reason);
    const decisionRestriction = viewModel.must_not_use_for_decision === true
        ? "限制：禁止用于决策"
        : viewModel.must_not_use_for_decision === false
            ? "限制：未标记阻断"
            : "限制：限制信息缺失";
    return `
        <section class="tui-research-evidence" data-research-compact-summary aria-label="单标的研究快照">
            <h3 class="tui-research-evidence-title">单标的研究快照</h3>
            <div class="tui-research-evidence-overview">
                <span data-research-freshness>材料状态：${researchEvidenceText(ownerStatus.label)}</span>
                <span${outcome ? ` data-owner-outcome="${researchEvidenceText(outcome)}"` : ""}>结果：${researchEvidenceText(outcomeLabel)}</span>
                ${decisionRestriction ? `<span class="tui-research-evidence-restriction">${researchEvidenceText(decisionRestriction)}</span>` : ""}
                <span data-research-reliability>可靠性：${researchEvidenceText(researchEvidenceReliabilityText(viewModel))}</span>
            </div>
            <p class="tui-research-evidence-disclaimer" data-research-disclaimer>
                仅汇总已有事实，未生成投资结论、反向论证或证伪条件。
            </p>
            ${blockingReason ? `<p class="tui-research-evidence-blocking-reason"><strong>结果限制：</strong>${researchEvidenceText(blockingReason)}</p>` : ""}
            ${renderResearchEvidenceCompactFacts(viewModel)}
            ${renderResearchEvidencePrimaryTimes(sections)}
            <div class="tui-research-evidence-disclosures" data-research-evidence-disclosures>
                ${sections.map(renderResearchEvidenceSection).join("")}
            </div>
        </section>
    `;
}
