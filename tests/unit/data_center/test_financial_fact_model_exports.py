"""Contract tests for the public FinancialFactModel import path."""

from django.apps import apps as django_apps

from apps.data_center import models as public_models
from apps.data_center.infrastructure import financial_fact_models
from apps.data_center.infrastructure import models as infrastructure_models


def test_infrastructure_models_reexports_registered_financial_fact_model() -> None:
    """Keep the model identity and Django registration stable across extraction."""

    model = financial_fact_models.FinancialFactModel

    assert infrastructure_models.FinancialFactModel is model
    assert public_models.FinancialFactModel is model
    assert django_apps.get_model("data_center", "FinancialFactModel") is model
    assert model._meta.app_label == "data_center"
    assert model._meta.model_name == "financialfactmodel"
    assert model._meta.db_table == "data_center_financial_fact"
