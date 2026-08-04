"""Data Center App Configuration."""

from django.apps import AppConfig


class DataCenterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.data_center"
    verbose_name = "Data Center"

    def ready(self) -> None:
        import apps.data_center.interface.admin  # noqa: F401
        from apps.data_center.application.config_summary_service import (
            configure_data_center_config_summary_repository,
        )
        from apps.data_center.application.read_facade import build_data_center_read_facade
        from apps.data_center.infrastructure.config_summary_repository import (
            DjangoDataCenterConfigSummaryRepository,
        )
        from core.integration.data_center_readiness import configure_data_center_read_port

        configure_data_center_read_port(build_data_center_read_facade())

        configure_data_center_config_summary_repository(DjangoDataCenterConfigSummaryRepository())
        from apps.data_center.application.pit_provider import configure_pit_providers

        from .infrastructure.pit_repository import (
            ManifestBoundPITDataView,
            PITManifestRepository,
        )

        def manifest_evidence(manifest_id: str):  # type: ignore[no-untyped-def]
            manifest = PITManifestRepository().get(manifest_id)
            if manifest is None:
                return None
            try:
                ManifestBoundPITDataView(manifest_id)
                verified = manifest.is_verified
            except ValueError:
                verified = False
            return {
                "manifest_id": manifest.manifest_id,
                "verified": verified,
                "coverage": dict(manifest.coverage),
            }

        configure_pit_providers(
            view_factory=ManifestBoundPITDataView,
            manifest_evidence_getter=manifest_evidence,
        )
        # Registry is lazily initialised on first request via get_registry().
        # Do NOT query the DB here — AppConfig.ready() runs before migrations
        # complete, which would raise RuntimeWarning and break fresh setups.
