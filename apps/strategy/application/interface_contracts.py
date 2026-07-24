"""Typed contracts for strategy application/interface boundaries."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Protocol

from apps.strategy.domain.entities import StrategyExecutionResult


class StrategyPortfolioView(Protocol):
    """Portfolio fields consumed by strategy interface services."""

    @property
    def id(self) -> int:
        """Return the portfolio identifier."""

    @property
    def account_name(self) -> str:
        """Return the display name of the portfolio."""


class StrategyAssignmentView(Protocol):
    """Assignment fields consumed by strategy interface services."""

    @property
    def portfolio_id(self) -> int:
        """Return the assigned portfolio identifier."""

    @property
    def portfolio(self) -> StrategyPortfolioView:
        """Return the assigned portfolio view."""


class StrategyExecutionLogView(Protocol):
    """Execution-log fields consumed by strategy read helpers."""

    @property
    def id(self) -> int:
        """Return the execution-log identifier."""

    @property
    def portfolio_id(self) -> int:
        """Return the executed portfolio identifier."""

    @property
    def execution_time(self) -> datetime:
        """Return the execution timestamp."""

    @property
    def execution_duration_ms(self) -> int:
        """Return the measured execution duration."""

    @property
    def signals_generated(self) -> list[dict[str, Any]]:
        """Return the generated signal payloads."""

    @property
    def is_success(self) -> bool:
        """Return whether the execution succeeded."""


class StrategyInterfaceRepositoryProtocol(Protocol):
    """Repository operations required by strategy interface services."""

    def get_strategy_queryset(self) -> Any:
        """Return the ORM queryset boundary used by DRF."""

    def get_strategy_queryset_for_owner(self, owner_profile_id: int) -> Any:
        """Return owner-scoped strategies."""

    def get_strategy_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> Any:
        """Return strategies visible to one caller."""

    def list_user_strategies_with_counts(self, owner_profile_id: int) -> Iterable[Any]:
        """Return strategies annotated with interface-facing counts."""

    def get_user_strategy_stats(self, owner_profile_id: int) -> dict[str, Any]:
        """Return aggregate strategy counts for one owner."""

    def list_strategy_rule_summary(
        self,
        strategy_id: int,
        limit: int = 3,
    ) -> list[Any]:
        """Return the highest-priority rule rows for one strategy."""

    def replace_rule_conditions(
        self,
        strategy_id: int,
        validated_rules: list[dict[str, Any]],
    ) -> None:
        """Replace persisted rule conditions."""

    def get_strategy_script_config(self, strategy_id: int) -> Any | None:
        """Return a persisted script configuration."""

    def delete_strategy_script_config(self, strategy_id: int) -> None:
        """Delete a persisted script configuration."""

    def get_strategy_ai_config(self, strategy_id: int) -> Any | None:
        """Return a persisted AI configuration."""

    def list_active_prompt_templates(self) -> list[Any]:
        """Return active prompt template rows."""

    def list_active_chain_configs(self) -> list[Any]:
        """Return active chain configuration rows."""

    def list_active_ai_providers_for_user(self, user_id: int) -> list[Any]:
        """Return active AI provider rows visible to one user."""

    def get_strategy_execution_logs_page(
        self,
        strategy_id: int,
        offset: int,
        limit: int,
    ) -> tuple[Any, int]:
        """Return one ORM-backed page of execution logs and its total."""

    def get_strategy_position_rule(self, strategy_id: int) -> Any | None:
        """Return the position rule attached to one strategy."""

    def get_position_management_rule_queryset(self) -> Any:
        """Return the ORM queryset boundary for position rules."""

    def get_position_management_rule_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> Any:
        """Return position rules visible to one caller."""

    def get_rule_condition_queryset(self) -> Any:
        """Return the ORM queryset boundary for rule conditions."""

    def get_rule_condition_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> Any:
        """Return rule conditions visible to one caller."""

    def get_script_config_queryset(self) -> Any:
        """Return the ORM queryset boundary for script configurations."""

    def get_script_config_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> Any:
        """Return script configurations visible to one caller."""

    def get_ai_strategy_config_queryset(self) -> Any:
        """Return the ORM queryset boundary for AI configurations."""

    def get_ai_strategy_config_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> Any:
        """Return AI configurations visible to one caller."""

    def strategy_is_accessible(
        self,
        *,
        strategy_id: int,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> bool:
        """Return whether one caller may bind configuration to a strategy."""

    def strategy_is_active(self, strategy_id: int) -> bool:
        """Return whether the strategy exists and is enabled for execution."""

    def get_assignment_queryset(self) -> Any:
        """Return the ORM queryset boundary for assignments."""

    def get_assignment_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> Any:
        """Return assignments visible to one owner or a staff caller."""

    def list_assignments_by_portfolio(self, portfolio_id: int) -> Any:
        """Return assignments for one portfolio."""

    def list_assignments_by_portfolio_for_access(
        self,
        *,
        portfolio_id: int,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> Any:
        """Return owner-scoped assignments for one portfolio."""

    def list_active_assignments_for_strategy(
        self,
        strategy_id: int,
    ) -> list[StrategyAssignmentView]:
        """Return active assignments for one strategy."""

    def bind_strategy(
        self,
        *,
        portfolio_id: int,
        strategy: Any,
        assigned_by: Any,
    ) -> Any:
        """Bind one strategy to a portfolio."""

    def unbind_portfolio_strategies(self, portfolio_id: int) -> None:
        """Deactivate active assignments for one portfolio."""

    def set_strategy_active(self, strategy_id: int, is_active: bool) -> Any | None:
        """Update and return one strategy row."""

    def set_rule_enabled(self, rule_id: int, is_enabled: bool) -> Any | None:
        """Update and return one rule row."""

    def set_assignment_active(self, assignment_id: int, is_active: bool) -> Any | None:
        """Update and return one assignment row."""

    def get_execution_log_queryset(self) -> Any:
        """Return the ORM queryset boundary for execution logs."""

    def get_execution_log_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> Any:
        """Return execution logs visible through both linked owners."""

    def list_execution_logs_by_strategy(
        self,
        strategy_id: int,
        limit: int = 100,
    ) -> list[StrategyExecutionLogView]:
        """Return recent execution logs for one strategy."""

    def list_execution_logs_by_strategy_for_access(
        self,
        *,
        strategy_id: int,
        owner_profile_id: int | None,
        include_all: bool = False,
        limit: int = 100,
    ) -> list[StrategyExecutionLogView]:
        """Return owner-scoped recent logs for one strategy."""

    def list_execution_logs_by_portfolio(
        self,
        portfolio_id: int,
        limit: int = 100,
    ) -> list[StrategyExecutionLogView]:
        """Return recent execution logs for one portfolio."""

    def list_execution_logs_by_portfolio_for_access(
        self,
        *,
        portfolio_id: int,
        owner_profile_id: int | None,
        include_all: bool = False,
        limit: int = 100,
    ) -> list[StrategyExecutionLogView]:
        """Return owner-scoped recent logs for one portfolio."""


class StrategyExecutionRunnerProtocol(Protocol):
    """Executor operation consumed by interface orchestration."""

    def execute_strategy(
        self,
        strategy_id: int,
        portfolio_id: int,
    ) -> StrategyExecutionResult:
        """Execute one strategy against one portfolio."""


class StrategyPortfolioProviderProtocol(Protocol):
    """Portfolio read operation consumed by strategy payload helpers."""

    def get_positions(self, portfolio_id: int) -> list[dict[str, Any]]:
        """Return normalized positions for one portfolio."""
