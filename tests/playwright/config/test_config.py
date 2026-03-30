"""
Test configuration for Playwright tests.
Centralizes URLs, credentials, and test settings.
"""
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class TestConfig:
    """Configuration for Playwright tests."""

    # Base URLs
    base_url: str = "http://localhost:8000"
    admin_url: str = "http://localhost:8000/admin"

    # Test credentials
    admin_username: str = "admin"
    admin_password: str = "Aa123456"

    # Timeout settings (milliseconds)
    default_timeout: int = 30000
    navigation_timeout: int = 60000
    screenshot_timeout: int = 5000

    # Screenshot settings
    screenshot_dir: str = "tests/playwright/reports/screenshots"
    full_page_screenshots: bool = True

    # Browser settings
    headless: bool = True  # Set to False for debugging
    browser_type: str = "chromium"
    viewport_width: int = 1920
    viewport_height: int = 1080

    # Page URLs - Auth
    login_url: str = "/account/login/"
    register_url: str = "/account/register/"
    logout_url: str = "/account/logout/"
    profile_url: str = "/account/profile/"

    # Page URLs - Dashboard
    dashboard_url: str = "/dashboard/"

    # Page URLs - Macro
    macro_data_url: str = "/macro/data/"
    macro_indicator_url: str = "/macro/indicator/"

    # Page URLs - Regime
    regime_dashboard_url: str = "/regime/dashboard/"
    regime_state_url: str = "/regime/state/"
    regime_history_url: str = "/regime/history/"

    # Page URLs - Signal
    signal_manage_url: str = "/signal/manage/"
    signal_create_url: str = "/signal/create/"
    signal_list_url: str = "/signal/list/"

    # Page URLs - Policy
    policy_manage_url: str = "/policy/workbench/"
    policy_events_url: str = "/policy/events/"

    # Page URLs - Equity
    equity_screen_url: str = "/equity/screen/"
    equity_detail_url: str = "/equity/detail/"
    equity_analysis_url: str = "/equity/analysis/"

    # Page URLs - Fund
    fund_dashboard_url: str = "/fund/dashboard/"
    fund_screen_url: str = "/fund/screen/"
    fund_detail_url: str = "/fund/detail/"

    # Page URLs - Asset Analysis
    asset_analysis_screen_url: str = "/asset-analysis/screen/"
    asset_analysis_score_url: str = "/asset-analysis/score/"

    # Page URLs - Backtest
    backtest_create_url: str = "/backtest/create/"
    backtest_results_url: str = "/backtest/results/"
    backtest_history_url: str = "/backtest/history/"

    # Page URLs - Simulated Trading
    simulated_trading_dashboard_url: str = "/simulated-trading/dashboard/"
    simulated_trading_positions_url: str = "/simulated-trading/positions/"
    simulated_trading_orders_url: str = "/simulated-trading/orders/"

    # Page URLs - Audit
    audit_reports_url: str = "/audit/reports/"
    audit_logs_url: str = "/audit/logs/"

    # Page URLs - Filter
    filter_manage_url: str = "/filter/manage/"
    filter_rules_url: str = "/filter/rules/"

    # Page URLs - Sector
    sector_analysis_url: str = "/sector/analysis/"
    sector_rotation_url: str = "/sector/rotation/"

    # Admin URLs
    admin_index: str = "/admin/"
    admin_macro: str = "/admin/macro/"
    admin_regime: str = "/admin/regime/"
    admin_signal: str = "/admin/signal/"
    admin_policy: str = "/admin/policy/"

    @property
    def all_user_urls(self) -> dict[str, str]:
        """All user-facing URLs for testing."""
        return {
            "login": self.login_url,
            "register": self.register_url,
            "dashboard": self.dashboard_url,
            "macro_data": self.macro_data_url,
            "regime_dashboard": self.regime_dashboard_url,
            "signal_manage": self.signal_manage_url,
            "policy_manage": self.policy_manage_url,
            "equity_screen": self.equity_screen_url,
            "fund_dashboard": self.fund_dashboard_url,
            "asset_analysis_screen": self.asset_analysis_screen_url,
            "backtest_create": self.backtest_create_url,
            "simulated_trading_dashboard": self.simulated_trading_dashboard_url,
            "audit_reports": self.audit_reports_url,
            "filter_manage": self.filter_manage_url,
            "sector_analysis": self.sector_analysis_url,
        }

    @property
    def all_admin_urls(self) -> dict[str, str]:
        """All admin URLs for testing."""
        return {
            "admin_index": self.admin_index,
            "admin_macro": self.admin_macro,
            "admin_regime": self.admin_regime,
            "admin_signal": self.admin_signal,
            "admin_policy": self.admin_policy,
        }

    @property
    def critical_paths(self) -> dict[str, list]:
        """Critical user paths to test."""
        return {
            "login_to_dashboard": [
                self.login_url,
                self.dashboard_url,
            ],
            "view_macro_data": [
                self.dashboard_url,
                self.macro_data_url,
            ],
            "check_regime": [
                self.dashboard_url,
                self.regime_dashboard_url,
                self.regime_state_url,
            ],
            "manage_signals": [
                self.dashboard_url,
                self.signal_manage_url,
                self.signal_create_url,
            ],
            "view_equity": [
                self.dashboard_url,
                self.equity_screen_url,
                self.equity_analysis_url,
            ],
            "run_backtest": [
                self.dashboard_url,
                self.backtest_create_url,
                self.backtest_results_url,
            ],
        }


# Global config instance
config = TestConfig()
