# 外包团队工作指南

> **创建日期**: 2026-02-21
> **最后更新**: 2026-02-23
> **审核来源**: 技术团队审核意见 (2026-02-20) + 甲方验收整改 (2026-02-23)

---

## 概述

本文档总结了技术团队对外包代码的审核意见和改进要求。所有外包团队成员必须严格遵循这些规则，以确保代码质量和架构一致性。

---

## 一、数据解析健壮性规则

### 1.1 必须处理无效数据

**问题背景**: 技术团队发现 `regime_dashboard_view` 中的 `float()` 转换在遇到 `None`、空字符串、非数字值时会崩溃。

**规则**: 所有从外部数据源（数据库、API、用户输入）获取的数值，必须使用安全的解析函数。

**正确示例**:
```python
def _safe_float(value, default=0.0):
    """安全地将值转换为 float，处理 None、空字符串、非数字值。"""
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

# 使用
growth_values = [_safe_float(item.get('value')) for item in data]
```

**错误示例**:
```python
# ❌ 这会在遇到 None 或 "N/A" 时崩溃
values = [float(item.get('value', 0)) for item in data]
```

### 1.2 安全解析函数模板

为常用数据类型创建统一的解析函数：

```python
def safe_int(value, default=0):
    """安全转换为整数"""
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def safe_float(value, default=0.0):
    """安全转换为浮点数"""
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def safe_str(value, default=""):
    """安全转换为字符串，去除首尾空格"""
    if value is None:
        return default
    return str(value).strip() or default

def safe_bool(value, default=False):
    """安全转换为布尔值"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', 'on')
    return bool(value)
```

---

## 二、错误处理规范

### 2.1 使用统一异常类

**规则**: 禁止使用裸 `Exception`，必须使用 `core/exceptions.py` 中定义的异常类。

**异常类层次**:
```
AgomTradeProException (基类)
├── ValidationError
│   ├── InvalidInputError
│   └── MissingRequiredFieldError
├── AuthenticationError
├── AuthorizationError
├── ResourceNotFoundError
├── DuplicateResourceError
├── BusinessLogicError
│   ├── RegimeNotDeterminedError
│   ├── SignalValidationError
│   └── IneligibleAssetError
└── ExternalServiceError
    ├── DataFetchError
    ├── AIServiceError
    ├── TushareError
    └── AKShareError
```

### 2.2 API 端点错误处理模式

**正确示例**:
```python
from rest_framework.response import Response
from core.exceptions import (
    ResourceNotFoundError,
    ValidationError,
    BusinessLogicError,
)
import logging

logger = logging.getLogger(__name__)

class MyViewSet(viewsets.ModelViewSet):
    def list(self, request):
        """
        List resources with proper error handling.

        Error responses:
        - 400: Validation error
        - 404: Resource not found
        - 409: Business logic conflict
        - 500: Server error (logged)
        """
        try:
            data = self._get_data(request)
            return Response(data)
        except ResourceNotFoundError as e:
            logger.warning(f"Resource not found: {e}")
            return Response({'error': str(e)}, status=404)
        except ValidationError as e:
            logger.info(f"Validation failed: {e}")
            return Response({'error': str(e)}, status=400)
        except BusinessLogicError as e:
            logger.warning(f"Business logic error: {e}")
            return Response({'error': str(e)}, status=409)
        except Exception as e:
            logger.exception(f"Unexpected error in {self.__class__.__name__}")
            return Response(
                {'error': '服务器内部错误，请稍后重试'},
                status=500
            )
```

### 2.3 数据加载函数使用 Result 模式

**规则**: 涉及外部调用的函数应返回结构化的结果对象。

