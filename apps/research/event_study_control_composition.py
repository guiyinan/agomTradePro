"""Composition root for the existing Research registry's event-study controls."""

from apps.research.application.event_study_control import EventStudyControl
from apps.research.infrastructure.event_study_control_repository import DjangoEventStudyRegistry


def build_event_study_control() -> EventStudyControl:
    """Build the durable registry extension without involving production providers."""
    return EventStudyControl(DjangoEventStudyRegistry())
