"""Composition root for the integrated QMT bridge."""

from apps.data_center.application.qmt_bridge import QmtBridgeService
from apps.data_center.infrastructure.qmt_bridge_repository import QmtBridgeRepository


def build_qmt_bridge_service() -> QmtBridgeService:
    """Wire bridge use cases to their Django persistence implementation."""
    return QmtBridgeService(QmtBridgeRepository())
