# 前端性能优化分析

> **分析日期**: 2026-02-20
> **最后更新**: 2026-02-20
> **当前状态**: 可用，部分优化已完成

---

## 当前状态

### 静态资源统计

| 资源类型 | 数量 | 大小 |
|---------|------|------|
| CSS 文件 | 32 个 | ~200KB |
| JS 文件 | ~15 个 | ~500KB |
| 总大小 | - | ~825KB |

### 基础模板加载 (base.html)

**CSS (16+ 文件)**:
- `design-tokens.css` - 设计变量
- `main.css` - 主样式
- 14 个模块 CSS (regime, signal, policy, equity, fund, etc.)
- `components.css` - 组件样式
- `floating-widget.css` - 浮动组件

**JavaScript (7+ 文件)**:
- `htmx.min.js` - HTMX 框架
- `flatpickr.min.js` + `flatpickr.zh.js` - 日期选择
- `sweetalert2.all.min.js` - 弹窗
- `alpine.min.js` (defer) - 响应式框架
- `utils.js`, `htmx-config.js` - 工具函数

---

## 问题分析

### 1. CSS 过度加载 (高影响)

**问题**: 每个页面加载所有 16+ 个模块的 CSS，但大多数页面只需要其中 1-2 个。

**影响**:
- 首次加载时间增加
- 浏览器需要解析不需要的 CSS
- 带宽浪费

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

## 优化建议

### P1 - 高优先级 (立即可做)

#### 1.1 按需加载模块 CSS

修改 `base.html`，使用模板块按需加载:

```html
<!-- base.html -->
{% block module_css %}{% endblock %}

<!-- regime/dashboard.html -->
{% block module_css %}
<link rel="stylesheet" href="{% static 'css/regime.css' %}">
{% endblock %}
```

**预期效果**: 减少 80%+ 的 CSS 加载量

#### 1.2 清理重复文件

```bash
# 删除旧版本
rm -rf static/css/components-v1/
rm static/css/main-v1.css
rm static/css/design-tokens-v1.css
```

### P2 - 中优先级 (需要配置)

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

## 预期效果

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| CSS 加载量 | ~200KB | ~40KB |
| 首屏时间 | ~2s | ~1s |
| 请求数 | 20+ | 10-12 |

---

## 监控建议

1. 使用 Lighthouse 定期检测
2. 添加 Web Vitals 监控
3. 设置性能预算 (CSS < 50KB, JS < 200KB)
