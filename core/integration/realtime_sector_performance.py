"""Composition root for the realtime sector-performance projection."""

from typing import Any

from apps.realtime.application.query_services import list_sector_performance_payloads
from apps.sector.application.repository_provider import get_sector_repository


def list_realtime_sector_performance_payloads() -> list[dict[str, Any]]:
    """Compose the realtime query with the sector-owned repository."""

    return list_sector_performance_payloads(get_sector_repository())
