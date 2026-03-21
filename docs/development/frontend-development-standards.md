# AgomTradePro 前端开发规范

> **版本**: 1.0
> **更新日期**: 2026-03-10
> **适用范围**: 所有前端页面（Django 模板 + 内联 JS/CSS）

---

## 1. 技术栈概览

| 技术 | 用途 | 备注 |
|------|------|------|
| **Django Templates** | 页面渲染 | 使用 `{% extends %}` 继承 |
| **HTMX** | 异步交互 | 渐进增强，无需 SPA |
| **Alpine.js** | 轻量响应式 | 简单交互状态管理 |
| **ECharts** | 图表 | 折线图、柱状图、象限图 |
| **SweetAlert2** | 对话框 | 确认、提示、危险操作 |
| **Flatpickr** | 日期选择 | 日期/时间输入 |
| **Bootstrap Icons** | 图标 | `<i class="bi bi-*">` |
| **Vanilla JS** | 业务逻辑 | 无 React/Vue/Angular |

**无构建步骤**：所有静态资源直接引用，不使用 Webpack/Vite。

---

## 2. 模板结构

### 2.1 继承模式

所有页面必须继承 `base.html`：

```django
{% extends "base.html" %}
{% load static %}

{% block title %}页面标题 - AgomTradePro{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{% static 'css/module.css' %}">
{% endblock %}

{% block content %}
<!-- 页面内容 -->
{% endblock %}

{% block extra_js %}
<script src="{% static 'js/module.js' %}"></script>
{% endblock %}
```

### 2.2 可用 Block

| Block | 用途 | 位置 |
|-------|------|------|
| `title` | 页面标题 | `<title>` |
| `extra_css` | 页面专属 CSS | `<head>` 底部 |
| `content` | 主内容区域 | `<main>` 内 |
| `extra_js` | 页面专属 JS | `<body>` 底部 |

### 2.3 模板文件位置

```
core/templates/
├── base.html                      # 全局基础模板
├── components/                    # 共享组件片段
│   └── alert_banner.html
├── <module>/                      # 模块页面模板
│   ├── list.html
│   ├── detail.html
│   └── form.html
apps/<module>/templates/<module>/  # App 内部模板（仅该 App 使用时）
```

**选择规则**：
- 跨模块共享 → `core/templates/`
- 仅单模块使用 → `apps/<module>/templates/<module>/`

---

## 3. CSS 规范

### 3.1 CSS 变量（Design Tokens）

所有颜色、间距、圆角必须使用 CSS 变量，定义在 `core/static/css/main.css` 的 `:root` 中：

```css
/* ✅ 正确 */
color: var(--color-primary);
padding: var(--spacing-md);
border-radius: var(--radius-sm);

/* ❌ 错误：硬编码 */
color: #36C;
padding: 16px;
border-radius: 4px;
```

### 3.2 CSS 选择器优先级 ⚠️

**核心规则**：页面内联样式必须使用 **ID 选择器** 定义模态框、弹窗等组件，避免被 `components.css` 中的全局 `.modal` 类覆盖。

```css
/* ❌ 错误：与 components.css 的 .modal 冲突 */
.modal {
    display: none;
    z-index: 1000;
}
.modal.active {
    display: block;
}

/* ✅ 正确：使用 ID 选择器提升优先级 */
#record-modal,
#fetch-modal {
    display: none;
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    z-index: 2100;
    background: none;
}
#record-modal.active,
#fetch-modal.active {
    display: block;
}
```

**背景**：`components.css` 定义了全局 `.modal` 样式，使用 `.show` 类切换显示。但部分页面使用 `.active` 类切换。两套机制冲突会导致模态框无法关闭。使用 ID 选择器可以确保页面内样式优先。

### 3.3 z-index 层级规范

| 层级 | z-index 范围 | 用途 |
|------|-------------|------|
| 基础内容 | 0 - 99 | 正常流内容 |
| 固定头部 | 100 - 199 | Header、导航栏 |
| 下拉菜单 | 200 - 499 | Dropdown、Tooltip |
| 全局组件 | 500 - 999 | 浮动组件、通知 |
| 全局弹窗（components.css） | 2000 | `.modal` 全局样式 |
| 页面弹窗（内联覆盖） | 2100 | 页面内 `#xxx-modal` |
| SweetAlert2 | 10000+ | 系统对话框 |

**弹窗内部 z-index**：

```css
.modal-overlay { z-index: 0; }   /* 遮罩层 */
.modal-content { z-index: 1; }   /* 内容层 */
```

