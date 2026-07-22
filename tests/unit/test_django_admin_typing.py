from django.contrib import admin

from apps.simulated_trading.models import FeeConfigModel
from shared.infrastructure.django_admin import TypedModelAdmin, TypedModelForm


class _TypedFeeAdmin(TypedModelAdmin[FeeConfigModel]):
    pass


class _TypedFeeForm(TypedModelForm[FeeConfigModel]):
    class Meta:
        model = FeeConfigModel
        fields = ("config_name",)


def test_typed_model_admin_is_runtime_subscriptable() -> None:
    """The shared generic base must not require django-stubs in production."""

    instance = _TypedFeeAdmin(FeeConfigModel, admin.site)

    assert isinstance(instance, admin.ModelAdmin)


def test_typed_model_form_is_runtime_subscriptable() -> None:
    """The shared ModelForm base must also remain safe in production imports."""

    assert _TypedFeeForm().fields["config_name"].required
