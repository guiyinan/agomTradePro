import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";
import { fileURLToPath } from "node:url";

const sourceRoot = fileURLToPath(new URL("../src/", import.meta.url));
const read = name => fs.readFileSync(`${sourceRoot}/${name}`, "utf8");
const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);

function retryRuntime(action) {
    const buttons = [];
    const calls = [];
    const context = {
        state: { screen: { screen: {}, actions: [action] } },
        CSS: { escape: value => value },
        els: { main: { appendChild: button => buttons.push(button) } },
        document: { createElement: () => ({ dataset: {}, addEventListener(_name, callback) { this.click = callback; } }) },
        currentAction: () => action,
        isPassiveRead: value => value?.method === "GET" && value.risk === "read" && !value.confirmation_required,
        resultContinuations: { continuationFields: () => new Set(["continuation_token"]) },
    };
    vm.createContext(context);
    vm.runInContext(read("15-workspace-state.js"), context);
    vm.runInContext(read("36-research-entry.js"), context);
    vm.runInContext(read("12-experience.js"), context);
    vm.runInContext(read("30-actions.js"), context);
    vm.runInContext(read("31-form-inputs.js"), context);
    vm.runInContext(read("32-continuation-ui.js"), context);
    context.appendPassiveReadEntry = () => false;
    context.runAction = (...args) => calls.push(args);
    return { context, calls, buttons };
}

test("a failed passive read retries only on explicit click and keeps safe parameters", () => {
    const action = { key: "fixture.read", method: "GET", risk: "read", fields: [
        { key: "identifier", input_type: "text", required: true },
        { key: "password", input_type: "password" },
        { key: "endpoint", input_type: "text", presentation_semantic: "endpoint_url" },
    ] };
    const runtime = retryRuntime(action);
    runtime.context.offerActionRetry(action.key, { identifier: "safe-code", password: "never-copy", endpoint: "https://private.invalid" });
    assert.equal(runtime.calls.length, 0);
    assert.equal(runtime.buttons.length, 1);
    assert.equal(runtime.buttons[0].textContent, "重新读取");
    runtime.buttons[0].click();
    assert.equal(runtime.calls.length, 1);
    const options = JSON.parse(JSON.stringify(runtime.calls[0][2]));
    assert.deepEqual(options, { params: { identifier: "safe-code" }, readRetry: true });
    assert.equal(runtime.buttons[0].disabled, true);
});

test("required hidden, secret and continuation inputs cannot be replayed", () => {
    for (const field of [
        { key: "hidden", input_type: "HIDDEN" },
        { key: "password", input_type: "PASSWORD" },
        { key: "secret", input_type: "text", presentation_semantic: "SECRET" },
        { key: "continuation_token", input_type: "text" },
    ]) {
        const action = { key: "fixture.read", method: "GET", risk: "read", fields: [
            { key: "identifier", input_type: "text", required: true }, { ...field, required: true },
        ] };
        const runtime = retryRuntime(action);
        runtime.context.offerActionRetry(action.key, { identifier: "safe-code", [field.key]: "do-not-replay" });
        assert.equal(runtime.calls.length, 0);
        assert.equal(runtime.buttons.length, 0);
    }
});

test("mutation retry preserves its original explicit confirmation and submission identity", () => {
    const action = { key: "fixture.write", method: "POST", risk: "write", confirmation_required: true, fields: [] };
    const runtime = retryRuntime(action);
    runtime.context.offerActionRetry(action.key, { amount: 1 }, { idempotencyKey: "original-submission", confirmed: true });
    assert.equal(runtime.calls.length, 0);
    assert.equal(runtime.buttons[0].textContent, "重试本次提交");
    runtime.buttons[0].click();
    assert.deepEqual(JSON.parse(JSON.stringify(runtime.calls[0][2])), {
        idempotencyKey: "original-submission", confirmed: true, params: { amount: 1 },
    });
});

function renderer() {
    const context = { escapeHtml, displayValue: value => value == null ? "-" : String(value) };
    vm.createContext(context);
    vm.runInContext(read("39-research-evidence.js"), context);
    return context;
}

