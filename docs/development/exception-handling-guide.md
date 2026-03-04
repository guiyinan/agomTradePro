# Exception Handling Guide

> **Last Updated**: 2026-03-04
> **Purpose**: Standardize exception handling across AgomSAAF for better observability and debugging

## Overview

This guide defines the standard patterns for exception handling in the AgomSAAF codebase. Proper exception handling ensures:

1. **Observability**: All exceptions are logged with sufficient context
2. **Categorization**: Exceptions can be classified by type for monitoring
3. **Recovery**: Appropriate actions can be taken based on exception type
4. **Debugging**: Root cause analysis is possible from logs

## Exception Hierarchy

All custom exceptions inherit from `AgomSAAFException` in `core/exceptions.py`:

```
AgomSAAFException
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
│   ├── IneligibleAssetError
│   ├── InsufficientDataError
│   └── DataValidationError
├── ExternalServiceError
│   ├── DataFetchError
│   │   ├── TushareError
│   │   └── AKShareError
│   └── AIServiceError
├── TimeoutError
└── ConfigurationError
    └── MissingConfigError
```

## When to Use Specific Exception Types

### 1. Validation Errors (`ValidationError`)

Use when input validation fails at API boundaries or user input points.

```python
from core.exceptions import ValidationError, InvalidInputError

# Use ValidationError for general validation failures
if not input_data:
    raise ValidationError("Input data is required")

# Use specific subclasses for well-known cases
if asset_code and not asset_code.startswith(('60', '00', '30')):
    raise InvalidInputError(f"Invalid asset code format: {asset_code}")
```

### 2. Business Logic Errors (`BusinessLogicError`)

Use when business rules are violated during domain logic execution.

```python
from core.exceptions import BusinessLogicError, IneligibleAssetError

# Domain rule violation
if regime.confidence < 0.6:
    raise BusinessLogicError("Regime confidence too low for signal generation")

# Specific business case
if policy_level >= 3:
    raise IneligibleAssetError(f"Asset {asset_code} not eligible at P{policy_level}")
```

### 3. External Service Errors (`ExternalServiceError`)

Use when external API calls fail. **Always wrap low-level exceptions**.

```python
from core.exceptions import ExternalServiceError, DataFetchError
import requests

# Before: Bare Exception
try:
    response = requests.get(url, timeout=5)
    response.raise_for_status()
except Exception as e:
    logger.error(f"Request failed: {e}")
    return None

# After: Specific exceptions
try:
    response = requests.get(url, timeout=5)
    response.raise_for_status()
except requests.Timeout as e:
    logger.warning(f"Request timeout: {url}")
    raise TimeoutError(f"External service timeout: {url}") from e
except requests.HTTPError as e:
    logger.exception(f"HTTP error from {url}: {e}")
    raise ExternalServiceError(f"Service returned error: {e.status_code}") from e
except requests.RequestException as e:
    logger.exception(f"Request failed: {url}")
    raise DataFetchError(f"Failed to fetch data from {url}") from e
```

### 4. Data Errors (`DataValidationError`, `InsufficientDataError`)

Use when data quality or quantity is insufficient for operations.

```python
from core.exceptions import DataValidationError, InsufficientDataError

if len(series) < 30:
    raise InsufficientDataError(
        f"Insufficient data points: {len(series)} < 30 required"
    )

if series.isna().any():
    raise DataValidationError("Series contains NaN values")
```

## Exception Handling Patterns

### Pattern 1: At Application Layer (Use Cases)

```python
from core.exceptions import DataFetchError, BusinessLogicError

class MyUseCase:
    def execute(self, request):
        try:
            # Business logic here
            result = self._process_data(request)
            return result
        except DataFetchError as e:
            # Known external error - convert to business error
            logger.warning(f"Data fetch failed: {e}")
            raise BusinessLogicError(f"Cannot process: {e}") from e
        except ValueError as e:
            # Input validation error
            logger.error(f"Invalid input: {e}")
            raise
        except Exception as e:
            # Unexpected error - log and wrap
            logger.exception(f"Unexpected error in MyUseCase: {e}")
            raise BusinessLogicError("Processing failed") from e
```

### Pattern 2: At Task Layer (Celery)

