"""Account-scoped M1 publication must not be selectable through preview input."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.risk_center.application.m1_rebalance_risk_policy import (
    GetM1RiskPolicyQualificationUseCase,
    M1RiskPolicyQualification,
)
from apps.risk_center.domain.m1_rebalance_risk_policy import M1RiskSourceSnapshot
from apps.simulated_trading.application.m1_rebalance_risk_policy import (
    M1RiskPolicyAccountSource,
)
from apps.simulated_trading.infrastructure.m1_risk_policy_account_source_reader import (
    DjangoM1RiskPolicyAccountSourceReader,
)
from tests.integration.simulated_trading import test_readonly_rebalance_plan_owner_api as owner_case


@pytest.mark.django_db
@pytest.mark.parametrize(
    "preview_prefix",
    ("/api/account", "/api/simulated-trading"),
    ids=("account-api", "sdk-simulated-trading-api"),
)
def test_preview_uses_path_owner_and_server_active_revision(
    monkeypatch: pytest.MonkeyPatch,
    preview_prefix: str,
) -> None:
    """Forged account/version body fields cannot select another owner's revision."""

    owner, account = owner_case._create_owner_account(
        username="ref03-preview-owner",
        positions=(),
        stop_loss_pct=8.0,
    )
    strategy = owner_case._create_strategy(
        user=owner,
        target_weights={owner_case.ASSET_BUY: 0.10},
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        stop_loss_pct=8.0,
    )
    foreign_owner, foreign_account = owner_case._create_owner_account(
        username="ref03-preview-foreign-owner",
        positions=(),
        stop_loss_pct=8.0,
    )
    foreign_strategy = owner_case._create_strategy(
        user=foreign_owner,
        target_weights={owner_case.ASSET_BUY: 0.10},
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        stop_loss_pct=8.0,
    )

    preview_clock = SimpleNamespace(current=timezone.now() + timedelta(minutes=2))
    monkeypatch.setattr(timezone, "now", lambda: preview_clock.current)
    owner_case._install_preview_ports(
        monkeypatch,
        account=account,
        user_id=owner.pk,
        classification_asset_types={owner_case.ASSET_BUY: "equity"},
    )
    owner_client = APIClient()
    foreign_client = APIClient()
    owner_version = owner_case._publish_m1_policy_for_preview(
        monkeypatch,
        client=owner_client,
        owner=owner,
        account=account,
        strategy=strategy,
    )
    foreign_version = owner_case._publish_m1_policy_for_preview(
        monkeypatch,
        client=foreign_client,
        owner=foreign_owner,
        account=foreign_account,
        strategy=foreign_strategy,
    )
    assert owner_version != foreign_version

    forged = owner_client.post(
        f"{preview_prefix}/accounts/{account.pk}/inspections/run/",
        {
            "strategy_id": strategy.pk,
            "inspection_date": timezone.localdate().isoformat(),
            "auto_create_proposal": False,
            "account_id": foreign_account.pk,
            "risk_policy_version": foreign_version,
        },
        format="json",
    )

    assert forged.status_code == 200
    assert forged["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    forged_body = forged.json()
    assert forged_body["reports"][0]["account_id"] == account.pk
    plan = forged_body["reports"][0]["plan"]
    assert plan["risk_context"]["risk_policy_version"] == owner_version
    assert foreign_version not in json.dumps(forged_body, sort_keys=True)

    reports_before = owner_case.DailyInspectionReportModel.objects.filter(
        account_id=foreign_account.pk
    ).count()
    cross_account = owner_client.post(
        f"{preview_prefix}/accounts/{foreign_account.pk}/inspections/run/",
        {
            "strategy_id": foreign_strategy.pk,
            "inspection_date": timezone.localdate().isoformat(),
            "auto_create_proposal": False,
            "account_id": account.pk,
            "risk_policy_version": owner_version,
        },
        format="json",
    )

    assert cross_account.status_code == 403
    assert cross_account["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    cross_body = cross_account.json()
    assert cross_body.get("reports") is None
    serialized_error = json.dumps(cross_body, sort_keys=True)
    assert owner_version not in serialized_error
    assert foreign_version not in serialized_error
    assert (
        owner_case.DailyInspectionReportModel.objects.filter(account_id=foreign_account.pk).count()
        == reports_before
    )


@pytest.mark.django_db
def test_preview_owner_source_mismatch_returns_unknown_without_revision_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mismatched persisted account source yields no revision or executable BUY."""

    owner, account = owner_case._create_owner_account(
        username="ref03-preview-source-owner",
        positions=(),
        stop_loss_pct=8.0,
    )
    foreign_owner, _foreign_account = owner_case._create_owner_account(
        username="ref03-preview-source-foreign-owner",
        positions=(),
        stop_loss_pct=8.0,
    )
    strategy = owner_case._create_strategy(
        user=owner,
        target_weights={owner_case.ASSET_BUY: 0.10},
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        stop_loss_pct=8.0,
    )
    preview_clock = SimpleNamespace(current=timezone.now() + timedelta(minutes=2))
    monkeypatch.setattr(timezone, "now", lambda: preview_clock.current)
    owner_case._install_preview_ports(
        monkeypatch,
        account=account,
        user_id=owner.pk,
        classification_asset_types={owner_case.ASSET_BUY: "equity"},
    )
    client = APIClient()
    owner_version = owner_case._publish_m1_policy_for_preview(
        monkeypatch,
        client=client,
        owner=owner,
        account=account,
        strategy=strategy,
    )

    original_read = DjangoM1RiskPolicyAccountSourceReader.read_owner_source

    def mismatched_account_source(
        reader: DjangoM1RiskPolicyAccountSourceReader,
        *,
        account_id: int,
    ) -> M1RiskPolicyAccountSource | None:
        source = original_read(reader, account_id=account_id)
        if source is None or account_id != account.pk:
            return source
        return replace(source, owner_user_id=foreign_owner.pk)

    monkeypatch.setattr(
        DjangoM1RiskPolicyAccountSourceReader,
        "read_owner_source",
        mismatched_account_source,
    )
    qualification_queries: list[int] = []
    original_qualification = GetM1RiskPolicyQualificationUseCase.execute

    def track_qualification_query(
        use_case: GetM1RiskPolicyQualificationUseCase,
        *,
        account_id: int,
        as_of: datetime,
        current_source: M1RiskSourceSnapshot,
    ) -> M1RiskPolicyQualification:
        qualification_queries.append(account_id)
        return original_qualification(
            use_case,
            account_id=account_id,
            as_of=as_of,
            current_source=current_source,
        )

    monkeypatch.setattr(
        GetM1RiskPolicyQualificationUseCase,
        "execute",
        track_qualification_query,
    )
    response = owner_case._post_inspection(
        client=client,
        account_id=account.pk,
        strategy_id=strategy.pk,
    )

    assert response.status_code == 200
    assert response["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    body = response.json()
    plan = body["reports"][0]["plan"]
    context = plan["risk_context"]
    falsification = context["risk_falsification"]
    buy = next(row for row in plan["asset_items"] if row["asset_code"] == owner_case.ASSET_BUY)

    assert qualification_queries == []
    assert context["risk_policy_version"] is None
    assert context["risk_policy_qualification_status"] == "unknown"
    assert "M1_RISK_ACCOUNT_OWNER_SOURCE_MISMATCH" in context["risk_policy_reason_codes"]
    assert falsification["risk_policy_version"] is None
    assert falsification["status"] == "unknown"
    assert buy["status"] == "blocked"
    assert buy["actionable_quantity"] is None
    assert buy["actionable_amount"] is None
    assert owner_version not in json.dumps(body, sort_keys=True)
