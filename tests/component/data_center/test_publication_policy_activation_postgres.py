"""Opt-in PostgreSQL coverage for candidate-bound publication policy activation."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlsplit

import psycopg
import pytest
from django.core.management import CommandError, call_command
from django.db import connection, connections, models, transaction
from django.db.utils import load_backend

from apps.data_center.domain.contracts import PublicationPolicy
from apps.data_center.infrastructure.catalog_models import (
    DataOwnerRegistrationModel,
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.publication_rollback_models import CanonicalPublicationModel
from tests.component.data_center.test_publication_policy_activation import (
    activation_inputs as _legacy_activation_inputs,
)

_POSTGRES_FLAG = "AGOM_EVID06_POSTGRES_TEST"
_POSTGRES_URL = "AGOM_EVID06_POSTGRES_TEST_DATABASE_URL"
_DATABASE_NAME = "evid06_authority_test"
_CATALOG_MODELS: tuple[tuple[str, type[models.Model]], ...] = (
    ("data_center_dataset_contract", DatasetContractModel),
    ("data_center_dataset_provider_binding", DatasetProviderBindingModel),
    ("data_center_data_owner_registration", DataOwnerRegistrationModel),
)
_ACTIVATION_MODELS: tuple[type[models.Model], ...] = (
    DatasetContractModel,
    DatasetProviderBindingModel,
    DataOwnerRegistrationModel,
    DatasetPublicationPolicyModel,
    CanonicalPublicationModel,
)


@dataclass(frozen=True, slots=True)
class _PostgresTarget:
    """Connection details for the explicitly opted-in disposable database."""

    credentials: dict[str, object] = field(repr=False)

    def connect(self):
        """Open an independent PostgreSQL probe connection."""

        return psycopg.connect(**self.credentials)


def _rowset(model: type[models.Model]) -> list[dict[str, object]]:
    """Return all persisted fields in deterministic primary-key order."""

    raw_rows = list(model._default_manager.order_by("pk").values())
    return cast(list[dict[str, object]], raw_rows)


def _rowset_fingerprint(model: type[models.Model]) -> tuple[int, str]:
    """Hash the same complete rowset used by the activation preflight."""

    encoded = json.dumps(
        _rowset(model),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")
    return model._default_manager.count(), hashlib.sha256(encoded).hexdigest()


def _catalog_baseline() -> dict[str, dict[str, object]]:
    """Return complete fingerprints for the three unrelated catalog tables."""

    return {
        table_name: {
            "row_count": row_count,
            "all_persisted_fields_sha256": digest,
            "encoding": "catalog-rowset-v1-including-identities-and-timestamps",
        }
        for table_name, model in _CATALOG_MODELS
        for row_count, digest in [_rowset_fingerprint(model)]
    }


def _require_postgres_target() -> tuple[dict[str, object], str]:
    """Validate the opt-in URL before any table creation is attempted."""

    if os.environ.get(_POSTGRES_FLAG, "").strip() != "1":
        pytest.skip(f"PostgreSQL activation coverage is opt-in; set {_POSTGRES_FLAG}=1")
    raw_url = os.environ.get(_POSTGRES_URL, "").strip()
    if not raw_url:
        pytest.fail(f"{_POSTGRES_URL} is required when {_POSTGRES_FLAG}=1")
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        pytest.fail(f"{_POSTGRES_URL} must use a PostgreSQL URL")
    hostname = (parsed.hostname or "").lower()
    if hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail(f"{_POSTGRES_URL} must target a loopback PostgreSQL host")
    configured_name = unquote(parsed.path.removeprefix("/"))
    if configured_name != _DATABASE_NAME:
        pytest.fail(f"{_POSTGRES_URL} must target {_DATABASE_NAME}")
    credentials: dict[str, object] = {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": _DATABASE_NAME,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "connect_timeout": 30,
        # Private transport startup is bounded independently of SQL/lock
        # deadlines. These loopback-only options never affect production.
        "sslmode": "disable",
        "gssencmode": "disable",
    }
    return credentials, hostname


@pytest.fixture(scope="module")
def _activation_postgres_schema(
    django_db_blocker: object,
) -> Iterator[_PostgresTarget]:
    """Create and remove only the five tables in an empty loopback test DB."""

    credentials, hostname = _require_postgres_target()
    original = connections["default"]
    database_settings = deepcopy(original.settings_dict)
    database_settings.update(
        ENGINE="django.db.backends.postgresql",
        NAME=_DATABASE_NAME,
        USER=credentials["user"],
        PASSWORD=credentials["password"],
        HOST=hostname,
        PORT=str(credentials["port"]),
        CONN_MAX_AGE=0,
        OPTIONS={"connect_timeout": 30, "sslmode": "disable", "gssencmode": "disable"},
    )
    wrapper = load_backend(database_settings["ENGINE"]).DatabaseWrapper(
        database_settings,
        alias="default",
    )
    created: list[type[models.Model]] = []
    expected_names = {model._meta.db_table for model in _ACTIVATION_MODELS}

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        connections["default"] = wrapper
        try:
            if wrapper.vendor != "postgresql":
                pytest.fail("activation PostgreSQL fixture resolved a non-PostgreSQL backend")
            with wrapper.cursor() as cursor:
                cursor.execute("SELECT current_database()")
                row = cursor.fetchone()
            if row is None or str(row[0]) != _DATABASE_NAME:
                pytest.fail("activation PostgreSQL fixture database identity mismatch")
            if wrapper.introspection.table_names():
                pytest.fail(
                    "activation PostgreSQL fixture requires the empty evid06_authority_test database"
                )
            with wrapper.schema_editor() as editor:
                for model in _ACTIVATION_MODELS:
                    editor.create_model(model)
                    created.append(model)
            assert set(wrapper.introspection.table_names()) == expected_names
            yield _PostgresTarget(credentials)
        finally:
            if created:
                if set(wrapper.introspection.table_names()) != {
                    model._meta.db_table for model in created
                }:
                    raise AssertionError(
                        "activation PostgreSQL cleanup found tables outside this fixture"
                    )
                with wrapper.schema_editor() as editor:
                    for model in reversed(created):
                        editor.delete_model(model)
                assert wrapper.introspection.table_names() == []
            wrapper.close()
            connections["default"] = original


def _truncate_activation_rows() -> None:
    """Clear only rows from the five tables owned by this test harness."""

    names = ", ".join(
        connections["default"].ops.quote_name(model._meta.db_table) for model in _ACTIVATION_MODELS
    )
    with connections["default"].cursor() as cursor:
        cursor.execute(f"TRUNCATE TABLE {names} RESTART IDENTITY")
    for model in _ACTIVATION_MODELS:
        assert model._default_manager.count() == 0


@pytest.fixture(autouse=True)
def _independent_activation_cleanup(
    _activation_postgres_schema: _PostgresTarget,
    django_db_blocker: object,
) -> Iterator[None]:
    """Keep every activation case isolated and prove cleanup reaches zero rows."""

    del _activation_postgres_schema
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        _truncate_activation_rows()
    yield
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        _truncate_activation_rows()


@pytest.fixture
def activation_inputs(
    _activation_postgres_schema: _PostgresTarget,
    tmp_path: Path,
) -> dict[str, object]:
    """Reuse the ten-policy candidate fixture and complete its five-model catalog."""

    del _activation_postgres_schema
    inputs = cast(dict[str, object], _legacy_activation_inputs.__wrapped__(tmp_path))
    candidate_payload = cast(
        dict[str, object],
        json.loads(Path(str(inputs["candidate"])).read_text(encoding="utf-8")),
    )
    policies = cast(list[dict[str, object]], candidate_payload["policies"])
    for row in policies:
        dataset_key = str(row["dataset_key"])
        DatasetProviderBindingModel.objects.create(
            dataset_key=dataset_key,
            contract_version="1.0",
            schema_version="1.0",
            provider="activation-test",
            capability="publication",
            priority=1,
            freshness_seconds=86_400,
            validator_key="activation-test",
            enabled=True,
        )
        DataOwnerRegistrationModel.objects.create(
            dataset_key=dataset_key,
            data_platform_owner="data-platform",
            business_owner="business-owner",
            acceptance_owner="acceptance-owner",
            active=True,
        )

    expected_path = Path(str(inputs["expected"]))
    expected = cast(
        dict[str, object],
        json.loads(expected_path.read_text(encoding="utf-8")),
    )
    expected["unrelated_catalog_baseline"] = _catalog_baseline()
    expected_path.write_text(
        json.dumps(expected, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return inputs


def _run_command(inputs: dict[str, object], *, execute: bool = False) -> dict[str, object]:
    """Run the public management command and decode its JSON result."""

    from io import StringIO

    output = StringIO()
    options: dict[str, object] = {
        "expected_state": str(inputs["expected"]),
        "policies": str(inputs["candidate"]),
        "stdout": output,
    }
    if execute:
        options["execute"] = True
    call_command("activate_publication_policies", **options)
    return cast(dict[str, object], json.loads(output.getvalue()))


def _candidate_identity_map(inputs: dict[str, object]) -> dict[str, str]:
    """Parse candidate policy identities through the command's typed boundary."""

    from apps.data_center.management.commands.activate_publication_policies import (
        _candidate_policies,
        _expected_state,
    )

    expected = _expected_state(Path(str(inputs["expected"])))
    policies, _manifest_hash = _candidate_policies(Path(str(inputs["candidate"])), expected)
    return {policy.dataset.value: policy.identity for policy in policies}


