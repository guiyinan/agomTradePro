"""Explicit configuration and alias isolation at the public creation boundary."""

from dataclasses import replace

import pytest
from django.db import connections

from apps.account.application.creation_evidence_settings import (
    ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION,
    CanonicalAccountCreationEvidenceSettings,
)
from apps.simulated_trading.creation_composition import (
    build_simulated_account_creation_stages,
)


def _settings() -> CanonicalAccountCreationEvidenceSettings:
    return CanonicalAccountCreationEvidenceSettings(
        schema_version=ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION,
        ttl_seconds=300,
        allocation_recorder_service_id="test-allocation",
        physical_v2_recorder_service_id="test-physical",
        allocated_v3_recorder_service_id="test-allocated",
        binding_recorder_service_id="test-binding",
    )


@pytest.mark.parametrize("alias", [None, True, "", " ", "default ", "two aliases"])
def test_invalid_alias_is_rejected_before_any_database_access(alias):
    with pytest.raises(ValueError, match="database alias"):
        build_simulated_account_creation_stages(using=alias, settings=_settings())


@pytest.mark.parametrize("settings", [None, {}, replace(_settings(), ttl_seconds=10**12)])
def test_invalid_or_unusable_settings_cannot_construct_creation_stages(settings):
    with pytest.raises((TypeError, ValueError)):
        build_simulated_account_creation_stages(using="unregistered-local-test", settings=settings)


def test_build_does_not_open_database_or_read_runtime_configuration():
    alias = "unregistered-local-test"
    assert alias not in connections.databases
    stages = build_simulated_account_creation_stages(using=alias, settings=_settings())
    assert stages.database_alias == alias
    assert alias not in connections.databases
