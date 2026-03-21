# 证券分析模块样式改进指南

> **创建日期**: 2026-02-18
> **负责**: ui-ux-designer, frontend-dev
> **状态**: ✅ **已完成**
> **优先级**: P1 (阻塞任务 #13 完成)

### 完成日期
2026-02-18

### 完成内容
- ✅ `static/css/equity.css` - 完整的样式文件，使用设计Token
- ✅ `static/css/fund.css` - 完整的样式文件，使用设计Token
- ✅ `core/templates/equity/base.html` - 无内联样式
- ✅ `core/templates/fund/dashboard.html` - 移除582行内联`<style>`标签，所有`style="..."`属性已替换为类名

---

## 1. 问题概述

证券分析模块（equity 和 fund）存在以下不符合设计 Token 规范的问题：

### 问题清单

| 文件 | 问题类型 | 严重程度 |
|------|----------|----------|
| `core/templates/equity/base.html` | 内联 `<style>` 标签，硬编码颜色/字体/间距 | P1 |
| `core/templates/fund/dashboard.html` | 内联 `style` 属性，硬编码颜色/字体 | P1 |

---

## 2. Equity 模块改进方案

### 2.1 创建 CSS 文件

创建 `static/css/equity.css`，内容如下：

```css
/**
 * Equity Module Styles
 * 个股分析模块样式，使用设计Token v1.0
 *
 * @version 1.0.0
 * @updated 2026-02-18
 */

/* 容器 */
.equity-container {
    max-width: var(--content-max-width, 1400px);
    margin: 0 auto;
    padding: var(--spacing-lg);
}

/* 头部 */
.equity-header {
    margin-bottom: var(--spacing-xl);
}

.equity-header h1 {
    font-size: var(--font-size-h1);
    color: var(--color-text-primary);
    margin: 0 0 var(--spacing-xs) 0;
}

.equity-header p {
    color: var(--color-text-secondary);
    margin: 0;
}

/* 标签页 */
.page-tabs {
    display: flex;
    gap: var(--spacing-sm);
    margin-bottom: var(--spacing-lg);
    border-bottom: 2px solid var(--color-border);
}

.page-tab {
    padding: var(--spacing-sm) var(--spacing-lg);
    background: none;
    border: none;
    color: var(--color-text-secondary);
    cursor: pointer;
    font-size: var(--font-size-body);
    border-bottom: 3px solid transparent;
    margin-bottom: -2px;
    transition: all var(--duration-normal) var(--ease-in-out);
}

.page-tab:hover {
    color: var(--color-primary);
}

.page-tab.active {
    color: var(--color-primary);
    border-bottom-color: var(--color-primary);
}

/* 卡片 */
.card {
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: var(--spacing-lg);
    margin-bottom: var(--spacing-lg);
}

.card-title {
    font-size: var(--font-size-h3);
    font-weight: var(--font-weight-semibold);
    margin: 0 0 var(--spacing-md) 0;
}

/* 筛选组 */
.filter-group {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--spacing-md);
}

.filter-item {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-xs);
}

.filter-item label {
    font-size: var(--font-size-small);
    font-weight: var(--font-weight-medium);
    color: var(--color-text-primary);
}

.filter-item input,
.filter-item select {
    padding: var(--spacing-sm) var(--spacing-md);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    font-size: var(--font-size-body);
}

/* 按钮 */
.btn {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-sm);
    padding: var(--spacing-sm) var(--spacing-lg);
    border-radius: var(--radius-xs);
    font-size: var(--font-size-body);
    font-weight: var(--font-weight-medium);
    cursor: pointer;
    transition: all var(--duration-normal) var(--ease-in-out);
}

.btn-primary {
    background: var(--color-primary);
    color: var(--color-text-inverse);
    border: 1px solid var(--color-primary);
}

.btn-primary:hover {
    background: var(--color-primary-hover);
}

.btn-secondary {
    background: var(--color-surface);
    color: var(--color-text-primary);
    border: 1px solid var(--color-border);
}

.btn-secondary:hover {
    background: var(--color-surface-alt);
}

/* 结果表格 */
.results-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: var(--spacing-lg);
}

.results-table thead {
    background: var(--color-surface);
    border-bottom: 1px solid var(--color-border-dark);
}

.results-table th {
    padding: var(--spacing-sm);
    text-align: left;
    font-weight: var(--font-weight-semibold);
    font-size: var(--font-size-small);
}

.results-table td {
    padding: var(--spacing-sm);
    border-bottom: 1px solid var(--color-border);
}

.results-table tr:hover {
    background: var(--color-surface);
}

/* 辅助类 */
.text-muted {
    color: var(--color-text-muted);
}

.text-small {
    font-size: var(--font-size-small);
}

.mt-sm {
    margin-top: var(--spacing-sm);
}
```

### 2.2 修改模板文件

**修改 `core/templates/equity/base.html`**:

```html
{% extends "base.html" %}
{% load static %}

{% block extra_css %}
<!-- 替换原有的 <style> 标签 -->
<link rel="stylesheet" href="{% static 'css/equity.css' %}">
{% endblock %}
```

---

## 3. Fund 模块改进方案

### 3.1 创建 CSS 文件

创建 `static/css/fund.css`，内容如下：

```css
/**
 * Fund Module Styles
 * 基金分析模块样式，使用设计Token v1.0
 *
 * @version 1.0.0
 * @updated 2026-02-18
 */

/* 页面头部 */
.page-header {
    margin-bottom: var(--spacing-xl);
}

.header-content {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    flex-wrap: wrap;
    gap: var(--spacing-md);
}

.header-content h1 {
    font-size: var(--font-size-h1);
    font-weight: var(--font-weight-bold);
    margin: 0 0 var(--spacing-sm) 0;
}

.subtitle {
    color: var(--color-text-secondary);
    font-size: var(--font-size-body);
}

.description {
    color: var(--color-text-muted);
    font-size: var(--font-size-small);
}

/* 统计行 */
.stats-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--spacing-md);
    margin-bottom: var(--spacing-lg);
}

.stat-card {
    display: flex;
    align-items: center;
    gap: var(--spacing-md);
    padding: var(--spacing-md);
    background: var(--color-surface);
    border-radius: var(--radius-lg);
}

.stat-icon {
    font-size: 32px;
}

.stat-info {
    flex: 1;
}

.stat-label {
    font-size: var(--font-size-small);
    color: var(--color-text-muted);
    margin-bottom: var(--spacing-xs);
}

.stat-value {
    font-size: var(--font-size-h4);
    font-weight: var(--font-weight-semibold);
    color: var(--color-text-primary);
}

.stat-detail {
    font-size: var(--font-size-small);
    color: var(--color-text-muted);
    margin-top: var(--spacing-xs);
}

/* 主布局 */
.fund-dashboard {
    display: grid;
    grid-template-columns: 250px 1fr;
    gap: var(--spacing-lg);
}

/* 侧边栏 */
.left-sidebar {
    width: 250px;
}

.sidebar-card {
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: var(--spacing-md);
    margin-bottom: var(--spacing-md);
}

.sidebar-header h3 {
    font-size: var(--font-size-h4);
    font-weight: var(--font-weight-semibold);
    margin: 0 0 var(--spacing-md) 0;
}

.nav-menu {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-xs);
}

.nav-item {
    display: flex;
    align-items: center;
    gap: var(--spacing-sm);
    padding: var(--spacing-sm) var(--spacing-md);
    color: var(--color-text-secondary);
    text-decoration: none;
    border-radius: var(--radius-md);
    transition: all var(--duration-fast) var(--ease-in-out);
}

.nav-item:hover {
    background: var(--color-surface);
    color: var(--color-text-primary);
}

.nav-item.active {
    background: var(--color-primary-light);
    color: var(--color-primary);
    font-weight: var(--font-weight-medium);
}

.nav-icon {
    font-size: 18px;
}

/* 内容区域 */
.content-section {
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: var(--spacing-lg);
    margin-bottom: var(--spacing-lg);
}

.section-header {
    margin-bottom: var(--spacing-lg);
}

.section-header h2 {
    font-size: var(--font-size-h2);
    font-weight: var(--font-weight-semibold);
    margin: 0 0 var(--spacing-sm) 0;
}

.section-description {
    color: var(--color-text-secondary);
    font-size: var(--font-size-small);
}
```

### 3.2 修改模板文件

**修改 `core/templates/fund/dashboard.html`**:

```html
{% extends "base.html" %}
{% load static %}

{% block title %}基金分析 - AgomTradePro{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{% static 'css/fund.css' %}">
{% endblock %}

{% block content %}
<!-- 替换内联样式为类名 -->
<div class="page-header">
    <div class="header-content">
        <div>
            <h1>基金分析</h1>
            <p class="subtitle">基于 Regime 的基金筛选与分析</p>
            <p class="description">基金筛选、风格分析、业绩评估</p>
        </div>
    </div>
</div>

<!-- 替换内联 style 属性 -->
<div class="stats-row">
    <div class="stat-card">
        <div class="stat-icon">📊</div>
        <div class="stat-info">
            <div class="stat-label">当前宏观环境</div>
            <div class="stat-value">{{ regime_display }}</div>
            <div class="stat-detail">{{ current_regime }}</div>
        </div>
    </div>
    <!-- 其他 stat-card 类似修改 -->
</div>

<!-- 其他内容类似修改 -->
{% endblock %}
```

---

## 4. 硬编码值 → Token 映射表

### 颜色映射

| 硬编码值 | 应使用 Token |
|----------|-------------|
| `#1a1a1a` | `var(--color-text-primary)` |
| `#333333` | `var(--color-text-primary)` |
| `#666666` | `var(--color-text-secondary)` |
| `#999999` | `var(--color-text-muted)` |
| `#2563eb` | `var(--color-primary)` |
| `#3b82f6` | `var(--color-primary-hover)` |
| `#e5e7eb` | `var(--color-border)` |
| `#f3f4f6` | `var(--color-surface)` |

### 字体大小映射

| 硬编码值 | 应使用 Token |
|----------|-------------|
| `28px` | `var(--font-size-h1)` |
| `24px` | `var(--font-size-h2)` |
| `20px` | `var(--font-size-h3)` |
| `16px` | `var(--font-size-h4)` |
| `15px` | `var(--font-size-body)` |
| `14px` | `var(--font-size-body)` |
| `12px` | `var(--font-size-small)` |

### 间距映射

| 硬编码值 | 应使用 Token |
|----------|-------------|
| `4px` | `var(--spacing-xs)` |
| `8px` | `var(--spacing-sm)` |
| `10px` | `var(--spacing-sm)` |
| `12px` | `var(--spacing-md)` 或 `var(--spacing-sm)` |
| `16px` | `var(--spacing-md)` |
| `20px` | `var(--spacing-lg)` |
| `24px` | `var(--spacing-lg)` |
| `30px` | `var(--spacing-xl)` |
| `32px` | `var(--spacing-xl)` |

---

## 5. 验收标准

改进完成后，应满足以下标准：

- [ ] 无内联 `<style>` 标签
- [ ] 无内联 `style="..."` 属性（除特殊情况）
- [ ] 所有颜色使用 `var(--color-*)`
- [ ] 所有字体大小使用 `var(--font-size-*)`
- [ ] 所有间距使用 `var(--spacing-*)`
- [ ] 所有圆角使用 `var(--radius-*)`
- [ ] 页面视觉与其他模块一致

---

## 6. 实施步骤

1. **创建 CSS 文件**
   - 创建 `static/css/equity.css`
   - 创建 `static/css/fund.css`

2. **修改模板文件**
   - 修改 `core/templates/equity/base.html`
   - 修改 `core/templates/fund/dashboard.html`
   - 其他相关模板文件

3. **测试验证**
   - 在浏览器中测试页面显示
   - 确认与其他模块视觉一致
   - 检查响应式布局

4. **更新文档**
   - 更新改造清单状态
   - 标记任务 #13 相关子任务完成

---

**文档版本**: v1.0
**维护**: ui-ux-designer
**最后更新**: 2026-02-18