def _policy_rows_by_dataset() -> dict[str, list[dict[str, object]]]:
    """Snapshot complete policy rows grouped by immutable dataset identity."""

    result: dict[str, list[dict[str, object]]] = {}
    for row in _rowset(DatasetPublicationPolicyModel):
        dataset_key = str(row["dataset_key"])
        result.setdefault(dataset_key, []).append(row)
    return result


def _published_rows() -> list[dict[str, object]]:
    """Snapshot every canonical publication row in primary-key order."""

    return _rowset(CanonicalPublicationModel)


def _show_pg_timeouts() -> tuple[str, str]:
    """Read the caller connection's PostgreSQL timeout settings."""

    with connection.cursor() as cursor:
        cursor.execute("SHOW lock_timeout")
        lock_row = cursor.fetchone()
        cursor.execute("SHOW statement_timeout")
        statement_row = cursor.fetchone()
    assert lock_row is not None and statement_row is not None
    return str(lock_row[0]).lower(), str(statement_row[0]).lower()


def _set_pg_timeouts(lock_timeout: str, statement_timeout: str) -> None:
    """Set caller-session timeout values without interpolating SQL text."""

    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('lock_timeout', %s, false)", [lock_timeout])
        cursor.execute("SELECT set_config('statement_timeout', %s, false)", [statement_timeout])


