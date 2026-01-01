# AgomSAAF 前端设计指南

> **设计理念**: 简洁、淡雅、专业 - 参考 Wikipedia 风格
> **目标**: 最大化数据可读性，最小化视觉干扰

---

## 1. 配色方案 (Color Palette)

### 主色调 - 淡雅蓝灰系

| 颜色名称 | HEX | RGB | 用途 |
|---------|-----|-----|------|
| **Background** | `#FFFFFF` | `rgb(255, 255, 255)` | 页面背景 |
| **Surface** | `#F8F9FA` | `rgb(248, 249, 250)` | 卡片/面板背景 |
| **Border** | `#E0E0E0` | `rgb(224, 224, 224)` | 边框、分隔线 |
| **Text Primary** | `#202122` | `rgb(32, 33, 34)` | 主要文字 |
| **Text Secondary** | `#54595D` | `rgb(84, 89, 93)` | 次要文字 |
| **Text Muted** | `#72777D` | `rgb(114, 119, 125)` | 辅助文字 |

### 功能色

| 颜色名称 | HEX | RGB | 用途 |
|---------|-----|-----|------|
| **Primary** | `#36C` | `rgb(51, 102, 204)` | 主要操作、链接 |
| **Primary Hover** | `#447FF5` | `rgb(68, 127, 245)` | 链接悬停 |
| **Success** | `#14866D` | `rgb(20, 134, 109)` | 成功/Positive |
| **Warning** | `#AB7100` | `rgb(171, 113, 0)` | 警告 |
| **Error** | `#D33` | `rgb(221, 51, 51)` | 错误/Negative |
| **Info** | `#36C` | `rgb(51, 102, 204)` | 信息提示 |

### Regime 象限色 (淡雅版)

| 象限 | HEX | RGB | 说明 |
|------|-----|-----|------|
| **Recovery** | `#A7C7F7` | `rgb(167, 199, 247)` | 复苏 - 淡蓝 |
| **Overheat** | `#F4C2C2` | `rgb(244, 194, 194)` | 过热 - 淡红 |
| **Stagflation** | `#E0E0E0` | `rgb(224, 224, 224)` | 滞胀 - 灰色 |
| **Deflation** | `#C8D8B8` | `rgb(200, 216, 184)` | 通缩 - 淡绿 |

---

## 2. 字体系统 (Typography)

### 字体家族

```css
/* 英文 */
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Liberation Sans',
             'Helvetica Neue', 'Arial', sans-serif;

/* 中文 */
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
             'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
```

### 字体大小

| 级别 | 大小 | 行高 | 用途 |
|------|------|------|------|
| **H1** | 28px | 36px | 页面标题 |
| **H2** | 24px | 32px | 区块标题 |
| **H3** | 20px | 28px | 小节标题 |
| **H4** | 18px | 26px | 子标题 |
| **Body** | 14px | 22px | 正文 |
| **Small** | 12px | 18px | 辅助信息 |

### 字重

```css
font-weight: 400;  /* Regular - 正文 */
font-weight: 500;  /* Medium - 强调 */
font-weight: 600;  /* Semibold - 标题 */
```

---

## 3. 间距系统 (Spacing)

使用 4px 基础单位的倍数：

| 名称 | 值 | 用途 |
|------|-----|------|
| **xs** | 4px | 极小间距 |
| **sm** | 8px | 小间距 |
| **md** | 16px | 默认间距 |
| **lg** | 24px | 中等间距 |
| **xl** | 32px | 大间距 |
| **xxl** | 48px | 超大间距 |

---

## 4. 组件样式 (Component Styles)

### 按钮 (Buttons)

```css
/* 主要按钮 */
.btn-primary {
    background: #36C;
    color: #FFFFFF;
    border: 1px solid #36C;
    padding: 8px 16px;
    border-radius: 2px;
    font-size: 14px;
    cursor: pointer;
}

.btn-primary:hover {
    background: #447FF5;
}

/* 次要按钮 */
.btn-secondary {
    background: #F8F9FA;
    color: #202122;
    border: 1px solid #A2A9B1;
    padding: 8px 16px;
    border-radius: 2px;
    font-size: 14px;
}

/* 文字按钮 */
.btn-text {
    background: transparent;
    color: #36C;
    border: none;
    padding: 8px 12px;
    font-size: 14px;
    text-decoration: underline;
}
```

### 卡片 (Cards)

