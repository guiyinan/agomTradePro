"""Pure tests for the dormant server-issued Data Center sync identity port."""

import hashlib
import json
from uuid import uuid4

import pytest

from apps.data_center.application.sync_identity import (
    IssueSyncExecutionIdentityCommand,
    IssueSyncExecutionIdentityUseCase,
    SyncExecutionIdentity,
    sync_execution_identity_hash,
)


def _identity(**changes: object) -> SyncExecutionIdentity:
    values: dict[str, object] = {
        "run_id": str(uuid4()),
        "ingested_run_id": str(uuid4()),
        "batch_id": str(uuid4()),
        "dataset_key": "macro.CN_CPI",
        "provider_name": "provider-a",
    }
    values.update(changes)
    payload = {
        "batch_id": values["batch_id"],
        "dataset_key": values["dataset_key"],
        "ingested_run_id": values["ingested_run_id"],
        "provider_name": values["provider_name"],
        "run_id": values["run_id"],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    identity_hash = hashlib.sha256(
        b"agomtradepro:data-center:sync-execution-identity:v1\0" + encoded
    ).hexdigest()
    return SyncExecutionIdentity(
        **{**values, "identity_hash": identity_hash}  # type: ignore[arg-type]
    )


def test_identity_hash_is_stable_and_exposes_exact_raw_audit_pair() -> None:
    identity = _identity()
    assert identity.identity_hash == sync_execution_identity_hash(identity)
    assert identity.raw_audit_correlation == (identity.run_id, identity.ingested_run_id)


@pytest.mark.parametrize(
    "field",
    ["run_id", "ingested_run_id", "batch_id"],
)
def test_identity_rejects_noncanonical_uuid(field: str) -> None:
    with pytest.raises(ValueError, match="canonical UUID"):
        _identity(**{field: "run-1"})


def test_identity_rejects_hash_or_context_tampering() -> None:
    identity = _identity()
    with pytest.raises(ValueError, match="identity_hash"):
        SyncExecutionIdentity(
            run_id=identity.run_id,
            ingested_run_id=identity.ingested_run_id,
            batch_id=identity.batch_id,
            dataset_key="macro.CPI",
            provider_name=identity.provider_name,
            identity_hash=identity.identity_hash,
        )


def test_command_contains_no_identity_or_clock_fields() -> None:
    command = IssueSyncExecutionIdentityCommand(
        dataset_key="macro.CN_CPI",
        provider_name="provider-a",
    )
    assert command.dataset_key == "macro.CN_CPI"
    assert not hasattr(command, "run_id")
    assert not hasattr(command, "ingested_run_id")
    assert not hasattr(command, "recorded_at")


def test_use_case_accepts_only_owner_issued_matching_identity() -> None:
    identity = _identity()

    class Issuer:
        def issue(self, *, dataset_key: str, provider_name: str) -> SyncExecutionIdentity:
            assert (dataset_key, provider_name) == ("macro.CN_CPI", "provider-a")
            return identity

    result = IssueSyncExecutionIdentityUseCase(Issuer()).execute(
        IssueSyncExecutionIdentityCommand(dataset_key="macro.CN_CPI", provider_name="provider-a")
    )
    assert result == identity


def test_use_case_rejects_issuer_selector_substitution() -> None:
    identity = _identity(dataset_key="macro.CPI")

    class Issuer:
        def issue(self, *, dataset_key: str, provider_name: str) -> SyncExecutionIdentity:
            del dataset_key, provider_name
            return identity

    with pytest.raises(ValueError, match="dataset_key"):
        IssueSyncExecutionIdentityUseCase(Issuer()).execute(
            IssueSyncExecutionIdentityCommand(
                dataset_key="macro.CN_CPI", provider_name="provider-a"
            )
        )