@contextmanager
def _stricter_caller_timeouts() -> Iterator[tuple[str, str]]:
    """Install 2s/7s caller bounds and restore the prior session settings."""

    previous = _show_pg_timeouts()
    _set_pg_timeouts("2s", "7s")
    try:
        assert _show_pg_timeouts() == ("2s", "7s")
        yield previous
    finally:
        _set_pg_timeouts(*previous)


def _assert_probe_write_blocked(
    probe: psycopg.Connection,
    statement: str,
    params: Sequence[object],
) -> None:
    """Require PostgreSQL's lock timeout SQLSTATE while the parent holds locks."""

    probe.execute("SELECT set_config('lock_timeout', %s, true)", ["150ms"])
    with pytest.raises(psycopg.errors.LockNotAvailable) as locked:
        probe.execute(statement, params)
    assert locked.value.sqlstate == "55P03"
    probe.rollback()


def _probe_write(
    probe: psycopg.Connection,
    statement: str,
    params: Sequence[object],
) -> None:
    """Execute one probe write with a short transaction-local lock timeout."""

    probe.execute("SELECT set_config('lock_timeout', %s, true)", ["150ms"])
    probe.execute(statement, params)


def _contract_insert() -> tuple[str, tuple[object, ...]]:
    """Build a disposable contract insert for the lock probe."""

    contract_version = "probe-lock-v1"
    statement = """
        INSERT INTO data_center_dataset_contract (
            dataset_key, contract_version, schema_version, owner, frequency,
            decision_critical, fields, freshness_seconds, comparable_group,
            active, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, TRUE, %s::jsonb, %s, %s, TRUE,
                  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """
    params: tuple[object, ...] = (
        "probe.lock.dataset",
        contract_version,
        "1.0",
        "probe",
        "daily",
        json.dumps([{"name": "observed_at", "value_type": "datetime"}]),
        3_600,
        "activation-lock-probe",
    )
    return statement, params


def _policy_update() -> tuple[str, tuple[object, ...]]:
    """Build a no-op policy update that still requires a row/table lock."""

    return (
        "UPDATE data_center_dataset_publication_policy "
        "SET retention_days = retention_days "
        "WHERE dataset_key = %s AND active = TRUE",
        ("asset.master",),
    )


