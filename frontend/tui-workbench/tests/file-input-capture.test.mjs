import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import test from "node:test";

const sourceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const captureSource = readFileSync(resolve(sourceRoot, "31-form-inputs.js"), "utf8");

function createRuntime() {
    class MockFileReader {
        listeners = new Map();
        result = "";
        error = null;

        addEventListener(eventName, listener) {
            this.listeners.set(eventName, listener);
        }

        readAsText(file) {
            this.result = file.legacyText;
            queueMicrotask(() => this.listeners.get("load")?.());
        }
    }

    const context = {
        FileReader: MockFileReader,
        TextDecoder,
        maxTextFileBytes: 2_097_152,
        formFieldElement: (form, fieldKey) => form.elements[fieldKey] || null,
        coerceFieldValue: (_field, value) => String(value ?? ""),
    };
    vm.createContext(context);
    vm.runInContext(captureSource, context, { filename: "31-form-inputs.js" });
    return context;
}

function file(name, content, declaredSize = content.byteLength) {
    const bytes = content instanceof Uint8Array ? content : new Uint8Array(content);
    return {
        name,
        size: declaredSize,
        arrayBuffer: async () => bytes.slice().buffer,
        legacyText: new TextDecoder().decode(bytes),
    };
}

const filenameFields = [
    {
        key: "csv_text",
        input_type: "file",
        value_type: "string",
        binding: "body",
        file_name_field: "original_filename",
        max_bytes: 1_048_576,
    },
    {
        key: "original_filename",
        input_type: "hidden",
        value_type: "string",
        binding: "body",
        required: true,
        default: "",
    },
];

test("opt-in file capture preserves BOM, CRLF, UTF-8 and the exact Unicode filename", async () => {
    const runtime = createRuntime();
    const original = "\uFEFF委托编号,费用\r\n001,0.80\r\n";
    const payload = new TextEncoder().encode(original);
    const params = await runtime.collectParams(
        {
            elements: {
                csv_text: { files: [file("费用原件.csv", payload)] },
                original_filename: { value: "spoofed.csv" },
            },
        },
        { fields: filenameFields },
    );

    assert.equal(params.csv_text, original);
    assert.equal(params.original_filename, "费用原件.csv");
});

test("opt-in strict UTF-8 rejects invalid bytes and accepts the exact configured byte limit", async () => {
    const runtime = createRuntime();
    const accepted = file("small.csv", new TextEncoder().encode("abc"));
    assert.equal(
        await runtime.readTextFile(accepted, { maxBytes: 3, strictUtf8: true }),
        "abc",
    );

    const invalid = file("broken.csv", Uint8Array.from([0xc3, 0x28]));
    await assert.rejects(
        runtime.readTextFile(invalid, { maxBytes: 3, strictUtf8: true }),
        /有效的 UTF-8/,
    );
});

test("opt-in capture checks actual bytes, refuses empty files, and does not submit a stale hidden filename", async () => {
    const runtime = createRuntime();
    const tooLarge = file("large.csv", new TextEncoder().encode("abcd"), 3);
    await assert.rejects(
        runtime.readTextFile(tooLarge, { maxBytes: 3, strictUtf8: true }),
        /大小限制/,
    );

    const empty = file("empty.csv", new Uint8Array());
    await assert.rejects(
        runtime.readTextFile(empty, { maxBytes: 3, strictUtf8: true }),
        /文件为空/,
    );

    const params = await runtime.collectParams(
        {
            elements: {
                csv_text: { files: [] },
                original_filename: { value: "stale.csv" },
            },
        },
        { fields: filenameFields },
    );
    assert.equal(Object.hasOwn(params, "csv_text"), false);
    assert.equal(Object.hasOwn(params, "original_filename"), false);
});

test("legacy file capture keeps FileReader decoding and the generic two MiB cap", async () => {
    const runtime = createRuntime();
    const legacy = file("legacy.txt", new TextEncoder().encode("legacy"));
    assert.equal(await runtime.readTextFile(legacy), "legacy");

    const tooLarge = file(
        "legacy-large.txt",
        new Uint8Array(),
        runtime.maxTextFileBytes + 1,
    );
    await assert.rejects(runtime.readTextFile(tooLarge), /2MB/);
});

test("opt-in file capture rejects malformed filename bindings before reading", async () => {
    const runtime = createRuntime();
    const spoofable = [
        filenameFields[0],
        { ...filenameFields[1], input_type: "text" },
    ];
    await assert.rejects(
        runtime.collectParams(
            { elements: { csv_text: { files: [file("x.csv", new TextEncoder().encode("x"))] } } },
            { fields: spoofable },
        ),
        /文件名字段/,
    );
});
