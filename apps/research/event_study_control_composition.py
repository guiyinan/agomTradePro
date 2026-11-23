"""Composition root for the existing Research registry's event-study controls."""

from collections.abc import Callable
from functools import partial
from pathlib import Path

from apps.research.application.calendar_validation import (
    FinalCalendarEvaluator,
    FinalCalendarInputs,
)
from apps.research.application.event_study_control import EventStudyControl
from apps.research.domain.event_study_control import FinalOOSClaim
from apps.research.infrastructure.calendar_final_report import publish_final_calendar_report
from apps.research.infrastructure.event_study_control_repository import DjangoEventStudyRegistry
from apps.research.infrastructure.validation_ridge import ridge_predict


def build_event_study_control() -> EventStudyControl:
    """Build the durable registry extension without involving production providers."""
    return EventStudyControl(DjangoEventStudyRegistry())


def build_final_calendar_evaluator(
    read_verified_inputs: Callable[[FinalOOSClaim], FinalCalendarInputs], output_directory: Path
) -> FinalCalendarEvaluator:
    """Assemble the registered reader, training-only ridge estimator and receipt-keyed writer."""
    return FinalCalendarEvaluator(
        read_verified_inputs,
        partial(publish_final_calendar_report, output_directory),
        ridge_predict,
    )
