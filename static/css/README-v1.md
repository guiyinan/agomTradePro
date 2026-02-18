# AgomSAAF Design Tokens v1.0 - 使用指南

> **版本**: v1.0.0
> **基于文档**: docs/architecture/ui_ux_design_tokens_v1.md
> **创建日期**: 2026-02-18

---

## 概述

本目录包含 AgomSAAF 项目的设计 Token 系统和组件样式库 v1.0。

**设计理念**：简洁、淡雅、专业 - 参考 Wikipedia 风格
**目标**：最大化数据可读性，最小化视觉干扰

## 文件结构

```
static/css/
├── design-tokens-v1.css       # 设计 Token 变量定义（v1.0）
├── main-v1.css                 # 主样式文件（v1.0）
├── components-v1/              # 组件样式目录（v1.0）
│   ├── buttons.css              # 按钮组件
│   ├── tables.css               # 表格组件
│   ├── forms.css                # 表单组件
│   ├── alerts.css               # 告警框组件
│   ├── badges.css               # 标签徽章组件
│   └── cards.css                # 卡片组件
└── README.md                    # 本文件
```

## 快速开始

### 1. 引入样式文件

在 Django 模板中引入主样式文件：

```django
{% load static %}
<link rel="stylesheet" href="{% static 'css/main-v1.css' %}">
```

或单独引入设计 Token 和需要的组件：

```django
<link rel="stylesheet" href="{% static 'css/design-tokens-v1.css' %}">
<link rel="stylesheet" href="{% static 'css/components-v1/buttons.css' %}">
```

### 2. 使用设计Token

在自定义样式中使用 CSS 变量：

```css
.custom-element {
  color: var(--color-text-primary);
  background: var(--color-surface);
  padding: var(--spacing-md);
  border-radius: var(--radius-xs);
}
```

## 可用的设计 Token

### 颜色

```css
/* 基础色 */
--color-bg                 /* #FFFFFF 页面背景 */
--color-surface            /* #F8F9FA 卡片/面板背景 */
--color-border             /* #E0E0E0 边框 */

/* 文字色 */
--color-text-primary       /* #202122 主要文字 */
--color-text-secondary     /* #54595D 次要文字 */
--color-text-muted         /* #72777D 辅助文字 */

/* 功能色 */
--color-primary            /* #3366CC 主要操作 */
--color-success            /* #14866D 成功 */
--color-warning            /* #AB7100 警告 */
--color-error              /* #DD3333 错误 */

/* Regime 象限色 */
--color-regime-recovery    /* #A7C7F7 复苏 */
--color-regime-overheat    /* #F4C2C2 过热 */
--color-regime-stagflation /* #E0E0E0 滞胀 */
--color-regime-deflation   /* #C8D8B8 通缩 */
```

### 间距

```css
--spacing-xs   /* 4px */
--spacing-sm   /* 8px */
--spacing-md   /* 16px */
--spacing-lg   /* 24px */
--spacing-xl   /* 32px */
--spacing-xxl  /* 48px */
```

### 字体

```css
--font-size-h1   /* 28px */
--font-size-h2   /* 24px */
--font-size-h3   /* 20px */
--font-size-h4   /* 18px */
--font-size-body /* 14px */
--font-size-small/* 12px */
```

### 圆角

```css
--radius-xs   /* 2px */
--radius-sm   /* 4px */
--radius-md   /* 8px */
--radius-lg   /* 12px */
--radius-full /* 9999px */
```

## 组件使用示例

### 按钮

```html
<!-- 主要按钮 -->
<button class="btn btn-primary">保存</button>

<!-- 次要按钮 -->
<button class="btn btn-secondary">取消</button>

<!-- 危险按钮 -->
<button class="btn btn-danger">删除</button>

<!-- 小按钮 -->
<button class="btn btn-primary btn-sm">小按钮</button>
```

### 表格

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

### 表单

```html
<div class="form-group">
  <label class="form-label">用户名</label>
  <input type="text" class="input" placeholder="请输入用户名">
  <span class="form-text">用户名长度为 4-20 个字符</span>
</div>
```

### 告警框

```html
<div class="alert alert-success">操作成功</div>
<div class="alert alert-warning">警告信息</div>
<div class="alert alert-error">错误信息</div>
```

### 标签

```html
<span class="tag tag-success">成功</span>
<span class="tag tag-warning">警告</span>
<span class="tag tag-error">错误</span>

<!-- Regime 标签 -->
<span class="tag tag-regime-recovery">复苏</span>
<span class="tag tag-regime-overheat">过热</span>
```

### 卡片

```html
<div class="card">
  <div class="card-header">标题</div>
  <div class="card-body">内容</div>
</div>
```

## 工具类

### 间距

```html
<div class="p-md">中等内边距</div>
<div class="mb-lg">大下边距</div>
```

### 文本

```html
<p class="text-secondary">次要文字</p>
<p class="text-center">居中文本</p>
<p class="text-muted">静音文本</p>
```

### 显示

```html
<div class="d-flex">Flex 容器</div>
<div class="d-flex-between">两端对齐</div>
```

## 最佳实践

1. **优先使用设计 Token**：避免硬编码颜色、间距值
2. **组件化思维**：使用预定义组件类而非自定义样式
3. **响应式设计**：使用容器类和工具类处理响应式布局
4. **可访问性**：使用语义化 HTML，确保键盘导航可用

## 迁移指南

### 从内联样式迁移到 Token

**之前**：
```css
.custom-box {
  padding: 16px;
  background: #F8F9FA;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
}
```

**之后**：
```css
.custom-box {
  padding: var(--spacing-md);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xs);
}
```

## 版本历史

- **v1.0** (2026-02-18): 初始版本，基于 ui_ux_design_tokens_v1.md

## 维护

本样式库由 AgomSAAF 前端团队维护。

**文档维护**: ui-ux-designer
**样式实现**: frontend-dev
**最后更新**: 2026-02-18
