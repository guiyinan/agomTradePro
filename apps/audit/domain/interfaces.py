"""
Audit Domain Layer - Repository Protocols

Repository interfaces for audit operations.
"""

from typing import List, Optional, Protocol, Dict
from datetime import date


class AuditRepositoryProtocol(Protocol):
    """Repository protocol for audit data access"""

    def get_indicator_performance(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> List[dict]:
        """Get indicator performance records within a date range"""
        ...

    def get_latest_indicator_performance(self, indicator_code: str) -> Optional[dict]:
        """Get the latest performance record for an indicator"""
        ...

    def get_active_threshold_configs(self) -> List[dict]:
        """Get all active threshold configurations"""
        ...

    def get_validation_summary(self, validation_run_id: str) -> Optional[dict]:
        """Get validation summary by run ID"""
        ...

    def get_recent_validations(self, limit: int = 10) -> List[dict]:
        """Get recent validation records"""
        ...


class MacroIndicatorRepositoryProtocol(Protocol):
    """Repository protocol for macro indicator data access"""

    def get_indicator_by_code(self, code: str) -> Optional[dict]:
        """Get indicator metadata by code"""
        ...


class RegimeLogRepositoryProtocol(Protocol):
    """Repository protocol for regime log data access"""

    def get_regime_logs_by_date_range(
        self,
        start_date: date,
        end_date: date,
    ) -> List[dict]:
        """Get regime logs within a date range"""
        ...
