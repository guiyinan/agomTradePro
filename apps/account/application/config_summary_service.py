"""Account-owned summaries used by the system config center."""

from __future__ import annotations

from typing import Any, Protocol


class AccountConfigSummaryRepository(Protocol):
    """Read model contract for account config-center summaries."""

    def get_account_settings_summary(self, user: Any) -> dict[str, Any]:
        """Return account profile and access-token summary for one user."""

    def get_system_settings_summary(self) -> dict[str, Any]:
        """Return singleton system settings summary."""

    def get_trading_cost_summary(self, user: Any) -> dict[str, Any]:
        """Return portfolio trading-cost summary for one user."""

    def get_market_visual_tokens(self) -> dict[str, str]:
        """Return runtime market visual tokens."""

    def get_admin_console_counts(self) -> dict[str, int]:
        """Return admin console account counters."""

    def get_runtime_macro_index_metadata_map(self) -> dict[str, dict[str, Any]]:
        """Return runtime macro indicator metadata map."""

    def get_runtime_macro_index_codes(self) -> list[str]:
        """Return runtime macro indicator codes."""

    def get_runtime_macro_publication_lags(self) -> dict[str, dict[str, Any]]:
        """Return runtime macro publication lag settings."""

    def get_runtime_qlib_config(self) -> dict[str, Any]:
        """Return runtime qlib config."""

    def get_runtime_alpha_fixed_provider(self) -> str:
        """Return runtime fixed alpha provider."""

    def get_runtime_benchmark_code(self, key: str, default: str = "") -> str:
        """Return a runtime benchmark code by key."""


class AccountConfigSummaryService:
    """Application service for account-owned config center summaries."""

    def __init__(self, repository: AccountConfigSummaryRepository):
        self.repository = repository

    def get_account_settings_summary(self, user: Any) -> dict[str, Any]:
        """Return account settings summary."""

        if not getattr(user, "is_authenticated", False):
            return {
                "status": "missing",
                "summary": {"message": "请先登录"},
            }
        return self.repository.get_account_settings_summary(user)

    def get_system_settings_summary(self) -> dict[str, Any]:
        """Return system settings summary."""

        return self.repository.get_system_settings_summary()

    def get_trading_cost_summary(self, user: Any) -> dict[str, Any]:
        """Return trading-cost summary."""

        if not getattr(user, "is_authenticated", False):
            return {
                "status": "missing",
                "summary": {"message": "请先登录"},
            }
        return self.repository.get_trading_cost_summary(user)

    def get_market_visual_tokens(self) -> dict[str, str]:
        """Return runtime market visual tokens."""

        return self.repository.get_market_visual_tokens()

    def get_admin_console_counts(self) -> dict[str, int]:
        """Return admin console account counters."""

        return self.repository.get_admin_console_counts()

    def get_runtime_macro_index_metadata_map(self) -> dict[str, dict[str, Any]]:
        """Return runtime macro indicator metadata map."""

        return self.repository.get_runtime_macro_index_metadata_map()

    def get_runtime_macro_index_codes(self) -> list[str]:
        """Return runtime macro indicator codes."""

        return self.repository.get_runtime_macro_index_codes()

    def get_runtime_macro_publication_lags(self) -> dict[str, dict[str, Any]]:
        """Return runtime macro publication lag settings."""

        return self.repository.get_runtime_macro_publication_lags()

    def get_runtime_qlib_config(self) -> dict[str, Any]:
        """Return runtime qlib config."""

        return self.repository.get_runtime_qlib_config()

    def get_runtime_alpha_fixed_provider(self) -> str:
        """Return runtime fixed alpha provider."""

        return self.repository.get_runtime_alpha_fixed_provider()

    def get_runtime_benchmark_code(self, key: str, default: str = "") -> str:
        """Return a runtime benchmark code by key."""

        return self.repository.get_runtime_benchmark_code(key, default)


_config_summary_repository: AccountConfigSummaryRepository | None = None


def configure_account_config_summary_repository(repository: AccountConfigSummaryRepository) -> None:
    """Register the account config-summary repository."""

    global _config_summary_repository
    _config_summary_repository = repository


def get_account_config_summary_service() -> AccountConfigSummaryService:
    """Return the configured account config-summary service."""

    if _config_summary_repository is None:
        raise RuntimeError("Account config summary repository is not configured")
    return AccountConfigSummaryService(_config_summary_repository)
