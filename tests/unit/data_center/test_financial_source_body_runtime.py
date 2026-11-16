"""Pure contracts for Config Center backed, lazy statutory body storage."""

from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from django.core.management.base import CommandError

from apps.data_center import financial_availability_owner_api_composition as owner_module
from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilitySourceRead,
    FinancialAvailabilitySourceReaderPort,
)
from apps.data_center.application.statutory_source_documents import (
    StatutorySourceDocumentBodyStorePort,
)
from apps.data_center.domain.statutory_source_documents import StatutorySourceBodyReference
from apps.data_center.infrastructure import financial_source_body_runtime as runtime_module
from apps.data_center.management.commands.initialize_statutory_source_body_storage import (
    Command as InitializeSourceBodyStorageCommand,
)
from apps.data_center.management.commands.manage_financial_numeric_catalog import (
    Command as ManageFinancialNumericCatalogCommand,
)
from core.exceptions import DataValidationError


class _ValueReader:
    """Return explicit active-value fixtures and record requested keys."""

    def __init__(self, values: dict[str, object | None]) -> None:
        self.values = values
        self.calls: list[str] = []

    def __call__(self, definition_key: str) -> object | None:
        self.calls.append(definition_key)
        return self.values.get(definition_key)


class _BodyStore:
    """Keep exact body operations in memory for lazy-composition tests."""

    def __init__(self, reference: StatutorySourceBodyReference, body: bytes) -> None:
        self.reference = reference
        self.body = body

    def store(self, capture_id: UUID, body: bytes) -> StatutorySourceBodyReference:
        assert capture_id == self.reference.capture_id
        assert body == self.body
        return self.reference

    def read(self, reference: StatutorySourceBodyReference) -> bytes:
        assert reference == self.reference
        return self.body


class _SourceReader:
    """Record when the C2 source-reader factory is actually exercised."""

    def __init__(self, database_alias: str) -> None:
        self.database_alias = database_alias
        self.calls = 0

    def read_exact_capture(
        self,
        *,
        issuer: str,
        document_id: str,
        source_version: str,
        capture_id: UUID,
        known_at: datetime,
    ) -> FinancialAvailabilitySourceRead | None:
        self.calls += 1
        assert issuer and document_id and source_version
        assert type(capture_id) is UUID
        assert type(known_at) is datetime
        return None


def _valid_runtime_values(root: Path) -> dict[str, object | None]:
    """Build only explicit values; no fixture is used as an operational default."""

    return {
        runtime_module.STATUTORY_SOURCE_BODY_ROOT_KEY: str(root),
        runtime_module.STATUTORY_SOURCE_BODY_MAX_BYTES_KEY: 8192,
    }


def test_definitions_register_one_shared_explicit_storage_contract() -> None:
    definitions = runtime_module.statutory_source_body_storage_definitions()

    assert tuple(definition.key for definition in definitions) == (
        runtime_module.STATUTORY_SOURCE_BODY_ROOT_KEY,
        runtime_module.STATUTORY_SOURCE_BODY_MAX_BYTES_KEY,
    )
    assert tuple(definition.value_type for definition in definitions) == ("string", "bytes")
    assert all(definition.owner_app == "data_center" for definition in definitions)
    assert all(definition.reload_mode == "restart_required" for definition in definitions)
    assert definitions[1].minimum == 1
    assert "no path is seeded" in definitions[0].description.lower()
    assert "no size is seeded" in definitions[1].description.lower()


def test_runtime_config_reads_exact_keys_and_does_not_create_root(tmp_path: Path) -> None:
    root = tmp_path / "private-body-store"
    reader = _ValueReader(_valid_runtime_values(root))

    config = runtime_module.resolve_statutory_source_body_storage_config(
        runtime_value_reader=reader
    )

    assert config.root == root
    assert config.max_body_bytes == 8192
    assert reader.calls == [
        runtime_module.STATUTORY_SOURCE_BODY_ROOT_KEY,
        runtime_module.STATUTORY_SOURCE_BODY_MAX_BYTES_KEY,
    ]
    assert not root.exists()


@pytest.mark.parametrize(
    ("missing_key",),
    (
        (runtime_module.STATUTORY_SOURCE_BODY_ROOT_KEY,),
        (runtime_module.STATUTORY_SOURCE_BODY_MAX_BYTES_KEY,),
    ),
)
def test_missing_active_value_blocks_without_fallback(
    tmp_path: Path,
    missing_key: str,
) -> None:
    values = _valid_runtime_values(tmp_path / "private-body-store")
    values.pop(missing_key)
    reader = _ValueReader(values)

    with pytest.raises(DataValidationError) as captured:
        runtime_module.resolve_statutory_source_body_storage_config(runtime_value_reader=reader)

    assert captured.value.code == "STATUTORY_SOURCE_BODY_CONFIG_INVALID"
    assert not (tmp_path / "private-body-store").exists()


def test_operator_activation_requires_explicit_values_without_creating_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-body-store"
    patch, environment, actor, reason = InitializeSourceBodyStorageCommand._activation_input(
        {
            "environment": "development",
            "actor": "operator",
            "reason": "explicit runtime storage configuration",
            "root": str(root),
            "max_body_bytes": 8192,
        }
    )

    assert environment == "development"
    assert actor == "operator"
    assert reason == "explicit runtime storage configuration"
    assert patch == {
        runtime_module.STATUTORY_SOURCE_BODY_ROOT_KEY: str(root),
        runtime_module.STATUTORY_SOURCE_BODY_MAX_BYTES_KEY: 8192,
    }
    assert not root.exists()

    with pytest.raises(CommandError):
        InitializeSourceBodyStorageCommand._activation_input(
            {
                "environment": "development",
                "actor": "operator",
                "reason": "missing body limit",
                "root": str(root),
                "max_body_bytes": None,
            }
        )


