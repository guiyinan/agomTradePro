    function renderViewModel(viewModel) {
        if (!viewModel) {
            renderError("没有返回可渲染的业务视图。");
            return;
        }
        state.currentViewModel = viewModel;
        setWorkspaceViewKind(viewModel.kind || "message");
        els.mainTitle.textContent = (viewModel.title || "视图").toUpperCase();
        if (renderRegisteredRenderer(viewModel, els.main)) {
            resetGridState({ preserveRowContext: true });
        } else if (viewModel.kind === "datagrid") {
            renderDataGrid(viewModel);
        } else {
            resetGridState({ preserveRowContext: true });
            renderNonGridView(viewModel);
        }
        bindDecisionCueActions();
        bindCopyButtons(els.main);
        if (viewModel.kind !== "datagrid") {
            updatePager(viewModel.pager || null);
        }
        refreshRowFillButtons();
    }

    function renderNonGridView(viewModel) {
        if (requiresMissingRendererFallback(viewModel)) {
            renderCustomFallback(viewModel);
            return;
        }
        const renderers = {
            detail: renderDetail,
            chart: renderChart,
            image: renderImage,
            kpi_trend: renderKpiTrend,
            table_chart: renderTableChart,
            host_slot: renderHostSlot,
            custom: renderCustomFallback,
            message: renderMessage,
        };
        (renderers[viewModel.kind] || renderMessage)(viewModel);
    }

    function renderRegisteredRenderer(viewModel, container) {
        const rendererName = String(viewModel.renderer || "").trim();
        if (!rendererName || builtInRendererNames.has(rendererName)) {
            return false;
        }
        const renderer = rendererRegistry.get(rendererName);
        if (!renderer) {
            return false;
        }
        container.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status || "正常")} / ${escapeHtml(viewModel.title || rendererName)}</div>
            ${renderDecisionCue(viewModel)}
            <div class="tui-extension-host" data-renderer="${escapeHtml(rendererName)}"></div>
        `;
        const host = container.querySelector(".tui-extension-host");
        try {
            renderer({
                viewModel,
                container: host,
                runtimeConfig,
                escapeHtml,
            });
        } catch (_error) {
            host.innerHTML = renderEmptyState("扩展视图暂时不可用。", ["请稍后重试，或改用默认任务查看数据。"]);
        }
        return true;
    }

    function requiresMissingRendererFallback(viewModel) {
        const rendererName = String(viewModel.renderer || "").trim();
        if (!rendererName || builtInRendererNames.has(rendererName)) {
            return false;
        }
        return ["chart", "kpi_trend", "table_chart", "host_slot", "custom"].includes(viewModel.kind);
    }

    function renderDataGrid(viewModel) {
        state.currentViewModel = viewModel;
        state.currentColumns = viewModel.columns || [];
        state.currentRows = viewModel.rows || [];
        state.clientPage = 1;
        applyFilter(false);
    }

    function rowMatchesFilter(row) {
        const needle = state.filterText.trim().toLowerCase();
        if (!needle) {
            return true;
        }
        return Object.values(row || {}).some((value) => String(value ?? "").toLowerCase().includes(needle));
    }

    function applyFilter(announce) {
        if (!state.currentViewModel || state.currentViewModel.kind !== "datagrid") {
            if (announce) {
                setStatus("当前视图不可筛选");
            }
            return;
        }
        if (announce) {
            state.clientPage = 1;
        }
        state.visibleRows = state.currentRows.filter(rowMatchesFilter);
        state.selectedRowIndex = Math.min(state.selectedRowIndex, Math.max(0, state.visibleRows.length - 1));
        drawDataGrid();
        if (announce) {
            setStatus(state.filterText ? `筛选 ${state.visibleRows.length}/${state.currentRows.length}` : "筛选已清除");
        }
    }

    function drawDataGrid() {
        const viewModel = state.currentViewModel;
        const columns = state.currentColumns;
        const allRows = state.visibleRows;
        const localPage = !viewModel.pager && typeof runtimeCore.clientPage === "function"
            ? runtimeCore.clientPage(allRows, state.clientPage, state.clientPageSize)
            : { rows: allRows, pager: null };
        const rows = localPage.rows;
        const activePager = viewModel.pager || localPage.pager;
        state.lastPager = activePager;
        const pageOffset = localPage.pager
            ? (localPage.pager.page - 1) * state.clientPageSize
            : 0;
        const filterSuffix = state.filterText ? ` / 筛选: ${state.filterText} (${allRows.length}/${state.currentRows.length})` : "";
        const emptyMessage = state.filterText
            ? "没有匹配的记录。"
            : (viewModel.empty_message || "暂无可显示数据。");
        const gridBody = rows.length && columns.length
            ? `
                <table>
                    <thead>
                        <tr>${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr>
                    </thead>
                    <tbody>
                        ${rows.map((row, rowIndex) => {
                            const globalIndex = pageOffset + rowIndex;
                            return `
                            <tr data-row-index="${globalIndex}" class="${globalIndex === state.selectedRowIndex ? "is-selected" : ""}">
                                ${columns.map((column) => {
                                    const value = displayValue(row[column.key]);
                                    return `<td class="${cellClass(value, column.label || column.key)}" title="${escapeHtml(value)}">${escapeHtml(value)}</td>`;
                                }).join("")}
                            </tr>
                        `;
                        }).join("")}
                    </tbody>
                </table>
            `
            : renderEmptyState(
                emptyMessage,
                state.filterText ? ["清空筛选后查看全部记录。"] : viewModel.empty_guidance,
                state.filterText ? [] : viewModel.next_steps,
            );
        els.main.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status)} / ${escapeHtml(viewModel.title)}${escapeHtml(filterSuffix)}</div>
            ${renderDecisionCue(viewModel)}
            <div class="tui-datagrid" role="grid" tabindex="0" aria-label="${escapeHtml(viewModel.title)}">
                ${gridBody}
            </div>
            ${renderDataGridPager(activePager)}
        `;
        els.main.querySelectorAll("[data-row-index]").forEach((row) => {
            row.addEventListener("click", () => selectRow(Number(row.dataset.rowIndex || 0)));
            row.addEventListener("dblclick", () => openSelectedRowDetail());
        });
        els.main.querySelectorAll("[data-page-delta]").forEach((button) => {
            button.addEventListener("click", () => pageDelta(Number(button.dataset.pageDelta || 0)));
        });
        bindNextStepButtons(els.main, viewModel.next_steps);
        if (rows.length) {
            if (state.selectedRowIndex < pageOffset || state.selectedRowIndex >= pageOffset + rows.length) {
                state.selectedRowIndex = pageOffset;
            }
            if (pageOffset === 0) {
                state.selectedRowContext = rowContextWithSource(rows[state.selectedRowIndex]);
            } else {
                state.selectedRowContext = rowContextWithSource(state.visibleRows[state.selectedRowIndex]);
            }
        } else {
            state.selectedRowContext = null;
        }
        updatePager(activePager);
        renderSelectedRowInspector();
        refreshRowFillButtons();
    }

    function renderDataGridPager(pager) {
        if (!pager) {
            return "";
        }
        const page = pager.page ?? "-";
        const totalPages = pager.total_pages ?? "-";
        const totalRows = pager.total_rows ?? 0;
        return `
            <div class="tui-datagrid-pager" aria-label="分页">
                <button type="button" data-page-delta="-1" ${pager.has_previous ? "" : "disabled"}>上一页</button>
                <span>第 ${escapeHtml(page)} / ${escapeHtml(totalPages)} 页</span>
                <span>共 ${escapeHtml(totalRows)} 行</span>
                <button type="button" data-page-delta="1" ${pager.has_next ? "" : "disabled"}>下一页</button>
            </div>
        `;
    }

    function renderEmptyState(message, guidance, nextSteps = []) {
        const lines = (guidance || []).filter(Boolean);
        const steps = Array.isArray(nextSteps) ? nextSteps : [];
        return `
            <div class="tui-empty-state tui-empty-guidance">
                <strong>${escapeHtml(message)}</strong>
                ${lines.length ? `
                    <ul>
                        ${lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}
                    </ul>
                ` : ""}
                ${steps.length ? `
                    <div class="tui-entry-actions">
                        ${steps.map((step, index) => `
                            <button type="button" data-next-step-index="${index}">
                                ${escapeHtml(step.label || "继续")}
                            </button>
                        `).join("")}
                    </div>
                ` : ""}
            </div>
        `;
    }

    function bindNextStepButtons(container, nextSteps) {
        container.querySelectorAll("[data-next-step-index]").forEach((button) => {
            button.addEventListener("click", () => {
                const index = Number(button.dataset.nextStepIndex || 0);
                executeNextStep((nextSteps || [])[index]);
            });
        });
    }

    function executeNextStep(step) {
        if (!step) {
            return;
        }
        if (step.action_key) {
            const params = step.params && typeof step.params === "object" ? { ...step.params } : {};
            runAction(step.action_key, null, { params });
            return;
        }
        if (step.screen_key) {
            loadScreen(step.screen_key);
            return;
        }
        setStatus(step.hint || "已记录下一步");
    }

    function renderChart(viewModel) {
        renderSemanticView(viewModel, "图表", renderChartMarkup);
    }

    function renderImage(viewModel) {
        renderSemanticView(viewModel, "图片", renderImageMarkup);
    }

    function renderKpiTrend(viewModel) {
        renderSemanticView(viewModel, "指标趋势", renderKpiTrendMarkup);
    }

    function renderTableChart(viewModel) {
        renderSemanticView(viewModel, "表格图表", renderTableChartMarkup);
    }

    function renderHostSlot(viewModel) {
        renderSemanticView(viewModel, "宿主插槽", renderHostSlotMarkup);
        processHostSlot(els.main);
    }

    function renderCustomFallback(viewModel) {
        renderSemanticView(viewModel, "自定义视图", renderExtensionFallback);
    }

    function renderSemanticView(viewModel, fallbackTitle, renderMarkup) {
        els.main.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status || "正常")} / ${escapeHtml(viewModel.title || fallbackTitle)}</div>
            ${renderDecisionCue(viewModel)}
            ${renderMarkup(viewModel)}
        `;
    }

    function renderChartMarkup(viewModel, options = {}) {
        const compact = Boolean(options.compact);
        const chartType = String(viewModel.chart_type || viewModel.renderer || "line").toLowerCase();
        const series = chartSeries(viewModel);
        const points = series.flatMap((item) => item.points);
        if (!points.length) {
            return renderEmptyState(
                viewModel.empty_message || "暂无图表数据。",
                viewModel.empty_guidance,
                viewModel.next_steps,
            );
        }
        const svg = chartType === "pie"
            ? renderPieSvg(series[0].points)
            : chartType === "bar"
                ? renderBarSvg(series[0].points)
                : renderLineSeriesSvg(series);
        const legend = chartType === "line"
            ? series.map((item, index) => {
                const latest = item.points[item.points.length - 1];
                return `
                    <span class="tui-chart-series-legend">
                        <i class="series-${index % 6}"></i>
                        ${escapeHtml(item.label)} ${escapeHtml(formatNumber(latest.value))}
                    </span>
                `;
            }).join("")
            : series[0].points.slice(0, compact ? 4 : 8).map((point) => `
                <span><i></i>${escapeHtml(point.label)} ${escapeHtml(formatNumber(point.value))}</span>
            `).join("");
        return `
            <section class="tui-rich-view tui-chart-view ${compact ? "is-compact" : ""}">
                <div class="tui-rich-header">
                    <strong>${escapeHtml(viewModel.title || "Chart")}</strong>
                    <span>${escapeHtml(chartType.toUpperCase())}</span>
                </div>
                ${svg}
                <div class="tui-chart-legend">${legend}</div>
                ${renderChartTextSummary(series, viewModel)}
            </section>
        `;
    }

    function renderImageMarkup(viewModel, options = {}) {
        const source = imageSourceFromViewModel(viewModel);
        if (!source) {
            return renderEmptyState(viewModel.empty_message || "暂无图片链接。", []);
        }
        const alt = String(viewModel.alt || viewModel.caption || viewModel.title || "Image");
        const caption = String(viewModel.caption || "");
        const title = String(viewModel.title || "Image");
        return `
            <figure class="tui-rich-view tui-image-view ${options.compact ? "is-compact" : ""}">
                <div class="tui-rich-header">
                    <strong>${escapeHtml(title)}</strong>
                    <span>IMAGE</span>
                </div>
                <button class="tui-image-frame" type="button"
                        data-image-preview
                        data-image-src="${escapeHtml(source)}"
                        data-image-alt="${escapeHtml(alt)}"
                        data-image-caption="${escapeHtml(caption)}"
                        data-image-title="${escapeHtml(title)}">
                    <img src="${escapeHtml(source)}" alt="${escapeHtml(alt)}" loading="lazy" decoding="async">
                </button>
                ${caption ? `<figcaption>${escapeHtml(caption)}</figcaption>` : ""}
            </figure>
        `;
    }

    function imageSourceFromViewModel(viewModel) {
        const candidates = [
            viewModel.url,
            viewModel.src,
            viewModel.image_url,
            viewModel.imageUrl,
            viewModel.href,
        ];
        for (const candidate of candidates) {
            const source = normalizeImageSource(candidate);
            if (source) {
                return source;
            }
        }
        return "";
    }

    function normalizeImageSource(value) {
        const raw = String(value || "").trim();
        if (!raw) {
            return "";
        }
        try {
            const url = new URL(raw, window.location.href);
            if (url.protocol === "http:" || url.protocol === "https:") {
                return raw;
            }
            if (url.protocol === "data:" && /^data:image\/(?:apng|avif|gif|jpe?g|png|webp);/i.test(raw)) {
                return raw;
            }
            if (url.protocol === "data:" && allowSvgDataImages && /^data:image\/svg\+xml(?:[;,]|$)/i.test(raw)) {
                return raw;
            }
        } catch (_error) {
            return "";
        }
        return "";
    }

    function renderKpiTrendMarkup(viewModel, options = {}) {
        const points = (viewModel.trend || []).map(normalizePoint).filter(Boolean);
        const values = points.map((point) => point.value);
        const explicitValue = Number.parseFloat(viewModel.value);
        if (!values.length && !Number.isFinite(explicitValue)) {
            return `
                <div class="tui-panel-placeholder tui-contract-error" data-render-contract-error="kpi_trend">
                    <div>指标结果数据不完整，已停止展示占位数值。</div>
                    <small>请刷新后重试；若持续出现，请检查数据同步与结果投影。</small>
                </div>
            `;
        }
        const first = values.length ? values[0] : explicitValue;
        const last = values.length ? values[values.length - 1] : explicitValue;
        const delta = last - first;
        const directionClass = delta >= 0 ? "is-up" : "is-down";
        return `
            <section class="tui-rich-view tui-kpi-view ${options.compact ? "is-compact" : ""}">
                <div class="tui-kpi-main">
                    <span>${escapeHtml(viewModel.label || viewModel.title || "KPI")}</span>
                    <strong>${escapeHtml(hasDisplayValue(viewModel.value) ? viewModel.value : formatNumber(last))}</strong>
                    <em class="${directionClass}">${delta >= 0 ? "+" : ""}${escapeHtml(formatNumber(delta))}</em>
                </div>
                ${points.length ? `<div class="tui-kpi-spark">${renderLineSvg(points, { spark: true })}</div>` : ""}
            </section>
        `;
    }

    function renderTableChartMarkup(viewModel, options = {}) {
        const chart = viewModel.chart || {};
        const table = viewModel.table || {};
        return `
            <section class="tui-rich-view tui-table-chart-view ${options.compact ? "is-compact" : ""}">
                ${renderChartMarkup({ ...chart, title: chart.title || viewModel.title }, { compact: options.compact })}
                <div class="tui-table-chart-grid">
                    ${renderPanelDataGrid({ max_rows: options.compact ? 4 : 10, columns: table.columns || [] }, table)}
                </div>
            </section>
        `;
    }

    function renderHostSlotMarkup(viewModel, options = {}) {
        const allowHostHtml = Boolean(runtimeConfig.allowHostHtmlSlots);
        const html = String(viewModel.partial_html || "");
        const message = viewModel.fallback_message || "宿主插槽内容由宿主应用控制。";
        if (!allowHostHtml || !html) {
            return `
                <section class="tui-rich-view tui-host-slot ${options.compact ? "is-compact" : ""}">
                    <div class="tui-rich-header">
                        <strong>${escapeHtml(viewModel.slot_key || viewModel.title || "host-slot")}</strong>
                        <span>HOST SLOT</span>
                    </div>
                    ${renderEmptyState(message, allowHostHtml ? [] : ["当前 runtime 未开启 allowHostHtmlSlots。"])}
                </section>
            `;
        }
        return `
            <section class="tui-rich-view tui-host-slot ${options.compact ? "is-compact" : ""}" data-host-slot="${escapeHtml(viewModel.slot_key || "")}">
                ${html}
            </section>
        `;
    }

    function processHostSlot(container) {
        if (runtimeConfig.allowHostHtmlSlots && window.htmx && typeof window.htmx.process === "function") {
            container.querySelectorAll(".tui-host-slot").forEach((slot) => window.htmx.process(slot));
        }
    }

    function renderExtensionFallback(viewModel) {
        const rendererName = String(viewModel.renderer || "").trim() || "custom";
        return renderEmptyState(
            viewModel.fallback_message || `没有注册 renderer: ${rendererName}`,
            ["宿主可以通过 window.AgomTUIRenderers.register(name, rendererFn) 注册扩展。"],
        );
    }

    function chartPoints(viewModel) {
        return chartSeries(viewModel)[0]?.points || [];
    }

    function chartSeries(viewModel) {
        const sourceSeries = Array.isArray(viewModel.series) ? viewModel.series : [];
        const normalizedSeries = sourceSeries
            .filter((item) => Array.isArray(item?.points))
            .map((item, index) => ({
                key: String(item.key || `series-${index + 1}`),
                label: String(item.label || item.name || `序列 ${index + 1}`),
                points: item.points.map(normalizePoint).filter(Boolean),
            }))
            .filter((item) => item.points.length);
        if (normalizedSeries.length) {
            return normalizedSeries;
        }
        const points = (Array.isArray(viewModel.points) ? viewModel.points : [])
            .map(normalizePoint)
            .filter(Boolean);
        return points.length ? [{ key: "value", label: String(viewModel.label || viewModel.title || "数值"), points }] : [];
    }

    function renderChartTextSummary(series, viewModel) {
        const xAxisLabel = String(viewModel.x_axis_label || "横轴");
        return `
            <dl class="tui-chart-accessible-summary" aria-label="图表文本摘要">
                <div><dt>横轴</dt><dd>${escapeHtml(xAxisLabel)}</dd></div>
                ${series.map((item) => {
                    const first = item.points[0];
                    const latest = item.points[item.points.length - 1];
                    return `
                        <div>
                            <dt>${escapeHtml(item.label)}</dt>
                            <dd>${escapeHtml(first.label)} ${escapeHtml(formatNumber(first.value))}
                                至 ${escapeHtml(latest.label)} ${escapeHtml(formatNumber(latest.value))}</dd>
                        </div>
                    `;
                }).join("")}
            </dl>
        `;
    }

    function normalizePoint(point, index = 0) {
        if (point === null || point === undefined) {
            return null;
        }
        if (typeof point === "number") {
            return { label: String(index + 1), value: point };
        }
        const value = Number.parseFloat(point.value ?? point.y ?? point.count ?? point.total);
        if (!Number.isFinite(value)) {
            return null;
        }
        return {
            label: String(point.label ?? point.x ?? point.name ?? index + 1),
            value,
        };
    }

    function chartScale(points, width, height, padding) {
        const values = points.map((point) => point.value);
        const min = Math.min(0, ...values);
        const max = Math.max(1, ...values);
        const span = max - min || 1;
        return {
            x(index) {
                if (points.length <= 1) {
                    return width / 2;
                }
                return padding + (index / (points.length - 1)) * (width - padding * 2);
            },
            y(value) {
                return height - padding - ((value - min) / span) * (height - padding * 2);
            },
        };
    }

    function renderLineSvg(points, options = {}) {
        const width = options.spark ? 240 : 640;
        const height = options.spark ? 72 : 220;
        const padding = options.spark ? 8 : 28;
        const scale = chartScale(points, width, height, padding);
        const path = points.map((point, index) => `${index === 0 ? "M" : "L"}${scale.x(index).toFixed(1)} ${scale.y(point.value).toFixed(1)}`).join(" ");
        return `
            <svg class="tui-chart-svg ${options.spark ? "is-spark" : ""}" viewBox="0 0 ${width} ${height}" aria-hidden="true">
                <path class="tui-chart-gridline" d="M${padding} ${height - padding}H${width - padding}"></path>
                <path class="tui-chart-line" d="${escapeHtml(path)}"></path>
                ${points.map((point, index) => `<circle class="tui-chart-point" cx="${scale.x(index).toFixed(1)}" cy="${scale.y(point.value).toFixed(1)}" r="${options.spark ? 2 : 3}"></circle>`).join("")}
            </svg>
        `;
    }

    function renderLineSeriesSvg(series) {
        const width = 640;
        const height = 220;
        const padding = 28;
        const allPoints = series.flatMap((item) => item.points);
        const labels = [...new Set(allPoints.map((point) => point.label))];
        const scale = chartScale(allPoints, width, height, padding);
        const xFor = (label) => {
            if (labels.length <= 1) {
                return width / 2;
            }
            const index = Math.max(0, labels.indexOf(label));
            return padding + (index / (labels.length - 1)) * (width - padding * 2);
        };
        return `
            <svg class="tui-chart-svg" viewBox="0 0 ${width} ${height}" aria-hidden="true">
                <path class="tui-chart-gridline" d="M${padding} ${height - padding}H${width - padding}"></path>
                ${series.map((item, seriesIndex) => {
                    const path = item.points.map((point, index) => `${index === 0 ? "M" : "L"}${xFor(point.label).toFixed(1)} ${scale.y(point.value).toFixed(1)}`).join(" ");
                    return `
                        <path class="tui-chart-line series-${seriesIndex % 6}" d="${escapeHtml(path)}"></path>
                        ${item.points.map((point) => `<circle class="tui-chart-point series-${seriesIndex % 6}" cx="${xFor(point.label).toFixed(1)}" cy="${scale.y(point.value).toFixed(1)}" r="3"></circle>`).join("")}
                    `;
                }).join("")}
            </svg>
        `;
    }

    function renderBarSvg(points) {
        const width = 640;
        const height = 220;
        const padding = 28;
        const values = points.map((point) => point.value);
        const max = Math.max(0, ...values);
        const min = Math.min(0, ...values);
        const span = max - min || 1;
        const yFor = (value) => height - padding - ((value - min) / span) * (height - padding * 2);
        const zeroY = yFor(0);
        const barGap = 8;
        const barWidth = Math.max(8, (width - padding * 2 - barGap * (points.length - 1)) / points.length);
        return `
            <svg class="tui-chart-svg" viewBox="0 0 ${width} ${height}" aria-hidden="true">
                <path class="tui-chart-gridline" d="M${padding} ${zeroY.toFixed(1)}H${width - padding}"></path>
                ${points.map((point, index) => {
                    const x = padding + index * (barWidth + barGap);
                    const valueY = yFor(point.value);
                    const y = Math.min(zeroY, valueY);
                    const barHeight = Math.max(2, Math.abs(valueY - zeroY));
                    return `<rect class="tui-chart-bar" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}"></rect>`;
                }).join("")}
            </svg>
        `;
    }

    function renderPieSvg(points) {
        const total = points.reduce((sum, point) => sum + Math.max(0, point.value), 0) || 1;
        let offset = 0;
        const slices = points.map((point, index) => {
            const value = Math.max(0, point.value);
            const dash = (value / total) * 100;
            const slice = `<circle class="tui-chart-pie-slice slice-${index % 6}" r="70" cx="100" cy="100" pathLength="100" stroke-dasharray="${dash} ${100 - dash}" stroke-dashoffset="${-offset}"></circle>`;
            offset += dash;
            return slice;
        }).join("");
        return `
            <svg class="tui-chart-svg tui-chart-pie" viewBox="0 0 200 200" aria-hidden="true">
                ${slices}
                <circle class="tui-chart-pie-hole" r="38" cx="100" cy="100"></circle>
            </svg>
        `;
    }

    function formatNumber(value) {
        if (value === null || value === undefined || String(value).trim() === "") {
            return "-";
        }
        const number = Number(value);
        if (!Number.isFinite(number)) {
            return String(value ?? "-");
        }
        return Math.abs(number) >= 100 ? number.toFixed(0) : number.toFixed(2).replace(/\.00$/, "");
    }

    function renderDetail(viewModel) {
        const semantics = currentActionSemantics();
        const detailBody = semantics.length
            ? renderSemanticDetailView(viewModel, semantics)
            : renderSemanticGridFields(viewModel.fields || []);
        const isEmpty = !detailBody;
        const nested = semantics.length ? [] : (viewModel.nested || []);
        els.main.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status)} / ${escapeHtml(viewModel.title)}</div>
            ${renderDecisionCue(viewModel)}
            ${detailBody || renderEmptyState(
                viewModel.empty_message || "暂无摘要数据。",
                viewModel.empty_guidance,
                viewModel.next_steps,
            )}
            ${nested.length ? `
                <div class="tui-nested-list">
                    ${nested.map((item) => `<span>${escapeHtml(item.label)}: ${escapeHtml(item.count)} 行</span>`).join("")}
                </div>
            ` : ""}
            ${!isEmpty && Array.isArray(viewModel.next_steps) && viewModel.next_steps.length ? renderEmptyState("建议下一步", [], viewModel.next_steps) : ""}
        `;
        bindNextStepButtons(els.main, viewModel.next_steps);
    }

    function renderMessage(viewModel) {
        const sections = Array.isArray(viewModel.sections) ? viewModel.sections : [];
        const body = sections.length
            ? sections.map((section) => `
                <section class="tui-message-section">
                    <h4>${escapeHtml(section.title || "摘要")}</h4>
                    ${(section.body || []).map((line) => `<p>${escapeHtml(line)}</p>`).join("")}
                    ${(section.rows || []).length ? `
                        <dl class="tui-message-fields">
                            ${section.rows.map((row) => `
                                <dt>${escapeHtml(row.label)}</dt>
                                <dd>${escapeHtml(row.value)}</dd>
                            `).join("")}
                        </dl>
                    ` : ""}
                </section>
            `).join("")
            : `<div class="tui-message">${escapeHtml(viewModel.message || "")}</div>`;
        els.main.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status || "正常")} / ${escapeHtml(viewModel.title || "消息")}</div>
            ${renderDecisionCue(viewModel)}
            <div class="tui-message-list">${body}</div>
            ${Array.isArray(viewModel.next_steps) && viewModel.next_steps.length ? renderEmptyState("建议下一步", [], viewModel.next_steps) : ""}
        `;
        bindNextStepButtons(els.main, viewModel.next_steps);
    }

    function renderDecisionCue(viewModel) {
        const screen = state.screen?.screen || {};
        const context = screen.business_context || {};
        if (!context.decision_output && !context.objective && !viewModel?.business_summary) {
            return "";
        }
        const workflow = screen.workflow || {};
        const next = workflow.next || {};
        const actions = (state.screen && state.screen.actions) || [];
        const summary = summarizeActions(actions);
        const evidence = resultEvidenceLabel(viewModel);
        const businessSummary = String(viewModel?.business_summary || "").trim();
        const rows = [
            ["判断产出", businessSummary || context.decision_output || context.objective],
            ["当前证据", evidence],
        ];
        if (viewModel?.blocking_reason) {
            rows.push(["当前阻断", viewModel.blocking_reason]);
        }
        const cueActions = [];
        if (summary.operation) {
            rows.push(["可执行操作", `${summary.operation} 项，提交前确认`]);
        }
        const progress = screenProgress(actions);
        if (progress.total) {
            rows.push(["本屏进度", `${progress.completed}/${progress.total}`]);
        }
        const nextPrimary = nextPrimaryAction();
        if (nextPrimary) {
            rows.push(["本屏下一项", nextPrimary.label]);
            cueActions.push({
                command: "next-primary",
                label: nextPrimary.label,
                key: "F6",
                title: "运行下一主流程",
            });
        }
        if (next.label) {
            rows.push(["下一步", next.label]);
            cueActions.push({
                command: "workflow-next",
                label: next.label,
                key: "F4",
                title: "进入流程下一屏",
            });
        }
        return `
            <section class="tui-decision-cue">
                ${rows.map(([label, value]) => `
                    <div>
                        <span>${escapeHtml(label)}</span>
                        <strong>${escapeHtml(value)}</strong>
                    </div>
                `).join("")}
                ${cueActions.length ? `
                    <div class="tui-decision-actions">
                        <span>继续</span>
                        <strong>
                            ${cueActions.map((action) => `
                                <button type="button" data-decision-action="${escapeHtml(action.command)}">
                                    ${escapeHtml(action.title)}: ${escapeHtml(action.label)}
                                    <kbd>${escapeHtml(action.key)}</kbd>
                                </button>
                            `).join("")}
                        </strong>
                    </div>
                ` : ""}
            </section>
        `;
    }

    function bindDecisionCueActions() {
        els.main.querySelectorAll("[data-decision-action]").forEach((button) => {
            button.addEventListener("click", () => {
                const command = button.dataset.decisionAction;
                if (command === "next-primary") {
                    runNextPrimaryAction();
                } else if (command === "workflow-next") {
                    loadWorkflowStep(1);
                }
            });
        });
    }

    function resultEvidenceLabel(viewModel) {
        if (!viewModel) {
            return "尚未返回业务视图";
        }
        if (viewModel.kind === "datagrid") {
            const total = viewModel.pager?.total_rows ?? state.currentRows.length;
            if (state.filterText) {
                return `筛选后 ${state.visibleRows.length}/${state.currentRows.length} 行`;
            }
            return `表格 ${state.currentRows.length}/${total} 行`;
        }
        if (viewModel.kind === "detail") {
            const fields = (viewModel.fields || []).length;
            const nested = (viewModel.nested || []).reduce((count, item) => count + Number(item.count || 0), 0);
            return nested ? `详情 ${fields} 项，关联 ${nested} 行` : `详情 ${fields} 项`;
        }
        if (viewModel.kind === "chart") {
            const points = chartPoints(viewModel).length;
            return `图表 ${points} 点`;
        }
        if (viewModel.kind === "kpi_trend") {
            const points = (viewModel.trend || []).length;
            return points ? `指标趋势 ${points} 点` : "指标趋势";
        }
        if (viewModel.kind === "table_chart") {
            const rows = viewModel.table?.rows?.length || 0;
            return `图表表格 ${rows} 行`;
        }
        if (viewModel.kind === "host_slot") {
            return "宿主插槽";
        }
        if (viewModel.kind === "custom") {
            return `自定义 ${viewModel.renderer || "renderer"}`;
        }
        const sections = (viewModel.sections || []).length;
        return sections ? `消息 ${sections} 段` : "消息结果";
    }

    function renderInspector(info) {
        const sections = Array.isArray(info.sections) ? info.sections : [];
        const rows = normalizeInspectorRows(info.rows || []);
        const bodyLines = operatorText(info.body || "").split(/\n+/).map((line) => line.trim()).filter(Boolean);
        const rowsTitle = operatorText(info.rowsTitle || "流程状态");
        els.inspector.innerHTML = `
            <section class="tui-inspector-card tui-inspector-summary">
                <div class="tui-inspector-title">${escapeHtml(info.title || "说明")}</div>
                ${bodyLines.map((line) => `<p>${escapeHtml(line)}</p>`).join("")}
            </section>
            ${rows.length ? `
                <section class="tui-inspector-card">
                    <div class="tui-inspector-title">${escapeHtml(rowsTitle)}</div>
                    <dl class="tui-inspector-grid">
                        ${rows.map((row) => `
                            <dt>${escapeHtml(row.label)}</dt>
                            <dd>${escapeHtml(row.value)}</dd>
                        `).join("")}
                    </dl>
                </section>
            ` : ""}
            ${sections.length ? `
                <div class="tui-inspector-sections">
                    ${sections.map((section) => `
                        <section class="tui-message-section">
                            <h4>${escapeHtml(operatorText(section.title || "摘要"))}</h4>
                            ${(section.body || []).map((line) => `<p>${escapeHtml(operatorText(line))}</p>`).join("")}
                            ${(section.actions || []).length ? `
                                <div class="tui-inspector-actions">
                                    ${section.actions.map((action) => `
                                        <button type="button" data-inspector-action="${escapeHtml(action.ui_key)}">
                                            <span>${escapeHtml(action.label)}</span>
                                            <kbd>${escapeHtml(action.verb)}</kbd>
                                        </button>
                                    `).join("")}
                                </div>
                            ` : ""}
                            ${(section.rows || []).length ? `
                                <dl class="tui-message-fields">
                                    ${normalizeInspectorRows(section.rows).map((row) => `
                                        <dt>${escapeHtml(row.label)}</dt>
                                        <dd>${escapeHtml(row.value)}</dd>
                                    `).join("")}
                                </dl>
                            ` : ""}
                        </section>
                    `).join("")}
                </div>
            ` : ""}
        `;
        els.inspector.querySelectorAll("[data-inspector-action]").forEach((button) => {
            button.addEventListener("click", () => runInspectorAction(button.dataset.inspectorAction));
        });
    }

    function normalizeInspectorRows(rows) {
        return (rows || []).map((row) => {
            if (Array.isArray(row)) {
                return { label: row[0], value: row[1] };
            }
            return { label: row.label, value: row.value };
        }).filter((row) => row.label !== undefined && row.value !== undefined)
            .map((row) => ({
                label: operatorText(row.label),
                value: operatorText(row.value),
            }));
    }

    function inspectorFlowRows(result) {
        const progress = screenProgress();
        const nextAction = nextPrimaryAction();
        const operationCount = ((state.screen && state.screen.actions) || [])
            .filter((action) => actionTier(action) === "operation")
            .length;
        const rows = [
            ["操作方式", actionVerbLabel(result.action)],
            ["本屏进度", `${progress.completed}/${progress.total}`],
        ];
        if (nextAction && nextAction.key !== result.action.key) {
            rows.push(["下一项", nextAction.label]);
        }
        if (operationCount) {
            rows.push(["可执行操作", `${operationCount} 项`]);
        }
        if (result.action.confirmation_required) {
            rows.push(["确认策略", "提交前会要求确认"]);
        }
        return rows;
    }

    function renderResultInspector(result, viewModel) {
        const businessContext = state.screen?.screen?.business_context || {};
        const contextSections = businessContextSections(businessContext);
        const operationActions = ((state.screen && state.screen.actions) || [])
            .filter((action) => actionTier(action) === "operation")
            .slice(0, 5)
            .map((action) => `${action.label} / ${actionVerbLabel(action)}`);
        const actionRows = inspectorFlowRows(result);
        const sections = [
            ...contextSections,
            ...(operationActions.length ? [{
                title: "后续动作",
                body: operationActions,
                rows: [],
            }] : []),
        ];
        if (!viewModel) {
            renderInspector({
                title: result.action.label,
                body: result.action.description || "",
                rows: actionRows,
                sections,
            });
            return;
        }
        if (viewModel.kind === "detail") {
            renderInspector({
                title: "操作说明",
                body: result.action.description || "中间主面板显示完整业务明细，右栏只保留流程、证据与后续动作。",
                rowsTitle: "流程状态",
                rows: actionRows,
                sections: [
                    {
                        title: "阅读提示",
                        body: ["完整业务明细已在中间主面板显示。右栏不再重复渲染同一对象。"],
                        rows: [],
                    },
                    ...sections,
                ],
            });
            return;
        }
        if (viewModel.kind === "message") {
            renderInspector({
                title: "操作说明",
                body: result.action.description || "中间主面板显示当前结果说明，右栏保留导航与后续动作。",
                rowsTitle: "流程状态",
                rows: actionRows,
                sections: [
                    {
                        title: "阅读提示",
                        body: ["结果说明已在中间主面板显示。右栏保留流程导航、业务目标与后续动作。"],
                        rows: [],
                    },
                    ...sections,
                ],
            });
            return;
        }
        renderSelectedRowInspector([
            ...actionRows,
            ...operationActions.slice(0, 3).map((label, index) => [`可执行动作 ${index + 1}`, label]),
        ]);
    }

    function renderError(message) {
        els.main.innerHTML = `<div class="tui-error">${escapeHtml(message)}</div>`;
        updatePager(null);
        setStatus("错误");
    }

    function updatePager(pager) {
        state.lastPager = pager;
        if (!pager) {
            els.pager.textContent = "";
            els.pager.hidden = true;
            return;
        }
        els.pager.hidden = false;
        els.pager.textContent = `页 ${pager.page}/${pager.total_pages} | ${pager.total_rows} 行 | ${pager.has_previous ? "PgUp" : "--"} / ${pager.has_next ? "PgDn" : "--"}`;
    }

    function updateRawDrawer() {
        els.rawPanel.textContent = state.lastRaw === null ? "尚未加载原始响应。" : JSON.stringify(state.lastRaw, null, 2);
    }

    function toggleRawDrawer(show) {
        els.rawDrawer.hidden = typeof show === "boolean" ? !show : !els.rawDrawer.hidden;
        setStatus(els.rawDrawer.hidden ? "原始响应关闭" : "原始响应打开");
    }

    function selectRow(index) {
        state.selectedRowIndex = index;
        els.main.querySelectorAll("[data-row-index]").forEach((row) => {
            row.classList.toggle("is-selected", Number(row.dataset.rowIndex || 0) === index);
        });
        const row = state.visibleRows[index];
        state.selectedRowContext = rowContextWithSource(row);
        if (row) {
            setStatus(`行 ${index + 1}/${state.visibleRows.length}`);
            renderSelectedRowInspector();
        }
        refreshRowFillButtons();
    }

    function renderSelectedRowInspector(prefixRows = []) {
        if (!state.currentViewModel || state.currentViewModel.kind !== "datagrid") {
            return;
        }
        const row = state.visibleRows[state.selectedRowIndex];
        const rows = row
            ? rowDisplayRows(row, 14)
            : [["状态", state.filterText ? "没有匹配记录" : "暂无记录"]];
        const rowContext = rowContextWithSource(row);
        const rowActions = rowContext ? actionsAvailableForRow(rowContext) : [];
        const sections = [];
        if (rowActions.length) {
            sections.push({
                title: "选中行可做",
                body: ["直接使用选中记录填入参数。"],
                actions: rowActions.map((action) => ({
                    ui_key: actionUiKey(action),
                    label: action.label,
                    verb: actionVerbLabel(action),
                })),
                rows: [],
            });
        }
        sections.push({
            title: "键盘操作",
            body: ["方向键移动，Enter 打开详情，F7 筛选，F9 进入任务区，F8 导出。"],
            rows: [],
        });
        renderInspector({
            title: row ? `选中记录 ${state.selectedRowIndex + 1}/${state.visibleRows.length}` : "表格状态",
            body: state.currentViewModel.title || "",
            rows: [...prefixRows, ...rows],
            sections,
        });
    }

    function actionsAvailableForRow(row) {
        const actions = (state.screen && state.screen.actions) || [];
        return actions
            .filter((action) => {
                const fields = (action.fields || []).filter((field) => field.input_type !== "hidden");
                if (!fields.length) {
                    return false;
                }
                return fields.some((field) => rowValueForField(row, field, action) !== undefined);
            })
            .sort((left, right) => {
                const tierRank = { operation: 0, advanced: 1, primary: 2, support: 3 };
                return (tierRank[actionTier(left)] ?? 9) - (tierRank[actionTier(right)] ?? 9)
                    || Number(left.sequence || 999) - Number(right.sequence || 999);
            })
            .slice(0, 5);
    }

    function paramsFromRowForAction(row, action) {
        const params = {};
        const fields = (action && action.fields) || [];
        fields.forEach((field) => {
            if (field.input_type === "hidden") {
                return;
            }
            const value = rowValueForField(row, field, action);
            if (value !== undefined && value !== null && value !== "") {
                params[field.key] = value;
            }
        });
        return params;
    }

    function runInspectorAction(actionRef) {
        const row = rowContextWithSource(state.visibleRows[state.selectedRowIndex]);
        const action = currentAction(actionRef);
        if (!row || !action) {
            setStatus("没有可执行的选中行任务");
            return;
        }
        const params = paramsFromRowForAction(row, action);
        const missing = (action.fields || [])
            .filter((field) => field.required && !field.default && field.input_type !== "hidden")
            .filter((field) => params[field.key] === undefined || params[field.key] === null || String(params[field.key]).trim() === "");
        if (missing.length) {
            setStatus(`选中行缺少参数: ${missing.map((field) => field.label).join(", ")}`);
            return;
        }
        runAction(action.key, null, { params });
    }

    function moveRow(delta) {
        const rows = els.main.querySelectorAll("[data-row-index]");
        if (!rows.length) {
            return;
        }
        const firstIndex = Number(rows[0].dataset.rowIndex || 0);
        const lastIndex = Number(rows[rows.length - 1].dataset.rowIndex || 0);
        const next = Math.max(firstIndex, Math.min(lastIndex, state.selectedRowIndex + delta));
        selectRow(next);
        els.main.querySelector(`[data-row-index="${next}"]`)?.scrollIntoView({ block: "nearest" });
    }

    async function pageDelta(delta) {
        if (state.lastPager?.client_side) {
            if (delta < 0 && !state.lastPager.has_previous) {
                setStatus("已经是第一页");
                return;
            }
            if (delta > 0 && !state.lastPager.has_next) {
                setStatus("已经是最后一页");
                return;
            }
            state.clientPage = Math.max(1, state.clientPage + delta);
            state.selectedRowIndex = (state.clientPage - 1) * state.clientPageSize;
            drawDataGrid();
            setStatus(`第 ${state.clientPage} 页`);
            return;
        }
        if (state.pendingController) {
            setStatus("翻页中，请稍候");
            return;
        }
        if (!state.lastAction || !state.lastPager) {
            setStatus("当前视图不可翻页");
            return;
        }
        const action = currentAction(state.lastAction);
        if (!action) {
            setStatus("任务未找到");
            return;
        }
        if (delta < 0 && !state.lastPager.has_previous) {
            setStatus("已经是第一页");
            return;
        }
        if (delta > 0 && !state.lastPager.has_next) {
            setStatus("已经是最后一页");
            return;
        }
        const patch = paginationParamPatch(action, state.lastPager, state.lastParams, delta);
        if (!patch) {
            setStatus("当前分页参数不可推断");
            return;
        }
        await runAction(state.lastAction, null, { params: { ...state.lastParams, ...patch } });
    }

    function paginationParamPatch(action, pager, params, delta) {
        const pagination = action.pagination || {};
        const pagerMode = String(pager.pagination_mode || pager.mode || "");
        const mode = pagination.mode || (pagerMode === "limit_offset" ? "offset" : pagerMode) || inferPaginationMode(action);
        if (mode === "cursor") {
            const cursorParam = pagination.cursor_param || firstFieldKey(action, ["cursor", "nextCursor", "next_cursor"]);
            const cursor = delta > 0
                ? valueAtPath(pager, pagination.next_cursor_path || "next_cursor")
                : valueAtPath(pager, pagination.previous_cursor_path || "previous_cursor");
            return cursorParam && cursor ? { [cursorParam]: cursor } : null;
        }
        if (mode === "offset") {
            const offsetParam = pagination.offset_param || firstFieldKey(action, ["offset", "start"]);
            const limitParam = pagination.limit_param || firstFieldKey(action, ["limit", "pageSize", "page_size"]);
            const limit = Number(params[limitParam] || pager.page_size || pager.limit || 10);
            const current = Number(params[offsetParam] || pager.offset || 0);
            if (!offsetParam || !Number.isFinite(limit) || !Number.isFinite(current)) {
                return null;
            }
            const nextOffset = Math.max(0, current + (delta * limit));
            return limitParam ? { [offsetParam]: nextOffset, [limitParam]: limit } : { [offsetParam]: nextOffset };
        }
        const pageParam = pagination.page_param || firstFieldKey(action, ["page", "pageNum", "page_num", "pageNo", "page_no"]);
        const pageSizeParam = pagination.page_size_param || firstFieldKey(action, ["page_size", "pageSize", "limit", "size"]);
        const current = Number(params[pageParam] || pager.page || 1);
        if (!pageParam || !Number.isFinite(current)) {
            return null;
        }
        const next = Math.max(1, current + delta);
        const patch = { [pageParam]: next };
        const pageSize = Number(params[pageSizeParam] || pager.page_size || pager.pageSize || 0);
        if (pageSizeParam && Number.isFinite(pageSize) && pageSize > 0) {
            patch[pageSizeParam] = pageSize;
        }
        return patch;
    }

    function inferPaginationMode(action) {
        const fields = (action.fields || []).map((field) => String(field.key || ""));
        if (fields.some((key) => ["cursor", "nextCursor", "next_cursor"].includes(key))) {
            return "cursor";
        }
        if (fields.some((key) => ["offset", "start"].includes(key))) {
            return "offset";
        }
        return "page";
    }

    function firstFieldKey(action, candidates) {
        const fields = (action.fields || []).map((field) => String(field.key || ""));
        return candidates.find((candidate) => fields.includes(candidate)) || candidates[0] || "";
    }

    function valueAtPath(value, path) {
        if (!path) {
            return undefined;
        }
        return String(path).split(".").reduce((current, key) => {
            if (current && Object.prototype.hasOwnProperty.call(current, key)) {
                return current[key];
            }
            return undefined;
        }, value);
    }
