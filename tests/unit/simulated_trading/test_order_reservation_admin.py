"""Financial rows cannot bypass application locks through Django Admin."""

from types import SimpleNamespace

from django.contrib import admin
from django.test import RequestFactory

from apps.simulated_trading.interface.admin import (
    SimulatedAccountAdmin,
    SimulatedOrderReservationAdmin,
    SimulatedPositionAdmin,
)
from apps.simulated_trading.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
)


def test_account_and_position_admin_keep_view_but_refuse_financial_writes() -> None:
    request = RequestFactory().get("/admin/")
    request.user = SimpleNamespace(
        is_active=True, is_staff=True, is_superuser=True, has_perm=lambda permission: True
    )
    for model, admin_type in (
        (SimulatedAccountModel, SimulatedAccountAdmin),
        (PositionModel, SimulatedPositionAdmin),
        (SimulatedOrderReservationModel, SimulatedOrderReservationAdmin),
    ):
        model_admin = admin_type(model, admin.site)
        assert model_admin.has_view_permission(request)
        assert not model_admin.has_add_permission(request)
        assert not model_admin.has_change_permission(request)
        assert not model_admin.has_delete_permission(request)
        assert "delete_selected" not in model_admin.get_actions(request)
