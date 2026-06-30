"""Application-level query helpers for cross-app rotation access."""

from __future__ import annotations

from typing import Any

from apps.rotation.application.repository_provider import get_rotation_asset_class_repository


def list_asset_master_rotation_candidate_codes() -> list[str]:
    """Return rotation-domain codes that can seed data-center asset master rows."""

    return get_rotation_asset_class_repository().list_asset_master_candidate_codes()


def list_asset_master_rotation_rows(base_codes: list[str]) -> list[dict[str, Any]]:
    """Return local rotation rows for data-center asset master backfill."""

    return get_rotation_asset_class_repository().list_asset_master_rows(base_codes)
