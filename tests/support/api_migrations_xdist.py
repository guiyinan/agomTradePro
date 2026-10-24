"""Opt-in pytest plugin for API and migration xdist isolation contracts."""

from tests.support.xdist_worker_contracts import (
    django_db_modify_db_settings_xdist_suffix,
    pytest_sessionstart,
    pytest_testnodedown,
    record_testsuite_property,
)

__all__ = (
    "django_db_modify_db_settings_xdist_suffix",
    "pytest_sessionstart",
    "pytest_testnodedown",
    "record_testsuite_property",
)
