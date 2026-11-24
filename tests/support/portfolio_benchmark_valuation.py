"""Isolated real Portfolio configuration and broker accounting statement for benchmark acceptance."""

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from apps.portfolio.domain.policy_benchmark_definition import (
    PolicyBenchmarkConstituentDefinition,
    PolicyBenchmarkMethodologyRef,
)
from apps.portfolio.infrastructure import benchmark_daily_configuration as config
from tests.unit.portfolio import test_planning_policy_activation as planning
from tests.unit.portfolio import test_policy_benchmark_corporate_action as corporate
from tests.unit.portfolio import test_policy_benchmark_cost_tax as cost
from tests.unit.portfolio import test_policy_benchmark_definition as definitions
from tests.unit.portfolio import test_policy_benchmark_fx_fixing as fx
from tests.unit.portfolio import test_policy_benchmark_methodology_activation as method
from tests.unit.portfolio import test_policy_benchmark_price_fixing as pricing
from tests.unit.portfolio import test_policy_benchmark_trading_calendar as calendar


def publish_valuation_configuration(
    day: date, asset: str, *, using: str = "default", action_source=None, planning_overrides=None
) -> tuple[str, str]:
    """Publish genuine five-method, benchmark and planning ledgers for the selected test session."""
    recorded = datetime.combine(day - timedelta(days=3), time(0), UTC)
    end = recorded + timedelta(days=30)
    days = tuple(
        (
            calendar._valuation_day
            if (day + timedelta(days=i)).weekday() < 5
            else calendar._closed_day
        )(day + timedelta(days=i), i)
        for i in range(10)
    )
    cal = calendar._calendar(
        coverage_start=day,
        coverage_end=day + timedelta(days=9),
        days=days,
        recorded_at=recorded,
        valid_until=end,
    )
    methods = []
    for builder in (
        corporate._methodology,
        cost._methodology,
        fx._methodology,
        pricing._methodology,
    ):
        old = builder()
        refs = tuple(
            replace(r, recorded_at=recorded - timedelta(days=1), valid_until=end)
            for r in old.source_priority
        )
        if builder is corporate._methodology and action_source is not None:
            refs = (action_source,)
        if builder is pricing._methodology:
            refs = (replace(refs[0], owner="data_center", artifact_id="equity.price.bar.current"),)
        body = builder(source_priority=refs, recorded_at=recorded, valid_until=end)
        methods.append(body)
    methods.append(cal)
    refs = {}
    for key, body, repo in zip(
        (
            "corporate_action_ref",
            "cost_tax_ref",
            "fx_fixing_ref",
            "price_fixing_ref",
            "trading_calendar_ref",
        ),
        methods,
        (
            config.DjangoPolicyBenchmarkCorporateActionRepository,
            config.DjangoPolicyBenchmarkCostTaxRepository,
            config.DjangoPolicyBenchmarkFxFixingRepository,
            config.DjangoPolicyBenchmarkPriceFixingRepository,
            config.DjangoPolicyBenchmarkTradingCalendarRepository,
        ),
        strict=True,
    ):
        repository = repo(using=using)
        with repository.atomic():
            repository.append(body, recorded_at=recorded)
        refs[key] = PolicyBenchmarkMethodologyRef(
            "portfolio",
            body.artifact_type,
            body.methodology_id,
            body.methodology_version,
            body.content_hash,
            body.recorded_at,
            body.valid_until,
        )
    definition = definitions._definition(
        **refs,
        recorded_at=recorded + timedelta(minutes=1),
        valid_until=end,
        valuation_cutoff="15:30:00",
        constituents=(PolicyBenchmarkConstituentDefinition(asset, asset, "CNY", Decimal(1), 0),),
    )
    policy = planning._definition(
        **(
            {
                "slippage_rate": Decimal(0),
                "max_asset_weight": Decimal(1),
                "recorded_at": recorded,
                "valid_until": end,
            }
            | (planning_overrides or {})
        )
    )
    for value, repo in (
        (definition, config.DjangoPolicyBenchmarkDefinitionRepository),
        (policy, config.DjangoPlanningPolicyDefinitionRepository),
    ):
        repository = repo(using=using)
        with repository.atomic():
            repository.append(value, recorded_at=value.recorded_at)
    submit = recorded + timedelta(minutes=3)
    approve = recorded + timedelta(minutes=4)
    ms = method._subject(definition, requested_at=submit)
    ma = method._activation(ms, issued_at=approve)
    ps = planning._subject(definition=policy, requested_at=submit)
    pa = planning._activation(subject=ps, issued_at=approve)
    for subject, activation, repo in (
        (ms, ma, config.DjangoPolicyBenchmarkMethodologyActivationRepository),
        (ps, pa, config.DjangoPlanningPolicyActivationRepository),
    ):
        repository = repo(using=using)
        with repository.atomic():
            repository.append_subject(subject, recorded_at=submit)
            repository.append(activation, expected_predecessor_hash=None, recorded_at=approve)
    return definition.definition_id, policy.policy_id


