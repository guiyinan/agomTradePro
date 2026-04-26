"""Data center repository providers for application consumers."""

from __future__ import annotations

from apps.data_center.infrastructure.connection_tester import run_connection_test
from apps.data_center.infrastructure.providers import MacroFactRepository


def get_macro_fact_repository() -> MacroFactRepository:
    """Return the default macro fact repository."""

    return MacroFactRepository()


def run_data_center_connection_test(*args, **kwargs):
    """Run a data-center connection test via the infrastructure implementation."""

    return run_connection_test(*args, **kwargs)
