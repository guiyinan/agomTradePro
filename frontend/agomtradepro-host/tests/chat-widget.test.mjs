import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const widgetUrl = new URL(
    "../../../core/static/js/components/chat-widget.js",
    import.meta.url,
);
const dashboardUrl = new URL(
    "../../../core/templates/dashboard/index.html",
    import.meta.url,
);

async function loadWidgetClass() {
    const source = await readFile(widgetUrl, "utf8");
    const context = { module: { exports: {} } };
    vm.runInNewContext(source, context, { filename: widgetUrl.pathname });
    return context.module.exports;
}

test("dashboard wires the shared chat widget instead of duplicate inline handlers", async () => {
    const dashboard = await readFile(dashboardUrl, "utf8");

    assert.match(dashboard, /js\/components\/chat-widget\.js/);
    assert.match(dashboard, /new AgomChatWidget\(/);
    assert.match(dashboard, /dashboardChat\.sendText\(/);
    assert.doesNotMatch(dashboard, /chatSendBtn\.onclick/);
    assert.doesNotMatch(dashboard, /API_URLS\.promptChat/);
});

test("sendText feeds the shared widget's normal send path", async () => {
    const Widget = await loadWidgetClass();
    const widget = Object.create(Widget.prototype);
    const calls = [];
    widget.elements = { input: { value: "" } };
    widget._adjustTextareaHeight = () => calls.push("adjust");
    widget.sendMessage = () => {
        calls.push(widget.elements.input.value);
        return Promise.resolve();
    };

    await widget.sendText("当前宏观环境如何？");

    assert.deepEqual(calls, ["adjust", "当前宏观环境如何？"]);
    assert.equal(widget.elements.input.value, "当前宏观环境如何？");
});
