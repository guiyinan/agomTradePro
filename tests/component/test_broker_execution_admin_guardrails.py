import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from apps.broker_execution.admin import (
    BrokerAccountAccessAdmin,
    BrokerAccountBindingAdmin,
    BrokerAgentAdmin,
    BrokerAgentCredentialAdmin,
    BrokerExecutionAlertAdmin,
    BrokerExecutionAuditAdmin,
    BrokerExecutionDailyReportAdmin,
    LiveOrderAdmin,
    ReconciliationDifferenceAdmin,
    ReconciliationRunAdmin,
    TradingControlAdmin,
)
from apps.broker_execution.infrastructure.models import (
    BrokerAccountAccessModel,
    BrokerAccountBindingModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    BrokerExecutionAlertModel,
    BrokerExecutionAuditModel,
    BrokerExecutionDailyReportModel,
    LiveOrderModel,
    ReconciliationDifferenceModel,
    ReconciliationRunModel,
    TradingControlModel,
)


@pytest.mark.django_db
def test_broker_execution_admin_registration_and_readonly_contracts():
    request = RequestFactory().get("/admin/broker-execution/")
    request.user = get_user_model().objects.create_superuser(
        username="broker_execution_admin",
        password="testpass123",
        email="broker-execution@example.com",
    )
    expected = {
        BrokerAgentModel: BrokerAgentAdmin,
        BrokerAccountBindingModel: BrokerAccountBindingAdmin,
        BrokerAccountAccessModel: BrokerAccountAccessAdmin,
        LiveOrderModel: LiveOrderAdmin,
        ReconciliationRunModel: ReconciliationRunAdmin,
        ReconciliationDifferenceModel: ReconciliationDifferenceAdmin,
        BrokerExecutionAlertModel: BrokerExecutionAlertAdmin,
        BrokerExecutionDailyReportModel: BrokerExecutionDailyReportAdmin,
        TradingControlModel: TradingControlAdmin,
        BrokerAgentCredentialModel: BrokerAgentCredentialAdmin,
        BrokerExecutionAuditModel: BrokerExecutionAuditAdmin,
    }

    for model, admin_type in expected.items():
        model_admin = admin.site._registry[model]
        assert isinstance(model_admin, admin_type)
        assert model_admin.has_add_permission(request) is False
        assert model_admin.has_change_permission(request) is False
        assert model_admin.has_delete_permission(request) is False
        assert set(model_admin.get_readonly_fields(request)) == {
            field.name for field in model._meta.fields
        }


@pytest.mark.django_db
def test_broker_binding_admin_keeps_raw_account_reference_hidden():
    request = RequestFactory().get("/admin/broker-execution/account-binding/")
    request.user = get_user_model().objects.create_superuser(
        username="broker_binding_admin",
        password="testpass123",
        email="broker-binding@example.com",
    )
    model_admin = admin.site._registry[BrokerAccountBindingModel]

    assert "broker_account_ref" in (model_admin.get_exclude(request) or ())
    assert "broker_account_ref" not in model_admin.list_display
    assert "broker_account_ref" not in model_admin.search_fields


@pytest.mark.django_db
def test_broker_credential_admin_does_not_publish_secret_hash_in_list_or_search():
    model_admin = admin.site._registry[BrokerAgentCredentialModel]

    assert "secret_hash" not in model_admin.list_display
    assert "secret_hash" not in model_admin.search_fields
