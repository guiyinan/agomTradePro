"""Governed financial source-time match contracts fail closed by default."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from apps.data_center.domain.financial_source_time_contract import (
    FinancialSourceTimeJoinField,
    FinancialSourceTimeJoinSemantic,
    FinancialSourceTimeMatchContract,
    financial_source_time_contract_sha256,
)
from apps.data_center.infrastructure.financial_source_time_contract_registry import (
    FinancialSourceTimeContractRegistryError,
    load_financial_source_time_contract_registry,
)


def _contract_payload() -> dict[str, object]:
    """Return one synthetic contract with every required exact join dimension."""

    payload: dict[str, object] = {
        "provider_name": "synthetic-provider",
        "financial_dataset_key": "equity.financial.fact",
        "source_time_dataset_key": "equity.financial.source-time",
        "endpoint": "synthetic_financial_notice",
        "contract_id": "synthetic-provider.financial-notice.exact",
        "contract_version": "v1",
        "parser_version": "synthetic-financial-notice.v1",
        "source_timezone": "Asia/Shanghai",
        "join_fields": [
            {
                "semantic": FinancialSourceTimeJoinSemantic.ASSET_CODE.value,
                "financial_field": "ts_code",
                "source_field": "asset_code",
            },
            {
                "semantic": FinancialSourceTimeJoinSemantic.PERIOD_END.value,
                "financial_field": "end_date",
                "source_field": "period_end",
            },
            {
                "semantic": FinancialSourceTimeJoinSemantic.ANNOUNCEMENT_DATE.value,
                "financial_field": "ann_date",
                "source_field": "announcement_date",
            },
        ],
        "source_row_id_field": "notice_id",
        "announced_at_field": "announced_at",
        "available_at_field": "available_at",
        "projection_fields": [
            "notice_id",
            "asset_code",
            "period_end",
            "announcement_date",
            "announced_at",
            "available_at",
        ],
    }
    payload["contract_sha256"] = financial_source_time_contract_sha256(payload)
    return payload


def _write_registry(path: Path, *, status: str, contracts: list[object]) -> Path:
    """Write one test registry with canonical JSON syntax."""

    path.write_text(
        json.dumps(
            {
                "schema_version": "financial-source-time-match-contract-registry.v1",
                "status": status,
                "contracts": contracts,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_repository_registry_is_awaiting_owner_approval_and_denies_lookup() -> None:
    """The committed registry cannot authorize a source-time match."""

    registry = load_financial_source_time_contract_registry(
        Path("governance/financial_source_time_match_contracts.json")
    )

    assert registry.status == "awaiting_owner_approval"
    assert registry.contracts == ()
    assert (
        registry.get(
            provider_name="tushare",
            contract_id="tushare.financial-announcement.exact",
            contract_version="v1",
            contract_sha256="a" * 64,
        )
        is None
    )


def test_active_registry_resolves_only_the_exact_contract_identity(tmp_path: Path) -> None:
    """An approved synthetic contract is addressable only by all four identity fields."""

    payload = _contract_payload()
    registry = load_financial_source_time_contract_registry(
        _write_registry(tmp_path / "registry.json", status="active", contracts=[payload])
    )

    contract = registry.get(
        provider_name="synthetic-provider",
        contract_id="synthetic-provider.financial-notice.exact",
        contract_version="v1",
        contract_sha256=str(payload["contract_sha256"]),
    )
    assert contract is not None
    assert contract.to_dict() == payload
    assert (
        registry.get(
            provider_name="synthetic-provider",
            contract_id="synthetic-provider.financial-notice.exact",
            contract_version="v2",
            contract_sha256=str(payload["contract_sha256"]),
        )
        is None
    )


@pytest.mark.parametrize(
    ("status", "contracts"),
    [
        ("active", []),
        ("awaiting_owner_approval", [_contract_payload()]),
        ("completed", []),
    ],
)
def test_registry_status_cannot_promote_or_hide_contracts(
    tmp_path: Path,
    status: str,
    contracts: list[object],
) -> None:
    """Only a non-empty active registry may expose contracts."""

    path = _write_registry(tmp_path / "registry.json", status=status, contracts=contracts)
    with pytest.raises(FinancialSourceTimeContractRegistryError):
        load_financial_source_time_contract_registry(path)


def test_registry_rejects_unknown_or_duplicate_json_keys(tmp_path: Path) -> None:
    """Ambiguous JSON cannot become a governance contract."""

    payload = _contract_payload()
    payload["unexpected"] = True
    path = _write_registry(tmp_path / "unknown.json", status="active", contracts=[payload])
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="contract keys"):
        load_financial_source_time_contract_registry(path)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema_version":"financial-source-time-match-contract-registry.v1",'
        '"status":"active","status":"active","contracts":[]}',
        encoding="utf-8",
    )
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="duplicate JSON key"):
        load_financial_source_time_contract_registry(duplicate)


def test_registry_rejects_non_finite_json_constants(tmp_path: Path) -> None:
    """Python-specific NaN syntax cannot enter a governed contract document."""

    path = tmp_path / "nan.json"
    path.write_text(
        '{"schema_version":"financial-source-time-match-contract-registry.v1",'
        '"status":NaN,"contracts":[]}',
        encoding="utf-8",
    )

    with pytest.raises(FinancialSourceTimeContractRegistryError, match="non-finite"):
        load_financial_source_time_contract_registry(path)


def test_registry_rejects_digest_or_identity_substitution(tmp_path: Path) -> None:
    """Changed contract content and duplicate identities both fail closed."""

    payload = _contract_payload()
    payload["endpoint"] = "substituted_financial_notice"
    path = _write_registry(tmp_path / "digest.json", status="active", contracts=[payload])
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="contract_sha256"):
        load_financial_source_time_contract_registry(path)

    first = _contract_payload()
    second = dict(first)
    path = _write_registry(
        tmp_path / "identity.json",
        status="active",
        contracts=[first, second],
    )
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="duplicate contract"):
        load_financial_source_time_contract_registry(path)


def test_contract_requires_asset_period_and_announcement_date_join(tmp_path: Path) -> None:
    """A date-only asset join cannot be registered as exact financial lineage."""

    payload = _contract_payload()
    payload["join_fields"] = list(payload["join_fields"])[::2]
    payload["contract_sha256"] = financial_source_time_contract_sha256(payload)
    path = _write_registry(tmp_path / "weak.json", status="active", contracts=[payload])

    with pytest.raises(FinancialSourceTimeContractRegistryError, match="join semantics"):
        load_financial_source_time_contract_registry(path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("financial_dataset_key", "equity.financial.other", "financial dataset"),
        ("source_time_dataset_key", "equity.financial.notice", "dataset is invalid"),
        ("source_timezone", "Mars/Olympus", "timezone is unknown"),
        ("announced_at_field", "response_completed_at", "synthetic time field"),
        ("available_at_field", "fetched_at", "synthetic time field"),
        ("provider_name", " padded", "provider_name is invalid"),
        ("provider_name", "provider\nname", "control characters"),
    ],
)
def test_contract_rejects_invalid_semantics_before_digest_acceptance(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    """Content hashing cannot make invalid provider semantics acceptable."""

    payload = _contract_payload()
    payload[field] = value
    if field in {"announced_at_field", "available_at_field"}:
        cast(list[str], payload["projection_fields"]).append(value)
    payload["contract_sha256"] = financial_source_time_contract_sha256(payload)
    path = _write_registry(tmp_path / f"{field}.json", status="active", contracts=[payload])

    with pytest.raises(FinancialSourceTimeContractRegistryError, match=message):
        load_financial_source_time_contract_registry(path)


def test_contract_rejects_duplicate_fields_and_invalid_digest_shape(tmp_path: Path) -> None:
    """Join/projection ambiguity and non-SHA identities remain invalid."""

    duplicate_join = _contract_payload()
    join_fields = cast(list[dict[str, object]], duplicate_join["join_fields"])
    join_fields[1]["financial_field"] = join_fields[0]["financial_field"]
    duplicate_join["contract_sha256"] = financial_source_time_contract_sha256(duplicate_join)
    path = _write_registry(
        tmp_path / "duplicate-join.json", status="active", contracts=[duplicate_join]
    )
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="join fields"):
        load_financial_source_time_contract_registry(path)

    duplicate_projection = _contract_payload()
    projection = cast(list[str], duplicate_projection["projection_fields"])
    projection.append(projection[0])
    duplicate_projection["contract_sha256"] = financial_source_time_contract_sha256(
        duplicate_projection
    )
    path = _write_registry(
        tmp_path / "duplicate-projection.json",
        status="active",
        contracts=[duplicate_projection],
    )
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="projection fields"):
        load_financial_source_time_contract_registry(path)

    invalid_hash = _contract_payload()
    invalid_hash["contract_sha256"] = "not-a-digest"
    path = _write_registry(tmp_path / "hash.json", status="active", contracts=[invalid_hash])
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="contract_sha256"):
        load_financial_source_time_contract_registry(path)


def test_domain_types_reject_untyped_join_and_projection_values(tmp_path: Path) -> None:
    """Direct constructors cannot bypass typed join or projection checks."""

    with pytest.raises(ValueError, match="join semantic must be typed"):
        FinancialSourceTimeJoinField(
            semantic=cast(FinancialSourceTimeJoinSemantic, "asset_code"),
            financial_field="ts_code",
            source_field="asset_code",
        )

    payload = _contract_payload()
    registry = load_financial_source_time_contract_registry(
        _write_registry(tmp_path / "valid.json", status="active", contracts=[payload])
    )
    contract = cast(FinancialSourceTimeMatchContract, registry.contracts[0])
    with pytest.raises(ValueError, match="join fields must be typed"):
        replace(contract, join_fields=())
    with pytest.raises(ValueError, match="projection fields must be text"):
        replace(contract, projection_fields=cast(tuple[str, ...], (1,)))
    with pytest.raises(ValueError, match="projection fields are incomplete"):
        replace(contract, projection_fields=("asset_code",))
    with pytest.raises(ValueError, match="evidence fields must be distinct"):
        replace(contract, available_at_field=contract.announced_at_field)
    with pytest.raises(ValueError, match="evidence fields must be distinct"):
        replace(contract, announced_at_field="announcement_date")
