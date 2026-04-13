# 前端性能优化分析

> **分析日期**: 2026-02-20
> **最后更新**: 2026-04-12
> **当前状态**: 可用，按需加载已实现 ✅

---

## 当前状态

### 静态资源统计

| 资源类型 | 数量 | 大小 |
|---------|------|------|
| CSS 文件 | 18 个 | ~140KB |
| JS 文件 | ~15 个 | ~500KB |
| 总大小 | - | ~640KB |

### 基础模板加载 (base.html)

**全局 CSS (始终加载)**:
- `design-tokens.css` (5KB) - 设计变量
- `main.css` (13KB) - 主样式（含组件导入）
- `components.css` - 组件样式（备用）
- `floating-widget.css` - 浮动组件
- **首屏 CSS 总计**: ~40KB

**模块 CSS (按需加载)**:
- `regime.css` (6KB) - Regime 判定页面
- `signal.css` (10KB) - 投资信号管理
- `policy.css` (4KB) - 政策跟踪
- `equity.css` (10KB) - 个股分析
- `fund.css` (8KB) - 基金分析
- `account.css` (7KB) - 账户管理
- `backtest.css` (5KB) - 回测引擎
- `strategy.css` (7KB) - 策略管理
- `audit.css` (7KB) - 审计归因
- `macro.css` (6KB) - 宏观数据
- 等等...

**按需加载实现**: 各模块模板通过 `{% block extra_css %}` 只加载自身需要的 CSS。

**JavaScript (7+ 文件)**:
- `htmx.min.js` - HTMX 框架
- `flatpickr.min.js` + `flatpickr.zh.js` - 日期选择
- `sweetalert2.all.min.js` - 弹窗
- `alpine.min.js` (defer) - 响应式框架
- `utils.js`, `htmx-config.js` - 工具函数

---

## 问题分析

### 1. CSS 按需加载 ✅ 已实现

**状态**: 已实现，各模块模板通过 `{% block extra_css %}` 按需加载模块 CSS。

**实现方式**:
```html
<!-- base.html -->
{% block extra_css %}{% endblock %}

<!-- regime/dashboard.html -->
{% block extra_css %}
<link rel="stylesheet" href="{% static 'css/regime.css' %}">
{% endblock %}
```

**效果**:
- 首屏仅加载 ~40KB 全局 CSS
- 各页面额外加载 5-10KB 模块 CSS
- 总加载量减少 80%+

### 2. 重复的 CSS 文件 ✅ 已清理

**发现** (已修复):
- ~~`components/` 和 `components-v1/` 目录存在重复~~ - 已删除 `components-v1/`
- ~~`main.css` 和 `main-v1.css` 同时存在~~ - 已删除 `-v1.css` 文件
- ~~`base-v1.html` 未使用~~ - 已删除
- 部分模块 CSS 可能包含重复的组件样式（待检查）

**清理操作** (2026-02-20):
- 删除 `static/css/components-v1/` 目录
- 删除 `static/css/*-v1.css` 文件
- 删除 `core/templates/base-v1.html`

### 3. 无 CSS/JS 压缩

**问题**: 开发环境使用未压缩的 CSS，生产环境也没有自动压缩。

---

## 实施计划

### Phase 1: 清理 ✅ 已完成 (2026-02-20)

1. ✅ 删除 `-v1` 版本的重复文件
2. ✅ 删除 `base-v1.html` 模板
3. ✅ 审查并删除未使用的 CSS

**已删除文件**:
- `static/css/components-v1/` 目录（含所有文件）
- `static/css/design-tokens-v1.css`
- `static/css/main-v1.css`
- `static/css/components-v1.css`
- `core/templates/base-v1.html`

### Phase 2: 按需加载 ✅ 已完成 (2026-02-21)

1. ✅ 各模块模板使用 `{% block extra_css %}` 按需加载 CSS
2. ✅ 移除未使用的 `{% block module_css %}` 从 base.html
3. ✅ 更新文档反映当前实现状态

