# AgomTradePro 前端设计指南

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
    <title>AgomTradePro</title>
    <link rel="stylesheet" href="/static/css/main.css">
</head>
<body>
    <header class="header">
        <div class="header-logo">AgomTradePro</div>
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

## 14. HTMX 技术栈 (Phase 1 更新)

### 14.1 集成的前端库

系统已集成以下前端库（通过 CDN）：

| 库名 | 版本 | 用途 |
|------|------|------|
| **HTMX** | 1.9.10 | 异步交互、无刷新页面更新 |
| **Bootstrap Icons** | 1.11.3 | 图标库 |
| **Flatpickr** | 6.0.7 | 日期选择器 |
| **SweetAlert2** | 11.10.3 | 美化确认框 |
| **Alpine.js** | 3.13.5 | 轻量级响应式交互 |

### 14.2 HTMX 使用模式

#### 列表分页

```html
<div id="item-list">
    <!-- HTMX 加载内容 -->
</div>

<button hx-get="/items/?page=2"
        hx-target="#item-list"
        hx-swap="innerHTML"
        hx-indicator="#loader">
    加载更多
</button>

<div id="loader" class="htmx-indicator">加载中...</div>
```

#### 模态框表单

```html
<button hx-get="/items/create/"
        hx-target="#modal"
        hx-swap="innerHTML">
    新建
</button>

<div id="modal" class="modal">
    <!-- 表单内容 -->
</div>
```

#### 实时搜索

```html
<input type="search"
       name="q"
       hx-get="/items/search/"
       hx-trigger="keyup changed delay:500ms"
       hx-target="#results">
```

#### 删除确认

```html
<button hx-delete="/items/1/"
        hx-confirm="确定删除？"
        hx-target="closest tr"
        hx-swap="outerHTML">
    删除
</button>
```

### 14.3 HTMX 响应头

服务器可以通过 HTTP 响应头控制 HTMX 行为：

| 头部 | 用途 |
|------|------|
| `HX-Trigger` | 触发客户端事件 |
| `HX-Redirect` | 客户端重定向 |
| `HX-Refresh` | 刷新页面 |
| `X-Success-Message` | 成功消息（自定义） |
| `X-Error-Message` | 错误消息（自定义） |

---

## 15. 新增 CSS 组件 (Phase 1)

### 15.1 模态框 (Modal)

```html
<div id="myModal" class="modal">
    <div class="modal-backdrop"></div>
    <div class="modal-dialog">
        <div class="modal-header">
            <h3 class="modal-title">标题</h3>
            <button class="modal-close">&times;</button>
        </div>
        <div class="modal-body">
            内容
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary">取消</button>
            <button class="btn btn-primary">确定</button>
        </div>
    </div>
</div>
```

### 15.2 标签页 (Tabs)

```html
<div class="tabs">
    <ul class="tab-list">
        <li class="tab-item active" data-target="tab1" data-content="content1">标签1</li>
        <li class="tab-item" data-target="tab2" data-content="content2">标签2</li>
    </ul>
</div>

<div id="content1" class="tab-content active">内容1</div>
<div id="content2" class="tab-content">内容2</div>
```

### 15.3 手风琴 (Accordion)

```html
<div class="accordion">
    <div class="accordion-item">
        <div class="accordion-header">
            <span class="accordion-title">标题</span>
            <span class="accordion-icon">▼</span>
        </div>
        <div class="accordion-content">
            <div class="accordion-body">内容</div>
        </div>
    </div>
</div>
```

### 15.4 表单增强组件

#### 滑块

```html
<div class="form-range">
    <input type="range" min="1" max="100" value="50">
    <span class="form-range-value">50</span>
</div>
```

#### 开关

```html
<label class="form-switch">
    <input type="checkbox">
    <span class="switch-track"></span>
    <span>启用</span>
</label>
```

#### 搜索框

```html
<div class="search-box">
    <input type="text" placeholder="搜索...">
</div>
```

### 15.5 时间轴 (Timeline)

```html
<div class="timeline">
    <div class="timeline-item">
        <div class="timeline-date">2024-01-01</div>
        <div class="timeline-content">事件内容</div>
    </div>
</div>
```

### 15.6 进度条 (Progress)

```html
<div class="progress">
    <div class="progress-bar" style="width: 75%"></div>
</div>
```

---

## 16. JavaScript 工具库 (Phase 1)

### 16.1 格式化函数

```javascript
// 数字格式化
formatNumber(1234.56)  // "1,234.56"

// 货币格式化
formatCurrency(1234.56)  // "¥1,234.56"

// 百分比格式化
formatPercent(0.1234)  // "+12.34%"

// 日期格式化
formatDate(new Date())  // "2024-01-01"

// 相对时间
timeAgo('2024-01-01')  // "3天前"
```

### 16.2 SweetAlert2 封装

```javascript
// 成功提示
alertSuccess('操作成功', '数据已保存')

// 错误提示
alertError('操作失败', '请稍后重试')

// 确认对话框
if (await confirmDialog('确定删除？', '此操作不可撤销')) {
    // 执行删除
}

// 危险操作确认
if (await confirmDanger('危险操作', '将永久删除数据')) {
    // 执行操作
}

// 加载提示
const swal = alertLoading('处理中...')
// 完成后关闭
Swal.close()
```

### 16.3 模态框操作

