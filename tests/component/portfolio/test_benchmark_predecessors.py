"""Exercise issued-time price members, successor publications and permanent custody withdrawals."""

import hashlib
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.data_center.benchmark_history_composition import (
    read_benchmark_member_hash,
    read_current_benchmark_day_member_hash,
)
from apps.portfolio import benchmark_predecessor_composition as history
from apps.portfolio.application.benchmark_daily_sources import DayOwner
from apps.portfolio.domain.benchmark_execution_approval import BenchmarkScope
from apps.portfolio.domain.policy_benchmark_daily_valuation import BenchmarkDayUnavailable
from apps.portfolio.infrastructure.benchmark_statement_revocation_models import (
    BenchmarkStatementRevocationModel,
)
from apps.portfolio.infrastructure.policy_benchmark_daily_valuation_models import (
    _claim_valuation_insert,
)


@pytest.mark.django_db(transaction=True, available_apps=["apps.data_center", "apps.audit"])
def test_historical_member_survives_new_session_but_rejects_published_correction(monkeypatch):
    from tests.support.portfolio_benchmark_market import activate_benchmark_market_day

    first = datetime(2026, 11, 23, 7, 30, tzinfo=UTC)
    second = first + timedelta(days=1)
    tick = [first]
    monkeypatch.setattr(timezone, "now", lambda: tick[0])
    asset = "600000.SH"

    def publish(session, close):
        return activate_benchmark_market_day(
            asset=asset, day=session.date(), close=Decimal(str(close)), at=tick[0]
        )

    origin = publish(first, 10)
    with transaction.atomic():
        digest = read_benchmark_member_hash(
            asset=asset,
            day=first.date(),
            at=first,
            publication_hash=origin.publication_hash,
            expected_price=Decimal(10),
            using="default",
        )
        assert digest and len(digest) == 64
        assert (
            read_benchmark_member_hash(
                asset=asset,
                day=first.date(),
                at=first,
                publication_hash=origin.publication_hash,
                expected_price=Decimal(11),
                using="default",
            )
            is None
        )
    tick[0] = second
    newer = publish(second, 11)
    assert newer.publication_id != origin.publication_id

    def read():
        with transaction.atomic():
            return read_current_benchmark_day_member_hash(
                asset=asset, day=first.date(), issued_at=first, at=tick[0], using="default"
            )

    assert read() == digest
    tick[0] += timedelta(minutes=1)
    publish(first, 12)
    tick[0] += timedelta(minutes=1)
    # A subsequent routine publication cannot hide the intervening restatement.
    publish(second, 11.5)
    assert read() is None


@pytest.mark.django_db
def test_authenticated_withdrawal_requires_exact_original_and_invalidates_descendants(monkeypatch):
    now = timezone.now()
    user = 17
    owner = DayOwner(
        BenchmarkScope("account", "portfolio-17", user, "tenant", "owner"),
        17,
        "a" * 64,
        "b" * 64,
        now + timedelta(hours=1),
        source_id="fixture-identity",
        source_version="v1",
        policy_id="fixture-policy",
        policy_version="v1",
    )
    epoch = history.Epoch(
        owner_user_id=user,
        account_id="portfolio-17",
        account_namespace="account",
        sequence=1,
        scope_hash=history.valuation_digest(
            asdict(owner.scope), owner.physical_id, owner.identity_hash, owner.policy_hash
        ),
        definition_id="d",
        policy_id="p",
        configuration_hash="d" * 64,
        started_at=now,
        content_hash="e" * 64,
    )
    with _claim_valuation_insert(epoch):
        epoch.save(force_insert=True)
    raw = b"retained exact certified statement"
    row = history.Daily(
        epoch=epoch,
        version=1,
        observation_date=now.date(),
        observed_at=now,
        recorded_at=now,
        valid_until=owner.valid_until,
        snapshot_id=1,
        reconciliation_hash="f" * 64,
        original_statement=raw,
        original_hash=hashlib.sha256(raw).hexdigest(),
        fixing_hash="c" * 64,
        predecessor_hash="",
        balance={},
    )
    row.content_hash = history.daily_valuation_digest(row)
    with _claim_valuation_insert(row):
        row.save(force_insert=True)

    class Sources:
        @contextmanager
        def signer(self, *, request, using, before_commit):
            with transaction.atomic():
                yield request
                before_commit()

        def owner(self, **kwargs):
            return owner

    monkeypatch.setattr(history, "benchmark_day_sources", Sources)

    def revoke(actor, digest):
        history.revoke_benchmark_statement(
            request=actor, epoch_id=epoch.pk, day=now.date(), original_hash=digest
        )

    with pytest.raises(BenchmarkDayUnavailable, match="owner_unavailable"):
        revoke(user + 1, row.original_hash)
    with pytest.raises(BenchmarkDayUnavailable, match="original_mismatch"):
        revoke(user, "0" * 64)
    history.require_uncorrected_benchmark_day(row, using="default")
    history.require_benchmark_predecessors(
        epoch=epoch, through_version=0, expected_hash="", owner=owner, using="default"
    )
    revoke(user, row.original_hash)
    revoke(user, row.original_hash)
    assert BenchmarkStatementRevocationModel.objects.count() == 1
    with pytest.raises(BenchmarkDayUnavailable, match="statement_revoked"):
        history.require_benchmark_predecessors(
            epoch=epoch,
            through_version=1,
            expected_hash=row.content_hash,
            owner=owner,
            using="default",
        )
    with pytest.raises(ValidationError):
        BenchmarkStatementRevocationModel.objects.get().delete()
