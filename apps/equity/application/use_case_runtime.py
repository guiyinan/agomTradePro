"""Runtime configuration and recoverable error policy for equity use cases."""

from core.exceptions import ConfigurationError, DataFetchError, DataValidationError

RECOVERABLE_EQUITY_USE_CASE_EXCEPTIONS = (
    ArithmeticError,
    AttributeError,
    ConnectionError,
    ImportError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
    DataFetchError,
    DataValidationError,
    ConfigurationError,
)


def get_runtime_benchmark_code(key: str, default: str = "") -> str:
    """Return a runtime benchmark code through the account-owned config service."""

    from apps.equity.application import use_cases as _facade

    value = _facade.get_account_config_summary_service().get_runtime_benchmark_code(key, default)
    return str(value or default)
