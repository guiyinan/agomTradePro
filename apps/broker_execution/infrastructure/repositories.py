"""Compatibility repository facade for broker execution persistence."""

from __future__ import annotations

from .broker_access_repository import BrokerAccessRepositoryMixin
from .broker_agent_repository import BrokerAgentRepositoryMixin
from .broker_management_repository import BrokerManagementRepositoryMixin
from .broker_reconciliation_repository import BrokerReconciliationRepositoryMixin


class DjangoBrokerExecutionRepository(
    BrokerAccessRepositoryMixin,
    BrokerAgentRepositoryMixin,
    BrokerManagementRepositoryMixin,
    BrokerReconciliationRepositoryMixin,
):
    """ORM-backed broker execution repository with scoped atomic operations."""


__all__ = ["DjangoBrokerExecutionRepository"]