```python
from dataclasses import dataclass
from typing import Optional, Generic, TypeVar

T = TypeVar('T')

@dataclass
class Result(Generic[T]):
    """操作结果封装"""
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

def load_data(code: str) -> Result[dict]:
    """加载数据，返回结构化结果"""
    try:
        if not code:
            return Result(
                success=False,
                error="代码不能为空",
                error_code="INVALID_CODE"
            )

        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()

        return Result(success=True, data=data)

    except requests.Timeout:
        return Result(
            success=False,
            error="请求超时",
            error_code="TIMEOUT"
        )
    except Exception as e:
        logger.exception(f"Unexpected error loading data for {code}")
        return Result(
            success=False,
            error="服务器内部错误",
            error_code="INTERNAL_ERROR"
        )
```

---

## 三、测试驱动开发

### 3.1 修复必须配合测试用例

**规则**: 任何 bug 修复或功能新增，必须先写测试用例。

**审核案例**: 技术团队修复 regime dashboard 的数值解析问题时，同步创建了测试用例：

```python
# tests/unit/test_regime_interface_views.py

def test_regime_dashboard_view_handles_invalid_raw_data_values(monkeypatch):
    """测试 regime dashboard 能正确处理无效的原始数据值"""
    fake_response = SimpleNamespace(
        success=True,
        result=SimpleNamespace(
            regime=SimpleNamespace(value="Recovery"),
            growth_level=50.1,
            inflation_level=2.3,
        ),
        raw_data={
            "growth": [
                {"date": "2026-01", "value": "50.2"},
                {"date": "2026-02", "value": None},      # None 值
                {"date": "2026-03", "value": ""},        # 空字符串
                {"date": "2026-04", "value": "bad"},     # 非数字
            ],
            "inflation": [
                {"date": "2026-01", "value": "2.1"},
                {"date": "2026-02", "value": "N/A"},     # 非数字
            ],
        },
        warnings=[],
        error=None,
    )

    # ... mock setup ...

    context = regime_dashboard_view(request)

    assert context["error"] is None
    # 验证无效值被正确处理为 0.0
    assert json.loads(context["regime_result"]["growth_values"]) == [50.2, 0.0, 0.0, 0.0]
    assert json.loads(context["regime_result"]["inflation_values"]) == [2.1, 0.0]
```

### 3.2 测试覆盖要求

| 层级 | 最低覆盖率 | 说明 |
|------|-----------|------|
| Domain 层 | 90% | 核心业务逻辑必须有完整测试 |
| Application 层 | 80% | UseCase 必须有集成测试 |
| Interface 层 | 70% | API 端点必须有边界测试 |
| Infrastructure 层 | 60% | 数据访问层需要 mock 测试 |

### 3.3 测试命名规范

```python
# ✅ 正确：描述性命名，说明测试场景
def test_regime_dashboard_view_handles_invalid_raw_data_values():
    pass

def test_calculate_regime_returns_recovery_when_pmi_rising_and_cpi_low():
    pass

# ❌ 错误：模糊命名
def test_dashboard():
    pass

def test_case_1():
    pass
```

### 3.4 页面 Smoke / E2E 测试契约

**规则**: 页面测试禁止只断言 `200`、URL 命中或 body 非空。所有关键页面的 Smoke / E2E 测试必须至少覆盖以下三类契约：

1. **关键 DOM 锚点**: 页面标题、核心卡片、主表格、主要按钮、图表容器必须存在且可见
2. **数据渲染完成**: 关键指标不能停留在 `-`、空字符串、`加载中...`、纯占位骨架或空壳容器
3. **基础样式契约**: 关键卡片/按钮/图表容器必须验证基础样式已生效，例如非透明背景、非零圆角、有效尺寸

该规则同样适用于 `setup wizard`、`operator/ops`、`profile`、配置表单页等运营和支撑页面，不能把它们降级成“只要能打开就算通过”。
页面测试不得使用 `[200, 302, 404]` 这类宽松状态码白名单；如果页面是正式入口，应断言明确的 `200` 和页面合同，重定向或缺页必须单独写权限/路由测试。

**最低要求示例**:

