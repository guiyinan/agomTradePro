"""Calendar object permissions preserve Django's ordinary Admin behavior."""

from __future__ import annotations

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import models
from django.test import RequestFactory

from apps.data_center.application.calendar_catalog_bootstrap import CALENDAR_DATASET_KEY
from apps.data_center.interface.admin import (
    DataOwnerRegistrationAdmin,
    DatasetContractAdmin,
    DatasetProviderBindingAdmin,
    DatasetPublicationPolicyAdmin,
)
from apps.data_center.models import (
    DataOwnerRegistrationModel,
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
)


@pytest.mark.parametrize(
    "admin_type,model",
    [
        (DatasetContractAdmin, DatasetContractModel),
        (DatasetProviderBindingAdmin, DatasetProviderBindingModel),
        (DatasetPublicationPolicyAdmin, DatasetPublicationPolicyModel),
        (DataOwnerRegistrationAdmin, DataOwnerRegistrationModel),
    ],
)
@pytest.mark.parametrize("calendar_object", [True, False])
def test_calendar_admin_denies_changes_without_changing_ordinary_permissions(
    admin_type: type[admin.ModelAdmin[models.Model]],
    model: type[models.Model],
    calendar_object: bool,
) -> None:
    """Even Django's superuser permission shortcut cannot grant calendar edits."""

    request = RequestFactory().post("/admin/calendar-catalog/change/", {"_save": "Save"})
    request.user = get_user_model()(
        pk=1,
        username="calendar-permission-unit",
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )
    obj = model(dataset_key=CALENDAR_DATASET_KEY if calendar_object else "fixture.ordinary.catalog")
    model_admin = admin_type(model, admin.AdminSite())

    assert model_admin.has_change_permission(request, obj) is (not calendar_object)
