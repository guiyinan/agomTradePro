"""Governed financial source-time match contracts fail closed by default."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
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
    FinancialSourceTimeContractApproval,
    FinancialSourceTimeContractRegistry,
    FinancialSourceTimeContractRegistryError,
    financial_source_time_contract_set_sha256,
    load_financial_source_time_contract_registry,
)

_MISSING = object()


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


def _approval(contracts: list[object]) -> dict[str, str]:
    """Return synthetic test-only approval metadata bound to claimed contract digests."""

    claimed_digests = [
        str(contract["contract_sha256"])
        for contract in contracts
        if isinstance(contract, dict) and "contract_sha256" in contract
    ]
    digests = sorted(
        {
            value
            for value in claimed_digests
            if len(value) == 64 and all(character in "0123456789abcdef" for character in value)
        }
    )
    if contracts and not digests:
        digests = ["a" * 64]
    return {
        "approved_at": "2026-09-23T01:02:03Z",
        "approved_by": "test-owner",
        "receipt_sha256": "f" * 64,
        "contract_set_sha256": financial_source_time_contract_set_sha256(digests),
    }


def _write_registry(
    path: Path,
    *,
    status: str,
    contracts: list[object],
    approval: object = _MISSING,
) -> Path:
    """Write one test registry with canonical JSON syntax."""

    resolved_approval = (
        _approval(contracts) if approval is _MISSING and status == "active" else approval
    )
    if resolved_approval is _MISSING:
        resolved_approval = None
    path.write_text(
        json.dumps(
            {
                "schema_version": "financial-source-time-match-contract-registry.v2",
                "status": status,
                "contracts": contracts,
                "approval": resolved_approval,
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
    assert registry.approval is None
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
    assert registry.approval is not None
    assert registry.approval.approved_by == "test-owner"
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


def test_active_registry_requires_owner_approval_bound_to_exact_contract_set(
    tmp_path: Path,
) -> None:
    """An active string and contracts alone cannot authorize matching."""

    payload = _contract_payload()
    without_approval = _write_registry(
        tmp_path / "missing-approval.json",
        status="active",
        contracts=[payload],
        approval=None,
    )
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="approval is required"):
        load_financial_source_time_contract_registry(without_approval)

    approval = _approval([payload])
    approval["contract_set_sha256"] = "0" * 64
    drifted = _write_registry(
        tmp_path / "drifted-approval.json",
        status="active",
        contracts=[payload],
        approval=approval,
    )
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="contract set"):
        load_financial_source_time_contract_registry(drifted)


def test_pending_registry_rejects_approval_claims(tmp_path: Path) -> None:
    """Pending policy cannot carry approval-looking metadata."""

    path = _write_registry(
        tmp_path / "pending-approval.json",
        status="awaiting_owner_approval",
        contracts=[],
        approval={
            "approved_at": "2026-09-23T01:02:03Z",
            "approved_by": "test-owner",
            "receipt_sha256": "f" * 64,
            "contract_set_sha256": financial_source_time_contract_set_sha256([]),
        },
    )
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="cannot contain approval"):
        load_financial_source_time_contract_registry(path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("approved_at", "2026-09-23", "approved_at"),
        ("approved_at", "2026-09-23T01:02:03+08:00", "approved_at"),
        ("approved_at", "2026-09-23T01:02:03.000001Z", "approved_at"),
        ("approved_by", " padded-owner", "approved_by"),
        ("receipt_sha256", "not-a-digest", "receipt_sha256"),
    ],
)
def test_active_registry_rejects_invalid_approval_fields(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    """Approval metadata must remain exact, bounded and content-addressed."""

    payload = _contract_payload()
    approval = _approval([payload])
    approval[field] = value
    path = _write_registry(
        tmp_path / f"approval-{field}.json",
        status="active",
        contracts=[payload],
        approval=approval,
    )
    with pytest.raises(FinancialSourceTimeContractRegistryError, match=message):
        load_financial_source_time_contract_registry(path)


def test_contract_set_hash_is_order_invariant_and_membership_sensitive() -> None:
    """Approval binds the exact validated contract digest set, independent of JSON order."""

    first = "1" * 64
    second = "2" * 64
    expected = financial_source_time_contract_set_sha256([first, second])
    assert financial_source_time_contract_set_sha256([second, first]) == expected
    assert financial_source_time_contract_set_sha256([first]) != expected
    assert financial_source_time_contract_set_sha256([first, "3" * 64]) != expected
    with pytest.raises(ValueError, match="digest set"):
        financial_source_time_contract_set_sha256([first, first])
    with pytest.raises(ValueError, match="digest set"):
        financial_source_time_contract_set_sha256(cast(list[str], [first, 7]))


def test_direct_registry_construction_cannot_bypass_approval(tmp_path: Path) -> None:
    """The public frozen registry type enforces approval even without JSON loading."""

    path = Path("governance/financial_source_time_match_contracts.json")
    pending = load_financial_source_time_contract_registry(path)
    assert pending.approval is None

    with pytest.raises(FinancialSourceTimeContractRegistryError, match="immutable tuple"):
        FinancialSourceTimeContractRegistry(
            status="awaiting_owner_approval",
            contracts=cast(tuple[FinancialSourceTimeMatchContract, ...], []),
            approval=None,
        )
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="typed contracts"):
        FinancialSourceTimeContractRegistry(status="active", contracts=(), approval=None)
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="must be empty"):
        FinancialSourceTimeContractRegistry(
            status="awaiting_owner_approval",
            contracts=(),
            approval=FinancialSourceTimeContractApproval(
                approved_at=datetime(2026, 9, 23, 1, 2, 3, tzinfo=UTC),
                approved_by="test-owner",
                receipt_sha256="f" * 64,
                contract_set_sha256=financial_source_time_contract_set_sha256([]),
            ),
        )
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="approved_by"):
        FinancialSourceTimeContractApproval(
            approved_at=datetime(2026, 9, 23, 1, 2, 3, tzinfo=UTC),
            approved_by=cast(str, 7),
            receipt_sha256="f" * 64,
            contract_set_sha256=financial_source_time_contract_set_sha256([]),
        )
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="whole-second UTC"):
        FinancialSourceTimeContractApproval(
            approved_at=datetime(2026, 9, 23, 1, 2, 3, 1, tzinfo=UTC),
            approved_by="test-owner",
            receipt_sha256="f" * 64,
            contract_set_sha256=financial_source_time_contract_set_sha256([]),
        )

    first_path = _write_registry(
        tmp_path / "first.json", status="active", contracts=[_contract_payload()]
    )
    first = load_financial_source_time_contract_registry(first_path).contracts[0]
    second_payload = _contract_payload()
    second_payload["endpoint"] = "anns_d_v2"
    second_payload["contract_sha256"] = financial_source_time_contract_sha256(second_payload)
    second_path = _write_registry(
        tmp_path / "second.json", status="active", contracts=[second_payload]
    )
    second = load_financial_source_time_contract_registry(second_path).contracts[0]
    digests = [first.contract_sha256, second.contract_sha256]
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="duplicate contract"):
        FinancialSourceTimeContractRegistry(
            status="active",
            contracts=(first, second),
            approval=FinancialSourceTimeContractApproval(
                approved_at=datetime(2026, 9, 23, 1, 2, 3, tzinfo=UTC),
                approved_by="test-owner",
                receipt_sha256="f" * 64,
                contract_set_sha256=financial_source_time_contract_set_sha256(digests),
            ),
        )


def test_registry_rejects_unknown_or_duplicate_json_keys(tmp_path: Path) -> None:
    """Ambiguous JSON cannot become a governance contract."""

    payload = _contract_payload()
    payload["unexpected"] = True
    path = _write_registry(tmp_path / "unknown.json", status="active", contracts=[payload])
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="contract keys"):
        load_financial_source_time_contract_registry(path)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema_version":"financial-source-time-match-contract-registry.v2",'
        '"status":"active","status":"active","contracts":[],"approval":null}',
        encoding="utf-8",
    )
    with pytest.raises(FinancialSourceTimeContractRegistryError, match="duplicate JSON key"):
        load_financial_source_time_contract_registry(duplicate)


def test_registry_rejects_non_finite_json_constants(tmp_path: Path) -> None:
    """Python-specific NaN syntax cannot enter a governed contract document."""

    path = tmp_path / "nan.json"
    path.write_text(
        '{"schema_version":"financial-source-time-match-contract-registry.v2",'
        '"status":NaN,"contracts":[],"approval":null}',
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
    with pytest.raises(ValueError, match="join fields must be an immutable tuple"):
        replace(
            contract,
            join_fields=cast(tuple[FinancialSourceTimeJoinField, ...], list(contract.join_fields)),
        )
    with pytest.raises(ValueError, match="projection fields must be an immutable tuple"):
        replace(
            contract,
            projection_fields=cast(tuple[str, ...], list(contract.projection_fields)),
        )
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
