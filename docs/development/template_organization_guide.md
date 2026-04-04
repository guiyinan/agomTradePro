# 模板组织规范

> **版本**: v1.0
> **创建日期**: 2026-02-18
> **维护**: backend-dev

---

## 1. 概述

本文档定义 AgomTradePro 项目的模板组织规范，确保模板文件的单一真源原则。

---

## 2. 模板目录结构

### 2.1 全局模板 (`core/templates/`)

**用途**: 不属于特定应用模块的全局模板

**目录结构**:
```
core/templates/
├── base.html              # 基础模板
├── 404.html               # 404 错误页面
├── 500.html               # 500 错误页面
├── components/            # 全局组件
│   ├── alert_banner.html
│   ├── json_assistant.html
│   └── ...
├── admin/                 # 管理后台全局功能
│   ├── base.html
│   ├── docs_manage.html
│   └── ...
├── docs/                  # 文档功能
│   ├── list.html
│   └── detail.html
└── ops/                   # 设置中心模板（目录名保留 ops）
    └── center.html
```

### 2.2 应用模板 (`apps/*/templates/<app_name>/`)

**用途**: 特定应用模块的模板

**目录结构**:
```
apps/
├── simulated_trading/
│   └── templates/
│       └── simulated_trading/
│           ├── my_accounts.html
│           ├── my_account_detail.html
│           └── ...
├── audit/
│   └── templates/
│       └── audit/
│           ├── base.html
│           ├── audit_page.html
│           └── ...
├── alpha_trigger/
│   └── templates/
│       └── alpha_trigger/
│           ├── list.html
│           └── ...
└── ...
```

---

## 3. 模板查找顺序

Django 按以下顺序查找模板：

1. `core/templates/` (由 `TEMPLATES.DIRS` 配置)
2. `apps/*/templates/` (由 `APP_DIRS = True` 启用)

**重要**: 确保模板名称不冲突，避免意外覆盖。

---

## 4. 命名规范

### 4.1 全局模板命名

- 使用小写字母和下划线
- 示例: `base.html`, `alert_banner.html`

### 4.2 应用模板命名

- 放在 `{app_name}/` 子目录中
- 使用小写字母和下划线
- 示例: `simulated_trading/my_accounts.html`

### 4.3 模板变量命名

- 使用小写字母和下划线
- 示例: `{{ account_name }}`, `{{ total_assets }}`

---

## 5. 模板引用规范

### 5.1 视图中引用模板

```python
# 正确 - 使用相对路径
def my_view(request):
    return render(request, 'my_accounts.html')

# 错误 - 不要硬编码完整路径
def my_view(request):
    return render(request, 'simulated_trading/my_accounts.html')
```

### 5.2 模板继承

```django
<!-- 正确 - 继承全局基础模板 -->
{% extends "base.html" %}

<!-- 应用特定基础模板 -->
{% extends "audit/base.html" %}
```

---

## 6. 迁移指南

### 6.1 添加新模板

**全局模板**: 放在 `core/templates/`
- 示例: `core/templates/components/new_component.html`

**应用模板**: 放在 `apps/{app_name}/templates/{app_name}/`
- 示例: `apps/myapp/templates/myapp/new_page.html`

### 6.2 迁移现有模板

当需要将模板从 `core/templates/` 迁移到应用目录时：

1. 创建应用模板目录: `apps/{app_name}/templates/{app_name}/`
2. 移动模板文件
3. 更新视图中的模板路径引用
4. 测试确保功能正常

---

## 7. 禁止事项

1. **不要** 在项目根目录创建 `templates/` 目录
2. **不要** 跨目录重复同名模板
3. **不要** 在视图中硬编码完整模板路径
4. **不要** 将应用模板放在 `core/templates/` 中（除非是全局共享的）

---

## 8. Django 配置

```python
# core/settings/base.py

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'core', 'templates')],  # 全局模板目录
        'APP_DIRS': True,  # 启用应用模板查找
        'OPTIONS': {
            'context_processors': [
                # ...
            ],
        },
    },
]
```

---

**维护**: backend-dev
**最后更新**: 2026-02-18
