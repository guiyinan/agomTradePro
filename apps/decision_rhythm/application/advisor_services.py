"""Compatibility exports for the split auto-advisor application services."""

from apps.decision_rhythm.application import advisor_contracts as _advisor_contracts
from apps.decision_rhythm.application import advisor_execution as _advisor_execution
from apps.decision_rhythm.application import advisor_intents as _advisor_intents
from apps.decision_rhythm.application import advisor_performance as _advisor_performance
from apps.decision_rhythm.application import advisor_providers as _advisor_providers
from apps.decision_rhythm.application import advisor_serialization as _advisor_serialization
from apps.decision_rhythm.application import advisor_sheet as _advisor_sheet
from apps.decision_rhythm.application.advisor_contracts import *  # noqa: F403
from apps.decision_rhythm.application.advisor_execution import *  # noqa: F403
from apps.decision_rhythm.application.advisor_intents import *  # noqa: F403
from apps.decision_rhythm.application.advisor_performance import *  # noqa: F403
from apps.decision_rhythm.application.advisor_providers import *  # noqa: F403
from apps.decision_rhythm.application.advisor_serialization import *  # noqa: F403
from apps.decision_rhythm.application.advisor_sheet import *  # noqa: F403

__all__ = [
    *_advisor_serialization.__all__,
    *_advisor_contracts.__all__,
    *_advisor_intents.__all__,
    *_advisor_execution.__all__,
    *_advisor_performance.__all__,
    *_advisor_providers.__all__,
    *_advisor_sheet.__all__,
]
