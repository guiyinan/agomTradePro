# AgomSAAF UI/UX 设计 Token 规范 v1

> **版本**: v1.0
> **创建日期**: 2026-02-18
> **设计理念**: 简洁、淡雅、专业
> **目标**: 最大化数据可读性，最小化视觉干扰

---

## 1. 设计 Token 系统概述

设计 Token 是设计决策的最小单位，包括颜色、间距、字体、圆角、阴影等。使用 Token 可以确保整个系统的视觉一致性。

### 1.1 Token 命名规范

```css
/* 命名格式: --{category}-{item}-{variant}-{state} */
--color-primary                    /* 颜色-主色 */
--color-primary-hover              /* 颜色-主色-悬停态 */
--spacing-md                       /* 间距-中等 */
--radius-md                        /* 圆角-中等 */
--shadow-sm                        /* 阴影-小 */
```

### 1.2 使用原则

1. **优先使用 Token**: 所有样式优先使用预定义的 CSS 变量
2. **禁止硬编码**: 避免在代码中直接写颜色值、尺寸等
3. **保持一致性**: 同一概念使用相同的 Token
4. **渐进增强**: 新的 Token 需要先在文档中定义，再使用

---

## 2. 颜色系统 (Colors)

### 2.1 基础色 (Base Colors)

```css
:root {
    /* 背景色 */
    --color-bg: #FFFFFF;
    --color-surface: #F8F9FA;
    --color-surface-alt: #F0F1F3;

    /* 边框色 */
    --color-border: #E0E0E0;
    --color-border-light: #F0F0F0;
    --color-border-dark: #A2A9B1;
}
```

### 2.2 文字色 (Text Colors)

```css
:root {
    --color-text-primary: #202122;
    --color-text-secondary: #54595D;
    --color-text-muted: #72777D;
    --color-text-disabled: #A2A9B1;
}
```

### 2.3 功能色 (Semantic Colors)

```css
:root {
    /* 主色 */
    --color-primary: #3366CC;
    --color-primary-hover: #447FF5;
    --color-primary-active: #2952A3;
    --color-primary-light: rgba(51, 102, 204, 0.1);

    /* 成功 */
    --color-success: #14866D;
    --color-success-hover: #1AA88A;
    --color-success-bg: #D5FBDD;

    /* 警告 */
    --color-warning: #AB7100;
    --color-warning-hover: #D68C00;
    --color-warning-bg: #FEF7E2;

    /* 错误 */
    --color-error: #DD3333;
    --color-error-hover: #FF4444;
    --color-error-bg: #FEE7E7;

    /* 信息 */
    --color-info: #3366CC;
    --color-info-bg: #D5E9FF;
}
```

### 2.4 Regime 象限色 (Regime Colors)

```css
:root {
    --color-regime-recovery: #A7C7F7;     /* 复苏 - 淡蓝 */
    --color-regime-overheat: #F4C2C2;     /* 过热 - 淡红 */
    --color-regime-stagflation: #E0E0E0;  /* 滞胀 - 灰色 */
    --color-regime-deflation: #C8D8B8;    /* 通缩 - 淡绿 */
}
```

### 2.5 使用示例

```html
<!-- 错误用法：硬编码颜色 -->
<div style="color: #202122; background: #FFFFFF;">内容</div>

<!-- 正确用法：使用 Token -->
<div class="text-primary bg-surface">内容</div>
```

---

## 3. 字体系统 (Typography)

### 3.1 字体家族 (Font Families)

```css
:root {
    /* 英文 */
    --font-family-base: -apple-system, BlinkMacSystemFont, 'Segoe UI',
                         'Liberation Sans', 'Helvetica Neue', 'Arial', sans-serif;

    /* 中文 */
    --font-family-zh: -apple-system, BlinkMacSystemFont, 'Segoe UI',
                      'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;

    /* 代码 */
    --font-family-mono: 'SF Mono', 'Monaco', 'Cascadia Code', 'Roboto Mono',
                        'Courier New', monospace;
}
```

### 3.2 字体大小 (Font Sizes)

```css
:root {
    --font-size-h1: 28px;
    --font-size-h2: 24px;
    --font-size-h3: 20px;
    --font-size-h4: 18px;
    --font-size-body: 14px;
    --font-size-small: 12px;
    --font-size-xs: 11px;
}
```

