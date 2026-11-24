"""Exercise real Portfolio and Broker ledgers with independently varied custody and publication facts."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client, RequestFactory
from django.utils import timezone

from apps.broker_execution.infrastructure.models import (
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentModel,
)
from apps.portfolio import benchmark_daily_valuation_composition as workflow
from apps.portfolio.application.benchmark_daily_sources import DayOwner
from apps.portfolio.domain.benchmark_execution_approval import BenchmarkScope
from apps.portfolio.domain.policy_benchmark_daily_valuation import (
    BenchmarkDayUnavailable,
    close_single_stock_day,
    read_day_ledger,
)
from apps.portfolio.infrastructure.policy_benchmark_daily_valuation_models import (
    PortfolioBenchmarkDailyValuationModel,
)
from core.integration.portfolio_benchmark_daily_sources import _OwnerSources
from tests.support.portfolio_benchmark_valuation import (
    original_broker_day,
    publish_signed_broker_balances,
    publish_valuation_configuration,
)


@pytest.mark.django_db
def test_session_owner_publishes_and_rechecks_real_configuration_and_broker_run(monkeypatch):
    day = date(2026, 11, 24)
    cutoff = datetime(2026, 11, 24, 7, 30, tzinfo=UTC)
    tick = [cutoff - timedelta(minutes=1)]
    monkeypatch.setattr(timezone, "now", lambda: tick[0])
    owner = get_user_model().objects.create_user(username="bench-owner")
    outsider = get_user_model().objects.create_user(username="bench-other")

    def request_for(user):
        client = Client()
        client.force_login(user)
        request = RequestFactory().post("/")
        request.session = client.session
        request.user = user
        return request

    owner_request = request_for(owner)
    other_request = request_for(outsider)
    agent = BrokerAgentModel.objects.create(user=owner, agent_id="daily-real")
    binding = BrokerAccountBindingModel.objects.create(
        user=owner, account_id=71, agent=agent, broker_account_ref="custody-real"
    )
    definition, policy = publish_valuation_configuration(day, "600000.SH")

    def live_owner(self, *, namespace, account_id, user_id, using):
        if user_id == owner.pk and account_id == "portfolio-71":
            return DayOwner(
                BenchmarkScope(namespace, account_id, user_id, "tenant", "owner"),
                71,
                "a" * 64,
                "b" * 64,
                cutoff + timedelta(days=3),
            )
        return None

    from contextlib import contextmanager

    from django.contrib.auth import get_user

    @contextmanager
    def fixture_signer(self, *, request, using, before_commit):
        with transaction.atomic(using=using):
            yield int(get_user(request).pk)
            before_commit()

    monkeypatch.setattr(_OwnerSources, "signer", fixture_signer)
    monkeypatch.setattr(_OwnerSources, "owner", live_owner)
    fixes = {"close": 100, "hash": "d" * 64}

    def published(*, asset, day, at, using):
        close = cutoff - timedelta(minutes=30)
        return {
            "benchmark_asset_class": "stock",
            "benchmark_venue": "SSE",
            "dataset_key": "equity.price.bar",
            "publication_key": "current",
            "must_not_use_for_decision": False,
            "asset_code": asset,
            "freshness_scope": "asset",
            "freshness_status": "fresh",
            "policy_identity": "policy",
            "selected_source": "vendor",
            "publication_run_id": "00000000-0000-0000-0000-000000000001",
            "publication_hash": fixes["hash"],
            "observed_at": close,
            "published_at": cutoff,
            "as_of": close,
            "rows": [
                {
                    "asset_code": asset,
                    "timestamp": day.isoformat(),
                    "period": "1d",
                    "source": "vendor",
                    "fetched_at": close,
                    "close": fixes["close"],
                }
            ],
        }

    from apps.data_center import benchmark_close_price_composition as dc
    from apps.data_center import benchmark_history_composition as history

    monkeypatch.setattr(history, "read_benchmark_member_hash", lambda **kwargs: "f" * 64)
    monkeypatch.setattr(dc, "locked_benchmark_close_payload", published)
    epoch = workflow.start_benchmark_epoch(
        request=owner_request,
        account_namespace="account",
        account_id="portfolio-71",
        definition_id=definition,
        policy_id=policy,
    )
    tick[0] = cutoff + timedelta(seconds=1)
    snapshot = publish_signed_broker_balances(
        agent=agent, account_id=71, broker_ref=binding.broker_account_ref, captured_at=cutoff
    )
    statement = original_broker_day(
        broker_ref=binding.broker_account_ref,
        asset="600000.SH",
        opening=cutoff,
        closing=cutoff,
        costs="3",
    )

    def publish(request=owner_request, raw=statement):
        return workflow.publish_benchmark_day(
            request=request, epoch_id=epoch, snapshot_id=snapshot.pk, original_statement=raw
        )

    with pytest.raises(BenchmarkDayUnavailable):
        publish(other_request)
    with pytest.raises(BenchmarkDayUnavailable):
        publish(raw=statement.replace(b"closing_equity", b"external_flow_count"))
    for changes in (
        {"costs": "0"},
        {"interest": "5", "costs": "3"},
        {"split": "2", "costs": "3"},
        {"available_cash": "9999", "frozen_cash": "1", "costs": "3"},
        {
            "available_cash": "9990",
            "holdings_value": "10",
            "positions": (("600000.SH", "1", "0", "10"),),
        },
        {"broker_ref": "another-custodian-account"},
    ):
        inputs = {
            "broker_ref": binding.broker_account_ref,
            "asset": "600000.SH",
            "opening": cutoff,
            "closing": cutoff,
        } | changes
        with pytest.raises(BenchmarkDayUnavailable):
            publish(raw=original_broker_day(**inputs))
    assert not PortfolioBenchmarkDailyValuationModel.objects.exists()
    with pytest.raises(BenchmarkDayUnavailable):
        workflow.publish_benchmark_day(
            request=owner_request,
            epoch_id=epoch,
            snapshot_id=snapshot.pk + 1,
            original_statement=statement,
        )
    stale = publish_signed_broker_balances(
        agent=agent,
        account_id=71,
        broker_ref=binding.broker_account_ref,
        captured_at=cutoff - timedelta(days=1),
    )
    with pytest.raises(BenchmarkDayUnavailable):
        workflow.publish_benchmark_day(
            request=owner_request,
            epoch_id=epoch,
            snapshot_id=stale.pk,
            original_statement=statement,
        )
    bad_mark = publish_signed_broker_balances(
        agent=agent,
        account_id=71,
        broker_ref=binding.broker_account_ref,
        captured_at=cutoff - timedelta(seconds=15),
        cash_available="9500",
        holdings_value="500",
        positions=(("600000.SH", "4", "4", "500"),),
    )
    matching_bad_statement = original_broker_day(
        broker_ref=binding.broker_account_ref,
        asset="600000.SH",
        opening=cutoff,
        closing=cutoff,
        costs="3",
        available_cash="9500",
        holdings_value="500",
        positions=(("600000.SH", "4", "4", "500"),),
    )
    with pytest.raises(BenchmarkDayUnavailable, match="different closing marks"):
        workflow.publish_benchmark_day(
            request=owner_request,
            epoch_id=epoch,
            snapshot_id=bad_mark.pk,
            original_statement=matching_bad_statement,
        )
    facts = publish()
    assert publish() == facts
    assert Decimal(
        PortfolioBenchmarkDailyValuationModel.objects.get().balance["unit_nav"]
    ) == Decimal("0.9997")
    with transaction.atomic():
        assert (
            workflow.get_current_benchmark_valuation(valuation_id=epoch, valuation_version=1)
            == facts
        )
        fixes["hash"] = "e" * 64
        assert (
            workflow.get_current_benchmark_valuation(valuation_id=epoch, valuation_version=1)
            is None
        )
    fixes["hash"] = "d" * 64
    BrokerAccountSnapshotModel.objects.filter(pk=snapshot.pk).update(cash_available=9999)
    with transaction.atomic():
        assert (
            workflow.get_current_benchmark_valuation(valuation_id=epoch, valuation_version=1)
            is None
        )
    assert PortfolioBenchmarkDailyValuationModel.objects.count() == 1


@pytest.mark.parametrize(
    "mutate",
    [
        "unpriced_flow",
        "wrong_currency",
        "missing_holding_quantity",
        "bad_original_digest",
        "missing_original_line",
        "bad_csv",
    ],
)
def test_incomplete_or_unpriced_custody_archive_is_unusable(mutate):
    import hashlib
    from io import BytesIO
    from zipfile import ZipFile

    day = datetime(2026, 9, 9, 7, 30, tzinfo=UTC)
    packet = original_broker_day(
        broker_ref="custody",
        asset="A",
        opening=day,
        closing=day + timedelta(days=1),
        deposit="500",
        available_cash="9500",
        holdings_value="500",
        positions=(("A", "25", "20", "500"),),
    )
    with ZipFile(BytesIO(packet)) as z:
        source = z.read("source.csv").decode().splitlines()
        normal = z.read("day.csv").decode().splitlines()
    old = hashlib.sha256(("\n".join(source) + "\n").encode()).hexdigest()
    if mutate == "missing_original_line":
        normal.pop()
    elif mutate == "bad_original_digest":
        normal[1] = normal[1].replace(old, "0" * 64)
    elif mutate == "bad_csv":
        normal[1] = '"unterminated'
    else:
        kind = {
            "unpriced_flow": "deposit",
            "wrong_currency": "shadow_interest",
            "missing_holding_quantity": "position_quantity",
        }[mutate]
        offset = next(i for i, line in enumerate(source) if line.split(",")[1] == kind)
        if mutate == "missing_holding_quantity":
            source.pop(offset)
            normal.pop(offset + 1)
        else:
            before, after = (
                ((day + timedelta(days=1)).isoformat(), (day + timedelta(hours=12)).isoformat())
                if mutate == "unpriced_flow"
                else (",CNY,", ",USD,")
            )
            source[offset] = source[offset].replace(before, after)
            normal[offset + 1] = normal[offset + 1].replace(before, after)
    orig = "\n".join(source) + "\n"
    updated = hashlib.sha256(orig.encode()).hexdigest()
    result = BytesIO()
    with ZipFile(result, "w") as zipout:
        zipout.writestr("source.csv", orig)
        zipout.writestr("day.csv", ("\n".join(normal) + "\n").replace(old, updated))
    with pytest.raises(BenchmarkDayUnavailable):
        read_day_ledger(result.getvalue())


@pytest.mark.django_db
@pytest.mark.parametrize(
    "incompatible",
    [
        {"slippage_rate": Decimal("0.001")},
        {"max_asset_weight": Decimal("0.5")},
        {"fee_rate": Decimal("0")},
    ],
)
def test_incompatible_current_planning_policy_is_blocked(incompatible):
    from apps.portfolio.infrastructure.benchmark_daily_configuration import read_daily_configuration

    day = timezone.localdate() - timedelta(days=2)
    definition, policy = publish_valuation_configuration(
        day, "600000.SH", planning_overrides=incompatible
    )
    with transaction.atomic(), pytest.raises(BenchmarkDayUnavailable):
        read_daily_configuration(
            definition_id=definition,
            policy_id=policy,
            at=datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=8),
            using="default",
        )


def test_approved_single_stock_exact_turnover_fee_and_unitized_cash_subscription():
    clock = datetime(2026, 11, 24, 7, 30, tzinfo=UTC)
    rate, increment = Decimal(".0003"), Decimal(".01")

    def advance(packet, mark, prior):
        return close_single_stock_day(
            ledger=read_day_ledger(packet),
            mark=Decimal(mark),
            code="A",
            prior=prior,
            rate=rate,
            rounding_increment=increment,
        )

    def packet(day, **values):
        return original_broker_day(
            broker_ref="custody",
            asset="A",
            opening=clock,
            closing=clock + timedelta(days=day),
            **values,
        )

    with pytest.raises(BenchmarkDayUnavailable):
        advance(packet(0, costs="0"), "100", None)
    opening = advance(packet(0, costs="3"), "100", None)
    no_flow = advance(packet(1), "110", opening)
    assert no_flow.total_value == Decimal("10996.70") and no_flow.unit_nav == Decimal("1.09967")
    subscribed = advance(packet(1, deposit="1000", costs=".30"), "110", opening)
    assert subscribed.total_value == Decimal("11996.40") and subscribed.unit_nav == Decimal(
        "1.09964"
    )
    with pytest.raises(BenchmarkDayUnavailable):
        advance(packet(1, deposit="1000", costs="0"), "110", opening)
    with pytest.raises(BenchmarkDayUnavailable):
        advance(packet(1, split="2"), "110", opening)

    redeemed = advance(packet(1, withdrawal="1000", costs=".30"), "110", opening)
    assert redeemed.total_value == Decimal("9996.40") and redeemed.unit_nav == Decimal("1.09964")
    with pytest.raises(BenchmarkDayUnavailable):
        advance(packet(1, deposit="1000", withdrawal="100", costs=".27"), "110", opening)
    with pytest.raises(BenchmarkDayUnavailable):
        advance(packet(1, withdrawal="12000", costs="3.60"), "110", opening)
