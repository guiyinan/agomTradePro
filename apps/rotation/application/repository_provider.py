"""Rotation repository providers for application consumers."""

from __future__ import annotations

from apps.rotation.infrastructure.providers import RotationInterfaceRepository
from apps.rotation.infrastructure.services import RotationIntegrationService


def get_rotation_interface_repository() -> RotationInterfaceRepository:
    """Return the default rotation interface repository."""

    return RotationInterfaceRepository()


def get_rotation_integration_service() -> RotationIntegrationService:
    """Return the default rotation integration service."""

    return RotationIntegrationService()


def generate_rotation_signals(signal_date) -> dict:
    """Generate rotation signals through the application-facing provider."""

    service = get_rotation_integration_service()
    configs = service.config_repo.get_active()
    results = {
        "signal_date": signal_date.isoformat(),
        "total_configs": len(configs),
        "successful": 0,
        "failed": 0,
        "signals": [],
    }

    for config in configs:
        signal = service.generate_rotation_signal(config.name, signal_date=signal_date)
        if signal:
            results["successful"] += 1
            results["signals"].append(signal)
        else:
            results["failed"] += 1
            results["signals"].append(
                {
                    "config_name": config.name,
                    "error": "Signal generation failed",
                }
            )

    return results


def resolve_rotation_asset_names(codes: list[str]) -> dict[str, str]:
    """Resolve active rotation asset names by asset code."""

    normalized_codes = [str(code).upper() for code in codes if code]
    if not normalized_codes:
        return {}

    code_to_base = {code: code.split(".")[0] for code in normalized_codes}
    asset_master = get_rotation_integration_service().get_asset_master(include_inactive=False)
    name_map = {
        str(item.get("code", "")).upper(): item.get("name", "")
        for item in asset_master
        if item.get("code") and item.get("name")
    }
    return {
        code: name_map[base_code.upper()]
        for code, base_code in code_to_base.items()
        if base_code.upper() in name_map
    }
