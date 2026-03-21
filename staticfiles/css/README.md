# AgomTradePro Design Tokens - 使用指南

## 概述

本目录包含 AgomTradePro 项目的设计 Token 系统和组件样式库。

**设计理念**：简洁、淡雅、专业 - 参考 Wikipedia 风格
**目标**：最大化数据可读性，最小化视觉干扰

## 文件结构

```
static/css/
├── design-tokens.css       # 设计 Token 变量定义
├── main.css                 # 主样式文件（整合所有样式）
├── components/
│   ├── buttons.css          # 按钮组件
│   ├── tables.css           # 表格组件
│   ├── forms.css            # 表单组件
│   ├── alerts.css           # 提示框组件
│   ├── badges.css           # 徽章/标签组件
│   └── cards.css            # 卡片组件
└── README.md                # 本文件
```

## 快速开始

### 1. 引入样式文件

在 Django 模板中引入主样式文件：

```django
{% load static %}
<link rel="stylesheet" href="{% static 'css/main.css' %}">
```

或单独引入设计 Token 和需要的组件：

```django
<link rel="stylesheet" href="{% static 'css/design-tokens.css' %}">
<link rel="stylesheet" href="{% static 'css/components/buttons.css' %}">
```

### 2. 使用设计 Token

在自定义样式中使用 CSS 变量：

```css
.custom-element {
  color: var(--color-text-primary);
  background: var(--color-surface);
  padding: var(--spacing-md);
  border-radius: var(--radius-md);
}
```

## 可用的设计 Token

### 颜色

```css
/* 基础色 */
--color-bg                 /* 页面背景 #FFFFFF */
--color-surface            /* 卡片/面板背景 #F8F9FA */
--color-border             /* 边框 #E0E0E0 */

/* 文字色 */
--color-text-primary       /* 主要文字 #202122 */
--color-text-secondary     /* 次要文字 #54595D */
--color-text-muted         /* 辅助文字 #72777D */

/* 功能色 */
--color-primary            /* 主要操作 #3366CC */
--color-success            /* 成功 #14866D */
--color-warning            /* 警告 #AB7100 */
--color-error              /* 错误 #DD3333 */

/* Regime 象限色 */
--color-regime-recovery    /* 复苏 #A7C7F7 */
--color-regime-overheat    /* 过热 #F4C2C2 */
--color-regime-stagflation /* 滞胀 #E0E0E0 */
--color-regime-deflation   /* 通缩 #C8D8B8 */
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
--font-family-base    /* 系统字体栈 */
--font-size-h1        /* 28px */
--font-size-h2        /* 24px */
--font-size-h3        /* 20px */
--font-size-body      /* 14px */
--font-size-small     /* 12px */
```

### 圆角

```css
--radius-sm   /* 2px */
--radius-md   /* 4px */
--radius-lg   /* 8px */
--radius-xl   /* 12px */
```

## 组件使用示例

### 按钮

```html
<!-- 主要按钮 -->
<button class="btn btn-primary">确定</button>

<!-- 次要按钮 -->
<button class="btn btn-secondary">取消</button>

<!-- 危险按钮 -->
<button class="btn btn-danger">删除</button>

<!-- 文字按钮 -->
<button class="btn btn-text">了解更多</button>

<!-- 尺寸变体 -->
<button class="btn btn-primary btn-sm">小按钮</button>
<button class="btn btn-primary btn-lg">大按钮</button>
```

### 表格

```html
<div class="table-wrapper">
  <table class="table">
    <thead>
      <tr>
        <th>列1</th>
        <th>列2</th>
        <th>列3</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>数据1</td>
        <td>数据2</td>
        <td>数据3</td>
      </tr>
    </tbody>
  </table>
</div>
```

### 表单

```html
<div class="form-group">
  <label class="form-label required">用户名</label>
  <input type="text" class="form-input" placeholder="请输入用户名">
  <small class="form-text">用户名长度为 4-20 个字符</small>
</div>
```

### 提示框

```html
<!-- 成功提示 -->
<div class="alert alert-success">
  <span class="alert-icon">✓</span>
  <span>操作成功！</span>
</div>

<!-- 错误提示 -->
<div class="alert alert-error">
  <span class="alert-icon">✕</span>
  <span>操作失败，请重试</span>
</div>
```

### 徽章

```html
<!-- 状态徽章 -->
<span class="badge badge-success">已完成</span>
<span class="badge badge-warning">处理中</span>
<span class="badge badge-error">已拒绝</span>

<!-- Regime 徽章 -->
<span class="badge badge-regime-recovery">复苏</span>
<span class="badge badge-regime-overheat">过热</span>
```

### 卡片

```html
<div class="card">
  <div class="card-header">
    <h3 class="card-header-title">卡片标题</h3>
  </div>
  <div class="card-body">
    <p>卡片内容...</p>
  </div>
</div>
```

## 工具类

### 间距

```html
<div class="m-3">外边距 16px</div>
<div class="p-4">内边距 24px</div>
<div class="mt-2 mb-4">上下边距</div>
```

### 文本

```html
<div class="text-center">居中文本</div>
<div class="text-primary">主要色文本</div>
<div class="text-muted">静音文本</div>
```

### 显示

```html
<div class="d-none">隐藏元素</div>
<div class="d-flex">Flex 容器</div>
```

## 最佳实践

1. **优先使用设计 Token**：避免硬编码颜色、间距值
2. **组件化思维**：使用预定义组件类而非自定义样式
3. **响应式设计**：使用容器类和工具类处理响应式布局
4. **可访问性**：使用语义化 HTML，确保键盘导航可用

## 迁移指南

### 从内联样式迁移到 Token

**之前：**
```css
.custom-box {
  padding: 16px;
  background: #F8F9FA;
  border: 1px solid #E0E0E0;
  border-radius: 8px;
}
```

**之后：**
```css
.custom-box {
  padding: var(--spacing-md);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}
```

## 版本历史

- **v1.0.0** (2026-02-18): 初始版本，包含基础设计 Token 和核心组件

## 维护

本样式库由 AgomTradePro 前端团队维护。

如有问题或建议，请联系：team-lead
