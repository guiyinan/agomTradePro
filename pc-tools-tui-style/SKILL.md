---
name: pc-tools-tui-style
description: Build self-contained DOS/PC Tools style interactive HTML pages for Chinese regulatory, audit, compliance, risk, archive, or timeline summaries using one JSON-shaped reportData variable for config, raw records, tags, filters, and display items. Use when the user wants to reuse the visual style from “监管提示函梳理 2606-tui.html”, create a retro terminal/TUI dashboard, or turn structured notes into a filterable single-file HTML report with sidebar filters, chronological records, collapsible entries, and keyboard shortcuts.
---

# PC Tools TUI Style

## Purpose

Create a single-file HTML report that looks like a DOS-era PC Tools archive screen: gray menu bars, deep blue double-bordered panels, cyan/yellow/red status colors, monospace type, sidebar filters, timeline records, collapsible detail rows, and a bottom function-key bar.

Use `assets/pc-tools-tui-template.html` as the base. Copy it to the requested output name, then replace only the top-level `reportData` JSON variable in the script block. Keep page configuration, source records, original rows, and tags inside that one variable.

## Workflow

1. Normalize source material into `reportData.records` with these fields:
   - `id`, `date`, `type`, `typeLabel`, `title`, `source`, `tags`, `items`
   - each item uses `text`, `tags`, and optional `raw`
   - put the complete original structured row/object in record-level `raw` when available
2. Preserve the template structure:
   - `.tui-menubar` for title, counter, and system status
   - `.tui-sidebar` for type/year/month/tag/search filters
   - `.tui-main` for year/month grouped record cards
   - `.tui-footer` for shortcut/status labels
3. Keep the visual language consistent:
   - body background: DOS blue with scanline overlay
   - panels: deep blue, cyan double borders, black drop shadow
   - menu/footer: gray bars with inset highlight/shadow
   - active/hover controls: yellow background, black text
   - document types: red border for company-specific records, cyan for industry records
4. Keep the page self-contained. Do not add build tooling, external CSS, or remote assets unless explicitly requested.
5. Verify the result by opening the HTML in a browser or running a local static server if needed.

## Data Shape

Use this single JSON-shaped variable inside the template:

```js
const reportData = {
  "config": {
    "title": "监管问答梳理",
    "sidebarTitle": "REGULATORY QA INDEX",
    "mainTitle": "CHRONOLOGICAL QA SET",
    "status": ["NODE: QA-ARCHIVE", "DB: REG_QA", "STATUS: ONLINE"],
    "footer": ["F1 帮助", "F2 类型", "F3 年份", "F4 标签", "F5 搜索", "F9 重置", "/ 搜索", "ESC 清空", "R 重置", "IDX READY"],
    "searchPlaceholder": "输入关键词，如 保险资管",
    "monthFilterMode": "select"
  },
  "filters": {
    "typeOrder": ["asset-management", "general"],
    "tagOrder": ["保险资管产品", "保险资金运用", "投资管理能力"]
  },
  "records": [
    {
      "id": "qa-1",
      "date": "2024-12-06",
      "type": "asset-management",
      "typeLabel": "保险资管",
      "title": "保险资金投资同业存单的资产类别",
      "source": "国家金融监督管理总局（按答复日期推定）",
      "tags": ["保险资金运用", "同业存单", "固定收益"],
      "raw": {
        "一级分类": "保险资金运用",
        "问题": "请问保险资金投资同业存单，应纳入流动性资产还是固定收益类资产进行管理？",
        "回答": "剩余期限不超过1年的同业存单作为流动性资产管理，超过1年的作为固定收益类资产管理。",
        "提问日期": "2024-12-03",
        "答复日期": "2024-12-06"
      },
      "items": [
        { "text": "问题：请问保险资金投资同业存单，应纳入流动性资产还是固定收益类资产进行管理？", "tags": ["问题", "同业存单"] },
        { "text": "回答：剩余期限不超过1年的同业存单作为流动性资产管理，超过1年的作为固定收益类资产管理。", "tags": ["回答", "固定收益"] }
      ]
    }
  ]
};
```

## Content Rules

- Sort records by `date` descending unless the user asks otherwise.
- Derive `year` and `month` from `date`; keep `date` as `YYYY-MM-DD`.
- Use short, scannable item text. Preserve source wording for regulatory requirements when accuracy matters.
- Keep tags stable across records so the sidebar remains useful.
- Keep all original source fields in `raw`; the template includes `raw` in full-text search, so generated pages can search fields that are not displayed in the visible card.
- Put all display and filter data under `reportData`. Do not create separate `pageConfig`, `records`, `tags`, or lookup variables unless the user explicitly asks for custom code.
- Use `filters.typeOrder` and `filters.tagOrder` only when a deliberate sidebar order matters; otherwise leave them empty and let the template derive options from `records`.
- Use `config.monthFilterMode: "select"` when there are many months; the template renders a DOS-style month jump selector instead of many month buttons.
- Use Chinese labels for user-facing compliance reports, but keep system chrome labels such as `STATUS`, `DB`, `FILES`, and `ITEMS` in English to preserve the PC Tools feel.

## Template

Use `assets/pc-tools-tui-template.html` for the complete HTML/CSS/JS implementation. The root project also contains `pc-tools-tui-template.html` as a convenient copy.
