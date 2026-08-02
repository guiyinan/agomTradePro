"""Application ports for raw payload landing and schema observation."""

from __future__ import annotations

from typing import Protocol

from apps.data_center.domain.raw_landing import RawPayload, SchemaFingerprint


class RawLandingRepositoryPort(Protocol):
    """Persistence port for redacted raw payloads."""

    def save(self, payload: RawPayload) -> RawPayload: ...

    def get_by_hash(self, payload_hash: str) -> RawPayload | None: ...


class SchemaFingerprintRepositoryPort(Protocol):
    """Persistence port for provider schema signatures."""

    def observe(self, fingerprint: SchemaFingerprint) -> SchemaFingerprint: ...


class LandRawPayloadUseCase:
    """Persist a provider response only after redaction/hash validation."""

    def __init__(self, repository: RawLandingRepositoryPort) -> None:
        self._repository = repository

    def execute(self, payload: RawPayload) -> RawPayload:
        """Land a payload in the raw layer."""

        return self._repository.save(payload)


class ObserveSchemaFingerprintUseCase:
    """Record schema evolution evidence."""

    def __init__(self, repository: SchemaFingerprintRepositoryPort) -> None:
        self._repository = repository

    def execute(self, fingerprint: SchemaFingerprint) -> SchemaFingerprint:
        """Observe one provider schema signature."""

        return self._repository.observe(fingerprint)


__all__ = [
    "LandRawPayloadUseCase",
    "ObserveSchemaFingerprintUseCase",
    "RawLandingRepositoryPort",
    "SchemaFingerprintRepositoryPort",
]
