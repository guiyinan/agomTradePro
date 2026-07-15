"""Application composition root for controlled event replay."""

from django.conf import settings

from apps.events.application.replay_service import ReplayService
from apps.events.infrastructure.event_store import get_event_store
from apps.events.infrastructure.repositories import DjangoReplayRunRepository
from core.integration.event_replay import build_replay_target_registry


def build_replay_service() -> ReplayService:
    """Compose controlled replay from approved targets and concrete repositories."""

    return ReplayService(
        build_replay_target_registry(),
        get_event_store(),
        DjangoReplayRunRepository(),
        enabled=bool(settings.EVENT_REPLAY_ENABLED),
    )
