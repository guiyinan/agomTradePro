"""End-to-end Portfolio daily issuance and revocation in the disposable PostgreSQL database."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import Client
from django.utils import timezone

from apps.broker_execution.infrastructure.models import BrokerAccountBindingModel, BrokerAgentModel
from apps.portfolio.benchmark_execution_composition import read_current_benchmark_approval
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.portfolio_benchmark_account import persist_benchmark_account
from tests.support.portfolio_benchmark_approval import (
    isolated_benchmark_ledger as isolated_benchmark_ledger,
)
from tests.support.portfolio_benchmark_approval import (
    issue_benchmark_through_sessions,
    revoke_benchmark_through_session,
)
from tests.support.portfolio_benchmark_valuation import publish_benchmark_through_session

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def benchmark_world(monkeypatch, request):
    request.getfixturevalue("isolated_benchmark_ledger")
    if connection.vendor != "postgresql":
        pytest.skip("requires the dedicated native Portfolio database")
    wall = timezone.now
    actual = wall()
    local = ZoneInfo("Asia/Shanghai")
    # The approval is checked against the real PostgreSQL clock. Establish a prospective epoch
    # before the last completed close, then let that original be observed at the actual time.
    local_now = actual.astimezone(local)
    day = local_now.date()
    if (local_now.hour, local_now.minute) < (15, 31):
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    through_day = day
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    tick = [datetime(day.year, day.month, day.day, 15, 28, tzinfo=local).astimezone(UTC)]
    monkeypatch.setattr(timezone, "now", lambda: tick[0])
    users = get_user_model().objects
    owner = users.create_user(username="benchmark-owner", is_staff=True)
    reviewer = users.create_user(username="benchmark-reviewer", is_superuser=True, is_staff=True)
    for user, role in ((owner, "owner"), (reviewer, "admin")):
        profile = user.account_profile
        profile.rbac_role = role
        profile.approval_status = "approved"
        profile.save(update_fields=["rbac_role", "approval_status", "updated_at"])
    sessions = Client(), Client()
    for session, user in zip(sessions, (owner, reviewer), strict=True):
        session.force_login(user)
    account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name="Portfolio acceptance account",
        account_type="real",
        initial_capital=10000,
        current_cash=10000,
        current_market_value=0,
        total_value=10000,
    )
    assert not account.cash_known
    agent = BrokerAgentModel.objects.create(user=owner, agent_id="portfolio-valuation-agent")
    BrokerAccountBindingModel.objects.create(
        user=owner, account_id=account.pk, agent=agent, broker_account_ref="isolated-custody"
    )
    identity = persist_benchmark_account(
        owner_user_id=owner.pk,
        physical_row_pk=account.pk,
        portfolio_account_id=str(account.pk),
        valid_until=actual + timedelta(days=1),
    )
    path = Path(settings.BASE_DIR) / ".tmp" / "portfolio-benchmark" / uuid4().hex
    path.mkdir(parents=True)
    valuation = publish_benchmark_through_session(
        owner_session=sessions[0],
        account_namespace=identity.account_namespace,
        account_id=identity.account_id,
        physical_account_id=account.pk,
        owner_user_id=owner.pk,
        agent=agent,
        day=day,
        tmp_path=path,
        through_day=through_day,
        set_time=lambda value: tick.__setitem__(0, value),
    )
    monkeypatch.setattr(timezone, "now", wall)
    approved = issue_benchmark_through_sessions(
        owner_session=sessions[0],
        approver_session=sessions[1],
        valuation_id=valuation.valuation_id,
        valuation_version=valuation.valuation_version,
    )
    return owner, reviewer, *sessions, account, agent, identity, approved, valuation


def test_portfolio_approval_and_revocation(benchmark_world):
    owner, _, _, review, _, _, identity, approved, valuation = benchmark_world
    reviewed = review.get(f"/api/portfolio/benchmark-approvals/{approved.approval_id}/")
    assert reviewed.status_code == 200, reviewed.content[:500]
    source = reviewed.json()["source"]
    assert source["physical_row_pk"] == identity.physical_row_pk
    assert source["identity"] == [
        identity.source_id,
        identity.source_version,
        identity.identity_hash,
    ]
    assert source["account_policy"] == [
        identity.policy_id,
        identity.policy_version,
        identity.policy_hash,
    ]
    query = {
        "approval_id": approved.approval_id,
        "expected_version": approved.version,
        "expected_content_hash": approved.content_hash,
        "account_namespace": identity.account_namespace,
        "account_id": identity.account_id,
        "owner_user_id": owner.pk,
        "tenant_id": valuation.scope.tenant_id,
        "owner_id": valuation.scope.owner_id,
        "using": "default",
    }
    with transaction.atomic():
        assert read_current_benchmark_approval(**query) is not None
        assert (
            read_current_benchmark_approval(**{**query, "expected_content_hash": "0" * 64}) is None
        )
    revoke_benchmark_through_session(session=review, receipt=approved)
    with transaction.atomic():
        assert read_current_benchmark_approval(**query) is None


def test_withdrawn_first_close_invalidates_approved_second_close(benchmark_world):
    from apps.portfolio.infrastructure.policy_benchmark_daily_valuation_models import (
        PortfolioBenchmarkDailyValuationModel,
    )

    owner, _, session, _, _, _, identity, approved, valuation = benchmark_world
    assert valuation.valuation_version == 2
    first = PortfolioBenchmarkDailyValuationModel.objects.get(
        epoch_id=valuation.valuation_id, version=1
    )
    url = f"/api/portfolio/benchmark-valuations/epochs/{valuation.valuation_id}/statements/revoke/"
    query = {
        "approval_id": approved.approval_id,
        "expected_version": approved.version,
        "expected_content_hash": approved.content_hash,
        "account_namespace": identity.account_namespace,
        "account_id": identity.account_id,
        "owner_user_id": owner.pk,
        "tenant_id": valuation.scope.tenant_id,
        "owner_id": valuation.scope.owner_id,
        "using": "default",
    }
    wrong = session.post(
        url,
        {"observation_date": first.observation_date.isoformat(), "original_hash": "0" * 64},
        content_type="application/json",
    )
    assert wrong.status_code == 409 and wrong.headers["Content-Type"].startswith("application/json")
    with transaction.atomic():
        assert read_current_benchmark_approval(**query) is not None
    response = session.post(
        url,
        {
            "observation_date": first.observation_date.isoformat(),
            "original_hash": first.original_hash,
        },
        content_type="application/json",
    )
    assert response.status_code == 200 and response.json()["revoked"] is True
    with transaction.atomic():
        assert read_current_benchmark_approval(**query) is None