def original_broker_day(
    *,
    broker_ref: str,
    asset: str,
    opening: datetime,
    closing: datetime,
    starting_equity: str = "10000",
    ending_equity: str = "10000",
    available_cash: str = "10000",
    frozen_cash: str = "0",
    holdings_value: str = "0",
    positions: tuple[tuple[str, str, str, str], ...] = (),
    deposit: str | None = None,
    withdrawal: str | None = None,
    split: str = "1",
    distribution: str = "0",
    interest: str = "0",
    costs: str = "0",
    exchange_rate: str = "1",
    action_coverage: bytes | None = None,
) -> bytes:
    """Issue the test custody book with explicit no-flow, corporate-action and FX coverage."""
    account = hashlib.sha256(broker_ref.encode()).hexdigest()
    rows = [
        ("opening_equity", opening, account, starting_equity),
        ("closing_equity", closing, account, ending_equity),
        ("closing_cash_available", closing, account, available_cash),
        ("closing_cash_frozen", closing, account, frozen_cash),
        ("closing_position_market_value", closing, account, holdings_value),
        ("closing_position_count", closing, account, str(len(positions))),
        (
            "external_flow_count",
            closing,
            "",
            str(int(deposit is not None) + int(withdrawal is not None)),
        ),
        ("corporate_action_coverage", closing, "", "1"),
        ("fx_coverage", closing, "", "1"),
        ("shadow_interest", closing, "", interest),
        ("shadow_costs", closing, "", costs),
        ("split_ratio", closing, asset, split),
        ("distribution_per_open_share", closing, asset, distribution),
        ("close_fx", closing, asset, exchange_rate),
    ]
    for code, held, available, marked in positions:
        rows.extend(
            [
                ("position_quantity", closing, code, held),
                ("position_available", closing, code, available),
                ("position_value", closing, code, marked),
            ]
        )
    for kind, value in (("deposit", deposit), ("withdrawal", withdrawal)):
        if value is not None:
            rows.append((kind, closing, "", value))
    source = "".join(
        f"custody-{i}-{instant.date()}-{kind},{kind},{instant.isoformat()},{code},CNY,{value}\n"
        for i, (kind, instant, code, value) in enumerate(rows, 1)
    ).encode()
    digest = hashlib.sha256(source).hexdigest()
    normalized = (
        "kind,ref,at,asset,currency,value\n"
        + "".join(
            f"{kind},{digest}#{i},{instant.isoformat()},{code},CNY,{value}\n"
            for i, (kind, instant, code, value) in enumerate(rows, 1)
        )
    ).encode()
    result = BytesIO()
    with ZipFile(result, "w", compression=ZIP_STORED) as archive:
        archive.writestr(ZipInfo("day.csv"), normalized)
        archive.writestr(ZipInfo("source.csv"), source)
        if action_coverage is not None:
            archive.writestr(ZipInfo("action-coverage.json"), action_coverage)
    return result.getvalue()


