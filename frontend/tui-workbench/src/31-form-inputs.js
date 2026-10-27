    function fileCaptureDescriptor(field, fields) {
        const hasFilenameTarget = Object.prototype.hasOwnProperty.call(field, "file_name_field");
        const hasByteLimit = Object.prototype.hasOwnProperty.call(field, "max_bytes");
        if (!hasFilenameTarget && !hasByteLimit) {
            return null;
        }
        if (hasFilenameTarget !== hasByteLimit) {
            throw new Error("文件输入配置不完整");
        }
        if (
            field.input_type !== "file"
            || field.value_type !== "string"
            || field.binding !== "body"
            || !Number.isInteger(field.max_bytes)
            || field.max_bytes < 1
            || field.max_bytes > maxTextFileBytes
        ) {
            throw new Error("文件输入配置无效");
        }
        const filenameKey = field.file_name_field;
        if (
            typeof filenameKey !== "string"
            || !filenameKey.trim()
            || filenameKey === field.key
        ) {
            throw new Error("文件名字段配置无效");
        }
        const targets = fields.filter((candidate) => candidate.key === filenameKey);
        if (targets.length !== 1) {
            throw new Error("文件名字段必须唯一");
        }
        const target = targets[0];
        if (
            target.input_type !== "hidden"
            || target.value_type !== "string"
            || target.binding !== "body"
            || target.required !== true
            || (Object.prototype.hasOwnProperty.call(target, "default") && target.default !== "")
        ) {
            throw new Error("文件名字段必须是无预设值的隐藏文本字段");
        }
        return { filenameKey, maxBytes: field.max_bytes };
    }

    async function collectParams(form, action) {
        const params = {};
        if (!form) {
            return params;
        }
        const fields = (action && action.fields) || [];
        const fileCaptures = new Map();
        const filenameTargets = new Set();
        for (const field of fields) {
            const descriptor = fileCaptureDescriptor(field, fields);
            if (descriptor) {
                if (filenameTargets.has(descriptor.filenameKey)) {
                    throw new Error("文件名字段必须唯一");
                }
                filenameTargets.add(descriptor.filenameKey);
                fileCaptures.set(field.key, descriptor);
            }
        }

        const uploadedFilenames = [];
        for (const field of fields) {
            if (filenameTargets.has(field.key)) {
                continue;
            }
            const element = formFieldElement(form, field.key);
            if (!element) {
                continue;
            }
            if (field.input_type === "file") {
                if (element.files && element.files.length) {
                    const file = element.files[0];
                    const capture = fileCaptures.get(field.key);
                    if (capture) {
                        params[field.key] = await readTextFile(file, {
                            maxBytes: capture.maxBytes,
                            strictUtf8: true,
                        });
                        if (typeof file.name !== "string") {
                            throw new Error("无法读取文件名");
                        }
                        uploadedFilenames.push([capture.filenameKey, file.name]);
                    } else {
                        params[field.key] = await readTextFile(file);
                    }
                }
                continue;
            }
            const value = coerceFieldValue(field, element.value, element.checked);
            if (field.input_type === "checkbox" || value !== "") {
                params[field.key] = value;
            }
        }
        for (const [filenameKey, filename] of uploadedFilenames) {
            params[filenameKey] = filename;
        }
        return params;
    }

    async function readTextFile(file, options = {}) {
        const maxBytes = options.maxBytes ?? maxTextFileBytes;
        if (file && Number(file.size) > maxBytes) {
            throw options.strictUtf8 === true
                ? new Error("文件超过此输入允许的大小限制")
                : new Error("文件超过 2MB，请改用更小的文本文件");
        }
        if (options.strictUtf8 === true) {
            if (!file || typeof file.arrayBuffer !== "function") {
                throw new Error("浏览器无法读取所选文件");
            }
            const buffer = await file.arrayBuffer();
            if (buffer.byteLength > maxBytes || buffer.byteLength > maxTextFileBytes) {
                throw new Error("文件超过允许的大小限制");
            }
            if (buffer.byteLength === 0) {
                throw new Error("所选文件为空");
            }
            try {
                return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(buffer);
            } catch {
                throw new Error("文件不是有效的 UTF-8 文本");
            }
        }
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.addEventListener("load", () => resolve(String(reader.result || "")));
            reader.addEventListener("error", () => reject(reader.error || new Error("文件读取失败")));
            reader.readAsText(file, "utf-8");
        });
    }