```python
def test_regime_dashboard_contract(authenticated_page):
    authenticated_page.goto("/regime/dashboard/")

    expect(authenticated_page.locator("h1")).to_have_text("Regime 判定")
    expect(authenticated_page.locator(".regime-card.active")).to_be_visible()
    assert authenticated_page.locator(".chart-card").count() >= 2

    quadrant_text = authenticated_page.locator("text=当前象限：").inner_text()
    assert quadrant_text.strip()

    style = authenticated_page.locator(".regime-card.active").evaluate(
        "(element) => getComputedStyle(element).getPropertyValue('border-radius')"
    )
    assert style != "0px"
```

**禁止写法**:

```python
def test_regime_dashboard_loads(authenticated_page):
    authenticated_page.goto("/regime/dashboard/")
    assert authenticated_page.url.endswith("/regime/dashboard/")
    assert authenticated_page.locator("body").inner_text().strip()
```

**适用范围**:
- `tests/playwright/tests/smoke/`
- 所有关键业务页面的回归测试
- 所有用户可见的首页、列表页、工作台、图表页

如果页面依赖异步加载，测试必须等待异步数据完成，而不是在 `加载中...` 状态下提前通过。

---

## 四、文档同步规范

### 4.1 代码修改必须更新文档

**规则**: 每次代码修改后，必须同步更新以下相关文档：

| 修改类型 | 必须更新的文档 |
|---------|---------------|
| 新增 API 端点 | `docs/development/quick-reference.md`, `docs/testing/api/API_REFERENCE.md` |
| 修改数据模型 | `docs/architecture/project_structure.md` |
| 新增业务模块 | `CLAUDE.md`, `docs/INDEX.md` |
| 修复 bug | 在对应模块文档中添加说明 |
| 修改配置 | `docs/deployment/` 相关文档 |

**API 改动附加门禁**: 只要接口路径、参数、响应字段、状态码或前端展示文案发生变化，除上表外还必须同步检查：
- SDK 调用层与示例文档
- MCP 工具返回结构与示例文档
- OpenAPI 产物：`schema.yml`、`docs/testing/api/openapi.yaml`、`docs/testing/api/openapi.json`
- 用户可见提示：模板、页面告警、fallback/stale 提示文案

**执行入口**: 统一按 `docs/development/engineering-guardrails.md` 中的“API 改动同步门禁”执行，并在 `docs/development/quick-reference.md` 复核命令。

### 4.2 API 路由一致性

**当前问题**: 系统存在三种 API 路由格式：
- `/api/{module}/api/{endpoint}/` (旧格式)
- `/api/{module}/{endpoint}/` (推荐格式)
- `/{module}/api/{endpoint}/` (混合格式)

**规则**: 新增 API 必须使用推荐格式 `/api/{module}/{endpoint}/`

详细说明见: `docs/development/api-route-consistency.md`

---

## 五、代码提交规范

### 5.1 提交粒度

**规则**: 每个提交应该是单一、原子性的变更。

**正确示例**:
```
提交 1: Harden regime dashboard numeric parsing for invalid raw data
提交 2: Add unit tests for regime dashboard view
提交 3: Document safe_float utility function
```

**错误示例**:
```
提交 1: Fix bugs and add features and update docs and cleanup code
```

### 5.2 提交消息格式

```
<type>: <subject>

[optional body]

类型 (type):
- feat: 新功能
- fix: bug 修复
- docs: 文档更新
- refactor: 重构
- test: 测试相关
- chore: 构建/工具相关
```

**示例**:
```
fix: Harden regime dashboard numeric parsing for invalid raw data

- Add _safe_float helper to handle None, empty string, non-numeric values
- Replace direct float() calls with safe version
- Add unit tests for edge cases
```

---

## 六、前端开发规范

### 6.1 CSS 按需加载

**问题**: 之前每个页面加载所有 16+ 个模块的 CSS，导致性能问题。

**规则**: 使用模板块按需加载 CSS：

```html
<!-- base.html -->
{% block module_css %}{% endblock %}

<!-- regime/dashboard.html -->
{% block module_css %}
<link rel="stylesheet" href="{% static 'css/regime.css' %}">
{% endblock %}
```

### 6.2 禁止重复文件

