from __future__ import annotations

import pytest

from apps.account.infrastructure import account_authority_generation as generation
from apps.account.infrastructure.account_authority_generation_errors import (
    AccountAuthorityGenerationChanged,
    AccountAuthorityGenerationCoverageError,
    AccountAuthorityGenerationUnavailable,
)


def test_runtime_acl_wrapper_preserves_legacy_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = object()
    source_tables = ("account_source",)
    captured: dict[str, object] = {}

    monkeypatch.setattr(generation, "_connection", lambda using: connection)
    monkeypatch.setattr(generation, "_runtime_source_tables", lambda: source_tables)

    def verify_contract(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(
        generation,
        "verify_account_authority_generation_runtime_acl_contract",
        verify_contract,
    )

    generation.verify_account_authority_generation_runtime_acl(using="authority")

    assert captured == {
        "connection": connection,
        "source_tables": source_tables,
        "lock_function_name": "account_authority_generation_lock",
        "function_search_path": "search_path=pg_catalog",
        "lock_function_search_path": "search_path=pg_catalog",
    }
    assert generation.AccountAuthorityGenerationUnavailable is (
        AccountAuthorityGenerationUnavailable
    )
    assert generation.AccountAuthorityGenerationCoverageError is (
        AccountAuthorityGenerationCoverageError
    )
    assert generation.AccountAuthorityGenerationChanged is AccountAuthorityGenerationChanged