def test_preview_is_read_only_on_postgresql(activation_inputs: dict[str, object]) -> None:
    """Preview validates the exact candidate without changing any of five tables."""

    before_catalog = _catalog_baseline()
    before_policies = _policy_rows_by_dataset()
    before_publications = _published_rows()

    with _stricter_caller_timeouts() as previous_timeouts:
        with transaction.atomic():
            result = _run_command(activation_inputs)
            assert _show_pg_timeouts() == ("2s", "7s")
        assert _show_pg_timeouts() == ("2s", "7s")
    assert _show_pg_timeouts() == previous_timeouts

    assert result["mode"] == "preview"
    assert result["activated"] is False
    assert tuple(result["target_dataset_keys"]) == activation_inputs["targets"]
    assert _catalog_baseline() == before_catalog
    assert _policy_rows_by_dataset() == before_policies
    assert _published_rows() == before_publications


def test_parent_transaction_holds_catalog_and_policy_locks_until_commit(
    _activation_postgres_schema: _PostgresTarget,
    activation_inputs: dict[str, object],
) -> None:
    """Nested preview locks block metadata inserts and policy updates until outer commit."""

    contract_statement, contract_params = _contract_insert()
    policy_statement, policy_params = _policy_update()

    with transaction.atomic():
        _run_command(activation_inputs)
        with _activation_postgres_schema.connect() as probe:
            _assert_probe_write_blocked(probe, contract_statement, contract_params)
            _assert_probe_write_blocked(probe, policy_statement, policy_params)

    with _activation_postgres_schema.connect() as probe:
        _probe_write(probe, contract_statement, contract_params)
        probe.rollback()
        _probe_write(probe, policy_statement, policy_params)
        probe.rollback()


def test_fourth_policy_save_failure_rolls_back_policy_catalog_and_publication(
    activation_inputs: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late target failure leaves all policy rows and unrelated state unchanged."""

    before_policies = _policy_rows_by_dataset()
    before_catalog = _catalog_baseline()
    before_publications = _published_rows()
    calls: list[str] = []
    original_save = PublicationPolicyRepository.save

    def fail_on_fourth(
        repository: PublicationPolicyRepository,
        policy: PublicationPolicy,
    ) -> PublicationPolicy:
        """Allow three target writes, then abort the enclosing activation transaction."""

        calls.append(policy.dataset.value)
        if len(calls) == 4:
            raise ValueError("simulated fourth target policy failure")
        return original_save(repository, policy)

    monkeypatch.setattr(PublicationPolicyRepository, "save", fail_on_fourth)
    with _stricter_caller_timeouts() as previous_timeouts:
        with transaction.atomic():
            with pytest.raises(CommandError, match="fourth target"):
                _run_command(activation_inputs, execute=True)
            assert _show_pg_timeouts() == ("2s", "7s")
        assert _show_pg_timeouts() == ("2s", "7s")
    assert _show_pg_timeouts() == previous_timeouts

    assert calls == sorted(cast(Sequence[str], activation_inputs["targets"]))
    assert _policy_rows_by_dataset() == before_policies
    assert _catalog_baseline() == before_catalog
    assert _published_rows() == before_publications


def test_execute_activates_exact_four_p2_heads_and_preserves_six_legacy_heads(
    activation_inputs: dict[str, object],
) -> None:
    """Execution changes exactly four candidate heads and preserves all other state."""

    before_policies = _policy_rows_by_dataset()
    before_catalog = _catalog_baseline()
    before_publications = _published_rows()
    expected_identities = _candidate_identity_map(activation_inputs)
    targets = set(cast(Sequence[str], activation_inputs["targets"]))
    result = _run_command(activation_inputs, execute=True)

    active_rows = list(
        DatasetPublicationPolicyModel.objects.filter(active=True).values(
            "dataset_key", "contract_version", "schema_version", "policy_version"
        )
    )
    active_identities = {
        policy.dataset.value: policy.identity
        for policy in (
            row.to_domain()
            for row in DatasetPublicationPolicyModel.objects.filter(active=True).order_by(
                "dataset_key"
            )
        )
    }
    result_identities = {
        str(row["dataset_key"]): str(row["identity"])
        for row in cast(list[dict[str, object]], result["active_policy_identities"])
    }

    assert result["mode"] == "execute"
    assert result["activated"] is True
    assert set(active_identities) == set(expected_identities)
    assert result_identities == expected_identities
    assert {key for key in active_identities if key in targets} == targets
    assert all(active_identities[key].startswith("p2:2:") for key in targets)
    assert len(active_rows) == 10
    assert DatasetPublicationPolicyModel.objects.count() == 14
    for dataset_key in sorted(set(expected_identities) - targets):
        assert _policy_rows_by_dataset()[dataset_key] == before_policies[dataset_key]
    assert _catalog_baseline() == before_catalog
    assert _published_rows() == before_publications
