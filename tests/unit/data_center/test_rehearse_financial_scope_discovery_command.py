"""Tests for the isolated financial scope discovery management command."""

from pathlib import Path

import pytest
from django.core.management.base import CommandError

from apps.data_center.management.commands import rehearse_financial_scope_discovery


def test_blocked_discovery_preserves_report_without_capacity_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the source failure evidence and avoid deriving a success receipt."""
    report: dict[str, object] = {
        "result": {
            "outcome": "blocked",
            "error_codes": ["REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_PROVIDER_MISMATCH"],
        }
    }
    writes: list[str] = []
    builder_called = False

    def record_write(path: Path, payload: dict[str, object]) -> None:
        writes.append(path.name)

    def fail_if_called(**kwargs: object) -> dict[str, object]:
        nonlocal builder_called
        builder_called = True
        raise AssertionError("blocked source reports cannot produce a capacity receipt")

    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "_validate_inputs",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "_run_discovery",
        lambda **kwargs: report,
    )
    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "_write_exclusive_json",
        record_write,
    )
    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "build_financial_scope_capacity_receipt",
        fail_if_called,
    )

    with pytest.raises(
        CommandError,
        match="REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_PROVIDER_MISMATCH",
    ):
        rehearse_financial_scope_discovery.Command().handle(
            candidate_sha="a" * 40,
            target_trade_date="2026-10-09",
            release_universe_sha256="b" * 64,
            provider_identities=Path("provider-identities.json"),
            provider_identities_sha256="c" * 64,
            expected_database_name="isolated",
            expected_database_host="isolated",
            artifact_root=Path("artifacts"),
            output_dir=Path("output"),
        )

    assert writes == ["financial-scope-discovery.json"]
    assert not builder_called