```javascript
// 打开/关闭模态框
openModal('myModal')
closeModal('myModal')
```

### 16.4 表单辅助

```javascript
// 序列化表单
const data = serializeForm(form)

// 重置表单
resetForm(form)

// 显示字段错误
showFieldError(input, '该字段不能为空')

// 清除字段错误
clearFieldError(input)
```

### 16.5 表格操作

```javascript
// 排序表格
sortTable(table, colIndex, 'number')

// 过滤表格
filterTable(table, colIndex, '关键词')
```

### 16.6 工具函数

```javascript
// 复制到剪贴板
await copyToClipboard('要复制的文本')

// 下载文件
downloadFile('/path/to/file.pdf', 'document.pdf')

// 下载 CSV
downloadCSV(data, 'filename.csv')

// 防抖
const debouncedSearch = debounce(searchFunc, 300)

// 节流
const throttledScroll = throttle(scrollFunc, 200)
```

---

## 17. Django 视图基类 (Phase 1)

### 17.1 HTMX 视图基类

#### HtmxTemplateView

```python
from shared.infrastructure.htmx import HtmxTemplateView

class MyView(HtmxTemplateView):
    template_name = 'my_template.html'
    htmx_template_name = 'my_partial.html'  # HTMX 请求使用
```

#### HtmxListView

```python
from shared.infrastructure.htmx import HtmxListView

class ItemListView(HtmxListView):
    model = Item
    template_name = 'items/list.html'
    htmx_template_name = 'items/table.html'  # HTMX 只更新表格
    paginate_by = 20
    search_fields = ['name', 'description']  # 可搜索字段
    ordering_fields = {'name': 'name', 'date': 'created_at'}  # 可排序字段
```

#### HtmxFormView

```python
from shared.infrastructure.htmx import HtmxFormView

class ItemFormView(HtmxFormView):
    template_name = 'items/form.html'
    htmx_template_name = 'items/form_partial.html'
    form_class = ItemForm
    success_url = '/items/'
    success_message = '保存成功'
```

#### HtmxDeleteView

```python
from shared.infrastructure.htmx import HtmxDeleteView

class ItemDeleteView(HtmxDeleteView):
    model = Item
    success_url = '/items/'
    success_message = '删除成功'
```

### 17.2 权限混合类

```python
from shared.infrastructure.htmx import StaffRequiredMixin, SuperuserRequiredMixin

class AdminOnlyView(StaffRequiredMixin, TemplateView):
    template_name = 'admin/page.html'

class SuperuserView(SuperuserRequiredMixin, TemplateView):
    template_name = 'superuser/page.html'
```

---

## 18. 装饰器 (Phase 1)

### 18.1 权限装饰器

```python
from shared.infrastructure.htmx import (
    staff_required,
    superuser_required,
    login_htmx_view
)

@staff_required
def admin_view(request):
    # 只有管理员可访问
    return render(request, 'admin/page.html')

@login_htmx_view
def protected_view(request):
    # 需要登录，自动处理 HTMX
    return render(request, 'protected/page.html')
```

### 18.2 HTMX 装饰器

```python
from shared.infrastructure.htmx import (
    htmx_only,
    htmx_trigger,
    htmx_view
)

@htmx_only
def htmx_only_view(request):
    # 只接受 HTMX 请求
    return render(request, 'partial.html')

@htmx_trigger('updateList')
def trigger_view(request):
    # 响应后触发客户端事件
    return render(request, 'partial.html')
```

### 18.3 消息装饰器

```python
from shared.infrastructure.htmx import (
    success_message,
    error_message
)

@success_message('操作成功')
def my_view(request):
    # 添加成功消息
    return redirect('/somewhere/')
```

---

## 19. HTMX 检测工具

### 19.1 Python 端检测

```python
from shared.infrastructure.htmx import is_htmx

def my_view(request):
    if is_htmx(request):
        # HTMX 请求
        return render(request, 'partial.html')
    else:
        # 普通请求
        return render(request, 'full.html')
```

### 19.2 模板中检测

```django
{% if is_htmx %}
    <!-- HTMX 请求内容 -->
{% else %}
    <!-- 完整页面 -->
{% endif %}
```

### 19.3 JavaScript 端检测

```javascript
document.body.addEventListener('htmx:afterRequest', function(evt) {
    console.log('HTMX 请求完成');
});
```

---

## 20. 最佳实践

### 20.1 HTMX 使用建议

1. **渐进增强**：确保页面在没有 HTMX 的情况下也能正常工作
2. **适当使用**：不是所有交互都需要 HTMX，简单操作可以直接用表单提交
3. **错误处理**：始终处理 HTMX 请求失败的情况
4. **性能考虑**：大量数据使用分页，避免一次性加载

### 20.2 组件使用建议

1. **模态框**：用于表单编辑、详情查看
2. **标签页**：用于内容分组
3. **手风琴**：用于折叠内容
4. **加载状态**：为长时间操作添加加载指示器

### 20.3 安全建议

1. **CSRF 保护**：所有 HTMX 请求都应包含 CSRF Token
2. **权限验证**：服务端必须验证用户权限
3. **输入验证**：始终验证用户输入
4. **XSS 防护**：注意动态内容的转义

---

**文档版本**: V2.0 (Phase 1 更新)
**维护**: AgomTradePro Team
**更新日期**: 2026-01-04
