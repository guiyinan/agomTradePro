# 错误处理改进指南

> **创建日期**: 2026-02-20
> **目标**: 改进关键路径的错误处理

---

## 当前状态

系统已有基本的错误处理机制:
- Django 中间件捕获异常
- API ViewSet 返回标准错误响应
- HTMX 错误事件处理

---

## 改进建议

### 1. API 端点错误处理

#### 当前模式

```python
def list(self, request):
    try:
        # 业务逻辑
        return Response(data)
    except Exception as e:
        return Response({'error': str(e)}, status=500)
```

#### 改进后

```python
from rest_framework.exceptions import APIException
from core.exceptions import (
    ResourceNotFoundError,
    ValidationError,
    BusinessLogicError,
)

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
        # 业务逻辑
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

### 2. 数据加载函数

#### 当前模式

```python
def load_data(code):
    response = requests.get(url)
    return response.json()
```

#### 改进后

```python
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class LoadDataResult:
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

def load_data(code: str) -> LoadDataResult:
    """
    Load data with comprehensive error handling.

    Returns:
        LoadDataResult with success status and data or error info
    """
    try:
        if not code:
            return LoadDataResult(
                success=False,
                error="代码不能为空",
                error_code="INVALID_CODE"
            )

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not data:
            return LoadDataResult(
                success=False,
                error="未找到数据",
                error_code="NO_DATA"
            )

        return LoadDataResult(success=True, data=data)

    except requests.Timeout:
        logger.error(f"Timeout loading data for {code}")
        return LoadDataResult(
            success=False,
            error="请求超时，请稍后重试",
            error_code="TIMEOUT"
        )
    except requests.HTTPError as e:
        logger.error(f"HTTP error loading data for {code}: {e}")
        return LoadDataResult(
            success=False,
            error=f"服务器错误: {e.response.status_code}",
            error_code="HTTP_ERROR"
        )
    except requests.RequestException as e:
        logger.error(f"Network error loading data for {code}: {e}")
        return LoadDataResult(
            success=False,
            error="网络错误，请检查连接",
            error_code="NETWORK_ERROR"
        )
    except Exception as e:
        logger.exception(f"Unexpected error loading data for {code}")
        return LoadDataResult(
            success=False,
            error="服务器内部错误",
            error_code="INTERNAL_ERROR"
        )
```

### 3. 外部服务调用

#### 当前模式

```python
def call_ai_service(prompt):
    return ai_client.generate(prompt)
```

#### 改进后

```python
from functools import wraps
from typing import Callable, TypeVar
import logging

logger = logging.getLogger(__name__)
T = TypeVar('T')

def with_retry(
    max_retries: int = 3,
    delay_seconds: float = 1.0,
    exceptions: tuple = (Exception,)
) -> Callable:
    """
    Decorator for retrying function calls on failure.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}), "
                            f"retrying in {delay_seconds}s: {e}"
                        )
                        import time
                        time.sleep(delay_seconds)
                    else:
                        logger.error(
                            f"{func.__name__} failed after {max_retries} "
                            f"attempts: {e}"
                        )

            raise last_exception
        return wrapper
    return decorator

@with_retry(max_retries=3, exceptions=(requests.RequestException,))
def call_ai_service(prompt: str) -> dict:
    """
    Call AI service with retry logic.

    Raises:
        AIServiceError: When AI service fails after retries
    """
    try:
        response = ai_client.generate(prompt)
        return response
    except AIServiceError:
        raise
    except Exception as e:
        logger.exception("Unexpected AI service error")
        raise AIServiceError(f"AI服务调用失败: {e}") from e
```

---

## 错误代码规范

| 错误代码 | 说明 | HTTP 状态码 |
|---------|------|------------|
| `INVALID_INPUT` | 输入验证失败 | 400 |
| `UNAUTHORIZED` | 未授权 | 401 |
| `FORBIDDEN` | 禁止访问 | 403 |
| `NOT_FOUND` | 资源不存在 | 404 |
| `CONFLICT` | 业务逻辑冲突 | 409 |
| `TIMEOUT` | 请求超时 | 504 |
| `NETWORK_ERROR` | 网络错误 | 503 |
| `INTERNAL_ERROR` | 服务器内部错误 | 500 |

---

## 实施清单

### 高优先级

- [x] 创建 `core/exceptions.py` 自定义异常 ✅ 2026-02-20
- [ ] 更新 API ViewSet 使用新异常
- [ ] 添加统一错误响应格式

### 中优先级

- [ ] 添加数据加载函数的 Result 模式
- [ ] 实现重试装饰器
- [ ] 改进日志记录

### 低优先级

- [ ] 创建错误监控面板
- [ ] 添加错误追踪 (Sentry)
- [ ] 实现告警通知

---

## 已完成项目

### 2026-02-20

- ✅ 创建 `core/exceptions.py`，包含以下异常类：
  - `AgomTradeProException` - 基础异常类
  - `ValidationError`, `InvalidInputError`, `MissingRequiredFieldError` - 验证错误
  - `AuthenticationError`, `AuthorizationError` - 认证授权错误
  - `ResourceNotFoundError`, `DuplicateResourceError` - 资源错误
  - `BusinessLogicError`, `RegimeNotDeterminedError`, `SignalValidationError`, `IneligibleAssetError` - 业务逻辑错误
  - `ExternalServiceError`, `DataFetchError`, `AIServiceError`, `TushareError`, `AKShareError` - 外部服务错误
  - `TimeoutError`, `ConfigurationError`, `MissingConfigError` - 其他错误