### 3.4 样式位置选择

| 场景 | 位置 | 示例 |
|------|------|------|
| 全局通用组件 | `core/static/css/main.css` | 按钮、卡片、表格 |
| HTMX 增强组件 | `core/static/css/components.css` | 模态框、手风琴、标签页 |
| 模块专属样式（多页面） | `core/static/css/<module>.css` | `macro.css` |
| 单页面样式 | 模板内 `<style>` | 页面独有的布局 |

### 3.4 Loading / Spinner 规范

- 区块加载态统一使用 `app-loading-state`、`app-spinner`、`app-loading-text`。
- 表格加载态统一使用 `app-loading-cell` 和 `app-loading-state--table`。
- 按钮内联加载态统一使用 `app-inline-spinner`。
- 禁止在新代码中新增裸 `.loading`、`.spinner`、`.loading-state` 类名。
- 旧的 `.loading`、`.loader-spinner` 只作为兼容别名保留，不再作为新入口。

### 3.5 命名约定

使用 **BEM 风格** 或 **语义命名**：

```css
/* ✅ 语义化 */
.page-header { }
.stats-bar { }
.filter-toolbar { }
.data-table { }

/* ✅ BEM 风格 */
.card { }
.card-header { }
.card-body { }

/* ❌ 避免 */
.div1 { }
.red-text { }
.mt-20 { }  /* 不使用 Tailwind 风格工具类 */
```

---

## 4. JavaScript 规范

### 4.1 函数命名：页面唯一 ⚠️

**核心规则**：`closeModal()` 等通用名称在不同模板中会冲突。每个页面的关闭/打开函数必须使用 **页面级唯一名称**。

```javascript
/* ❌ 错误：通用名称，多页面冲突 */
function closeModal() { ... }
function openModal() { ... }

/* ✅ 正确：加页面/功能前缀 */
function closeRecordModal() { ... }    // macro/data_controller
function closeConfigModal() { ... }    // rotation/configs
function closeFlowModal() { ... }      // account/settings
function closeReviewModal() { ... }    // policy/workbench
function closeFactorModal() { ... }    // factor/manage
function closePortfolioModal() { ... } // factor/portfolios
function openProviderModal() { ... }   // ai_provider/manage
```

### 4.2 全局工具函数

`core/static/js/utils.js` 提供以下全局工具，无需重复实现：

| 分类 | 函数 | 用途 |
|------|------|------|
| **格式化** | `formatNumber(n)` | 千分位 `1,234.56` |
| | `formatCurrency(n)` | 货币 `¥1,234.56` |
| | `formatPercent(n)` | 百分比 `+12.34%` |
| | `formatDate(d)` | 日期 `2026-01-01` |
| | `timeAgo(d)` | 相对时间 `3天前` |
| **对话框** | `alertSuccess(title, msg)` | 成功提示 |
| | `alertError(title, msg)` | 错误提示 |
| | `confirmDialog(title, msg)` | 确认对话框 |
| | `confirmDanger(title, msg)` | 危险操作确认 |
| **表格** | `sortTable(table, col, type)` | 排序 |
| | `filterTable(table, col, kw)` | 过滤 |
| **表单** | `serializeForm(form)` | 序列化 |
| | `showFieldError(input, msg)` | 字段报错 |
| | `clearFieldError(input)` | 清除报错 |
| **工具** | `copyToClipboard(text)` | 复制到剪贴板 |
| | `downloadCSV(data, name)` | 下载 CSV |
| | `debounce(fn, ms)` | 防抖 |
| | `throttle(fn, ms)` | 节流 |

### 4.3 Toast 通知

使用内置的 `showToast()`，不要自行实现：

```javascript
showToast('操作成功', 'success');
showToast('发生错误', 'error');
showToast('请注意', 'warning');
showToast('提示信息', 'info');
// 第三个参数为持续时间（毫秒），默认 3000
showToast('稍纵即逝', 'info', 1500);
```

### 4.4 API 调用模式

统一使用 `fetch` + `async/await`：

```javascript
async function loadData() {
    try {
        const response = await fetch('/api/module/resource/', {
            headers: {
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value
                    || getCookie('csrftoken'),
            },
        });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        renderData(data);
    } catch (error) {
        console.error('加载失败:', error);
        showToast('加载失败，请稍后重试', 'error');
    }
}
```

**POST/PUT/DELETE 请求**：