def publish_benchmark_through_session(
    *,
    owner_session,
    account_namespace: str,
    account_id: str,
    physical_account_id: int,
    owner_user_id: int,
    agent,
    day: date,
    tmp_path,
    set_time,
    through_day: date | None = None,
):
    """Use a disposable native DB and a forward-only test clock to produce one live-inception valuation.

    The caller establishes the real Account owner and Broker binding by 15:28 local. The
    current price publication, Broker snapshot/reconciliation, authenticated epoch/close and
    exact-current read below all pass through their ordinary owner implementations.
    """
    from uuid import UUID
    from zoneinfo import ZoneInfo

    from django.conf import settings
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.db import connection, transaction
    from django.utils import timezone

    from apps.broker_execution.infrastructure.models import (
        BrokerAccountBindingModel,
    )
    from apps.portfolio.benchmark_daily_valuation_composition import get_current_benchmark_valuation
    from tests.support.native_postgres_database import assert_native_postgres_test_database
    from tests.support.portfolio_benchmark_market import activate_benchmark_market_day
    from tests.support.tui_research.disposable import require_test_database

    if connection.vendor == "postgresql":
        assert_native_postgres_test_database()
        require_test_database(allow_native_postgres_test=True)
    else:
        require_test_database()
    asset = "600000.SH"
    cutoff = datetime.combine(day, time(15, 30), ZoneInfo("Asia/Shanghai")).astimezone(UTC)
    set_time(cutoff - timedelta(minutes=1))
    from tests.support.portfolio_benchmark_action_coverage import (
        action_coverage_member,
        make_action_source,
    )

    ref = replace(
        corporate._source(0, "independent-effective-action-feed"),
        owner="custody-event-publisher",
        recorded_at=cutoff - timedelta(days=5),
        valid_until=datetime.combine(day - timedelta(days=3), time(0), UTC) + timedelta(days=30),
    )
    action_ref, action_definition, independent_key = make_action_source(ref)
    definition, policy = publish_valuation_configuration(day, asset, action_source=action_ref)
    headers = {}
    cookie = owner_session.cookies.get(settings.CSRF_COOKIE_NAME)
    if cookie is not None:
        headers["HTTP_X_CSRFTOKEN"] = cookie.value
    start = owner_session.post(
        "/api/portfolio/benchmark-valuations/epochs/",
        {
            "account_namespace": account_namespace,
            "account_id": account_id,
            "definition_id": definition,
            "policy_id": policy,
        },
        **headers,
    )
    assert start.status_code == 200, start.content[:600]
    epoch = UUID(start.json()["epoch_id"])
    from apps.data_center.infrastructure.models import AssetMasterModel

    AssetMasterModel.objects.update_or_create(
        code=asset,
        defaults={
            "name": "Portfolio test stock",
            "currency": "CNY",
            "asset_type": "stock",
            "exchange": "SSE",
            "list_date": day - timedelta(days=30),
            "is_active": True,
        },
    )
    prior_close = None
    result = None
    sessions = (day,) if through_day is None else (day, through_day)
    for version, session_day in enumerate(sessions, 1):
        # Governance, actual import semantics and a decision-facing publication with retained synthetic raws.
        cutoff = datetime.combine(session_day, time(15, 30), ZoneInfo("Asia/Shanghai")).astimezone(
            UTC
        )
        origin = prior_close if prior_close is not None else cutoff
        fixing_price = 12.34 if prior_close is None else 12.40
        set_time(cutoff)
        activate_benchmark_market_day(
            asset=asset, day=session_day, close=Decimal(str(fixing_price)), at=cutoff
        )
        binding = BrokerAccountBindingModel.objects.get(
            account_id=physical_account_id, user_id=owner_user_id, agent=agent, is_active=True
        )
        # These independently captured test inputs exercise two different authenticated ingress routes.
        snapshot = publish_signed_broker_balances(
            agent=agent,
            account_id=physical_account_id,
            broker_ref=binding.broker_account_ref,
            captured_at=cutoff,
            cash_available="9406.40",
            cash_frozen="100.00",
            total_asset="10000.00" if prior_close is None else "10002.40",
            holdings_value="493.60" if prior_close is None else "496.00",
            positions=(("600000.SH", "40", "38", "493.60" if prior_close is None else "496.00"),),
        )
        set_time(cutoff + timedelta(minutes=1))
        packet_args = {
            "broker_ref": binding.broker_account_ref,
            "asset": asset,
            "opening": origin,
            "closing": cutoff,
            "costs": "3.00" if prior_close is None else "0",
            "starting_equity": "10000",
            "ending_equity": "10000" if prior_close is None else "10002.4",
            "available_cash": "9406.4",
            "frozen_cash": "100",
            "holdings_value": "493.6" if prior_close is None else "496",
            "positions": (("600000.SH", "40", "38", "493.6" if prior_close is None else "496"),),
        }

        def certify(packet, snapshot_id=snapshot.pk):
            return owner_session.post(
                f"/api/portfolio/benchmark-valuations/epochs/{epoch}/close/",
                {
                    "certify_complete": "true",
                    "broker_snapshot_id": snapshot_id,
                    "statement": SimpleUploadedFile(
                        "day.zip", packet, content_type="application/zip"
                    ),
                },
                **headers,
            )

        if prior_close is not None:
            unsigned = certify(original_broker_day(**packet_args))
            assert unsigned.status_code == 409, unsigned.content[:600]
            packet_args["action_coverage"] = action_coverage_member(
                action_ref,
                action_definition,
                independent_key,
                asset=asset,
                covered_from=origin,
                cutoff=cutoff,
                issued_at=timezone.now(),
            )
        response = certify(original_broker_day(**packet_args))
        assert response.status_code == 200, response.content[:600]
        with transaction.atomic():
            result = get_current_benchmark_valuation(valuation_id=epoch, valuation_version=version)
        assert result is not None and result.content_hash == response.json()["content_hash"]
        prior_close = cutoff
    assert result is not None
    return result