```css
.card {
    background: #FFFFFF;
    border: 1px solid #E0E0E0;
    border-radius: 2px;
    padding: 16px;
    margin-bottom: 16px;
}

.card-header {
    border-bottom: 1px solid #E0E0E0;
    padding-bottom: 12px;
    margin-bottom: 12px;
    font-size: 16px;
    font-weight: 600;
}
```

### 表格 (Tables)

```css
.table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
}

.table thead {
    background: #F8F9FA;
    border-bottom: 1px solid #A2A9B1;
}

.table th {
    padding: 12px;
    text-align: left;
    font-weight: 600;
}

.table td {
    padding: 12px;
    border-bottom: 1px solid #E0E0E0;
}

.table tr:hover {
    background: #F8F9FA;
}
```

### 输入框 (Inputs)

```css
.input {
    width: 100%;
    padding: 8px 12px;
    border: 1px solid #A2A9B1;
    border-radius: 2px;
    font-size: 14px;
}

.input:focus {
    outline: none;
    border-color: #36C;
    box-shadow: 0 0 0 2px rgba(51, 102, 204, 0.2);
}

.input:disabled {
    background: #F8F9FA;
    color: #72777D;
}
```

### 标签 (Tags/Badges)

```css
/* Regime 标签 */
.tag {
    display: inline-block;
    padding: 4px 8px;
    font-size: 12px;
    border-radius: 2px;
    font-weight: 500;
}

.tag-recovery { background: #A7C7F7; color: #202122; }
.tag-overheat { background: #F4C2C2; color: #202122; }
.tag-stagflation { background: #E0E0E0; color: #202122; }
.tag-deflation { background: #C8D8B8; color: #202122; }

/* 状态标签 */
.tag-success { background: #D5FBDD; color: #14866D; }
.tag-warning { background: #FEF7E2; color: #AB7100; }
.tag-error { background: #FEE7E7; color: #D33; }
.tag-info { background: #D5E9FF; color: #36C; }
```

---

## 5. 布局规范 (Layout)

### 页面结构

```
┌─────────────────────────────────────────────────────┐
│ Header (56px)                                        │
├──────────┬──────────────────────────────────────────┤
│          │                                          │
│ Sidebar  │         Main Content                     │
│ (200px)  │                                          │
│          │                                          │
│          │                                          │
└──────────┴──────────────────────────────────────────┘
```

### Header

```css
.header {
    height: 56px;
    background: #FFFFFF;
    border-bottom: 1px solid #A2A9B1;
    padding: 0 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.header-logo {
    font-size: 18px;
    font-weight: 600;
    color: #202122;
}

.header-nav {
    display: flex;
    gap: 24px;
}

.header-nav a {
    color: #54595D;
    text-decoration: none;
    font-size: 14px;
}

.header-nav a:hover {
    color: #36C;
}
```

### Sidebar

```css
.sidebar {
    width: 200px;
    background: #F8F9FA;
    border-right: 1px solid #E0E0E0;
    padding: 16px 0;
}

.sidebar-item {
    padding: 8px 16px;
    color: #202122;
    text-decoration: none;
    display: block;
    font-size: 14px;
}

.sidebar-item:hover {
    background: #E0E0E0;
}

.sidebar-item.active {
    background: #D5E9FF;
    color: #36C;
    font-weight: 500;
}
```

### Main Content

```css
.main-content {
    flex: 1;
    padding: 24px;
    max-width: 1400px;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
}
```

---

## 6. 图表配色 (Chart Colors)

### 折线图/柱状图

```javascript
const chartColors = {
    primary: '#36C',
    secondary: '#72777D',
    grid: '#E0E0E0',
    axis: '#54595D',

    // 多系列配色（淡雅）
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

### Regime 象限图

```javascript
const regimeColors = {
    Recovery: '#A7C7F7',
    Overheat: '#F4C2C2',
    Stagflation: '#E0E0E0',
    Deflation: '#C8D8B8'
};

// 象限坐标
const regimeQuadrants = {
    Recovery: { x: 1, y: -1 },   // 右上
    Overheat: { x: 1, y: 1 },    // 右下
    Stagflation: { x: -1, y: 1 }, // 左下
    Deflation: { x: -1, y: -1 }  // 左上
};
```

---

## 7. 动画效果 (Animations)

### 过渡效果

```css
/* 默认过渡 */
.transition {
    transition: all 0.2s ease-in-out;
}

/* 淡入淡出 */
@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

.fade-in {
    animation: fadeIn 0.3s ease-in-out;
}