```javascript
const response = await fetch('/api/module/resource/', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCookie('csrftoken'),
    },
    body: JSON.stringify({ key: 'value' }),
});
```

### 4.5 DOM 操作

```javascript
/* ✅ 使用 getElementById（最快） */
const el = document.getElementById('my-element');

/* ✅ 使用 querySelector（灵活） */
const el = document.querySelector('.card:first-child');

/* ❌ 不使用 jQuery */
$('#my-element')  // 项目未引入 jQuery
```

### 4.6 事件绑定

优先使用 `onclick` 属性（与现有代码一致），或在 `<script>` 中绑定：

```html
<!-- ✅ 内联事件（简单操作） -->
<button onclick="closeRecordModal()">关闭</button>

<!-- ✅ JS 绑定（复杂逻辑） -->
<script>
document.getElementById('myForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    // ...
});
</script>
```

### 4.7 错误处理

```javascript
/* ✅ 网络请求必须 try/catch */
try {
    const res = await fetch(url);
    const data = await res.json();
    if (data.success) {
        showToast('操作成功', 'success');
    } else {
        showToast('操作失败: ' + (data.error || data.message), 'error');
    }
} catch (error) {
    console.error('请求异常:', error);
    showToast('网络错误，请稍后重试', 'error');
}

/* ❌ 不要静默吞掉错误 */
try { ... } catch (e) { }
```

---

## 5. 弹窗（Modal）开发规范

弹窗是最常见的 CSS/JS 冲突点，必须严格遵守以下规则。

### 5.1 HTML 结构

```html
<div class="modal" id="<功能名>-modal">
    <div class="modal-overlay" onclick="close<功能名>Modal()"></div>
    <div class="modal-content">
        <div class="modal-header">
            <h3 id="<功能名>-modal-title">标题</h3>
            <button class="modal-close" onclick="close<功能名>Modal()">&times;</button>
        </div>
        <div class="modal-body">
            <!-- 内容 -->
        </div>
        <div class="modal-footer">
            <button class="btn-secondary" onclick="close<功能名>Modal()">取消</button>
            <button class="btn-primary">确认</button>
        </div>
    </div>
</div>
```

### 5.2 CSS 样式（页面内 `<style>`）

```css
#<功能名>-modal {
    display: none;
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    z-index: 2100;
    background: none;
}
#<功能名>-modal.active {
    display: block;
}
```

### 5.3 JS 函数

```javascript
function open<功能名>Modal() {
    document.getElementById('<功能名>-modal').classList.add('active');
}

function close<功能名>Modal() {
    document.getElementById('<功能名>-modal').classList.remove('active');
}
```

### 5.4 检查清单

- [ ] HTML 中 `id` 唯一，不与其他模态框冲突
- [ ] CSS 使用 `#id` 选择器，不使用 `.modal` 类选择器
- [ ] z-index ≥ 2100（高于 `components.css` 的 2000）
- [ ] JS 函数名使用唯一前缀（`close<功能名>Modal`）
- [ ] overlay 点击、关闭按钮、取消按钮均调用同一关闭函数
- [ ] 关闭时清理表单状态（如需要）

---

## 6. HTMX 使用规范

### 6.1 基本模式

```html
<!-- 异步加载内容 -->
<div hx-get="/api/items/"
     hx-trigger="load"
     hx-target="#item-list"
     hx-indicator="#loader">
</div>

<!-- 搜索（防抖） -->
<input type="search"
       hx-get="/api/items/search/"
       hx-trigger="keyup changed delay:500ms"
       hx-target="#results">

<!-- 删除确认 -->
<button hx-delete="/api/items/1/"
        hx-confirm="确定删除？"
        hx-target="closest tr"
        hx-swap="outerHTML">
    删除
</button>
```

### 6.2 CSRF 处理

HTMX 请求的 CSRF Token 已在 `htmx-config.js` 中全局配置，无需手动处理。

### 6.3 HTMX vs Fetch 选择

| 场景 | 推荐 | 原因 |
|------|------|------|
| 局部内容更新 | HTMX | 声明式，简洁 |
| 表单提交+刷新局部 | HTMX | 自动处理 swap |
| 复杂交互（多步骤、条件判断） | Fetch | 需要 JS 逻辑控制 |
| 文件上传 | Fetch | 需要 FormData 处理 |
| 需要处理响应数据再渲染 | Fetch | 需要 JS 处理 JSON |

---

## 7. 图表（ECharts）规范

### 7.1 初始化

