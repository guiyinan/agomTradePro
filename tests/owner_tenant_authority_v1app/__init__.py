from django.apps import AppConfig


class OwnerTenantAuthorityV1TestConfig(AppConfig):
    """Load only the isolated owner/tenant authority v1 schema."""

    name = "tests.owner_tenant_authority_v1app"
    label = "account"


class DataCenterAuthorityTestConfig(AppConfig):
    """Register the data-center model label without booting its runtime graph."""

    name = "apps.data_center"
    label = "data_center"
    default_auto_field = "django.db.models.BigAutoField"

    def import_models(self) -> None:
        """Avoid importing unrelated data-center models in this isolated harness."""

        self.models = self.apps.all_models[self.label]
        self.models_module = None