### 3.3 行高 (Line Heights)

```css
:root {
    --line-height-tight: 1.25;
    --line-height-normal: 1.5;
    --line-height-relaxed: 1.75;

    /* 具体行高 */
    --line-height-h1: 36px;
    --line-height-h2: 32px;
    --line-height-h3: 28px;
    --line-height-h4: 26px;
    --line-height-body: 22px;
    --line-height-small: 18px;
}
```

### 3.4 字重 (Font Weights)

```css
:root {
    --font-weight-normal: 400;
    --font-weight-medium: 500;
    --font-weight-semibold: 600;
    --font-weight-bold: 700;
}
```

### 3.5 使用示例

```html
<h1 class="h1">页面标题</h1>
<h2 class="h2">区块标题</h2>
<h3 class="h3">小节标题</h3>
<p class="body">正文内容</p>
<p class="text-muted">辅助信息</p>
```

---

## 4. 间距系统 (Spacing)

### 4.1 间距阶梯 (Spacing Scale)

基于 4px 基础单位的倍数系统：

```css
:root {
    --spacing-0: 0;
    --spacing-xs: 4px;      /* 0.25rem */
    --spacing-sm: 8px;      /* 0.5rem */
    --spacing-md: 16px;     /* 1rem */
    --spacing-lg: 24px;     /* 1.5rem */
    --spacing-xl: 32px;     /* 2rem */
    --spacing-xxl: 48px;    /* 3rem */
    --spacing-xxxl: 64px;   /* 4rem */
}
```

### 4.2 使用示例

```html
<!-- 错误用法 -->
<div style="padding: 16px 24px; margin-bottom: 32px;">内容</div>

<!-- 正确用法 -->
<div class="p-md mb-xl">内容</div>
```

---

## 5. 圆角系统 (Border Radius)

```css
:root {
    --radius-none: 0;
    --radius-xs: 2px;
    --radius-sm: 4px;
    --radius-md: 8px;
    --radius-lg: 12px;
    --radius-xl: 16px;
    --radius-full: 9999px;
}
```

### 使用场景

| 圆角值 | 使用场景 |
|--------|----------|
| `0` | 表格、分割线 |
| `2px` | 输入框、按钮（紧凑风格） |
| `4px` | 卡片、面板（默认） |
| `8px` | 标签、徽章 |
| `12px` | 模态框 |
| `16px` | 大型卡片 |
| `9999px` | 圆形按钮、头像 |

---

## 6. 阴影系统 (Shadows)

```css
:root {
    --shadow-none: none;
    --shadow-xs: 0 1px 2px rgba(0, 0, 0, 0.05);
    --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.08);
    --shadow-md: 0 2px 8px rgba(0, 0, 0, 0.08);
    --shadow-lg: 0 4px 16px rgba(0, 0, 0, 0.12);
    --shadow-xl: 0 8px 32px rgba(0, 0, 0, 0.16);
}
```

### 使用场景

| 阴影值 | 使用场景 |
|--------|----------|
| `none` | 默认状态 |
| `xs` | 输入框 focus |
| `sm` | 按钮 hover |
| `md` | 卡片默认 |
| `lg` | 下拉菜单 |
| `xl` | 模态框 |

---

## 7. 动画系统 (Animations)

### 7.1 时长 (Duration)

```css
:root {
    --duration-fast: 150ms;
    --duration-normal: 300ms;
    --duration-slow: 500ms;
}
```

### 7.2 缓动函数 (Easing)

```css
:root {
    --ease-in: cubic-bezier(0.4, 0, 1, 1);
    --ease-out: cubic-bezier(0, 0, 0.2, 1);
    --ease-in-out: cubic-bezier(0.4, 0, 0.2, 1);
}
```

### 7.3 使用示例

```css
.transition {
    transition: all var(--duration-normal) var(--ease-in-out);
}

.fade-in {
    animation: fadeIn var(--duration-normal) var(--ease-out);
}
```

---

## 8. 组件规范 (Component Standards)

### 8.1 按钮 (Buttons)

#### 主要按钮

```html
<button class="btn btn-primary">保存</button>
```

```css
.btn-primary {
    background: var(--color-primary);
    color: #FFFFFF;
    border: 1px solid var(--color-primary);
    padding: var(--spacing-sm) var(--spacing-md);
    border-radius: var(--radius-xs);
    font-size: var(--font-size-body);
    cursor: pointer;
    transition: all var(--duration-normal) var(--ease-in-out);
}

.btn-primary:hover {
    background: var(--color-primary-hover);
}
```