def publish_signed_broker_balances(
    *,
    agent,
    account_id,
    broker_ref,
    captured_at,
    cash_available="10000",
    cash_frozen="0",
    total_asset="10000",
    holdings_value="0",
    positions=(),
):
    """Submit a distinct HMAC-authenticated QMT capture through the machine HTTP API."""
    import json
    import secrets
    from uuid import uuid4

    from django.test import Client
    from django.utils import timezone

    from apps.broker_execution.application.agent_auth import build_agent_signature
    from apps.broker_execution.infrastructure.models import (
        BrokerAccountSnapshotModel,
        BrokerAgentCredentialModel,
    )

    secret = secrets.token_urlsafe(32)
    credential = BrokerAgentCredentialModel.objects.create(
        agent=agent,
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        scopes=["agent.snapshots.write"],
        allowed_account_ids=[account_id],
        expires_at=timezone.now() + timedelta(days=1),
    )
    body = json.dumps(
        {
            "contract_version": "1.0",
            "captured_at": captured_at.isoformat(),
            "account_id": account_id,
            "total_asset": total_asset,
            "cash_available": cash_available,
            "positions": [
                {
                    "asset_code": code,
                    "quantity": held,
                    "available_quantity": available,
                    "payload": {"market_value": amount},
                }
                for code, held, available, amount in positions
            ],
            "payload": {
                "valuation_close": {
                    "source": "xtquant.stock",
                    "broker_account_ref": broker_ref,
                    "assets_complete": True,
                    "positions_complete": True,
                    "currency": "CNY",
                    "cash_frozen": cash_frozen,
                    "position_market_value": holdings_value,
                }
            },
        }
    ).encode()
    # Transport authentication uses the live wall clock independently of the valuation test clock.
    nonce, request_id, sent_at = uuid4().hex, uuid4().hex, datetime.now(UTC).isoformat()
    response = Client().post(
        "/api/broker-execution/agent/v1/snapshots/",
        data=body,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Agent {credential.credential_id}.{secret}",
        HTTP_X_AGENT_ID=agent.agent_id,
        HTTP_X_REQUEST_ID=request_id,
        HTTP_X_SENT_AT=sent_at,
        HTTP_X_NONCE=nonce,
        HTTP_X_SIGNATURE=build_agent_signature(
            secret=secret, sent_at=sent_at, nonce=nonce, request_id=request_id, body=body
        ),
    )
    assert response.status_code == 200, response.content[:800]
    return BrokerAccountSnapshotModel.objects.get(
        agent=agent, account_id=account_id, captured_at=captured_at
    )
