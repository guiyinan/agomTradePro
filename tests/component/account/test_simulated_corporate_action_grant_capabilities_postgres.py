"""Real migrated V1/V2 evidence storage, without live consent or financial authority."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction

from apps.account.application.simulated_corporate_action_write_grant import (
    RequireSimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantConflict,
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    SimulatedCorporateActionWriteGrant,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_models import (
    SimulatedCorporateActionWriteGrantModel as GrantRow,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_repository import (
    DjangoSimulatedCorporateActionWriteGrantRepository as Repository,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_repository import (
    _grant_values,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_seal import (
    SimulatedCorporateActionWriteGrantSeal,
)
from apps.account.simulated_corporate_action_current_grant_composition import (
    _read_exact_current_grant,
)
from tests.component.account.test_simulated_corporate_action_write_grant_repository import (
    _Clock,
    _grant,
    _revocation,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Native migrated PostgreSQL contract; executed by the required PostgreSQL workflow.",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def require_real_capability_migration(django_db_setup: None, django_db_blocker: object) -> None:
    """Reject syncdb or an old physical schema before testing grant restoration."""
    del django_db_setup
    with django_db_blocker.unblock():
        assert connection.vendor == "postgresql"
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM django_migrations WHERE app='account' AND name='0071_simulated_corporate_action_grant_capabilities'"
            )
            assert cursor.fetchone() == (1,)


def _v2(
    original: SimulatedCorporateActionWriteGrant | None = None,
) -> SimulatedCorporateActionWriteGrant:
    base = original or _grant()
    return replace(
        base,
        grant_version="explicit-v2",
        schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        permission=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
        capabilities=(Capability.TAX_ASSESS, Capability.TAX_WITHHOLD),
        terms_version="synthetic-owner-terms-v2",
        terms_sha256="d" * 64,
        recorded_at=base.recorded_at + timedelta(minutes=1),
        supersedes_content_hash=base.content_hash if original is not None else None,
        content_hash="",
    )


def test_native_v1_roundtrip_keeps_cash_only_scope_and_null_v2_columns() -> None:
    grant = _grant()
    repository = Repository(clock=_Clock(grant.recorded_at))
    assert repository.append_grant(grant, expected_predecessor_content_hash=None) == grant
    row = GrantRow._default_manager.get(content_hash=grant.content_hash)
    assert (row.capabilities, row.terms_version, row.terms_sha256) == (None, None, None)
    assert row.canonical_payload == grant.to_payload()
    assert grant.effective_capabilities == (Capability.CASH_STAGE_WRITE,)
    assert not grant.supports_capability(Capability.TAX_ASSESS)


def test_native_v1_to_v2_selects_one_head_without_resurrecting_v1() -> None:
    old = _grant()
    Repository(clock=_Clock(old.recorded_at)).append_grant(
        old, expected_predecessor_content_hash=None
    )
    upgraded = _v2(old)
    repository = Repository(clock=_Clock(upgraded.recorded_at))
    assert (
        repository.append_grant(upgraded, expected_predecessor_content_hash=old.content_hash)
        == upgraded
    )
    assert upgraded.identity_hash == old.identity_hash
    assert repository.get_current_for_scope(
        "simulated", old.binding.account_id, as_of=upgraded.recorded_at
    ) == (upgraded,)
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        RequireSimulatedCorporateActionWriteGrant(repository).execute(
            old.selector, as_of=upgraded.recorded_at
        )
    current = repository.get_current_grant(selector=upgraded.selector, as_of=upgraded.recorded_at)
    assert current is not None and current.grant == upgraded
    assert not current.grant.supports_capability(Capability.CASH_STAGE_WRITE)
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        _read_exact_current_grant(
            selector=upgraded.selector,
            repository=repository,
            seal=SimulatedCorporateActionWriteGrantSeal(),
            as_of=upgraded.recorded_at,
        )
    assert GrantRow._default_manager.count() == 2


def test_native_v2_retry_narrowing_and_conflict_preserve_one_chain() -> None:
    grant = _v2()
    repository = Repository(clock=_Clock(grant.recorded_at))
    repository.append_grant(grant, expected_predecessor_content_hash=None)
    assert repository.append_grant(grant, expected_predecessor_content_hash=None) == grant
    narrowed = replace(
        grant,
        grant_version="narrowed-v2",
        capabilities=(Capability.TAX_ASSESS,),
        recorded_at=grant.recorded_at + timedelta(minutes=1),
        supersedes_content_hash=grant.content_hash,
        content_hash="",
    )
    repository = Repository(clock=_Clock(narrowed.recorded_at))
    assert (
        repository.append_grant(narrowed, expected_predecessor_content_hash=grant.content_hash)
        == narrowed
    )
    collision = replace(narrowed, capabilities=grant.capabilities, content_hash="")
    with pytest.raises(SimulatedCorporateActionWriteGrantConflict):
        repository.append_grant(collision, expected_predecessor_content_hash=grant.content_hash)
    assert repository.get_current_for_scope(
        "simulated", grant.binding.account_id, as_of=narrowed.recorded_at
    ) == (narrowed,)
    assert GrantRow._default_manager.count() == 2


def test_native_v2_whole_revocation_retains_expired_exact_withdrawal_metadata() -> None:
    grant = _v2()
    Repository(clock=_Clock(grant.recorded_at)).append_grant(
        grant, expected_predecessor_content_hash=None
    )
    at = grant.valid_until + timedelta(minutes=1)
    repository = Repository(clock=_Clock(at))
    historical = repository.get_exact_record(selector=grant.selector, as_of=at)
    assert historical is not None and historical.grant == grant
    revocation = _revocation(grant, recorded_at=at)
    assert repository.append_revocation(revocation) == revocation
    assert repository.append_revocation(revocation) == revocation
    assert repository.get_current_for_scope("simulated", grant.binding.account_id, as_of=at) == ()
    historical = repository.get_exact_record(selector=grant.selector, as_of=at)
    assert historical is not None and historical.revocation == revocation
    assert historical.grant.capabilities == (Capability.TAX_ASSESS, Capability.TAX_WITHHOLD)


@pytest.mark.parametrize("missing", ["terms_version", "terms_sha256"])
def test_native_database_check_rejects_null_v2_terms(missing: str) -> None:
    grant = _v2()
    values = _grant_values(grant, None)
    values[missing] = None
    fields = {field.attname: field for field in GrantRow._meta.concrete_fields}
    keys = tuple(values)
    columns = ",".join(connection.ops.quote_name(fields[key].column) for key in keys)
    arguments = [fields[key].get_db_prep_save(values[key], connection) for key in keys]
    table = connection.ops.quote_name(GrantRow._meta.db_table)
    placeholders = ",".join(["%s"] * len(keys))
    with pytest.raises(IntegrityError, match="acct_scawg_fixed_ck"):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", arguments
                )
    assert GrantRow._default_manager.count() == 0


def test_native_v2_cannot_downgrade_to_a_new_v1_head() -> None:
    grant = _v2()
    Repository(clock=_Clock(grant.recorded_at)).append_grant(
        grant, expected_predecessor_content_hash=None
    )
    downgraded = replace(
        _grant(version="downgrade-v1", at=grant.recorded_at + timedelta(minutes=1)),
        supersedes_content_hash=grant.content_hash,
        content_hash="",
    )
    repository = Repository(clock=_Clock(downgraded.recorded_at))
    with pytest.raises(SimulatedCorporateActionWriteGrantConflict):
        repository.append_grant(downgraded, expected_predecessor_content_hash=grant.content_hash)
    assert repository.get_current_for_scope(
        "simulated", grant.binding.account_id, as_of=downgraded.recorded_at
    ) == (grant,)
    assert GrantRow._default_manager.count() == 1


@pytest.mark.django_db(transaction=True, available_apps=["apps.account"])
def test_native_concurrent_v2_root_replay_retains_one_record() -> None:
    grant = _v2()
    barrier = Barrier(2)

    def worker() -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=15)
            stored = Repository(clock=_Clock(grant.recorded_at)).append_grant(
                grant, expected_predecessor_content_hash=None
            )
            return stored.content_hash
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: worker(), range(2))) == [grant.content_hash] * 2
    assert GrantRow._default_manager.count() == 1