```javascript
const chart = echarts.init(document.getElementById('chart-container'));
const option = {
    // 使用项目配色
    color: ['#A7C7F7', '#C8D8B8', '#F4C2C2', '#E8D5E2', '#F5DEB3'],
    // ...
};
chart.setOption(option);

// 响应式
window.addEventListener('resize', () => chart.resize());
```

### 7.2 容器要求

```html
<!-- ✅ 必须设置明确的宽高 -->
<div id="chart-container" style="width: 100%; height: 400px;"></div>

<!-- ❌ 不设高度会导致图表不显示 -->
<div id="chart-container"></div>
```

---

## 8. 安全规范

### 8.1 XSS 防护

```javascript
/* ❌ 危险：直接拼接 HTML */
container.innerHTML = `<div>${userInput}</div>`;

/* ✅ 安全：使用 textContent */
const div = document.createElement('div');
div.textContent = userInput;
container.appendChild(div);

/* ✅ 安全：Django 模板自动转义 */
{{ user_input }}  {# 自动转义 #}
{{ user_input|safe }}  {# 仅对确认安全的内容使用 #}
```

### 8.2 CSRF

- 所有非 GET 请求必须包含 CSRF Token
- HTMX 请求由 `htmx-config.js` 自动处理
- Fetch 请求需手动添加 `X-CSRFToken` Header

### 8.3 敏感数据

```javascript
/* ❌ 不要在前端存储敏感数据 */
localStorage.setItem('apiToken', token);

/* ❌ 不要在 console 打印敏感信息 */
console.log('token:', response.token);
```

---

## 9. 性能规范

### 9.1 资源加载

- 所有 JS/CSS 使用 `{% static %}` 引用，受 Django staticfiles 管理
- 图表库（ECharts）按需加载，仅在需要图表的页面引入
- 图片使用合适的格式和尺寸

### 9.2 DOM 操作

```javascript
/* ✅ 批量更新使用 DocumentFragment */
const fragment = document.createDocumentFragment();
items.forEach(item => {
    const row = createRow(item);
    fragment.appendChild(row);
});
tbody.appendChild(fragment);

/* ❌ 避免循环中逐个 DOM 操作 */
items.forEach(item => {
    tbody.innerHTML += createRowHTML(item);  // 每次触发重排
});
```

### 9.3 事件委托

```javascript
/* ✅ 对动态内容使用事件委托 */
document.getElementById('item-list').addEventListener('click', function(e) {
    const btn = e.target.closest('.delete-btn');
    if (btn) {
        deleteItem(btn.dataset.id);
    }
});

/* ❌ 避免给每个动态元素单独绑定 */
document.querySelectorAll('.delete-btn').forEach(btn => {
    btn.addEventListener('click', () => deleteItem(btn.dataset.id));
});
```

---

## 10. URL 和路由规范

### 10.1 路由分离

| 类型 | 文件 | URL 前缀 | 示例 |
|------|------|---------|------|
| 页面路由 | `urls.py` | `/<module>/` | `/macro/controller/` |
| API 路由 | `api_urls.py` | `/api/<module>/` | `/api/market-data/quotes/` |

**禁止在同一个文件中混用页面路由和 API 路由**。

### 10.2 模板中的 URL

```django
{# ✅ 使用 url 标签 #}
<a href="{% url 'macro:controller' %}">数据管理器</a>

{# ❌ 不要硬编码 URL #}
<a href="/macro/controller/">数据管理器</a>
```

### 10.3 JS 中的 URL

```javascript
/* ✅ 使用 data 属性传递 URL */
// HTML: <div id="app" data-api-url="{% url 'api:resource' %}">
const apiUrl = document.getElementById('app').dataset.apiUrl;

/* ✅ 或者使用内联变量 */
// <script> const API_BASE = '{% url "api:resource" %}'; </script>

/* ❌ 不要在 JS 中硬编码 URL */
fetch('/api/module/resource/');
```

---

## 11. 代码组织

### 11.1 内联 vs 外部文件

| 场景 | 方式 | 理由 |
|------|------|------|
| 单页面 < 100 行 JS/CSS | 内联 `<style>`/`<script>` | 减少 HTTP 请求 |
| 多页面共享 | 外部 `.js`/`.css` 文件 | 复用和缓存 |
| > 200 行 JS | 外部 `.js` 文件 | 可维护性 |

### 11.2 静态文件目录

