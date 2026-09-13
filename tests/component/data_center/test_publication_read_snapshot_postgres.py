"""Opt-in real PostgreSQL consistency, locking and rollback publication tests."""

import os
from collections.abc import Iterator, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from django.db import connections, transaction
from django.db.utils import load_backend
from django.utils import timezone

from apps.data_center.application.publication_utils import (
    member_reference,
    publication_hash,
    publication_member_from_reference,
)
from apps.data_center.application.query_services import query_published_valuation_facts
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.models import (
    AssetAliasModel,
    AssetMasterModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from apps.data_center.infrastructure.publication_read_snapshot import (
    PublicationReadSnapshotError,
    consistent_publication_read,
)
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository
from tests.component.data_center.test_current_publication_evidence_gate import _published_snapshot


@dataclass(frozen=True)
class _PGProbeFactory:
    credentials: dict[str, object] = field(repr=False)

    def connect(self):
        return psycopg.connect(**self.credentials)


@pytest.fixture(scope="module")
def _actual_publication_pg_schema(django_db_blocker) -> Iterator[_PGProbeFactory]:
    """Use only the explicitly opted-in empty dedicated loopback test database."""

    if os.environ.get("AGOM_EVID06_POSTGRES_TEST") != "1":
        pytest.skip("Enable the disposable loopback PostgreSQL test explicitly")
    parsed = urlsplit(os.environ.get("AGOM_EVID06_POSTGRES_TEST_DATABASE_URL", ""))
    assert parsed.scheme in {"postgres", "postgresql"}
    assert parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    assert unquote(parsed.path.removeprefix("/")) == "evid06_authority_test"
    credentials = {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": "evid06_authority_test",
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "connect_timeout": 10,
    }
    original = connections["default"]
    settings = deepcopy(original.settings_dict)
    settings.update(
        ENGINE="django.db.backends.postgresql",
        NAME=credentials["dbname"],
        USER=credentials["user"],
        PASSWORD=credentials["password"],
        HOST=credentials["host"],
        PORT=str(credentials["port"]),
        CONN_MAX_AGE=0,
        OPTIONS={"connect_timeout": 10},
    )
    wrapper = load_backend(settings["ENGINE"]).DatabaseWrapper(settings, alias="default")
    models = (
        DatasetContractModel,
        DatasetPublicationPolicyModel,
        AssetMasterModel,
        AssetAliasModel,
        ValuationFactModel,
        CanonicalPublicationModel,
        CoverageSnapshotModel,
        PublicationMemberModel,
    )
    created = []
    with django_db_blocker.unblock():
        connections["default"] = wrapper
        try:
            assert wrapper.vendor == "postgresql"
            assert wrapper.introspection.table_names() == [], "Refuse any preexisting test tables"
            with wrapper.schema_editor() as editor:
                for model in models:
                    editor.create_model(model)
                    created.append(model)
            yield _PGProbeFactory(credentials)
        finally:
            if created:
                with wrapper.schema_editor() as editor:
                    for model in reversed(created):
                        editor.delete_model(model)
                assert wrapper.introspection.table_names() == []
            wrapper.close()
            connections["default"] = original


@pytest.fixture
def actual_publication_pg(_actual_publication_pg_schema) -> Iterator[_PGProbeFactory]:
    """Reset only the eight tables created in the opted-in empty test database."""

    try:
        yield _actual_publication_pg_schema
    finally:
        wrapper = connections["default"]
        assert wrapper.vendor == "postgresql"
        assert wrapper.settings_dict["NAME"] == "evid06_authority_test"
        models = (
            DatasetContractModel,
            DatasetPublicationPolicyModel,
            AssetMasterModel,
            AssetAliasModel,
            ValuationFactModel,
            CanonicalPublicationModel,
            CoverageSnapshotModel,
            PublicationMemberModel,
        )
        expected = {model._meta.db_table for model in models}
        assert set(wrapper.introspection.table_names()) == expected
        names = ", ".join(wrapper.ops.quote_name(name) for name in sorted(expected))
        with wrapper.cursor() as cursor:
            cursor.execute(f"TRUNCATE TABLE {names}")


def _probe_update(probe, fact_pk: str) -> None:
    probe.execute("SELECT set_config('lock_timeout', %s, true)", ["150ms"])
    probe.execute("UPDATE data_center_valuation_fact SET pe_ttm=99 WHERE id=%s", [fact_pk])


def _probe_write(probe, statement: str, params: Sequence[object]) -> None:
    probe.execute("SELECT set_config('lock_timeout', %s, true)", ["150ms"])
    probe.execute(statement, params)


def _assert_probe_write_blocked(
    probe,
    statement: str,
    params: Sequence[object],
) -> None:
    with pytest.raises(psycopg.errors.LockNotAvailable) as locked:
        _probe_write(probe, statement, params)
    assert locked.value.sqlstate == "55P03"
    probe.rollback()


def test_outer_read_only_snapshot_keeps_gate_and_rows_consistent_after_concurrent_commit(
    actual_publication_pg,
) -> None:
    _policy, _publication, member = _published_snapshot()
    with consistent_publication_read("equity.valuation.fact"):
        with connections["default"].cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            assert cursor.fetchone() == ("repeatable read",)
            cursor.execute("SHOW transaction_read_only")
            assert cursor.fetchone() == ("on",)
        first = query_published_valuation_facts("000001.SZ")
        with actual_publication_pg.connect() as probe:
            probe.execute(
                "UPDATE data_center_valuation_fact SET pe_ttm=99 WHERE id=%s", [member.fact_pk]
            )
        second = query_published_valuation_facts("000001.SZ")
        assert first["must_not_use_for_decision"] is False
        assert second["rows"] == first["rows"]
        assert second["rows"][0]["pe_ttm"] == 12.5
    assert (
        query_published_valuation_facts("000001.SZ")["blocked_reason"]
        == "publication_member_fact_changed"
    )


def test_nested_read_committed_locks_remain_until_outer_unit_of_work_ends(
    actual_publication_pg,
) -> None:
    _policy, _publication, member = _published_snapshot()
    with actual_publication_pg.connect() as probe:
        with transaction.atomic():
            result = query_published_valuation_facts("000001.SZ")
            assert result["must_not_use_for_decision"] is False
            with pytest.raises(psycopg.errors.LockNotAvailable) as locked:
                _probe_update(probe, member.fact_pk)
            assert locked.value.sqlstate == "55P03"
            probe.rollback()
            assert query_published_valuation_facts("000001.SZ")["rows"][0]["pe_ttm"] == 12.5
        _probe_update(probe, member.fact_pk)
    assert query_published_valuation_facts("000001.SZ")["rows"] == []


def test_nested_read_committed_locks_dataset_contract_insert_until_outer_unit_of_work_ends(
    actual_publication_pg,
) -> None:
    _published_snapshot()
    dataset_key = "equity.valuation.fact"
    contract_version = f"probe-{uuid4().hex}"
    statement = """
        INSERT INTO data_center_dataset_contract (
            dataset_key,
            contract_version,
            schema_version,
            owner,
            frequency,
            decision_critical,
            fields,
            freshness_seconds,
            comparable_group,
            active,
            created_at,
            updated_at
        ) VALUES (%s, %s, %s, %s, %s, TRUE, %s::jsonb, %s, %s, TRUE,
                  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """
    params = (
        dataset_key,
        contract_version,
        "1.0",
        "probe",
        "daily",
        '[{"name":"observed_at","value_type":"datetime"}]',
        3600,
        "",
    )
    with actual_publication_pg.connect() as probe:
        with transaction.atomic():
            result = query_published_valuation_facts("000001.SZ")
            assert result["must_not_use_for_decision"] is False
            assert result["rows"][0]["pe_ttm"] == 12.5
            _assert_probe_write_blocked(probe, statement, params)
        _probe_write(probe, statement, params)
        assert probe.execute(
            "SELECT contract_version FROM data_center_dataset_contract "
            "WHERE dataset_key=%s AND contract_version=%s",
            [dataset_key, contract_version],
        ).fetchone() == (contract_version,)


def test_nested_read_committed_locks_asset_master_insert_until_outer_unit_of_work_ends(
    actual_publication_pg,
) -> None:
    _published_snapshot()
    asset_code = f"999{uuid4().hex[:8]}.SH"
    statement = """
        INSERT INTO data_center_asset_master (
            code,
            name,
            short_name,
            asset_type,
            exchange,
            is_active,
            list_date,
            delist_date,
            sector,
            industry,
            currency,
            total_shares,
            extra,
            created_at,
            updated_at
        ) VALUES (%s, 'Probe Asset', 'Probe', 'stock', 'SSE', TRUE,
                  NULL, NULL, '', '', 'CNY', NULL, '{}'::jsonb,
                  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """
    with actual_publication_pg.connect() as probe:
        with transaction.atomic():
            result = query_published_valuation_facts("000001.SZ")
            assert result["must_not_use_for_decision"] is False
            assert result["rows"][0]["pe_ttm"] == 12.5
            _assert_probe_write_blocked(probe, statement, [asset_code])
        _probe_write(probe, statement, [asset_code])
        assert probe.execute(
            "SELECT code FROM data_center_asset_master WHERE code=%s",
            [asset_code],
        ).fetchone() == (asset_code,)


def test_nested_read_committed_locks_asset_alias_insert_until_outer_unit_of_work_ends(
    actual_publication_pg,
) -> None:
    _published_snapshot()
    asset = AssetMasterModel.objects.create(
        code=f"600{uuid4().hex[:8]}.SH",
        name="Probe Alias Asset",
        asset_type="stock",
        exchange="SSE",
    )
    alias_code = f"probe-{uuid4().hex[:27]}"
    statement = """
        INSERT INTO data_center_asset_alias (
            asset_id,
            provider_name,
            alias_code,
            created_at
        ) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
    """
    params = (asset.pk, "probe", alias_code)
    with actual_publication_pg.connect() as probe:
        with transaction.atomic():
            result = query_published_valuation_facts("000001.SZ")
            assert result["must_not_use_for_decision"] is False
            assert result["rows"][0]["pe_ttm"] == 12.5
            _assert_probe_write_blocked(probe, statement, params)
        _probe_write(probe, statement, params)
        assert probe.execute(
            "SELECT asset_id, provider_name, alias_code FROM data_center_asset_alias "
            "WHERE provider_name=%s AND alias_code=%s",
            ["probe", alias_code],
        ).fetchone() == (asset.pk, "probe", alias_code)


def test_nested_repeatable_read_reuses_snapshot_without_share_table_locks(
    actual_publication_pg,
) -> None:
    _policy, _publication, member = _published_snapshot()
    with transaction.atomic():
        with connections["default"].cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        before = query_published_valuation_facts("000001.SZ")
        with actual_publication_pg.connect() as probe:
            _probe_update(probe, member.fact_pk)
        assert query_published_valuation_facts("000001.SZ")["rows"] == before["rows"]
        with connections["default"].cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() AND mode='ShareLock' AND locktype='relation'"
            )
            assert cursor.fetchone() == (0,)
    assert query_published_valuation_facts("000001.SZ")["rows"] == []


