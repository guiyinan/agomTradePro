"""Native Portfolio approval, current-source and concurrency contracts."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
from threading import Barrier
from uuid import uuid4
from zipfile import ZipFile

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, connection, connections, transaction
from django.test import Client
from django.utils import timezone

from apps.portfolio.benchmark_daily_valuation_composition import get_current_benchmark_valuation
from apps.portfolio.benchmark_execution_composition import read_current_benchmark_approval
from apps.portfolio.domain.benchmark_approval_history import benchmark_scope_key
from apps.portfolio.domain.policy_benchmark_daily_valuation import read_day_ledger
from apps.portfolio.infrastructure.benchmark_approval_models import BenchmarkApprovalEventModel
from apps.portfolio.infrastructure.policy_benchmark_daily_valuation_models import (
    PortfolioBenchmarkDailyValuationModel,
)
from tests.component.portfolio.test_benchmark_issuance_native import (
    benchmark_world as benchmark_world,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.portfolio_benchmark_ledger_cleanup import (
    isolated_benchmark_ledger as isolated_benchmark_ledger,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        settings.SETTINGS_MODULE != "core.settings.critical_postgres_test",
        reason="requires the isolated native Portfolio benchmark database",
    ),
]


def _assert_source_reissue_rejected(session, valuation):
    row = PortfolioBenchmarkDailyValuationModel.objects.get(
        epoch_id=valuation.valuation_id, version=valuation.valuation_version
    )
    original = bytes(row.original_statement)
    with ZipFile(BytesIO(original)) as archive:
        source, normalized = archive.read("source.csv"), archive.read("day.csv")
        coverage = archive.read("action-coverage.json")
    reissue = source.replace(b"custody-", b"reissued-custody-", 1)
    assert source != reissue
    changed = BytesIO()
    with ZipFile(changed, "w") as archive:
        archive.writestr("source.csv", reissue)
        archive.writestr("action-coverage.json", coverage)
        archive.writestr(
            "day.csv",
            normalized.replace(
                sha256(source).hexdigest().encode(), sha256(reissue).hexdigest().encode()
            ),
        )
    assert read_day_ledger(original) == read_day_ledger(changed.getvalue())
    url = f"/api/portfolio/benchmark-valuations/epochs/{valuation.valuation_id}/close/"

    def publish(packet):
        return session.post(
            url,
            {
                "certify_complete": "true",
                "broker_snapshot_id": row.snapshot_id,
                "statement": SimpleUploadedFile("day.zip", packet, content_type="application/zip"),
            },
        )

    same = publish(original)
    assert same.status_code == 200, same.content[:500]
    assert same.json()["content_hash"] == valuation.content_hash
    changed_response = publish(changed.getvalue())
    assert changed_response.status_code == 409, changed_response.content[:500]
    assert changed_response.json()["error"] == "day already closed with different evidence"
    assert (
        PortfolioBenchmarkDailyValuationModel.objects.filter(epoch_id=row.epoch_id).count()
        == valuation.valuation_version
    )


def _assert_two_session_submit_replays(session, valuation):
    identifier = uuid4()
    payload = {
        "request_id": str(identifier),
        "valuation_id": str(valuation.valuation_id),
        "valuation_version": valuation.valuation_version,
    }
    ready = Barrier(2)

    def send():
        client = Client()
        client.cookies = deepcopy(session.cookies)
        try:
            ready.wait(timeout=8)
            resp = client.post(
                "/api/portfolio/benchmark-approvals/", payload, content_type="application/json"
            )
            return resp.status_code, resp.json()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(send) for _ in range(2)]
        responses = [result.result(timeout=45) for result in results]
    assert any(code == 200 for code, _ in responses), responses
    assert all(code in {200, 404, 503} for code, _ in responses), responses
    replay = session.post(
        "/api/portfolio/benchmark-approvals/", payload, content_type="application/json"
    )
    assert replay.status_code == 200, replay.content[:500]
    assert all(body == replay.json() for code, body in responses if code == 200)
    assert list(
        BenchmarkApprovalEventModel.objects.filter(request_id=identifier).values_list(
            "action", "content_hash"
        )
    ) == [("submitted", replay.json()["content_hash"])]


def test_benchmark_current_signers_fences_and_replay(
    benchmark_world, isolated_benchmark_ledger, monkeypatch
):
    owner, reviewer, session, _, _, _, _, approved, valuation = benchmark_world
    query = {
        **asdict(valuation.scope),
        "approval_id": approved.approval_id,
        "expected_version": approved.version,
        "expected_content_hash": approved.content_hash,
        "using": "default",
    }
    with transaction.atomic():
        initial = read_current_benchmark_approval(**query)
        assert initial is not None and initial.valid_until <= valuation.valid_until
        other = connection.copy()
        try:
            with other.cursor() as cursor:
                cursor.execute("SET lock_timeout='300ms'")
                for actor in (owner, reviewer):
                    with pytest.raises(OperationalError) as blocked:
                        cursor.execute(
                            "UPDATE auth_user SET is_staff=is_staff WHERE id=%s", [actor.pk]
                        )
                    assert blocked.value.__cause__.sqlstate == "55P03"
                scope_key = benchmark_scope_key(valuation.scope)
                with pytest.raises(OperationalError) as blocked:
                    cursor.execute(
                        "INSERT INTO portfolio_benchmark_approval_event (scope_key) VALUES (%s)",
                        [scope_key],
                    )
                assert blocked.value.__cause__.sqlstate == "55P03"
                key = "portfolio.benchmark.approval:" + scope_key
                cursor.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", [key])
                assert cursor.fetchone() == (False,)
                cursor.execute(
                    "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", [key + ":other"]
                )
                assert cursor.fetchone() == (True,)
        finally:
            other.close()

    for actor, field, revoked in (
        (owner.account_profile, "rbac_role", "read_only"),
        (reviewer, "is_superuser", False),
    ):
        previous = getattr(actor, field)
        setattr(actor, field, revoked)
        actor.save(update_fields=[field])
        with transaction.atomic():
            assert read_current_benchmark_approval(**query) is None
        setattr(actor, field, previous)
        actor.save(update_fields=[field])
        with transaction.atomic():
            assert read_current_benchmark_approval(**query) == initial

    _assert_source_reissue_rejected(session, valuation)
    _assert_two_session_submit_replays(session, valuation)
    with monkeypatch.context() as cutoff, transaction.atomic():
        cutoff.setattr(timezone, "now", lambda: valuation.valid_until)
        assert (
            get_current_benchmark_valuation(
                valuation_id=valuation.valuation_id, valuation_version=valuation.valuation_version
            )
            is None
        )
        assert read_current_benchmark_approval(**query) is None