#### 次要按钮

```html
<button class="btn btn-secondary">取消</button>
```

#### 危险按钮

```html
<button class="btn btn-danger">删除</button>
```

#### 禁用状态

```html
<button class="btn btn-primary" disabled>禁用</button>
```

#### 按钮尺寸

```html
<button class="btn btn-primary btn-sm">小按钮</button>
<button class="btn btn-primary">默认按钮</button>
<button class="btn btn-primary btn-lg">大按钮</button>
```

### 8.2 输入框 (Inputs)

```html
<input type="text" class="input" placeholder="请输入...">
<input type="text" class="input input-error" placeholder="错误状态">
<input type="text" class="input" disabled placeholder="禁用状态">
```

```css
.input {
    width: 100%;
    padding: var(--spacing-sm) var(--spacing-sm);
    border: 1px solid var(--color-border-dark);
    border-radius: var(--radius-xs);
    font-size: var(--font-size-body);
    color: var(--color-text-primary);
}

.input:focus {
    outline: none;
    border-color: var(--color-primary);
    box-shadow: 0 0 0 2px var(--color-primary-light);
}

.input-error {
    border-color: var(--color-error);
}

.input:disabled {
    background: var(--color-surface);
    color: var(--color-text-disabled);
}
```

### 8.3 表格 (Tables)

```html
<table class="table">
    <thead>
        <tr>
            <th>列1</th>
            <th>列2</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>数据1</td>
            <td>数据2</td>
        </tr>
    </tbody>
</table>
```

```css
.table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--font-size-body);
}

.table thead {
    background: var(--color-surface);
    border-bottom: 1px solid var(--color-border-dark);
}

.table th {
    padding: var(--spacing-sm);
    text-align: left;
    font-weight: var(--font-weight-semibold);
}

.table td {
    padding: var(--spacing-sm);
    border-bottom: 1px solid var(--color-border);
}

.table tr:hover {
    background: var(--color-surface);
}
```

### 8.4 卡片 (Cards)

```html
<div class="card">
    <div class="card-header">标题</div>
    <div class="card-body">内容</div>
</div>
```

```css
.card {
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-xs);
    padding: var(--spacing-md);
}

.card-header {
    border-bottom: 1px solid var(--color-border);
    padding-bottom: var(--spacing-sm);
    margin-bottom: var(--spacing-sm);
    font-size: 16px;
    font-weight: var(--font-weight-semibold);
}
```

### 8.5 标签 (Tags)

#### 状态标签

```html
<span class="tag tag-success">成功</span>
<span class="tag tag-warning">警告</span>
<span class="tag tag-error">错误</span>
<span class="tag tag-info">信息</span>
```

#### Regime 标签

```html
<span class="tag tag-regime-recovery">复苏</span>
<span class="tag tag-regime-overheat">过热</span>
<span class="tag tag-regime-stagflation">滞胀</span>
<span class="tag tag-regime-deflation">通缩</span>
```

```css
.tag {
    display: inline-block;
    padding: var(--spacing-xs) var(--spacing-sm);
    font-size: var(--font-size-small);
    border-radius: var(--radius-xs);
    font-weight: var(--font-weight-medium);
}

.tag-success { background: var(--color-success-bg); color: var(--color-success); }
.tag-warning { background: var(--color-warning-bg); color: var(--color-warning); }
.tag-error { background: var(--color-error-bg); color: var(--color-error); }
.tag-info { background: var(--color-info-bg); color: var(--color-info); }
```

### 8.6 告警框 (Alerts)

```html
<div class="alert alert-success">操作成功</div>
<div class="alert alert-warning">警告信息</div>
<div class="alert alert-error">错误信息</div>
<div class="alert alert-info">提示信息</div>
```

### 8.7 空状态 (Empty States)

```html
<div class="empty-state">
    <div class="empty-state-icon">📭</div>
    <h3 class="empty-state-title">暂无数据</h3>
    <p class="empty-state-description">请先创建数据或调整筛选条件</p>
    <button class="btn btn-primary">创建数据</button>
</div>
```

### 8.8 加载态 (Loading States)

#### Spinner