**规则**: 禁止创建 `-v1`、`-old`、`-backup` 等后缀的文件。使用 git 进行版本控制。

**已清理的重复文件** (2026-02-20):
- `static/css/components-v1/`
- `static/css/main-v1.css`
- `core/templates/base-v1.html`

---

## 七、架构边界检查清单

每次提交代码前，必须检查以下规则：

### 7.1 Domain 层检查
- [ ] 没有导入 `django.*`
- [ ] 没有导入 `pandas`、`numpy`
- [ ] 没有导入 `requests` 或其他外部库
- [ ] 只使用 Python 标准库和 dataclasses

### 7.2 shared/ 检查
- [ ] `shared/` 没有依赖 `apps/`
- [ ] 没有在 `shared/` 中放置业务实体
- [ ] 没有在 `shared/` 中放置 Django Model

### 7.3 依赖方向检查
- [ ] 依赖方向正确: `Interface -> Application -> Domain`，`Infrastructure -> Domain`
- [ ] 没有循环依赖
- [ ] Application 层未直接导入 `infrastructure/models.py`
- [ ] Interface 层未直接调用 Repository/ORM（只能调用 UseCase）

---

## 八、自查清单

提交代码前，请完成以下自查：

### 功能完整性
- [ ] 代码实现了需求的所有功能点
- [ ] 处理了边界情况和异常路径
- [ ] 所有用户输入都经过验证

### 测试
- [ ] 编写了单元测试
- [ ] 所有测试通过
- [ ] 测试覆盖率达标

### 代码质量
- [ ] 通过 `black .` 格式化
- [ ] 通过 `ruff check .` 检查
- [ ] 通过 `mypy apps/` 类型检查

### 文档
- [ ] 更新了相关文档
- [ ] API 路由格式正确
- [ ] 提交消息清晰

### 架构合规
- [ ] 没有违反四层架构
- [ ] 没有违反 `apps/` vs `shared/` 边界
- [ ] 依赖方向正确

---

## 九、常见问题及解决方案

### Q1: 数据从数据库取出来可能是 None 怎么办？

使用安全解析函数：
```python
value = _safe_float(obj.possible_none_field)
```

### Q2: API 返回的数据格式不确定怎么办？

使用 Result 模式，并在调用方检查 success：
```python
result = load_data(code)
if not result.success:
    return Response({'error': result.error}, status=400)
data = result.data
```

### Q3: 需要在 shared/ 中使用 apps/ 的某个类怎么办？

**禁止直接导入**。使用以下方案之一：
1. 在 shared/ 定义 Protocol，在 apps/ 中实现
2. 将逻辑移动到 apps/ 中
3. 使用注册表模式，由 apps/ 注册实现

### Q4: 如何处理外部 API 调用失败？

1. 使用 `@with_retry` 装饰器进行重试
2. 设置合理的超时时间
3. 返回 Result 对象，不要抛出异常
4. 记录详细日志

---

## 九、API 路由与契约规范（2026-02-23 新增）

> 本节基于甲方验收整改要求新增

### 9.1 API 与页面路由分离

**规则**：API 路由和页面路由必须分离到不同的文件中。

**正确做法**：
```
apps/policy/interface/
├── urls.py        # 页面路由（返回 HTML）
└── api_urls.py    # API 路由（返回 JSON）
```

**错误做法**：
```python
# ❌ 在同一个 urls.py 中混用 API 和页面路由
urlpatterns = [
    path("events/", PageView.as_view()),      # HTML
    path("events/", APIView.as_view()),       # API - 冲突！
]
```

### 9.2 API 契约测试

**规则**：每个 API 端点必须有契约测试，验证返回格式。

**必测内容**：
1. Content-Type 是否正确（application/json）
2. 状态码是否符合预期
3. 响应结构是否符合契约

**示例**：
```python
@pytest.mark.django_db
def test_api_policy_events_endpoint_returns_json_contract():
    """API 端点必须返回 JSON，不是 HTML"""
    response = client.get("/api/policy/events/")

    assert response.headers["Content-Type"].startswith("application/json")
    # 不是 text/html
```

