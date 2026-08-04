from __future__ import annotations

import pytest

from scripts.check_system_settings_field_contract import (
    audit_system_settings_contract,
    discover_system_settings_fields,
    load_system_settings_contract,
    validate_system_settings_contract,
)


def test_system_settings_field_contract_covers_every_declared_field() -> None:
    report = audit_system_settings_contract()

    assert report["field_count"] == 48
    assert report["compatibility_field_count"] == 46
    assert report["group_count"] == 7


def test_system_settings_field_contract_blocks_unregistered_fields() -> None:
    fields = discover_system_settings_fields()
    contract = load_system_settings_contract()
    contract["field_groups"][-1]["fields"].remove("updated_at")

    with pytest.raises(ValueError, match="missing=updated_at"):
        validate_system_settings_contract(fields, contract)


def test_system_settings_field_contract_blocks_unknown_fields() -> None:
    fields = discover_system_settings_fields()
    contract = load_system_settings_contract()
    contract["field_groups"][-1]["fields"].append("future_setting")

    with pytest.raises(ValueError, match="unknown=future_setting"):
        validate_system_settings_contract(fields, contract)


def test_compatibility_group_requires_explicit_replacement() -> None:
    fields = discover_system_settings_fields()
    contract = load_system_settings_contract()
    contract["field_groups"][0]["replacement"] = None

    with pytest.raises(ValueError, match="requires a replacement decision"):
        validate_system_settings_contract(fields, contract)