### Phase 3: 压缩 (待实施)

1. 配置 `django-compressor`
2. 测试生产构建
3. 部署

### P2 - 中优先级 (需要配置)

---

## 2026-04-12 首页专项优化

### 问题

- 登录后首页同步执行多次 Alpha 可视化查询与决策平面查询，导致首屏响应偏慢
- 首页顶部 `今日关注` / `行动建议` 卡片在三栏布局下可用宽度不足
- Alpha 选股表在 `000001.SZ` 这类带交易所后缀代码场景下，无法稳定回填股票简称

### 本次处理

- Dashboard 首页改为复用单次 Alpha 聚合查询结果，避免同一请求内重复执行 `stock_scores/provider_status/coverage/ic_trends`
- Dashboard 首页改为复用单次决策平面查询结果，避免同一请求内重复执行 Watch/Candidate/Quota/Pending 查询
- Alpha 名称解析增加代码别名匹配：同时支持 `000001.SZ` 和 `000001` 两种格式回填证券名称
- 首页顶部关注卡片改为更宽的双栏比例布局，并缩小左右侧栏宽度释放主内容区空间

### 回归点

- `apps/dashboard/tests/test_alpha_views.py`
  - 验证首页只执行一次 Alpha 聚合查询
  - 验证首页只执行一次决策平面查询
- `apps/dashboard/tests/test_alpha_queries.py`
  - 验证 `StockInfoModel.stock_code=000001` 时，`000001.SZ` 仍能解析为 `平安银行`

#### 2.1 启用 Django 静态文件压缩

安装 `django-compressor`:

```python
# settings/production.py
INSTALLED_APPS += ['compressor']

COMPRESS_ENABLED = True
COMPRESS_CSS_FILTERS = ['compressor.filters.cssmin.CSSMinFilter']
COMPRESS_JS_FILTERS = ['compressor.filters.jsmin.JSMinFilter']
```

#### 2.2 添加浏览器缓存

```python
# settings/production.py
STATIC_URL = '/static/'
AWS_S3_OBJECT_PARAMETERS = {
    'CacheControl': 'max-age=31536000',
}
```

### P3 - 低优先级 (架构变更)

#### 3.1 迁移到 CSS 模块化

考虑使用:
- Django Manifest Static Files
- Webpack/Vite 构建
- CSS Modules 或 Tailwind CSS

#### 3.2 图片优化

- 使用 WebP 格式
- 添加懒加载
- 使用 CDN

---

## 实施计划

### Phase 1: 清理 ✅ 已完成 (2026-02-20)

1. ✅ 删除 `-v1` 版本的重复文件
2. ✅ 删除 `base-v1.html` 模板
3. ⏳ 审查并删除未使用的 CSS（待检查）

**已删除文件**:
- `static/css/components-v1/` 目录（含所有文件）
- `static/css/design-tokens-v1.css`
- `static/css/main-v1.css`
- `static/css/components-v1.css`
- `core/templates/base-v1.html`

### Phase 2: 按需加载 (2-4 小时)

1. 修改 `base.html` 模板结构
2. 更新各模块模板使用 `{% block module_css %}`
3. 测试所有页面

### Phase 3: 压缩 (1-2 小时)

1. 配置 `django-compressor`
2. 测试生产构建
3. 部署

---

## 当前效果

| 指标 | 值 | 说明 |
|------|-----|------|
| 首屏 CSS | ~40KB | 仅全局样式 |
| 模块 CSS | 5-10KB | 按需加载 |
| 总 CSS 加载量 | ~45-50KB | 首屏 + 模块 |
| 首屏时间 | ~1s | 已优化 |
| 请求数 | ~10-12 | 已优化 |

---

## 监控建议

1. 使用 Lighthouse 定期检测
2. 添加 Web Vitals 监控
3. 设置性能预算 (CSS < 50KB, JS < 200KB)