/* 滑入 */
@keyframes slideIn {
    from { transform: translateY(-10px); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
}

.slide-in {
    animation: slideIn 0.3s ease-out;
}
```

---

## 8. 响应式设计 (Responsive)

### 断点

```css
/* 移动端 */
@media (max-width: 768px) {
    .sidebar { display: none; }
    .main-content { padding: 16px; }
}

/* 平板 */
@media (min-width: 769px) and (max-width: 1024px) {
    .container { max-width: 900px; }
}

/* 桌面 */
@media (min-width: 1025px) {
    .container { max-width: 1200px; }
}
```

---

## 9. 图标系统 (Icons)

### 使用 SVG 图标

推荐使用 [Lucide Icons](https://lucide.dev/) 或 [Heroicons](https://heroicons.com/) - 风格简洁、线条优雅。

```html
<!-- 示例：趋势图标 -->
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline>
    <polyline points="17 6 23 6 23 12"></polyline>
</svg>
```

### 图标颜色

```css
.icon-primary { stroke: #36C; }
.icon-secondary { stroke: #72777D; }
.icon-muted { stroke: #A2A9B1; }
```

---

## 10. 特殊页面样式

### 登录页

```css
.login-page {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #F8F9FA;
}

.login-card {
    width: 400px;
    background: #FFFFFF;
    border: 1px solid #E0E0E0;
    border-radius: 2px;
    padding: 32px;
}
```

### 数据表格页

```css
.data-table-page {
    background: #FFFFFF;
}

.table-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px;
    border-bottom: 1px solid #E0E0E0;
}

.table-pagination {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px;
    border-top: 1px solid #E0E0E0;
}
```

---

## 11. 前端技术栈建议

### 方案 A: 纯 HTML + CSS + Vanilla JS
- 优点：简单、轻量、无构建步骤
- 适用：快速原型、简单界面

### 方案 B: Vue.js 3 + Element Plus
- 优点：组件丰富、文档完善
- 定制：使用自定义主题覆盖配色

### 方案 C: React + Ant Design
- 优点：生态成熟、组件强大
- 定制：使用 ConfigProvider 修改主题

### 方案 D: HTMX + Tailwind CSS
- 优点：轻量、Django 友好
- 定制：自定义 Tailwind 配置

---

## 12. CSS 变量定义

```css
:root {
    /* 基础色 */
    --color-bg: #FFFFFF;
    --color-surface: #F8F9FA;
    --color-border: #E0E0E0;

    /* 文字色 */
    --color-text-primary: #202122;
    --color-text-secondary: #54595D;
    --color-text-muted: #72777D;

    /* 功能色 */
    --color-primary: #36C;
    --color-primary-hover: #447FF5;
    --color-success: #14866D;
    --color-warning: #AB7100;
    --color-error: #D33;

    /* 间距 */
    --spacing-xs: 4px;
    --spacing-sm: 8px;
    --spacing-md: 16px;
    --spacing-lg: 24px;
    --spacing-xl: 32px;

    /* 圆角 */
    --radius-sm: 2px;
    --radius-md: 4px;
    --radius-lg: 8px;

    /* 阴影 */
    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
    --shadow-md: 0 2px 8px rgba(0, 0, 0, 0.08);
    --shadow-lg: 0 4px 16px rgba(0, 0, 0, 0.12);
}
```

---

## 13. 设计资源

### 参考

- **Wikipedia** - 整体风格参考
- **GitHub** - 代码展示、Markdown 样式
- **Vercel** - 简洁的文档风格
- **Stripe** - 数据表格设计

### 工具

- **Coolors** - 配色方案生成
- **Figma** - 设计原型
- **Tailwind CSS** - 快速开发

---

## 附录：快速样式模板

### 最小 HTML 模板

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AgomSAAF</title>
    <link rel="stylesheet" href="/static/css/main.css">
</head>
<body>
    <header class="header">
        <div class="header-logo">AgomSAAF</div>
        <nav class="header-nav">
            <a href="/regime/">Regime</a>
            <a href="/signals/">Signals</a>
            <a href="/backtest/">Backtest</a>
        </nav>
    </header>

    <div class="layout">
        <aside class="sidebar">
            <a href="/macro/" class="sidebar-item">宏观数据</a>
            <a href="/regime/" class="sidebar-item active">Regime 判定</a>
        </aside>

        <main class="main-content">
            <h1>Regime 判定</h1>
            <div class="card">
                <div class="card-header">当前状态</div>
                <div class="card-body">
                    <!-- 内容 -->
                </div>
            </div>
        </main>
    </div>
</body>
</html>
```

---

**文档版本**: V1.0
**维护**: AgomSAAF Team