def test_numeric_catalog_command_builds_service_without_loading_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body_store_calls: list[bool] = []

    def _body_store_must_be_lazy() -> StatutorySourceDocumentBodyStorePort:
        body_store_calls.append(True)
        raise AssertionError("command service construction must not initialize source storage")

    monkeypatch.setattr(
        runtime_module,
        "build_statutory_source_body_store",
        _body_store_must_be_lazy,
    )

    service = ManageFinancialNumericCatalogCommand._service("default")

    assert service is not None
    assert body_store_calls == []


@pytest.mark.parametrize(
    ("root_value", "maximum"),
    (
        ("", 16),
        (" relative/body-store ", 16),
        ("relative/body-store", 16),
        (Path("relative-body-store"), 16),
        ("/private/body-store\n", 16),
        ("/private/body-store\x7f", 16),
        ("/private/body-store", True),
        ("/private/body-store", 0),
        ("/private/body-store", -1),
        ("/private/body-store", 1.0),
        ("/private/body-store", sys.maxsize),
    ),
)
def test_invalid_root_or_size_fails_closed(root_value: object, maximum: object) -> None:
    with pytest.raises(DataValidationError) as captured:
        runtime_module.parse_statutory_source_body_storage_config(root_value, maximum)

    assert captured.value.code == "STATUTORY_SOURCE_BODY_CONFIG_INVALID"


def test_lazy_body_store_does_not_load_settings_until_first_body_operation() -> None:
    capture_id = UUID("d01a89a1-c0d0-4fce-830c-50e076f0c219")
    body = b"exact-source-body"
    reference = StatutorySourceBodyReference(
        capture_id=capture_id,
        reference=f"statutory-source-body:///v1/{capture_id}.body",
        body_sha256=hashlib.sha256(body).hexdigest(),
        body_size_bytes=len(body),
    )
    store = _BodyStore(reference, body)
    factory_calls: list[bool] = []

    def make_store() -> StatutorySourceDocumentBodyStorePort:
        factory_calls.append(True)
        return cast(StatutorySourceDocumentBodyStorePort, store)

    lazy = runtime_module.LazyStatutorySourceBodyStore(store_factory=make_store)
    assert factory_calls == []

    assert lazy.read(reference) == body
    assert lazy.store(capture_id, body) == reference
    assert factory_calls == [True]


def test_lazy_owner_reader_does_not_build_source_reader_until_read() -> None:
    source_reader = _SourceReader("default")
    factory_calls: list[bool] = []

    def make_reader() -> FinancialAvailabilitySourceReaderPort:
        factory_calls.append(True)
        return cast(FinancialAvailabilitySourceReaderPort, source_reader)

    lazy = runtime_module.LazyFinancialAvailabilitySourceReader(
        using="default",
        reader_factory=make_reader,
    )
    assert lazy.database_alias == "default"
    assert factory_calls == []

    assert (
        lazy.read_exact_capture(
            issuer="issuer",
            document_id="document",
            source_version="version",
            capture_id=UUID("1f0e9de1-606f-472a-a8fc-5d202b2196bf"),
            known_at=datetime(2026, 11, 16, tzinfo=UTC),
        )
        is None
    )
    assert factory_calls == [True]
    assert source_reader.calls == 1


def test_lazy_owner_reader_rejects_factory_alias_drift() -> None:
    lazy = runtime_module.LazyFinancialAvailabilitySourceReader(
        using="default",
        reader_factory=lambda: cast(
            FinancialAvailabilitySourceReaderPort, _SourceReader("archive")
        ),
    )

    with pytest.raises(DataValidationError) as captured:
        lazy.read_exact_capture(
            issuer="issuer",
            document_id="document",
            source_version="version",
            capture_id=UUID("1f0e9de1-606f-472a-a8fc-5d202b2196bf"),
            known_at=datetime(2026, 11, 16, tzinfo=UTC),
        )

    assert captured.value.code == "FIN_AVAILABILITY_ALIAS_MISMATCH"


def test_owner_repository_composition_does_not_load_runtime_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body_store_calls: list[bool] = []

    class _Records:
        database_alias = "default"

    class _OwnerEvents:
        def __init__(self, *, using: str, source_reader: object) -> None:
            self.database_alias = using
            self.source_reader = source_reader

    def _body_store_must_be_lazy() -> StatutorySourceDocumentBodyStorePort:
        body_store_calls.append(True)
        raise AssertionError("source body store must wait until an exact opening-rule read")

    monkeypatch.setattr(
        owner_module,
        "DjangoFinancialAvailabilityGovernanceRepository",
        lambda *, using: _Records(),
    )
    monkeypatch.setattr(
        owner_module,
        "DjangoFinancialAvailabilityOwnerEventRepository",
        _OwnerEvents,
    )
    monkeypatch.setattr(owner_module, "build_statutory_source_body_store", _body_store_must_be_lazy)

    records, owner_events = owner_module._build_owner_repositories()

    assert records.database_alias == "default"
    assert owner_events.database_alias == "default"
    assert owner_events.source_reader.database_alias == "default"
    assert body_store_calls == []
