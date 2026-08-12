"""App-neutral bridge for Config Center-owned secret storage."""

from __future__ import annotations

from typing import Protocol


class ConfigSecretStorePort(Protocol):
    """Minimal secret operations exposed to infrastructure consumers."""

    def config_secret_present(self, secret_ref: str) -> bool: ...

    def persist_config_secret(self, secret_ref: str, value: str | None) -> bool: ...

    def resolve_config_secret(self, secret_ref: str) -> str: ...


_provider: ConfigSecretStorePort | None = None


def configure_config_secret_store(provider: ConfigSecretStorePort) -> None:
    """Register the Config Center-owned secret facade."""

    global _provider
    _provider = provider


def config_secret_present(secret_ref: str) -> bool:
    """Return secret presence, failing closed before owner registration."""

    return False if _provider is None else bool(_provider.config_secret_present(secret_ref))


def persist_config_secret(secret_ref: str, value: str | None) -> bool:
    """Persist one secret through the configured owner facade."""

    if _provider is None:
        raise RuntimeError("config_secret_store_unconfigured")
    return bool(_provider.persist_config_secret(secret_ref, value))


def resolve_config_secret(secret_ref: str) -> str:
    """Resolve one secret through the configured owner facade."""

    if _provider is None:
        raise RuntimeError("config_secret_store_unconfigured")
    return _provider.resolve_config_secret(secret_ref)


__all__ = [
    "ConfigSecretStorePort",
    "config_secret_present",
    "configure_config_secret_store",
    "persist_config_secret",
    "resolve_config_secret",
]