```python
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from core.exceptions import ExternalServiceError

@shared_task(bind=True, max_retries=3)
def my_task(self):
    try:
        # Task logic
        result = perform_operation()
        return result
    except ExternalServiceError as e:
        # Retryable external error
        logger.warning(f"External service error: {e}, retrying...")
        raise self.retry(exc=e, countdown=60)
    except (ValueError, TypeError) as e:
        # Non-retryable validation error
        logger.error(f"Validation error: {e}")
        return {"status": "error", "error": str(e)}
    except MaxRetriesExceededError:
        logger.error("Max retries exceeded")
        return {"status": "error", "error": "max_retries_exceeded"}
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return {"status": "error", "error": "unknown_error"}
```

### Pattern 3: At Infrastructure Layer (Repositories)

```python
from core.exceptions import DataFetchError
from django.db import DatabaseError

class MyRepository:
    def get_data(self):
        try:
            return Model.objects.get(id=pk)
        except Model.DoesNotExist:
            logger.warning(f"Model {pk} not found")
            return None
        except DatabaseError as e:
            logger.exception(f"Database error: {e}")
            raise DataFetchError(f"Failed to retrieve data") from e
```

## Logging Best Practices

### Use Appropriate Log Levels

- **DEBUG**: Detailed diagnostic information
- **INFO**: Normal operation milestones
- **WARNING**: Something unexpected but recoverable
- **ERROR**: Error that affects operation but can continue
- **CRITICAL**: Serious error that requires immediate attention

### Always Log with Context

```python
# Bad
logger.error(f"Error: {e}")

# Good
logger.error(
    f"Failed to fetch regime data: {e}",
    extra={
        "regime_type": regime_type,
        "as_of_date": as_of_date.isoformat(),
        "data_source": source_name,
    }
)

# For exceptions, use logger.exception() to include stack trace
logger.exception(f"Failed to process request {request_id}")
```

## Migration Strategy

### Phase 1: Add Metrics (Current)

Add exception counter to `core/metrics.py`:

```python
exception_total = Counter(
    'app_exception_total',
    'Total exceptions by type',
    ['module', 'exception_class']
)
```

### Phase 2: Refactor Critical Modules

Priority order:
1. `apps/policy/application/` - 76 exceptions
2. `apps/account/application/` - 27 exceptions
3. `apps/regime/application/` - 22 exceptions
4. `apps/signal/application/` - 26 exceptions

### Phase 3: Validate and Monitor

- Verify all exceptions are logged
- Check metrics in Prometheus/Grafana
- Review logs for unclassified exceptions

## Anti-Patterns to Avoid

### 1. Bare Exception Handling

```python
# BAD
try:
    operation()
except Exception:
    pass  # Silent failure

# GOOD
try:
    operation()
except SpecificError as e:
    logger.warning(f"Expected error occurred: {e}")
    # Handle appropriately
```

### 2. Loss of Stack Trace

```python
# BAD
try:
    operation()
except ValueError as e:
    raise NewError(str(e))  # Stack trace lost

# GOOD
try:
    operation()
except ValueError as e:
    raise NewError(str(e)) from e  # Preserves __cause__
```

### 3. Generic Error Messages

```python
# BAD
raise BusinessLogicError("Error occurred")

# GOOD
raise BusinessLogicError(
    f"Regime {regime_type} cannot be determined with {len(data)} data points. "
    f"Minimum required: {MIN_DATA_POINTS}"
)
```

## Testing Exception Handling

```python
import pytest
from core.exceptions import DataFetchError

def test_use_case_handles_fetch_error():
    use_case = MyUseCase(repository=MockRepository())

    # Mock repository to raise error
    use_case.repository.get_data.side_effect = DataFetchError("API down")

    # Should handle gracefully
    result = use_case.execute(request)

    assert result.status == "error"
    assert "API down" in result.message

def test_repository_converts_db_error():
    repo = MyRepository()

    with pytest.raises(DataFetchError):
        repo.get_data()  # Converts DatabaseError to DataFetchError
```

## Quick Reference

| Exception Type | When to Use | HTTP Status |
|----------------|-------------|-------------|
| `ValidationError` | Input validation fails | 400 |
| `AuthenticationError` | Authentication fails | 401 |
| `AuthorizationError` | Permission denied | 403 |
| `ResourceNotFoundError` | Resource not found | 404 |
| `BusinessLogicError` | Business rule violation | 422 |
| `ExternalServiceError` | External API fails | 503 |
| `TimeoutError` | Operation timeout | 504 |
| `ConfigurationError` | Invalid config | 500 |

## Related Documents

- `core/exceptions.py` - Exception class definitions
- `core/metrics.py` - Metrics definitions
- `CLAUDE.md` - Project architecture rules
