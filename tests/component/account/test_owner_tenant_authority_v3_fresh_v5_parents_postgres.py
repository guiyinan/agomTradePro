"""Opt-in PostgreSQL facade proof that creates its V5 parents before approval."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter, process_time
from typing import Protocol, cast
from urllib.parse import unquote, urlsplit

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.db import connections, models, transaction
from django.db.backends.base.base import BaseDatabaseWrapper

from apps.account.account_owner_assignment_evidence_v5_composition import (
    build_account_owner_assignment_evidence_v5_facade,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
    ApproveAccountOwnerAssignmentEvidenceV5Command,
    GetCurrentAccountOwnerAssignmentEvidenceV5Command,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    IssueAccountOwnerAssignmentProvenanceReceiptV5,
    IssueAccountOwnerAssignmentProvenanceReceiptV5Command,
)
from apps.account.application.account_owner_assignment_subject_v5 import (
    RegisterAccountOwnerAssignmentSubjectV5,
    RegisterAccountOwnerAssignmentSubjectV5Command,
)
from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
    GetExactOwnerTenantAuthorityV3Command,
    IssueOwnerTenantAuthorityV3Command,
    RevokeOwnerTenantAuthorityV3Command,
)
from apps.account.application.single_owner_actor_authority import SingleOwnerPolicyBinding
from apps.account.infrastructure.account_actor_authority_raw_source_models_v3 import (
    AccountAuthenticationContextSourceV3AnchorModel,
    AccountAuthenticationContextSourceV3Model,
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
    AccountUserAuthoritySourceV3AnchorModel,
    AccountUserAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_repository import (
    DjangoAccountOwnerAssignmentSubjectV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_v5_models import (
    AccountOwnerAssignmentEvidenceV5Model,
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    AccountOwnerAssignmentSubjectV5Model,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_models import (
    AllocatedPhysicalAccountRowObservationV3Model,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
    CanonicalAccountCreationConsumptionClaimModel,
)
from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationAllocationModel,
    CanonicalAccountCreationBindingModel,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_models import (
    CanonicalAccountOwnershipReobservationV1Model,
)
from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.account.infrastructure.owner_tenant_authority_v3_models import (
    OwnerTenantAuthorityV3Model,
    OwnerTenantAuthorityV3RevocationModel,
)
from apps.account.infrastructure.physical_account_row_observation_v2_models import (
    PhysicalAccountRowObservationV2Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from apps.account.owner_tenant_authority_v3_composition import (
    build_owner_tenant_authority_v3_facade,
)
from apps.simulated_trading.account_physical_row_v2_composition import (
    build_account_physical_row_v2_provider,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_models import (
    SimulatedAccountRowSourceV2Model,
)
from shared.infrastructure.immutable_read_snapshot import immutable_read_snapshot
from tests.component.account.test_account_owner_assignment_provenance_receipt_v5_repository import (
    _seed_graph,
)
from tests.component.account.test_owner_tenant_authority_v3_composition import (
    _append_source_v2_for_physical,
)
from tests.support.owner_authority_current_sources import seed_current_actor_source
from tests.unit.account.test_account_owner_assignment_evidence_v5 import _evidence
from tests.unit.account.test_account_owner_assignment_subject_v5 import _subject

pytest_plugins = ["tests.component.account.test_owner_tenant_authority_v3_repository"]

PG_ALIAS = "evid06_authority_test"

_AUTH_MODELS: tuple[type[models.Model], ...] = (
    ContentType,
    Permission,
    Group,
    User,
    Session,
    AccountProfileModel,
    AccountAuthenticationContextSourceV3AnchorModel,
    AccountAuthenticationContextSourceV3Model,
    AccountUserAuthoritySourceV3AnchorModel,
    AccountUserAuthoritySourceV3Model,
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
)

_V5_MODELS: tuple[type[models.Model], ...] = (
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
    AccountOwnerAssignmentEvidenceV5Model,
)

_OWNER_MODELS: tuple[type[models.Model], ...] = (
    OwnerTenantAuthorityV3Model,
    OwnerTenantAuthorityV3RevocationModel,
    SimulatedAccountRowSourceV2Model,
)

_SCHEMA_MODELS = _AUTH_MODELS + _V5_MODELS + _OWNER_MODELS


class _DjangoDbBlocker(Protocol):
    def unblock(self) -> AbstractContextManager[None]:
        """Allow the fixture to create its isolated schema."""


def _collect_create_sql(
    connection: BaseDatabaseWrapper,
) -> tuple[str, ...]:
    """Collect model DDL without executing any per-model database request."""

    editor = connection.schema_editor(collect_sql=True, atomic=False)
    with editor:
        for model in _SCHEMA_MODELS:
            editor.create_model(model)
    raw_statements: object = getattr(editor, "collected_sql", None)
    if not isinstance(raw_statements, list):
        raise RuntimeError("schema editor did not expose collected PostgreSQL DDL")
    statements: list[str] = []
    for statement in raw_statements:
        if not isinstance(statement, str) or not statement.strip():
            raise RuntimeError("schema editor returned invalid PostgreSQL DDL")
        statements.append(statement)
    if not statements:
        raise RuntimeError("schema editor returned no PostgreSQL DDL")
    return tuple(statements)


def _owned_table_names(connection: BaseDatabaseWrapper) -> tuple[str, ...]:
    """Return every model and auto-created M2M table in drop dependency order."""

    names: list[str] = []
    seen: set[str] = set()
    for model in reversed(_SCHEMA_MODELS):
        for field in model._meta.local_many_to_many:
            through = field.remote_field.through
            if not through._meta.auto_created:
                continue
            table_name = through._meta.db_table
            if table_name not in seen:
                names.append(table_name)
                seen.add(table_name)
        table_name = model._meta.db_table
        if table_name not in seen:
            names.append(table_name)
            seen.add(table_name)
    return tuple(names)


def _collect_drop_sql(connection: BaseDatabaseWrapper) -> tuple[str, ...]:
    """Build reverse-order DROP statements without Django's implicit CASCADE."""

    return tuple(
        f"DROP TABLE {connection.ops.quote_name(table_name)};"
        for table_name in _owned_table_names(connection)
    )


