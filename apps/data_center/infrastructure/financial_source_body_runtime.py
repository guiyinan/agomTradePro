"""Resolve Config Center storage settings for retained statutory source bodies.

This module reads only the active typed Config Center values. It supplies no
filesystem path, body-size ceiling, or TTL defaults. Resolving settings does not
create a directory; the store is constructed only when a capture or exact body
read actually needs it.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilitySourceRead,
    FinancialAvailabilitySourceReaderPort,
)
from apps.data_center.application.statutory_source_documents import (
    StatutorySourceDocumentBodyStorePort,
)
from apps.data_center.domain.statutory_source_documents import StatutorySourceBodyReference
from core.exceptions import DataValidationError
from core.integration.config_center_runtime import RuntimeConfigDefinitionSpec
from core.integration.runtime_settings import get_runtime_config_value

STATUTORY_SOURCE_BODY_ROOT_KEY = "data_center.statutory_source_body.root"
STATUTORY_SOURCE_BODY_MAX_BYTES_KEY = "data_center.statutory_source_body.max_body_bytes"

_CONFIG_ERROR = "STATUTORY_SOURCE_BODY_CONFIG_INVALID"


class RuntimeConfigValueReader(Protocol):
    """Read one active Config Center value through the existing Core bridge."""

    def __call__(self, definition_key: str) -> object | None:
        """Return a typed value or ``None`` when it is unavailable."""


class StatutorySourceBodyStoreFactory(Protocol):
    """Construct the shared retained-body store only when a body is needed."""

    def __call__(self) -> StatutorySourceDocumentBodyStorePort:
        """Return a store backed by the current explicit runtime configuration."""


class FinancialAvailabilitySourceReaderFactory(Protocol):
    """Construct the C2 source reader when an opening rule requires it."""

    def __call__(self) -> FinancialAvailabilitySourceReaderPort:
        """Return a reader bound to one explicit database alias."""


@dataclass(frozen=True, slots=True)
class StatutorySourceBodyStorageRuntimeConfig:
    """Validated root and maximum body size from one active runtime profile."""

    root: Path
    max_body_bytes: int

    def __post_init__(self) -> None:
        """Reject implicit, relative, or unrepresentable storage settings."""

        if not isinstance(self.root, Path) or not self.root.is_absolute():
            raise ValueError("root must be an explicit absolute Path")
        if type(self.max_body_bytes) is not int or not 0 < self.max_body_bytes < sys.maxsize:
            raise ValueError("max_body_bytes must be an explicit positive bounded integer")


def statutory_source_body_storage_definitions() -> tuple[RuntimeConfigDefinitionSpec, ...]:
    """Return explicit Config Center definitions without operational defaults."""

    return (
        RuntimeConfigDefinitionSpec(
            key=STATUTORY_SOURCE_BODY_ROOT_KEY,
            namespace="data_center.statutory_source_body",
            owner_app="data_center",
            value_type="string",
            criticality="critical",
            reload_mode="restart_required",
            description=(
                "Explicit absolute private root shared by retained statutory and "
                "financial numeric source bodies. No path is seeded by this definition."
            ),
        ),
        RuntimeConfigDefinitionSpec(
            key=STATUTORY_SOURCE_BODY_MAX_BYTES_KEY,
            namespace="data_center.statutory_source_body",
            owner_app="data_center",
            value_type="bytes",
            criticality="critical",
            reload_mode="restart_required",
            minimum=1,
            description=(
                "Explicit maximum retained public-source body size in bytes. "
                "No size is seeded by this definition."
            ),
        ),
    )


def parse_statutory_source_body_storage_config(
    root_value: object,
    max_body_bytes_value: object,
) -> StatutorySourceBodyStorageRuntimeConfig:
    """Narrow two active values without creating or inspecting the filesystem."""

    if (
        type(root_value) is not str
        or not root_value
        or root_value != root_value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in root_value)
        or not Path(root_value).is_absolute()
    ):
        raise DataValidationError(
            "Retained source body root is missing or invalid.", code=_CONFIG_ERROR
        )
    if type(max_body_bytes_value) is not int or not 0 < max_body_bytes_value < sys.maxsize:
        raise DataValidationError(
            "Retained source body maximum size is missing or invalid.", code=_CONFIG_ERROR
        )
    try:
        return StatutorySourceBodyStorageRuntimeConfig(
            root=Path(root_value),
            max_body_bytes=max_body_bytes_value,
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise DataValidationError(
            "Retained source body storage configuration is invalid.", code=_CONFIG_ERROR
        ) from error


def resolve_statutory_source_body_storage_config(
    *,
    runtime_value_reader: RuntimeConfigValueReader | None = None,
) -> StatutorySourceBodyStorageRuntimeConfig:
    """Read and validate both values through the active Config Center profile.

    The optional reader is a test/composition seam; production defaults to the
    existing Core runtime-settings bridge. A missing value blocks without
    falling back to Django settings, environment variables, or a local path.
    """

    reader = get_runtime_config_value if runtime_value_reader is None else runtime_value_reader
    root_value = reader(STATUTORY_SOURCE_BODY_ROOT_KEY)
    max_body_bytes_value = reader(STATUTORY_SOURCE_BODY_MAX_BYTES_KEY)
    return parse_statutory_source_body_storage_config(root_value, max_body_bytes_value)


def build_statutory_source_body_store(
    *,
    runtime_config: StatutorySourceBodyStorageRuntimeConfig | None = None,
    runtime_value_reader: RuntimeConfigValueReader | None = None,
) -> StatutorySourceDocumentBodyStorePort:
    """Construct the shared Statutory body store from explicit runtime values."""

    config = (
        resolve_statutory_source_body_storage_config(runtime_value_reader=runtime_value_reader)
        if runtime_config is None
        else runtime_config
    )
    if type(config) is not StatutorySourceBodyStorageRuntimeConfig:
        raise DataValidationError(
            "Retained source body storage configuration is invalid.", code=_CONFIG_ERROR
        )
    from apps.data_center.infrastructure.statutory_source_body_store import (
        StatutorySourceBodyStore,
    )

    return StatutorySourceBodyStore(config.root, max_body_bytes=config.max_body_bytes)


class LazyStatutorySourceBodyStore(StatutorySourceDocumentBodyStorePort):
    """Defer runtime lookup and directory creation until store/read is requested."""

    def __init__(self, *, store_factory: StatutorySourceBodyStoreFactory | None = None) -> None:
        """Bind an optional test factory without resolving runtime settings."""

        self._store_factory = store_factory or build_statutory_source_body_store
        self._store: StatutorySourceDocumentBodyStorePort | None = None

    def _get_store(self) -> StatutorySourceDocumentBodyStorePort:
        """Resolve the private store once, on the first actual body operation."""

        if self._store is None:
            store = self._store_factory()
            if store is None:
                raise DataValidationError(
                    "Retained source body store is unavailable.", code=_CONFIG_ERROR
                )
            self._store = store
        return self._store

    def store(self, capture_id: UUID, body: bytes) -> StatutorySourceBodyReference:
        """Persist exact body bytes after resolving the active store settings."""

        return self._get_store().store(capture_id, body)

    def read(self, reference: StatutorySourceBodyReference) -> bytes:
        """Read and verify exact bytes after resolving the active store settings."""

        return self._get_store().read(reference)


class LazyFinancialAvailabilitySourceReader(FinancialAvailabilitySourceReaderPort):
    """Defer C2 source reader and body-store construction until an exact read."""

    def __init__(
        self,
        *,
        using: str,
        reader_factory: FinancialAvailabilitySourceReaderFactory,
    ) -> None:
        """Bind an alias and factory without loading runtime settings or files."""

        if type(using) is not str or not using or using.strip() != using:
            raise DataValidationError(
                "C2 source reader requires one explicit database alias.",
                code="FIN_AVAILABILITY_ALIAS_MISMATCH",
            )
        if not callable(reader_factory):
            raise DataValidationError(
                "C2 source reader factory is unavailable.", code=_CONFIG_ERROR
            )
        self._using = using
        self._reader_factory = reader_factory
        self._reader: FinancialAvailabilitySourceReaderPort | None = None

    @property
    def database_alias(self) -> str:
        """Return the bound alias without resolving storage settings."""

        return self._using

    def read_exact_capture(
        self,
        *,
        issuer: str,
        document_id: str,
        source_version: str,
        capture_id: UUID,
        known_at: datetime,
    ) -> FinancialAvailabilitySourceRead | None:
        """Build the source reader only for a real exact retained-source read."""

        return self._get_reader().read_exact_capture(
            issuer=issuer,
            document_id=document_id,
            source_version=source_version,
            capture_id=capture_id,
            known_at=known_at,
        )

    def _get_reader(self) -> FinancialAvailabilitySourceReaderPort:
        """Construct and cache one reader, rejecting a mismatched database alias."""

        if self._reader is None:
            reader = self._reader_factory()
            if (
                type(getattr(reader, "database_alias", None)) is not str
                or reader.database_alias != self._using
                or not callable(getattr(reader, "read_exact_capture", None))
            ):
                raise DataValidationError(
                    "C2 source reader uses a different database alias.",
                    code="FIN_AVAILABILITY_ALIAS_MISMATCH",
                )
            self._reader = reader
        return self._reader


__all__ = [
    "FinancialAvailabilitySourceReaderFactory",
    "LazyFinancialAvailabilitySourceReader",
    "LazyStatutorySourceBodyStore",
    "STATUTORY_SOURCE_BODY_MAX_BYTES_KEY",
    "STATUTORY_SOURCE_BODY_ROOT_KEY",
    "StatutorySourceBodyStorageRuntimeConfig",
    "build_statutory_source_body_store",
    "parse_statutory_source_body_storage_config",
    "resolve_statutory_source_body_storage_config",
    "statutory_source_body_storage_definitions",
]