```
core/static/
├── css/
│   ├── main.css              # 全局样式 + Design Tokens
│   ├── components.css        # HTMX 组件样式
│   ├── admin.css             # 管理后台
│   └── <module>.css          # 模块专属
├── js/
│   ├── utils.js              # 全局工具函数
│   ├── htmx-config.js        # HTMX 配置
│   └── <module>.js           # 模块专属
└── vendor/
    ├── htmx.min.js
    ├── alpine.min.js
    ├── echarts.min.js
    ├── flatpickr.min.js
    └── sweetalert2.all.min.js
```

---

## 12. 常见错误和排查

### 12.1 模态框无法关闭

**原因**：`components.css` 的 `.modal` 样式覆盖了页面内样式。

**排查**：
1. 打开浏览器 DevTools → Elements
2. 选中 modal 元素
3. 检查 Styles 面板中哪些规则生效
4. 确认是否使用了 ID 选择器

**修复**：参见第 5 节。

### 12.2 HTMX 请求后组件失效

**原因**：HTMX swap 替换了 DOM，原有事件绑定丢失。

**修复**：
```javascript
// 在 HTMX swap 后重新初始化
document.body.addEventListener('htmx:afterSwap', function(evt) {
    // 重新初始化日期选择器等
    initFlatpickr(evt.detail.target);
});
```

### 12.3 CSRF Token 403 错误

**原因**：非 GET 请求缺少 CSRF Token。

**修复**：确保 `htmx-config.js` 已加载，或手动添加 Header。

---

## 附录 A：新页面开发模板

```django
{% extends "base.html" %}
{% load static %}

{% block title %}功能名称 - AgomTradePro{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{% static 'css/module.css' %}">
{% endblock %}

{% block content %}
<div class="page-container">
    <div class="page-header">
        <h1>功能名称</h1>
        <div class="header-actions">
            <button class="btn-primary" onclick="openCreateModal()">
                <i class="bi bi-plus"></i> 新增
            </button>
        </div>
    </div>

    <div class="card">
        <div class="card-body">
            <table class="table" id="data-table">
                <thead>
                    <tr>
                        <th>名称</th>
                        <th>状态</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody id="table-body">
                    <!-- 动态渲染 -->
                </tbody>
            </table>
        </div>
    </div>
</div>

<!-- 模态框 -->
<div class="modal" id="create-modal">
    <div class="modal-overlay" onclick="closeCreateModal()"></div>
    <div class="modal-content">
        <div class="modal-header">
            <h3>新增</h3>
            <button class="modal-close" onclick="closeCreateModal()">&times;</button>
        </div>
        <div class="modal-body">
            <form id="create-form" onsubmit="handleSubmit(event)">
                {% csrf_token %}
                <!-- 表单字段 -->
                <div class="form-actions">
                    <button type="submit" class="btn-primary">保存</button>
                    <button type="button" class="btn-secondary" onclick="closeCreateModal()">取消</button>
                </div>
            </form>
        </div>
    </div>
</div>

<style>
#create-modal {
    display: none;
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    z-index: 2100;
    background: none;
}
#create-modal.active {
    display: block;
}
.modal-overlay {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    z-index: 0;
}
.modal-content {
    position: relative;
    width: 500px;
    max-width: 90%;
    margin: 100px auto;
    background: white;
    border-radius: var(--radius-lg, 12px);
    box-shadow: var(--shadow-lg);
    z-index: 1;
}
</style>
{% endblock %}

{% block extra_js %}
<script>
function openCreateModal() {
    document.getElementById('create-modal').classList.add('active');
}

function closeCreateModal() {
    document.getElementById('create-modal').classList.remove('active');
    document.getElementById('create-form').reset();
}

async function handleSubmit(event) {
    event.preventDefault();
    try {
        const form = event.target;
        const data = Object.fromEntries(new FormData(form));
        const response = await fetch('/api/module/resource/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': data.csrfmiddlewaretoken,
            },
            body: JSON.stringify(data),
        });
        const result = await response.json();
        if (result.success) {
            showToast('保存成功', 'success');
            closeCreateModal();
            loadData();
        } else {
            showToast('保存失败: ' + result.error, 'error');
        }
    } catch (error) {
        console.error('提交失败:', error);
        showToast('网络错误', 'error');
    }
}

async function loadData() {
    // 加载数据并渲染表格
}

document.addEventListener('DOMContentLoaded', loadData);
</script>
{% endblock %}
```

---

**文档版本**: 1.0
**维护**: AgomTradePro Team