def test_nested_read_only_read_committed_fails_closed_without_poisoning_parent(
    actual_publication_pg,
) -> None:
    _published_snapshot()
    with transaction.atomic():
        with connections["default"].cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
        with pytest.raises(PublicationReadSnapshotError, match="read-only READ COMMITTED"):
            query_published_valuation_facts("000001.SZ")
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)


def test_versioned_publish_locks_facts_and_commits_complete_members_atomically(
    actual_publication_pg,
) -> None:
    policy, previous, member = _published_snapshot()
    # A successor must contain a genuinely changed fact; identical scope/hash
    # is an idempotent publication, protected by the existing unique constraint.
    ValuationFactModel.objects.filter(pk=member.fact_pk).update(pe_ttm=13)
    reference = ValuationFactRepository().list_current_publication_candidates(("000001.SZ",))[0]
    identifier = str(uuid4())
    published_at = timezone.now()
    successor = replace(
        previous,
        publication_id=identifier,
        publication_hash=publication_hash([reference], policy_identity=policy.identity),
        published_at=published_at,
        coverage=replace(
            previous.coverage,
            publication_id=identifier,
            coverage_id=str(uuid4()),
            generated_at=published_at,
        ),
    )
    frozen = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=identifier,
        dataset_key=policy.dataset.value,
    )
    with actual_publication_pg.connect() as probe:
        with transaction.atomic():
            written = CanonicalPublicationRepository().publish_with_members(successor, (frozen,))
            assert written.policy_version == policy.identity
            assert CanonicalPublicationRepository().list_members(identifier) == [frozen]
            with pytest.raises(psycopg.errors.LockNotAvailable):
                _probe_update(probe, member.fact_pk)
            probe.rollback()
            rows = probe.execute(
                "SELECT publication_id FROM data_center_canonical_publication WHERE state='published'"
            ).fetchall()
            assert rows == [(UUID(previous.publication_id),)]
        rows = probe.execute(
            "SELECT publication_id FROM data_center_canonical_publication WHERE state='published'"
        ).fetchall()
        assert rows == [(UUID(identifier),)]


def test_forged_frozen_provenance_with_real_row_digest_never_replaces_current(
    actual_publication_pg,
) -> None:
    policy, previous, member = _published_snapshot()
    identifier = str(uuid4())
    forged = replace(
        member,
        publication_id=identifier,
        member_id=str(uuid4()),
        source_record_id="invented-body-proof",
    )
    publication = replace(
        previous,
        publication_id=identifier,
        publication_hash=publication_hash(
            [member_reference(forged)], policy_identity=policy.identity
        ),
        coverage=replace(previous.coverage, publication_id=identifier, coverage_id=str(uuid4())),
    )
    with pytest.raises(ValueError, match="canonical facts"):
        CanonicalPublicationRepository().publish_with_members(publication, (forged,))
    assert CanonicalPublicationRepository().get_current(policy.dataset.value, "current") == previous
    assert CanonicalPublicationModel.objects.count() == 1
    assert PublicationMemberModel.objects.count() == 1
