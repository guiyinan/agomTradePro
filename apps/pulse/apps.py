from django.apps import AppConfig


class PulseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pulse"
    verbose_name = "Pulse 脉搏层"

    def ready(self) -> None:
        """Register Pulse-owned integration providers."""

        from apps.pulse.application.data_center_gateway import (
            register_pulse_data_center_runtime,
        )

        register_pulse_data_center_runtime()
