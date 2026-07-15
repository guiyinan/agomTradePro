"""Django deploy checks for Alpha Trigger runtime wiring."""

from typing import Any

from django.core.checks import Error, Tags, register

from .application.handlers import AlphaTriggerEventHandler
from .application.subscribers import _create_alpha_trigger_handler


@register(Tags.models, deploy=True)
def check_alpha_trigger_subscriber_wiring(
    app_configs: Any,
    **kwargs: Any,
) -> list[Error]:
    """Require the critical Alpha Trigger subscriber factory to be constructible."""

    try:
        handler = _create_alpha_trigger_handler()
    except Exception as exc:
        return [
            Error(
                f"Alpha Trigger subscriber wiring is invalid: {exc}",
                hint=(
                    "Verify the trigger repository provider and "
                    "CreateAlphaTriggerUseCase composition."
                ),
                id="alpha_trigger.E001",
            )
        ]

    if not isinstance(handler, AlphaTriggerEventHandler):
        return [
            Error(
                "Alpha Trigger subscriber factory returned an unexpected handler.",
                hint="Return AlphaTriggerEventHandler from the registered factory.",
                id="alpha_trigger.E001",
            )
        ]
    return []
