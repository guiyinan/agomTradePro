"""Input contract for the explicit published-close preview basis."""

from __future__ import annotations

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.simulated_trading.interface import views
from apps.simulated_trading.interface.serializers import DailyInspectionRunRequestSerializer
from apps.simulated_trading.interface.views import DailyInspectionRunAPIView


@pytest.mark.parametrize("basis", ("market", "published_close"))
def test_preview_reference_price_basis_accepts_only_supported_modes(basis: str) -> None:
    """The public preview chooses a named basis, never an arbitrary publication lane."""

    serializer = DailyInspectionRunRequestSerializer(
        data={"reference_price_basis": basis, "auto_create_proposal": False}
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["reference_price_basis"] == basis


def test_preview_reference_price_basis_defaults_to_existing_market_mode() -> None:
    """Legacy requests keep the existing market reader by default."""

    serializer = DailyInspectionRunRequestSerializer(data={})

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["reference_price_basis"] == "market"


@pytest.mark.parametrize(
    "unsupported_field",
    ("publication_key", "cutoff", "knowledge_cutoff", "as_of"),
)
def test_preview_rejects_raw_publication_and_cutoff_controls(unsupported_field: str) -> None:
    """Callers cannot silently believe an ignored Data Center control was applied."""

    serializer = DailyInspectionRunRequestSerializer(
        data={unsupported_field: "m1-rebalance-reference"}
    )

    assert not serializer.is_valid()
    assert "non_field_errors" in serializer.errors


def test_published_close_mode_rejects_proposal_creation() -> None:
    """The historical-price view is read-only and cannot become a proposal shortcut."""

    serializer = DailyInspectionRunRequestSerializer(
        data={
            "reference_price_basis": "published_close",
            "auto_create_proposal": True,
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["auto_create_proposal"] is True


def test_preview_rejects_unknown_price_basis() -> None:
    """Unknown modes fail input validation rather than reverting to live prices."""

    serializer = DailyInspectionRunRequestSerializer(
        data={"reference_price_basis": "arbitrary_publication"}
    )

    assert not serializer.is_valid()
    assert "reference_price_basis" in serializer.errors


@pytest.mark.parametrize(
    ("payload", "expected_basis", "expected_status"),
    (
        ({}, "market", 200),
        ({"reference_price_basis": "published_close"}, "published_close", 200),
    ),
)
def test_owner_route_binds_only_the_selected_price_basis(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    expected_basis: str,
    expected_status: int,
) -> None:
    """The real DRF view keeps market default and injects the selected close lane."""

    from types import SimpleNamespace

    selected: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _owned_account(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(user_id=41)

    def _builder_factory(*args: object, **kwargs: object) -> object:
        selected.append((args, kwargs))
        return object()

    monkeypatch.setattr(views, "_get_owned_account_or_response", _owned_account)
    monkeypatch.setattr(views, "_authenticated_user_id", lambda request: 41)
    monkeypatch.setattr(
        views.rebalance_plan_preview_composition,
        "build_readonly_rebalance_plan_preview_builder",
        _builder_factory,
    )
    monkeypatch.setattr(
        views.simulated_interface_services,
        "run_daily_inspection",
        lambda **kwargs: {"report_id": 1},
    )

    request = APIRequestFactory().post(
        "/api/account/accounts/7/inspections/run/",
        payload,
        format="json",
    )
    force_authenticate(
        request,
        user=SimpleNamespace(is_authenticated=True, is_active=True, pk=41),
    )
    response = DailyInspectionRunAPIView.as_view()(request, account_id=7)
    response.render()

    assert response.status_code == expected_status
    assert response["Content-Type"].startswith("application/json")
    assert len(selected) == 1
    args, kwargs = selected[0]
    if expected_basis == "market":
        assert args == ()
        assert kwargs == {}
    else:
        assert args == ()
        assert kwargs == {"reference_price_basis": "published_close"}


def test_owner_route_rejects_published_close_proposal_before_any_preview_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The close lane cannot write a proposal or invoke price/data providers."""

    from types import SimpleNamespace

    monkeypatch.setattr(
        views,
        "_get_owned_account_or_response",
        lambda *args, **kwargs: SimpleNamespace(user_id=41),
    )
    monkeypatch.setattr(views, "_authenticated_user_id", lambda request: 41)
    monkeypatch.setattr(
        views.rebalance_plan_preview_composition,
        "build_readonly_rebalance_plan_preview_builder",
        lambda *args, **kwargs: pytest.fail("preview builder must not be created"),
    )
    monkeypatch.setattr(
        views.simulated_interface_services,
        "run_daily_inspection",
        lambda **kwargs: pytest.fail("inspection must not run"),
    )

    request = APIRequestFactory().post(
        "/api/account/accounts/7/inspections/run/",
        {"reference_price_basis": "published_close", "auto_create_proposal": True},
        format="json",
    )
    force_authenticate(
        request,
        user=SimpleNamespace(is_authenticated=True, is_active=True, pk=41),
    )
    response = DailyInspectionRunAPIView.as_view()(request, account_id=7)
    response.render()

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")


def test_preview_payload_preserves_selected_basis_and_item_publication() -> None:
    """Historical reports keep the chosen basis and exact row provenance."""

    from dataclasses import replace
    from datetime import UTC, date, datetime
    from decimal import Decimal

    from apps.risk_center.application.m1_rebalance_risk_policy import (
        M1RiskPolicyQualification,
    )
    from apps.risk_center.domain.m1_rebalance_risk_policy import RiskQualificationState
    from apps.simulated_trading.application.rebalance_plan_preview_assembly import (
        empty_rebalance_plan_preview,
    )
    from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
        RebalancePlanPreviewItem,
    )
    from apps.simulated_trading.application.rebalance_preview_context import (
        build_rebalance_plan_risk_context,
    )
    from apps.simulated_trading.application.rebalance_preview_reference_close import (
        PricePublicationReference,
    )

    cutoff = datetime(2026, 10, 27, 2, 0, tzinfo=UTC)
    observed_at = datetime(2026, 10, 26, 7, 0, tzinfo=UTC)
    risk_context = build_rebalance_plan_risk_context(
        summary={},
        strategy_id=None,
        position_rule_id=None,
        strategy_name=None,
        strategy_type=None,
        strategy_version=None,
        rule_name=None,
        max_position_pct=None,
        max_total_position_pct=None,
        stop_loss_pct=None,
        strategy_selection_state="confirmed_unconfigured",
        account_max_position_pct=None,
        account_max_total_position_pct=None,
        account_stop_loss_pct=None,
        risk_policy_qualification=M1RiskPolicyQualification(
            state=RiskQualificationState.MISSING,
            reason_codes=("M1_RISK_POLICY_VERSION_UNKNOWN",),
            revision=None,
        ),
        macro_regime="",
        policy_gear="",
        reference_price_basis="published_close",
    )
    preview = empty_rebalance_plan_preview(
        cutoff,
        "blocked",
        "NO_POSITIONS",
        risk_context,
    )
    publication = PricePublicationReference(
        dataset_key="equity.price.bar",
        publication_key="m1-rebalance-reference",
        publication_id="publication-1",
        publication_hash="a" * 64,
        publication_run_id="00000000-0000-0000-0000-000000000001",
        published_at=cutoff,
        publication_as_of=observed_at,
        knowledge_cutoff=cutoff,
        bar_date=date(2026, 10, 26),
        source_observed_at=observed_at,
        freshness_status="latest_completed_session",
    )
    item = RebalancePlanPreviewItem(
        scope="asset",
        action="hold",
        asset_code="600000.SH",
        asset_name="600000.SH",
        asset_type="equity",
        currency_unit=None,
        quantity_unit="shares",
        current_weight=None,
        target_weight=Decimal("0.1"),
        portfolio_value=None,
        current_amount=None,
        target_amount=None,
        suggested_amount=None,
        actionable_amount=None,
        current_quantity=None,
        target_quantity=None,
        suggested_quantity=None,
        actionable_quantity=None,
        remaining_quantity=None,
        sellable_quantity=None,
        reference_price=None,
        price_source=None,
        price_as_of=None,
        price_freshness=None,
        price_is_fallback=None,
        price_observed_at=None,
        identity=None,
        fee=None,
        drift_threshold=None,
        risk_rule_result=None,
        risk_rule_reason_code=None,
        risk_rule_entry_price_basis=None,
        status="blocked",
        reason_codes=("M1_REFERENCE_CLOSE_ROW_INVALID",),
        price_publication=publication,
    )

    assert preview.to_payload()["reference_price_basis"] == "published_close"
    assert item.to_payload()["price_publication"] == publication.to_payload()
    assert replace(item, price_publication=None).to_payload()["price_publication"] is None
