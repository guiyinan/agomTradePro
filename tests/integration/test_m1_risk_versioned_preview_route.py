"""The existing owner preview route must consume M1 risk qualification."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from tests.integration.simulated_trading import test_readonly_rebalance_plan_owner_api as owner_case


@pytest.mark.django_db
def test_existing_owner_preview_route_blocks_buy_when_version_source_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The current ordinary owner route exposes unknown policy and clears BUY readiness."""

    user, account = owner_case._create_owner_account(
        username="m1-risk-missing-version-route",
        positions=(),
        stop_loss_pct=None,
    )
    strategy = owner_case._create_strategy(
        user=user,
        target_weights={owner_case.ASSET_BUY: 0.10},
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        stop_loss_pct=None,
    )
    owner_case._install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
    )
    financial_before = owner_case._financial_snapshot()
    report_count_before = owner_case.DailyInspectionReportModel.objects.filter(
        account_id=account.pk
    ).count()
    proposal_count_before = owner_case.RebalanceProposalModel.objects.filter(
        account_id=account.pk
    ).count()
    client = APIClient()
    client.force_authenticate(user=user)

    response = owner_case._post_inspection(
        client=client,
        account_id=account.pk,
        strategy_id=strategy.pk,
    )

    assert response.status_code == 200
    assert response["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    plan = response.json()["reports"][0]["plan"]
    context = plan["risk_context"]
    falsification = context["risk_falsification"]
    buy = next(row for row in plan["asset_items"] if row["asset_code"] == owner_case.ASSET_BUY)

    assert context["rule_version"] is None
    assert context["rule_effective_from"] is None
    assert context["rule_effective_until"] is None
    assert context["risk_policy_version"] is None
    assert context["risk_policy_effective_from"] is None
    assert context["risk_policy_effective_until"] is None
    assert context["risk_policy_qualification_status"] == "missing"
    assert falsification["risk_policy_version"] is None
    assert falsification["effective_from"] is None
    assert falsification["status"] == "unknown"
    assert buy["action"] == "buy"
    assert buy["status"] == "blocked"
    assert buy["actionable_quantity"] is None
    assert buy["actionable_amount"] is None
    assert "M1_RISK_POLICY_VERSION_UNKNOWN" in buy["reason_codes"]

    owner_case._assert_no_financial_writes(
        before=financial_before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


@pytest.mark.django_db
def test_existing_owner_preview_route_qualifies_published_version_and_blocks_after_revoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real owner route uses a published M1 version until its real revoke audit."""

    user, account = owner_case._create_owner_account(
        username="m1-risk-qualified-version-route",
        positions=(),
        stop_loss_pct=8.0,
    )
    strategy = owner_case._create_strategy(
        user=user,
        target_weights={owner_case.ASSET_BUY: 0.10},
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        stop_loss_pct=8.0,
    )
    # One pytest-scoped Django clock drives revision known_at, preview as_of,
    # and the repository's explicit revocation effective_at consistently.
    preview_clock = SimpleNamespace(current=timezone.now() + timedelta(minutes=2))
    monkeypatch.setattr(timezone, "now", lambda: preview_clock.current)
    owner_case._install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        classification_asset_types={owner_case.ASSET_BUY: "equity"},
    )

    # The shared fixture replaces market ports but keeps the real M1
    # qualification use case, repository, and live source readers.
    effective_from = preview_clock.current

    client = APIClient()
    client.force_authenticate(user=user)
    published = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/",
        {
            "strategy_id": strategy.pk,
            "effective_from": effective_from.isoformat(),
            "effective_until": (timezone.now() + timedelta(days=30)).isoformat(),
            "reason": "I reviewed these limits for the M1 rebalance preview.",
            "max_single_position_applicability": "applicable",
            "max_single_position_limit_pct": "19",
            "max_total_position_applicability": "applicable",
            "max_total_position_limit_pct": "90",
            "max_stop_loss_applicability": "applicable",
            "max_stop_loss_limit_pct": "7",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="m1-risk-qualified-preview-publish",
    )

    assert published.status_code == 201
    assert published["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    published_body = published.json()
    risk_policy_version = published_body["risk_policy_version"]

    financial_before = owner_case._financial_snapshot()
    report_count_before = owner_case.DailyInspectionReportModel.objects.filter(
        account_id=account.pk
    ).count()
    proposal_count_before = owner_case.RebalanceProposalModel.objects.filter(
        account_id=account.pk
    ).count()
    qualified_preview = owner_case._post_inspection(
        client=client,
        account_id=account.pk,
        strategy_id=strategy.pk,
    )

    assert qualified_preview.status_code == 200
    assert qualified_preview["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    qualified_plan = qualified_preview.json()["reports"][0]["plan"]
    qualified_context = qualified_plan["risk_context"]
    qualified_falsification = qualified_context["risk_falsification"]
    qualified_buy = next(
        row for row in qualified_plan["asset_items"] if row["asset_code"] == owner_case.ASSET_BUY
    )

    assert qualified_plan["read_only"] is True
    assert qualified_plan["execution_submitted"] is False
    assert qualified_plan["status"] == "ready"
    assert Decimal(qualified_plan["estimated_buy_total"]) > Decimal("0")
    assert qualified_context["rule_version"] is None
    assert qualified_context["risk_policy_version"] == risk_policy_version
    assert qualified_context["risk_policy_qualification_status"] == "qualified"
    assert qualified_falsification["risk_policy_version"] == risk_policy_version
    assert qualified_falsification["status"] == "not_falsified"
    context_effective_from = parse_datetime(qualified_context["risk_policy_effective_from"])
    response_effective_from = parse_datetime(published_body["effective_from"])
    context_effective_until = parse_datetime(qualified_context["risk_policy_effective_until"])
    response_effective_until = parse_datetime(published_body["effective_until"])
    assert context_effective_from is not None
    assert response_effective_from is not None
    assert context_effective_from == response_effective_from
    assert context_effective_until is not None
    assert response_effective_until is not None
    assert context_effective_until == response_effective_until
    context_known_at = parse_datetime(qualified_context["risk_policy_known_at"])
    response_known_at = parse_datetime(published_body["known_at"])
    assert context_known_at is not None
    assert response_known_at is not None
    assert response_known_at == effective_from
    assert context_known_at == response_known_at
    assert qualified_buy["action"] == "buy"
    assert qualified_buy["status"] == "ready"
    assert qualified_buy["actionable_quantity"] is not None
    assert qualified_buy["actionable_amount"] is not None
    assert Decimal(qualified_buy["actionable_quantity"]) > Decimal("0")
    assert Decimal(qualified_buy["actionable_amount"]) > Decimal("0")
    owner_case._assert_no_financial_writes(
        before=financial_before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )

    preview_clock.current = effective_from + timedelta(seconds=1)
    revoked = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/"
        f"{risk_policy_version}/revoke/",
        {"reason": "I withdraw this M1 preview decision."},
        format="json",
        HTTP_IDEMPOTENCY_KEY="m1-risk-qualified-preview-revoke",
    )
    assert revoked.status_code == 200
    assert revoked["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    revoked_body = revoked.json()
    assert revoked_body["risk_policy_version"] == risk_policy_version
    assert revoked_body["revoked_at"]
    assert revoked_body["revoked_by_user_id"] == user.pk
    assert revoked_body["revocation_reason"] == "I withdraw this M1 preview decision."
    assert revoked_body["revocation_status"] == "revoked"

    financial_after_first_preview = owner_case._financial_snapshot()
    report_count_after_first_preview = owner_case.DailyInspectionReportModel.objects.filter(
        account_id=account.pk
    ).count()
    proposal_count_after_first_preview = owner_case.RebalanceProposalModel.objects.filter(
        account_id=account.pk
    ).count()
    preview_clock.current = effective_from + timedelta(seconds=2)
    revoked_preview = owner_case._post_inspection(
        client=client,
        account_id=account.pk,
        strategy_id=strategy.pk,
    )

    assert revoked_preview.status_code == 200
    assert revoked_preview["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    revoked_plan = revoked_preview.json()["reports"][0]["plan"]
    revoked_context = revoked_plan["risk_context"]
    revoked_buy = next(
        row for row in revoked_plan["asset_items"] if row["asset_code"] == owner_case.ASSET_BUY
    )
    assert revoked_context["risk_policy_version"] == risk_policy_version
    assert revoked_context["risk_policy_qualification_status"] == "revoked"
    assert revoked_buy["action"] == "buy"
    assert revoked_buy["status"] == "blocked"
    assert revoked_buy["actionable_quantity"] is None
    assert revoked_buy["actionable_amount"] is None
    assert "M1_RISK_POLICY_REVOKED" in revoked_buy["reason_codes"]
    owner_case._assert_no_financial_writes(
        before=financial_after_first_preview,
        account=account,
        report_count_before=report_count_after_first_preview,
        proposal_count_before=proposal_count_after_first_preview,
        report_count_delta=0,
    )