def _execute_schema_batch(
    connection: BaseDatabaseWrapper,
    statements: tuple[str, ...],
) -> None:
    """Execute one quoted PostgreSQL DDL batch inside a rollbackable transaction."""

    if not statements:
        raise RuntimeError("empty PostgreSQL schema batch")
    batch = "SET LOCAL lock_timeout = '5s';\nSET LOCAL statement_timeout = '30s';\n"
    batch += "\n".join(statements)
    with transaction.atomic(using=connection.alias):
        with connection.cursor() as cursor:
            cursor.execute(batch)


@pytest.fixture(name="owner_alias")
def owner_alias(
    django_db_blocker: _DjangoDbBlocker,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    """Create the complete V5 parent graph in one disposable PostgreSQL DDL batch."""

    if os.environ.get("AGOM_EVID06_POSTGRES_TEST") != "1":
        pytest.skip("set AGOM_EVID06_POSTGRES_TEST=1 for the disposable EVID-06 test")
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    database_url = os.environ.get("AGOM_EVID06_POSTGRES_TEST_DATABASE_URL", "").strip()
    parsed = urlsplit(database_url)
    database_name = unquote(parsed.path.removeprefix("/"))
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError("EVID-06 PostgreSQL tests require a PostgreSQL URL")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("EVID-06 PostgreSQL tests require a loopback host")
    if database_name != PG_ALIAS or not parsed.username:
        raise RuntimeError("EVID-06 PostgreSQL tests require the dedicated test database")
    if PG_ALIAS in connections.databases:
        raise RuntimeError(f"refusing preexisting database alias: {PG_ALIAS}")
    try:
        port = parsed.port
    except ValueError as error:
        raise RuntimeError("EVID-06 PostgreSQL test URL has an invalid port") from error
    database_settings = cast(dict[str, object], deepcopy(connections["default"].settings_dict))
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
    connection = connections[PG_ALIAS]
    try:
        with django_db_blocker.unblock():
            if connection.vendor != "postgresql":
                raise RuntimeError("EVID-06 alias did not resolve to PostgreSQL")
            if connection.introspection.table_names():
                raise RuntimeError("refusing a non-empty dedicated EVID-06 database")
            _execute_schema_batch(connection, _collect_create_sql(connection))
            try:
                expected_tables = set(_owned_table_names(connection))
                actual_tables = set(connection.introspection.table_names())
                if actual_tables != expected_tables:
                    raise RuntimeError("batched V5 schema does not match the owned model tables")
                yield PG_ALIAS
            finally:
                _execute_schema_batch(connection, _collect_drop_sql(connection))
    finally:
        connection.close()
        connections.databases.pop(PG_ALIAS, None)


@contextmanager
def _stage(alias: str, name: str, stages: list[dict[str, object]]) -> Iterator[None]:
    """Record caller CPU and SQL execution time without retaining SQL text."""

    counts: dict[str, int] = {}
    sql_seconds = 0.0

    def observe(
        execute: Callable[..., object],
        sql: str,
        params: object,
        many: bool,
        context: object,
    ) -> object:
        nonlocal sql_seconds
        keyword = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else "EMPTY"
        counts[keyword] = counts.get(keyword, 0) + 1
        started = perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            sql_seconds += perf_counter() - started

    started_at = datetime.now(UTC)
    started = perf_counter()
    cpu_started = process_time()
    completed = False
    try:
        with connections[alias].execute_wrapper(observe):
            yield
        completed = True
    finally:
        stages.append(
            {
                "name": name,
                "started_at_utc": started_at.isoformat(),
                "finished_at_utc": datetime.now(UTC).isoformat(),
                "completed": completed,
                "wall_seconds": perf_counter() - started,
                "caller_cpu_seconds": process_time() - cpu_started,
                "sql_client_execute_seconds": sql_seconds,
                "sql_counts": counts,
            }
        )
        progress_directory = os.environ.get("AGOM_EVID09_FRESH_PARENT_PROGRESS", "").strip()
        if progress_directory:
            progress_path = Path(progress_directory) / f"{len(stages):02d}-{name}.json"
            with progress_path.open("x", encoding="utf-8") as stream:
                json.dump(stages[-1], stream, sort_keys=True, indent=2)
                stream.write("\n")


@pytest.mark.skipif(
    os.environ.get("AGOM_EVID06_POSTGRES_TEST") != "1",
    reason="opt-in disposable PostgreSQL V5 parent creation proof",
)
def test_opt_in_postgres_facade_creates_v5_parents_and_rolls_back(
    owner_alias: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create Receipt/Subject/Evidence, issue/revoke authority, then roll back."""

    connection = connections[owner_alias]
    assert connection.vendor == "postgresql"
    stages: list[dict[str, object]] = []
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), pg_backend_pid()")
        identity = cursor.fetchone()
    assert identity is not None and identity[0] == "evid06_authority_test"
    assert int(identity[1]) > 0

    subject_template = _subject()
    capture_at = datetime(2026, 8, 15, 14, 20, tzinfo=UTC)
    now = _evidence(subject_template).recorded_at + timedelta(minutes=1)
    with pytest.raises(RuntimeError, match="rollback newly created V5 graph"):
        with transaction.atomic(using=owner_alias):
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SET LOCAL statement_timeout = '30s'")
            monkeypatch.setattr("django.utils.timezone.now", lambda: capture_at)
            with _stage(owner_alias, "raw_and_actor", stages):
                actor_source = seed_current_actor_source(
                    owner_alias, capture_at, _evidence().approval_valid_until + timedelta(minutes=1)
                )
            monkeypatch.setattr("django.utils.timezone.now", lambda: now)
            with _stage(owner_alias, "upstream_ledger_creation", stages):
                _seed_graph(owner_alias, subject_template.receipt)
                physical = subject_template.reobservation.current_physical
                source = _append_source_v2_for_physical(owner_alias, physical)
                assert source.is_current_at(now)
                assert source.content_hash == physical.source_content_hash
            assert (
                AccountOwnerAssignmentProvenanceReceiptV5Model.objects.using(owner_alias).count()
                == 0
            )
            assert AccountOwnerAssignmentSubjectV5Model.objects.using(owner_alias).count() == 0
            assert AccountOwnerAssignmentEvidenceV5Model.objects.using(owner_alias).count() == 0
            with _stage(owner_alias, "receipt_v5_creation", stages):
                receipt = IssueAccountOwnerAssignmentProvenanceReceiptV5(
                    DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository(using=owner_alias)
                ).execute(
                    IssueAccountOwnerAssignmentProvenanceReceiptV5Command(subject_template.receipt)
                )
            with _stage(owner_alias, "subject_v5_creation", stages):
                subject = RegisterAccountOwnerAssignmentSubjectV5(
                    DjangoAccountOwnerAssignmentSubjectV5Repository(using=owner_alias)
                ).execute(RegisterAccountOwnerAssignmentSubjectV5Command(_subject(receipt)))
            policy = subject.policy
            principal = AuthenticatedAccountPrincipalV3(
                principal_id=actor_source.principal_id,
                user_id=actor_source.user_id,
                authentication_context_hash=actor_source.authentication_context_content_hash,
                authenticated_at=actor_source.principal_authenticated_at,
                valid_until=actor_source.principal_valid_until,
            )
            policy_binding = SingleOwnerPolicyBinding(
                policy.policy_id,
                policy.policy_version,
                policy.content_hash,
                policy.tenant_id,
                policy.owner_id,
                policy.account_namespace,
                policy.account_id,
            )
            physical_provider = build_account_physical_row_v2_provider(using=owner_alias)
            evidence_facade = build_account_owner_assignment_evidence_v5_facade(
                principal=principal,
                policy_binding=policy_binding,
                actor_source_id=actor_source.source_id,
                actor_source_version=actor_source.source_version,
                actor_source_content_hash=actor_source.content_hash,
                validity_period=timedelta(minutes=30),
                physical_row_provider=physical_provider,
                using=owner_alias,
            )
            command = ApproveAccountOwnerAssignmentEvidenceV5Command(
                "fresh-component-evidence",
                "v5.1",
                subject.subject_id,
                subject.subject_version,
                subject.content_hash,
            )
            with _stage(owner_alias, "evidence_v5_approval", stages):
                with immutable_read_snapshot():
                    assert (
                        evidence_facade._approve._repository.get_winner(
                            evidence_id=command.evidence_id,
                            evidence_version=command.evidence_version,
                            as_of=now,
                        )
                        is None
                    )
                    assignment = evidence_facade.approve(command)
                    assert (
                        evidence_facade.get_current(
                            GetCurrentAccountOwnerAssignmentEvidenceV5Command(
                                assignment.evidence_id,
                                assignment.evidence_version,
                                assignment.content_hash,
                                now,
                            )
                        )
                        == assignment
                    )
            assert assignment.subject == subject
            assert AccountOwnerAssignmentEvidenceV5Model.objects.using(owner_alias).count() == 1
            facade = build_owner_tenant_authority_v3_facade(
                principal=principal,
                policy_binding=policy_binding,
                actor_source_id=actor_source.source_id,
                actor_source_version=actor_source.source_version,
                actor_source_content_hash=actor_source.content_hash,
                validity_period=timedelta(minutes=20),
                physical_row_provider=physical_provider,
                using=owner_alias,
            )
            with _stage(owner_alias, "authority_issue_and_revoke", stages):
                issue = facade.issue(
                    IssueOwnerTenantAuthorityV3Command(
                        "fresh-component-authority",
                        "v3.1",
                        assignment.evidence_id,
                        assignment.evidence_version,
                        assignment.content_hash,
                    )
                )
                selector = GetCurrentOwnerTenantAuthorityV3Command(
                    issue.authority_id,
                    issue.authority_version,
                    issue.content_hash,
                )
                observed = facade.get_current(selector)
                assert observed is not None and observed.authority == issue
                facade.revoke(
                    RevokeOwnerTenantAuthorityV3Command(
                        issue.authority_id,
                        issue.authority_version,
                        issue.content_hash,
                        "component-rollback",
                    )
                )
                assert facade.get_current(selector) is None
                assert (
                    facade.get_exact(
                        GetExactOwnerTenantAuthorityV3Command(
                            issue.authority_id,
                            issue.authority_version,
                            issue.content_hash,
                            now,
                        )
                    )
                    == issue
                )
            raise RuntimeError("rollback newly created V5 graph")

    for table in connection.introspection.table_names():
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {connection.ops.quote_name(table)}")  # noqa: S608
            count = cursor.fetchone()
        assert count is not None and count[0] == 0
    destination = os.environ.get("AGOM_EVID09_FRESH_PARENT_RESULT", "").strip()
    if destination:
        Path(destination).write_text(
            json.dumps(
                {
                    "schema": "evid09.fresh-v5-parent-component.v1",
                    "database": identity[0],
                    "backend_pid": identity[1],
                    "synthetic_local_identity": True,
                    "production_resources_used": False,
                    "outer_rollback_all_fixture_rows_empty": True,
                    "stages": stages,
                    "receipt_hash": receipt.content_hash,
                    "subject_hash": subject.content_hash,
                    "evidence_hash": assignment.content_hash,
                    "authority_hash": issue.content_hash,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