```html
<div class="spinner"></div>
```

#### 骨架屏

```html
<div class="skeleton">
    <div class="skeleton-line"></div>
    <div class="skeleton-line"></div>
</div>
```

---

## 9. 布局系统 (Layout)

### 9.1 容器

```css
.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 var(--spacing-md);
}

.container-sm { max-width: 900px; }
.container-lg { max-width: 1400px; }
```

### 9.2 网格

```html
<div class="grid grid-cols-2 gap-md">
    <div>列1</div>
    <div>列2</div>
</div>
```

### 9.3 Flexbox 工具类

```html
<div class="flex items-center justify-between gap-md">
    <div>左侧</div>
    <div>右侧</div>
</div>
```

---

## 10. 响应式断点 (Breakpoints)

```css
:root {
    --breakpoint-sm: 640px;
    --breakpoint-md: 768px;
    --breakpoint-lg: 1024px;
    --breakpoint-xl: 1280px;
}
```

---

## 11. 使用指南 (Usage Guide)

### 11.1 在 Django 模板中使用

```html
{% load static %}
<link rel="stylesheet" href="{% static 'css/design-tokens.css' %}">
```

### 11.2 迁移现有页面的步骤

1. **引入设计 Token CSS 文件**
2. **替换硬编码颜色为 Token 类名**
3. **替换内联样式为预定义类**
4. **统一组件使用标准类名**
5. **测试视觉一致性**

### 11.3 示例迁移

**迁移前**:
```html
<div style="background: #F8F9FA; padding: 16px; border-radius: 4px;">
    <h3 style="font-size: 20px; color: #202122;">标题</h3>
    <p style="color: #54595D;">内容</p>
    <button style="background: #3366CC; color: white; padding: 8px 16px; border-radius: 2px;">按钮</button>
</div>
```

**迁移后**:
```html
<div class="card">
    <h3 class="h3">标题</h3>
    <p class="text-secondary">内容</p>
    <button class="btn btn-primary">按钮</button>
</div>
```

---

## 12. 工具类参考 (Utility Classes)

### 12.1 间距工具类

```html
<!-- Padding -->
<div class="p-sm">小内边距</div>
<div class="p-md">默认内边距</div>
<div class="p-lg">大内边距</div>

<!-- Margin -->
<div class="mb-sm">小下边距</div>
<div class="mb-md">默认下边距</div>
<div class="mb-lg">大下边距</div>
```

### 12.2 文字工具类

```html
<p class="text-primary">主要文字</p>
<p class="text-secondary">次要文字</p>
<p class="text-muted">辅助文字</p>
<p class="text-center">居中对齐</p>
```

### 12.3 显示工具类

```html
<div class="d-none">隐藏</div>
<div class="d-block">块级</div>
<div class="d-inline">行内</div>
<div class="d-flex">Flex</div>
```

---

## 13. 图表配色 (Chart Colors)

```javascript
// 折线图/柱状图配色
const chartColors = {
    primary: '#3366CC',
    secondary: '#72777D',
    grid: '#E0E0E0',
    axis: '#54595D',
    series: [
        '#A7C7F7',  // 淡蓝
        '#C8D8B8',  // 淡绿
        '#F4C2C2',  // 淡红
        '#E8D5E2',  // 淡紫
        '#F5DEB3',  // 淡黄
        '#B8C8D8',  // 淡青
    ]
};
```

---

## 14. 可访问性 (Accessibility)

### 14.1 颜色对比度

所有文字与背景的对比度至少为 4.5:1（WCAG AA 标准）。

### 14.2 键盘导航

所有交互元素支持键盘访问，焦点状态清晰可见。

### 14.3 语义化 HTML

使用正确的 HTML 标签，确保屏幕阅读器可以正确解析。

---

## 15. 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-02-18 | 初始版本，定义核心设计 Token |

---

## 16. 相关文档

- [前端设计指南](frontend_design_guide.md)
- [Epic A 改造清单](../frontend/epic-a-refactor-checklist-2026-02-18.md)
- [UI/UX 审计报告](../archive/process/frontend/ui-ux-full-page-audit-2026-02-18.md)
- [用户旅程清单](../archive/process/frontend/ux-user-journey-checklist-2026-02-18.md)

---

**文档维护**: ui-ux-designer
**最后更新**: 2026-02-18
**下次审查**: 2026-03-18
