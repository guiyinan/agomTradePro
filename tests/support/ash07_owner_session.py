"""Real Django Session/CSRF client for ordinary isolated Owner acceptance tests."""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


def ordinary_owner_session_client(owner_id: int) -> tuple[APIClient, str]:
    """Authenticate the persisted ordinary Owner and retain Django's CSRF token."""

    if type(owner_id) is not int or owner_id < 1:
        raise ValueError("owner_id must be a positive exact integer")
    owner = User.objects.get(pk=owner_id)
    if not owner.is_active or owner.is_staff or owner.is_superuser:
        raise AssertionError("ordinary Risk acceptance must not use an administrator identity")
    client = APIClient(enforce_csrf_checks=True)
    response = client.get("/csrf/bootstrap/", secure=True, HTTP_ORIGIN="https://testserver")
    if response.status_code != 200:
        raise AssertionError("Django CSRF bootstrap endpoint is unavailable")
    response_payload = response.json()
    if type(response_payload) is not dict:
        raise AssertionError("Django CSRF bootstrap payload is malformed")
    payload = cast(dict[str, object], response_payload)
    token = payload.get("csrf_token")
    csrf_cookie = client.cookies.get(settings.CSRF_COOKIE_NAME)
    if type(token) is not str or not token or csrf_cookie is None or not csrf_cookie.value:
        raise AssertionError("Django CSRF token or cookie is missing")
    client.force_login(owner)
    session_cookie = client.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_cookie is None or not session_cookie.value:
        raise AssertionError("Django SessionAuthentication cookie is missing")
    return client, token


def create_simulated_account_for_approved_owner(owner: User) -> SimulatedAccountModel:
    """Create the existing synthetic-ledger Account shape for an approved test Owner."""

    if owner.pk is None or not owner.is_active or owner.is_staff or owner.is_superuser:
        raise AssertionError("an active ordinary Owner identity is required")
    profile = AccountProfileModel.objects.filter(user_id=owner.pk).first()
    if (
        profile is None
        or profile.rbac_role != "owner"
        or profile.approval_status != "approved"
        or not profile.user_agreement_accepted
        or not profile.risk_warning_acknowledged
        or profile.approved_by_id is None
        or profile.approved_by_id == owner.pk
    ):
        raise AssertionError("the ordinary Owner needs the explicit approved test profile")
    return SimulatedAccountModel._default_manager.create(
        user=owner,
        account_name=f"ASH07 approved Owner {uuid4().hex[:12]}",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        cash_known=True,
        cash_reconciliation_status="simulated_ledger",
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100000.00"),
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        auto_trading_enabled=True,
        is_active=True,
    )


__all__ = (
    "create_simulated_account_for_approved_owner",
    "ordinary_owner_session_client",
)
