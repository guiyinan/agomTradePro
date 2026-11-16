"""No-database adapter boundary checks for alias and v3 storage-kind enforcement."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.data_center.domain.financial_next_session_witness import (
    FinancialOfficialSourceIdentity,
)
from apps.data_center.infrastructure.financial_statutory_numeric_capture_adapter import (
    DjangoFinancialStatutoryNumericCaptureAdapter,
)
from core.exceptions import DataValidationError


class _Reader:
    """Minimal repository port stub that fails if an invalid adapter call reads data."""

    def __init__(self, alias: str) -> None:
        """Bind one test-only alias."""

        self._alias = alias

    @property
    def database_alias(self) -> str:
        """Return the test alias."""

        return self._alias

    def read_exact_capture(self, **kwargs: object) -> None:
        """Prove invalid selectors stop before storage access."""

        raise AssertionError("unexpected Statutory Source read")


class _NumericCaptureRepository:
    """Minimal alias-bearing 0116 port stub for preflight checks."""

    def __init__(self, alias: str) -> None:
        """Bind one test-only alias."""

        self._alias = alias

    @property
    def database_alias(self) -> str:
        """Return the test alias."""

        return self._alias


def test_repository_alias_mismatch_blocks_at_construction() -> None:
    """The adapter cannot combine source and numeric rows from different databases."""

    with pytest.raises(DataValidationError) as caught:
        DjangoFinancialStatutoryNumericCaptureAdapter(
            statutory_reader=_Reader("source_db"),
            numeric_capture_repository=_NumericCaptureRepository("default"),
            using="default",
        )

    assert caught.value.code == "FINANCIAL_DUAL_CAPTURE_ALIAS_MISMATCH"


def test_legacy_encrypted_identity_blocks_before_database_access() -> None:
    """The Statutory Source verifier never infers or verifies encryption claims."""

    adapter = DjangoFinancialStatutoryNumericCaptureAdapter(
        statutory_reader=_Reader("default"),
        numeric_capture_repository=_NumericCaptureRepository("default"),
        using="default",
    )
    legacy_identity = object.__new__(FinancialOfficialSourceIdentity)

    with pytest.raises(DataValidationError) as caught:
        adapter.read_as_of(
            legacy_identity,
            known_at=datetime(2026, 11, 16, 0, 0, tzinfo=UTC),
        )

    assert caught.value.code == "FINANCIAL_STATUTORY_IDENTITY_UNSUPPORTED"