### 9.2.1 页面 Smoke 不得只测 200（2026-05-11 新增）

**规则**：关键页面的回归测试不能只断言 `status_code == 200`，必须同时验证页面契约和真实数据形态。

**关键页面最少要求**：
1. `Content-Type` 必须是 `text/html`
2. 页面必须包含关键业务片段，而不是空壳模板
3. 页面内容中不得出现 `Internal Server Error`、`Traceback`、Django 默认报错页片段
4. 至少一条测试必须使用真实 ORM / Query 返回对象，而不是只用手工 `dict` fixture

**典型反例**：
```python
# ❌ 这类测试会放过很多真实渲染错误
response = client.get("/dashboard/")
assert response.status_code == 200
```

**推荐做法**：
```python
# ✅ 同时验证 HTML contract 与真实对象载荷
response = client.get("/dashboard/")
assert response.status_code == 200
assert response["Content-Type"].startswith("text/html")
content = response.content.decode("utf-8")
assert "待执行队列" in content
assert "进入新 Workflow" in content
assert "Internal Server Error" not in content
```

### 9.3 成对操作一致性

**规则**：CRUD 操作的参数签名必须保持一致。

**检查清单**：
- [ ] 如果 Delete 支持 `event_id` 参数，Update 也必须支持
- [ ] 如果 Create 返回特定字段，Update 也应返回相同字段
- [ ] 所有操作的错误处理方式必须一致

**错误案例**：
```python
# ❌ Delete 支持 event_id，Update 不支持
def delete(event_date, event_id=None):  # 支持 event_id
    ...

def update(event_date, level, ...):     # 缺少 event_id
    ...
```

**正确做法**：
```python
# ✅ 成对操作参数一致
def delete(event_date, event_id=None):
    ...

def update(event_date, level, ..., event_id=None):  # 也支持 event_id
    ...
```

### 9.4 修复完整性检查

**规则**：修复问题时，必须检查所有相关场景。

**检查步骤**：
1. 识别问题的影响范围
2. 列出所有相似的操作/模块
3. 确认是否需要同步修复
4. 添加回归测试

**案例**：
```
问题：Delete 按日期删除会影响同日所有事件

检查清单：
- [x] DeleteUseCase 添加 event_id 参数
- [x] UpdateUseCase 添加 event_id 参数 ← 容易遗漏！
- [x] 添加契约测试
- [x] 添加精确操作测试
```

### 9.5 路由重命名同步检查（2026-02-23 新增）

**规则**：修改路由名称时，必须同步更新所有引用。

**必须检查的位置**：
1. 模板文件（`.html`）中的 `{% url %}` 标签
2. JavaScript 文件中的 AJAX 请求 URL
3. Python 代码中的 `reverse()` 调用
4. 其他模块的 URL 引用

**检查命令**：
```bash
# 搜索旧路由名的所有引用
grep -r "old_route_name" --include="*.html" --include="*.js" --include="*.py"
```

**必须添加的测试**：
- 模板渲染测试，验证不会抛出 `NoReverseMatch`

**案例**：
```
路由重命名：api_analyze → analyze

必须同步更新：
- [x] urls.py 中的路由定义
- [ ] 模板文件中的 {% url "sentiment:api_analyze" %} ← 容易遗漏！
- [x] 添加模板渲染测试
```

---

## 十、参考资料

- `docs/development/outsourcing-task-book-2026-02-22.md` - 外包测试与修复任务书（当前执行批次）
- `docs/development/rectification-2026-02-23.md` - 外包交付整改报告（甲方验收）
- `CLAUDE.md` - 项目主规则文件
- `docs/development/error-handling-guide.md` - 错误处理详细指南
- `docs/development/api-route-consistency.md` - API 路由一致性分析
- `docs/development/frontend-performance-analysis.md` - 前端性能优化
- `docs/development/system-review-report.md` - 系统审视报告
- `core/exceptions.py` - 统一异常类定义

---

*本指南将根据技术团队的审核意见持续更新*
