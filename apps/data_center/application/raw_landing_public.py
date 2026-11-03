"""Generic application access to retained immutable provider payloads."""

from __future__ import annotations

import re
from collections.abc import Callable

from apps.data_center.application.raw_landing import (
    LandRawPayloadUseCase,
    RawLandingRepositoryPort,
)
from apps.data_center.domain.raw_landing import RawPayload

_repository_factory: Callable[[], RawLandingRepositoryPort] | None = None
_writer_factory: Callable[[], RawLandingRepositoryPort] | None = None


class RawPayloadLandingNotConfigured(RuntimeError):
    """Raised when an application requests RawPayload admission before ready."""


def configure_raw_landing_reader(factory: Callable[[], RawLandingRepositoryPort]) -> None:
    """Register the owning composition root's lazy retained-payload reader."""

    global _repository_factory
    _repository_factory = factory


def configure_raw_landing_writer(factory: Callable[[], RawLandingRepositoryPort]) -> None:
    """Register the owning Data Center composition's lazy RawPayload writer."""

    global _writer_factory
    _writer_factory = factory


def land_raw_payload(payload: RawPayload) -> RawPayload:
    """Persist one immutable RawPayload through the owning application use case."""

    if type(payload) is not RawPayload:
        raise TypeError("payload must be a RawPayload")
    if _writer_factory is None:
        raise RawPayloadLandingNotConfigured("RawPayload writer is not configured")
    return LandRawPayloadUseCase(_writer_factory()).execute(payload)


def get_retained_raw_payload(*, payload_hash: str) -> RawPayload | None:
    """Read an exact retained payload without fetching or creating provider data."""

    if re.fullmatch(r"sha256:[0-9a-f]{64}", payload_hash) is None:
        raise ValueError("payload_hash must identify exact SHA-256 content")
    if _repository_factory is None:
        return None
    return _repository_factory().get_by_hash(payload_hash)


__all__ = (
    "RawPayloadLandingNotConfigured",
    "configure_raw_landing_reader",
    "configure_raw_landing_writer",
    "get_retained_raw_payload",
    "land_raw_payload",
)
