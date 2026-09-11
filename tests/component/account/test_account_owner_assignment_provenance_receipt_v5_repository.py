"""Component coverage for the PostgreSQL ReceiptV5 evidence ledger."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from urllib.parse import unquote, urlsplit

import pytest
from django.core.exceptions import ValidationError

# isort 6 separates aliased django.db imports while Ruff keeps these names grouped.
# isort: off
from django.db import DatabaseError, connections, transaction
from django.db import connection as default_connection

# isort: on

from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.application.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3Recorder,
    PersistedAllocatedPhysicalAccountRowObservationV3,
)
from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    PersistedCanonicalAccountOwnershipReobservationV1,
)
from apps.account.application.physical_account_row_observation_v2 import (
    PersistedPhysicalAccountRowObservationV2,
    PhysicalAccountRowObservationV2Recorder,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v5 import (
    AccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_record_codec import (
    encode_account_owner_assignment_provenance_receipt_v5_record,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV5Conflict,
    DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption,
    DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository,
    DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable,
)
from apps.account.infrastructure.account_owner_assignment_v5_models import (
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    AccountOwnerAssignmentSubjectV5Model,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_models import (
    AllocatedPhysicalAccountRowObservationV3Model,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_repository import (
    DjangoAllocatedPhysicalAccountRowObservationV3Repository,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
    CanonicalAccountCreationConsumptionClaimModel,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)
from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationAllocationModel,
    CanonicalAccountCreationBindingModel,
)
from apps.account.infrastructure.canonical_account_creation_repository import (
    DjangoCanonicalAccountCreationRepository,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_models import (
    CanonicalAccountOwnershipReobservationV1Model,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_repository import (
    DjangoCanonicalAccountOwnershipReobservationV1Repository,
)
from apps.account.infrastructure.physical_account_row_observation_v2_models import (
    PhysicalAccountRowObservationV2Model,
)
from apps.account.infrastructure.physical_account_row_observation_v2_repository import (
    DjangoPhysicalAccountRowObservationV2Repository,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v5 import (
    _receipt,
    _successor,
)
from tests.unit.account.test_canonical_account_creation_consumption import _claim

PG_ALIAS = "receipt_v5_repository_test"


class _DjangoDbBlocker(Protocol):
    """Narrow protocol for the opt-in PostgreSQL schema fixture."""

    def unblock(self) -> AbstractContextManager[None]:
        """Temporarily allow isolated-schema DDL."""
        ...


class _Clock:
    """Use one deterministic aware clock for every parent repository."""

    def now(self) -> datetime:
        """Return the component test cutoff."""

        return _at(30)


class _FixedClock:
    """Return one exact parent persistence time."""

    def __init__(self, value: datetime) -> None:
        self._value = value

    def now(self) -> datetime:
        """Return the configured aware timestamp."""

        return self._value


def _at(day: int, hour: int = 12) -> datetime:
    """Return one fixed timezone-aware test instant."""

    return datetime(2026, 8, day, hour, tzinfo=UTC)


_MODELS = (
    CanonicalAccountCreationAllocationModel,
    AllocatedPhysicalAccountRowObservationV3Model,
    CanonicalAccountCreationConsumptionClaimModel,
    CanonicalAccountCreationBindingModel,
    CanonicalAccountCreationBindingV2Model,
    PhysicalAccountRowObservationV2Model,
    CanonicalAccountOwnershipReobservationV1Model,
    SingleOwnerAuthorityPolicyV1Model,
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    AccountOwnerAssignmentSubjectV5Model,
)


@pytest.fixture(name="receipt_v5_alias")
def receipt_v5_alias(
    django_db_blocker: _DjangoDbBlocker,
) -> Iterator[str]:
    """Create and tear down only the real parent and ReceiptV5 ledger tables."""

    if os.environ.get("AGOM_EVID06_POSTGRES_TEST") != "1":
        pytest.skip("set AGOM_EVID06_POSTGRES_TEST=1 for the dedicated PostgreSQL test")
    database_url = os.environ.get("AGOM_EVID06_POSTGRES_TEST_DATABASE_URL", "").strip()
    parsed = urlsplit(database_url)
    database_name = unquote(parsed.path.removeprefix("/"))
    if parsed.scheme not in {"postgres", "postgresql"} or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise RuntimeError("ReceiptV5 component tests require a loopback PostgreSQL URL")
    if database_name != "evid06_authority_test" or not parsed.username:
        raise RuntimeError("ReceiptV5 tests require the dedicated EVID-06 test database")
    if PG_ALIAS in connections.databases:
        raise RuntimeError(f"refusing preexisting database alias: {PG_ALIAS}")
    try:
        port = parsed.port
    except ValueError as error:
        raise RuntimeError("ReceiptV5 PostgreSQL URL has an invalid port") from error
    database_settings = cast(dict[str, object], deepcopy(default_connection.settings_dict))
    database_settings.update(
        {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": database_name,
            "USER": unquote(parsed.username),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname,
            "PORT": str(port or 5432),
            "CONN_MAX_AGE": 0,
            "OPTIONS": {},
        }
    )
    connections.databases[PG_ALIAS] = database_settings  # type: ignore[assignment]
    database_connection = connections[PG_ALIAS]
    created: list[type] = []
    try:
        with django_db_blocker.unblock():
            if database_connection.introspection.table_names():
                raise RuntimeError("refusing a non-empty ReceiptV5 test database")
            with database_connection.schema_editor() as editor:
                for model in _MODELS:
                    editor.create_model(model)
                    created.append(model)
            try:
                yield PG_ALIAS
            finally:
                with database_connection.cursor() as cursor:
                    for model in reversed(created):
                        table = database_connection.ops.quote_name(model._meta.db_table)
                        cursor.execute(f"DELETE FROM {table}")  # noqa: S608
                assert all(model._base_manager.using(PG_ALIAS).count() == 0 for model in created)
                with database_connection.schema_editor() as editor:
                    for model in reversed(created):
                        editor.delete_model(model)
    finally:
        database_connection.close()
        connections.databases.pop(PG_ALIAS, None)


def _seed_graph(
    alias: str,
    receipt: AccountOwnerAssignmentProvenanceReceiptV5,
) -> None:
    """Persist the exact allocation/root, BindingV2, PhysicalV2, policy, and re-observation."""

    clock = _Clock()
    binding = receipt.binding
    claim = _claim(consumer_generation="v2", consumer=binding)
    creation = DjangoCanonicalAccountCreationRepository(using=alias, clock=clock)
    with creation.atomic():
        creation.append_allocation(binding.allocation, recorded_at=binding.allocation.allocated_at)
    root_record = PersistedAllocatedPhysicalAccountRowObservationV3(
        observation=binding.creation_root,
        recorded_by=AllocatedPhysicalAccountRowObservationV3Recorder(
            service_id="receipt-v5-component"
        ),
    )
    root_repository = DjangoAllocatedPhysicalAccountRowObservationV3Repository(
        using=alias, clock=clock
    )
    with root_repository.atomic():
        root_repository.append(
            root_record,
            expected_predecessor_hash=None,
            recorded_at=binding.creation_root.recorded_at,
        )
    binding_repository = DjangoCanonicalAccountCreationConsumptionRepository(
        using=alias, clock=clock
    )
    with binding_repository.atomic():
        binding_repository.append_with_consumption_claim(
            binding,
            claim,
            expected_allocation_content_hash=binding.allocation.content_hash,
            expected_account_claim_hash=binding.account_claim_hash,
            expected_underlying_claim_hash=binding.underlying_claim_hash,
            expected_creation_root_content_hash=binding.creation_root.content_hash,
            expected_consumption_claim_content_hash=claim.content_hash,
            recorded_at=binding.recorded_at,
        )
    physical = receipt.reobservation.current_physical
    physical_record = PersistedPhysicalAccountRowObservationV2(
        observation=physical,
        recorded_by=PhysicalAccountRowObservationV2Recorder(
            recorder_id="receipt-v5-component",
            service_name="account",
        ),
    )
    physical_repository = DjangoPhysicalAccountRowObservationV2Repository(using=alias, clock=clock)
    with physical_repository.atomic():
        physical_repository.append(
            physical_record,
            expected_predecessor_hash=None,
            recorded_at=physical.recorded_at,
        )
    reobservation_repository = DjangoCanonicalAccountOwnershipReobservationV1Repository(
        using=alias, clock=clock
    )
    with reobservation_repository.atomic():
        reobservation_repository.append(
            PersistedCanonicalAccountOwnershipReobservationV1(receipt.reobservation),
            recorded_at=receipt.reobservation.recorded_at,
        )
    policy_repository = DjangoSingleOwnerAuthorityPolicyV1Repository(
        using=alias,
        clock=_FixedClock(receipt.policy.observed_at),
    )
    with policy_repository.atomic():
        policy_repository.append(policy=receipt.policy, expected_previous_content_hash=None)


def _repository(alias: str) -> DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository:
    """Build the ReceiptV5 repository with the deterministic component clock."""

    return DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository(using=alias, clock=_Clock())


def _table(alias: str) -> str:
    """Quote the ReceiptV5 table for deliberate tamper tests."""

    return connections[alias].ops.quote_name(
        AccountOwnerAssignmentProvenanceReceiptV5Model._meta.db_table
    )


def _clear_rows(alias: str) -> None:
    """Reset the already-created isolated schema between contract scenarios."""

    with connections[alias].cursor() as cursor:
        for model in reversed(_MODELS):
            table = connections[alias].ops.quote_name(model._meta.db_table)
            cursor.execute(f"DELETE FROM {table}")  # noqa: S608


def _exercise_root_replay_exact_and_expired_current_head(
    receipt_v5_alias: str,
) -> None:
    """Append/replay the root and retain expired exact/head history."""

    receipt = _receipt()
    _seed_graph(receipt_v5_alias, receipt)
    repository = _repository(receipt_v5_alias)
    expected = PersistedAccountOwnerAssignmentProvenanceReceiptV5(receipt)
    with repository.atomic():
        assert (
            repository.append(
                expected, expected_predecessor_hash=None, recorded_at=receipt.recorded_at
            )
            == expected
        )
        assert (
            repository.append(
                expected, expected_predecessor_hash=None, recorded_at=receipt.recorded_at
            )
            == expected
        )
    row = AccountOwnerAssignmentProvenanceReceiptV5Model._base_manager.using(receipt_v5_alias).get()
    assert row.policy_id > 0 and row.binding_id > 0 and row.reobservation_id > 0
    assert row.predecessor_id is None
    assert row.persisted_at == receipt.recorded_at
    assert row.canonical_payload == encode_account_owner_assignment_provenance_receipt_v5_record(
        expected
    )
    assert row.record_seal == expected.record_seal
    assert row.ledger_seal == expected.ledger_seal
    assert (
        repository.get_winner(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            as_of=_at(30),
        )
        == expected
    )
    assert (
        repository.get_exact_by_hash(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            expected_content_hash=receipt.content_hash,
            as_of=_at(30),
        )
        == expected
    )
    assert repository.get_current_head(receipt_id=receipt.receipt_id, as_of=_at(30)) == expected


def _exercise_successor_and_current_head_never_fall_back_after_expiry(
    receipt_v5_alias: str,
) -> None:
    """Append a successor and expose it as the final expired logical head."""

    first = _receipt()
    _seed_graph(receipt_v5_alias, first)
    repository = _repository(receipt_v5_alias)
    first_record = PersistedAccountOwnerAssignmentProvenanceReceiptV5(first)
    with repository.atomic():
        repository.append(
            first_record, expected_predecessor_hash=None, recorded_at=first.recorded_at
        )
    successor = _successor(first)
    successor_record = PersistedAccountOwnerAssignmentProvenanceReceiptV5(successor)
    with repository.atomic():
        assert (
            repository.append(
                successor_record,
                expected_predecessor_hash=first.content_hash,
                recorded_at=successor.recorded_at,
            )
            == successor_record
        )
    assert (
        repository.get_current_head(receipt_id=first.receipt_id, as_of=_at(30)) == successor_record
    )
    assert (
        repository.get_exact_by_hash(
            receipt_id=first.receipt_id,
            receipt_version=first.receipt_version,
            expected_content_hash=first.content_hash,
            as_of=_at(30),
        )
        == first_record
    )


def _exercise_future_and_wrong_predecessor_are_rejected(receipt_v5_alias: str) -> None:
    """Reject an invalid predecessor before any append can occur."""

    receipt = _receipt()
    _seed_graph(receipt_v5_alias, receipt)
    repository = _repository(receipt_v5_alias)
    with (
        repository.atomic(),
        pytest.raises(DjangoAccountOwnerAssignmentProvenanceReceiptV5Conflict, match="predecessor"),
    ):
        repository.append(
            PersistedAccountOwnerAssignmentProvenanceReceiptV5(receipt),
            expected_predecessor_hash="0" * 64,
            recorded_at=receipt.recorded_at,
        )
    with pytest.raises(DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable, match="future"):
        repository.get_exact_by_hash(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            expected_content_hash=receipt.content_hash,
            as_of=_at(31),
        )


def _exercise_payload_model_and_seal_tamper_fail_closed(
    receipt_v5_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full-world restore rejects every tampered ReceiptV5 storage field."""

    receipt = _receipt()
    _seed_graph(receipt_v5_alias, receipt)
    repository = _repository(receipt_v5_alias)
    record = PersistedAccountOwnerAssignmentProvenanceReceiptV5(receipt)
    competing = "receipt_v5_policy_competing"
    connections.databases[competing] = deepcopy(connections.databases[receipt_v5_alias])
    original_lock_policy = DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository._lock_policy

    def assert_policy_advisory_lock(
        instance: DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository,
        target: AccountOwnerAssignmentProvenanceReceiptV5,
    ) -> SingleOwnerAuthorityPolicyV1Model:
        locked_row = original_lock_policy(instance, target)
        with pytest.raises(DatabaseError):
            with transaction.atomic(using=competing):
                with connections[competing].cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '250ms'")
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        [target.policy.policy_id],
                    )
        return locked_row

    monkeypatch.setattr(
        DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository,
        "_lock_policy",
        assert_policy_advisory_lock,
    )
    try:
        with repository.atomic():
            repository.append(
                record,
                expected_predecessor_hash=None,
                recorded_at=receipt.recorded_at,
            )
    finally:
        connections[competing].close()
        connections.databases.pop(competing, None)
        monkeypatch.setattr(
            DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository,
            "_lock_policy",
            original_lock_policy,
        )
    row = AccountOwnerAssignmentProvenanceReceiptV5Model._base_manager.using(receipt_v5_alias).get()
    with pytest.raises(ValidationError):
        row.save(using=receipt_v5_alias, update_fields=["account_id"])
    with pytest.raises(ValidationError):
        AccountOwnerAssignmentProvenanceReceiptV5Model._base_manager.using(receipt_v5_alias).filter(
            pk=row.pk
        ).update(account_id="tampered")
    with pytest.raises(ValidationError):
        row.delete(using=receipt_v5_alias)
    with pytest.raises(
        DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable, match="PostgreSQL"
    ):
        DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository(using="default").get_winner(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            as_of=_at(30),
        )
    with pytest.raises(DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable, match="alias"):
        DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository(
            using="missing-receipt-v5-alias"
        ).get_winner(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            as_of=_at(30),
        )

    late_policy_time = receipt.recorded_at + timedelta(minutes=1)
    late_policy = replace(
        receipt.policy,
        policy_version="receipt-v5-late-policy",
        authorization_content_hash="b" * 64,
        observed_at=receipt.recorded_at,
        identity_hash="",
        content_hash="",
    )
    late_policy_repository = DjangoSingleOwnerAuthorityPolicyV1Repository(
        using=receipt_v5_alias,
        clock=_FixedClock(late_policy_time),
    )
    with late_policy_repository.atomic():
        late_policy_repository.append(
            policy=late_policy,
            expected_previous_content_hash=receipt.policy.content_hash,
        )
    assert (
        late_policy_repository.get_exact_current(
            policy_id=receipt.policy.policy_id,
            policy_version=receipt.policy.policy_version,
            expected_content_hash=receipt.policy.content_hash,
            as_of=receipt.recorded_at,
        )
        == receipt.policy
    )
    assert (
        late_policy_repository.get_exact_current(
            policy_id=late_policy.policy_id,
            policy_version=late_policy.policy_version,
            expected_content_hash=late_policy.content_hash,
            as_of=late_policy_time,
        )
        == late_policy
    )
    assert (
        repository.get_winner(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            as_of=receipt.recorded_at,
        )
        == record
    )

    other_policy = replace(
        receipt.policy,
        policy_id="receipt-v5-other-policy",
        identity_hash="",
        content_hash="",
    )
    policy_repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=receipt_v5_alias)
    with policy_repository.atomic():
        policy_repository.append(policy=other_policy, expected_previous_content_hash=None)
    original_policy_pk = (
        SingleOwnerAuthorityPolicyV1Model._base_manager.using(receipt_v5_alias)
        .get(content_hash=receipt.policy.content_hash)
        .pk
    )
    other_policy_pk = (
        SingleOwnerAuthorityPolicyV1Model._base_manager.using(receipt_v5_alias)
        .get(content_hash=other_policy.content_hash)
        .pk
    )
    with connections[receipt_v5_alias].cursor() as cursor:
        cursor.execute(  # noqa: S608
            f"UPDATE {_table(receipt_v5_alias)} SET policy_id = %s",
            [other_policy_pk],
        )
    with pytest.raises(
        DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption, match="parent anchor"
    ):
        repository.get_winner(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            as_of=_at(30),
        )
    with connections[receipt_v5_alias].cursor() as cursor:
        cursor.execute(  # noqa: S608
            f"UPDATE {_table(receipt_v5_alias)} SET policy_id = %s",
            [original_policy_pk],
        )
    canonical = encode_account_owner_assignment_provenance_receipt_v5_record(record)
    cases: tuple[tuple[str, object, object], ...] = (
        (
            "canonical_payload",
            {"receipt": {"tampered": True}, "record_seal": "0" * 64, "ledger_seal": "0" * 64},
            canonical,
        ),
        ("account_id", "tampered-account", receipt.account_id),
        ("record_seal", "0" * 64, record.record_seal),
        ("ledger_seal", "0" * 64, record.ledger_seal),
    )
    for field, tampered, original in cases:
        with connections[receipt_v5_alias].cursor() as cursor:
            if field == "canonical_payload":
                cursor.execute(  # noqa: S608
                    f"UPDATE {_table(receipt_v5_alias)} SET canonical_payload = %s::jsonb",
                    [json.dumps(tampered, sort_keys=True)],
                )
            else:
                cursor.execute(  # noqa: S608
                    f"UPDATE {_table(receipt_v5_alias)} SET {field} = %s",
                    [tampered],
                )
        with pytest.raises(DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption):
            repository.get_winner(
                receipt_id=receipt.receipt_id,
                receipt_version=receipt.receipt_version,
                as_of=_at(30),
            )
        with connections[receipt_v5_alias].cursor() as cursor:
            if field == "canonical_payload":
                cursor.execute(  # noqa: S608
                    f"UPDATE {_table(receipt_v5_alias)} SET canonical_payload = %s::jsonb",
                    [json.dumps(original, sort_keys=True)],
                )
            else:
                cursor.execute(  # noqa: S608
                    f"UPDATE {_table(receipt_v5_alias)} SET {field} = %s",
                    [original],
                )


@pytest.mark.django_db(transaction=True, databases="__all__")
def test_receipt_v5_repository_contract(
    receipt_v5_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise every ReceiptV5 persistence scenario in one isolated schema."""

    _exercise_root_replay_exact_and_expired_current_head(receipt_v5_alias)
    _clear_rows(receipt_v5_alias)
    _exercise_successor_and_current_head_never_fall_back_after_expiry(receipt_v5_alias)
    _clear_rows(receipt_v5_alias)
    _exercise_future_and_wrong_predecessor_are_rejected(receipt_v5_alias)
    _clear_rows(receipt_v5_alias)
    _exercise_payload_model_and_seal_tamper_fail_closed(receipt_v5_alias, monkeypatch)
    _clear_rows(receipt_v5_alias)
    from tests.component.account.test_account_owner_assignment_subject_v5_repository import (
        _exercise_subject_v5_repository_contract,
    )

    _exercise_subject_v5_repository_contract(receipt_v5_alias)


def test_helper_fixture_retains_exact_v5_domain_type() -> None:
    """Keep component construction tied to the V5 Domain value."""

    assert type(_receipt()) is AccountOwnerAssignmentProvenanceReceiptV5