function snapshot() {
    return { kind: "detail", owner_status: "blocked", outcome: "blocked", must_not_use_for_decision: true,
        sections: ["latest_quote", "price_history", "valuation", "financials", "news", "capital_flows"].map(key => ({
            key, label: key, owner_status: "blocked", required: true, must_not_use_for_decision: true,
            restriction_message: "数据已过期，请等待更新后重新读取。", block_reason_code: "publication_stale",
            upstream_freshness_status: "stale", columns: [{ key: "value", label: "数值" }],
            rows: [{ fields: [{ key: "value", label: "数值", value: 0 }] }], item_count: 1,
            source_times: [{ field: "announced_at", label: "公告时间", value: "2001-01-01T00:00:00+00:00", origin: "record.source_evidence" }],
        })),
    };
}

test("evidence renders owner restrictions, zero values and original clocks as collapsed disclosures", () => {
    const markup = renderer().renderResearchEvidenceSections(snapshot());
    assert.equal((markup.match(/<details class="tui-research-evidence-section">/g) || []).length, 6);
    assert.doesNotMatch(markup, /<details[^>]+\bopen(?:\s|=|>)/);
    assert.match(markup, /禁止用于决策/);
    assert.match(markup, /数据过期/);
    assert.match(markup, /<dd>0<\/dd>/);
    assert.match(markup, /2001-01-01T00:00:00\+00:00/);
    const visible = markup.replace(/<[^>]*>/g, "");
    assert.doesNotMatch(visible, /record\.source_evidence|publication_stale/);
    assert.equal(renderer().renderResearchEvidenceSections({ kind: "detail", sections: [] }), "");
});

test("execution outcome stays visible independently of the owner status", () => {
    const view = snapshot();
    view.owner_status = "fresh";
    for (const [outcome, label] of Object.entries({ partial: "部分返回", failed: "读取失败", noop: "无变更" })) {
        view.outcome = outcome;
        const markup = renderer().renderResearchEvidenceSections(view);
        assert.match(markup, new RegExp(`结果：${label}`));
        assert.match(markup, /状态：已返回/);
    }
});

test("primary source clocks never substitute publication or fetch for the event", () => {
    const runtime = renderer();
    const publication = { kind: "publication", field: "published_at", origin: "publication", value: "2026-10-17T00:00:00Z" };
    const news = { kind: "publication", field: "published_at", origin: "record", value: "2001-01-01T00:00:00Z" };
    assert.equal(runtime.researchEvidencePrimaryTime({ key: "news", source_times: [publication, news] }).value, news.value);
    assert.equal(runtime.researchEvidencePrimaryTime({ key: "news", source_times: [publication] }), null);
    const fetched = { kind: "fetch", field: "fetched_at", value: publication.value };
    assert.equal(runtime.researchEvidencePrimaryTime({ key: "latest_quote", source_times: [publication, fetched] }), null);
    const announced = { kind: "publication", field: "announced_at", origin: "record.source_evidence", value: news.value };
    assert.equal(runtime.researchEvidencePrimaryTime({ key: "financials", source_times: [{ kind: "observation", value: publication.value }, announced] }).value, announced.value);
    assert.equal(runtime.researchEvidenceReliabilityText({ owner_reliability: { reliability: 0 } }), "0");
    assert.equal(runtime.researchEvidenceReliabilityText({ owner_reliability: { status: "fresh" }, fields: {} }), "未提供独立评分");
});

test("untrusted evidence is escaped, bounded and cannot access prototype map entries", () => {
    const view = snapshot();
    const section = view.sections[0];
    section.owner_status = "__proto__";
    section.label = '<img src=x onerror="bad()">';
    section.rows = Array.from({ length: 20 }, () => ({ fields: [{ label: "值", value: "<script>bad()</script>" }] }));
    section.item_count = 20;
    section.truncated = true;
    const markup = renderer().renderResearchEvidenceSections(view);
    assert.doesNotMatch(markup, /<img|<script>|\[object Object\]/);
    assert.match(markup, /&lt;img/);
    assert.match(markup, /&lt;script&gt;/);
    assert.match(markup, /状态未知/);
    assert.equal((markup.match(/&lt;script&gt;/g) || []).length, 6);
    assert.match(markup, /20 条/);
});
