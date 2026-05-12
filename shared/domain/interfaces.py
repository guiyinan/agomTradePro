"""
Shared Domain Interfaces and Protocols.

Defines protocols that infrastructure layer must implement.
"""

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, Optional, Protocol, TypeVar

# Generic type variable for entities
T = TypeVar('T')
T_id = TypeVar('T_id')


@dataclass(frozen=True)
class TrendResult:
    """趋势计算结果"""
    values: tuple[float, ...]
    z_scores: tuple[float, ...]


class TrendCalculatorProtocol(Protocol):
    """趋势计算协议"""

    def calculate_hp_trend(
        self,
        series: list[float],
        lamb: float = 129600
    ) -> TrendResult:
        """HP 滤波计算趋势"""
        ...

    def calculate_z_scores(
        self,
        series: list[float],
        window: int = 60
    ) -> tuple[float, ...]:
        """计算 Z-score"""
        ...


@dataclass(frozen=True)
class DataSourceSecretsDTO:
    """数据源密钥数据传输对象"""
    tushare_token: str
    fred_api_key: str
    tushare_http_url: str | None = None
    juhe_api_key: str | None = None


class DatabaseSecretsLoaderProtocol(Protocol):
    """数据库密钥加载协议"""

    def __call__(self) -> DataSourceSecretsDTO | None:
        """从数据库加载密钥

        Returns:
            Optional[DataSourceSecretsDTO]: 如果数据库中有配置则返回，否则返回 None
        """
        ...


# =============================================================================
# Repository Protocols - Base interfaces for data access abstraction
# =============================================================================

class RepositoryProtocol(Protocol, Generic[T, T_id]):
    """
    Base Repository Protocol for Domain-Driven Design.

    This protocol defines the standard CRUD operations that all repositories
    must implement. Application layer should depend on this protocol, not
    concrete implementations.

    Type Parameters:
        T: The entity type this repository manages
        T_id: The type of the entity's identifier

    Example:
        class SignalRepositoryProtocol(RepositoryProtocol[InvestmentSignal, str]):
            def find_active_signals(self, asset_code: str) -> List[InvestmentSignal]: ...
    """

    def get_by_id(self, id: T_id) -> T | None:
        """Retrieve an entity by its identifier.

        Args:
            id: The entity's unique identifier

        Returns:
            The entity if found, None otherwise
        """
        ...

    def get_all(self) -> list[T]:
        """Retrieve all entities.

        Returns:
            List of all entities
        """
        ...

    def save(self, entity: T) -> T:
        """Persist an entity (create or update).

        Args:
            entity: The entity to persist

        Returns:
            The persisted entity (may include generated ID)
        """
        ...

    def delete(self, id: T_id) -> bool:
        """Delete an entity by its identifier.

        Args:
            id: The entity's unique identifier

        Returns:
            True if deleted, False if not found
        """
        ...


class FilterableRepositoryProtocol(RepositoryProtocol[T, T_id], Protocol):
    """
    Extended Repository Protocol with filtering capabilities.

    Use this when the repository needs to support complex queries.
    """

    def find_by_criteria(self, **criteria: Any) -> list[T]:
        """Find entities matching the given criteria.

        Args:
            **criteria: Key-value pairs for filtering

        Returns:
            List of matching entities
        """
        ...

    def count(self, **criteria: Any) -> int:
        """Count entities matching the given criteria.

        Args:
            **criteria: Key-value pairs for filtering

        Returns:
            Number of matching entities
        """
        ...
