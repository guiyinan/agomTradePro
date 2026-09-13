"""Opt-in PostgreSQL facade proof that creates its V5 parents before approval."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter, process_time

import pytest
from django.db import connections, transaction

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
from apps.account.owner_tenant_authority_v3_composition import (
    build_owner_tenant_authority_v3_facade,
)
from apps.simulated_trading.account_physical_row_v2_composition import (
    build_account_physical_row_v2_provider,
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
