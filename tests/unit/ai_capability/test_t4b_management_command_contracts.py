"""AI capability catalog command contracts for dry-run, apply, and failure summaries."""

from io import StringIO
from types import SimpleNamespace

import pytest

from apps.ai_capability.application.dtos import SyncResultDTO
from apps.ai_capability.application.governance_services import CapabilityGovernanceResult
from apps.ai_capability.management.commands import (
    govern_ai_capability_catalog,
    init_ai_capability_catalog,
    review_ai_capability_catalog,
    sync_ai_capability_catalog,
)


def _sync_result(*, errors: int = 0) -> SyncResultDTO:
    return SyncResultDTO(
        sync_type="incremental",
        total_discovered=9,
        created_count=3,
        updated_count=4,
        disabled_count=2,
        error_count=errors,
        duration_seconds=0.25,
        summary={
            "api": {"created": 2, "updated": 1},
            "ignored": "non-dict summary",
        },
    )


def _governance_result(*, apply: bool) -> CapabilityGovernanceResult:
    return CapabilityGovernanceResult(
        apply=apply,
        total_reviewed=10,
        changed_count=4,
        stale_count=2,
        stale_deleted_count=1,
        routing_enabled_count=3,
        routing_disabled_count=7,
        approved_count=3,
        pending_count=6,
        rejected_count=1,
        by_reason={"unsafe": 2, "stale": 1},
    )


def _output(command: object) -> str:
    return command.stdout._out.getvalue()  # type: ignore[attr-defined]


@pytest.mark.parametrize(("apply", "mode"), [(False, "DRY RUN"), (True, "APPLY")])
def test_govern_command_reports_text_mode_and_reasons(
    monkeypatch: pytest.MonkeyPatch,
    apply: bool,
    mode: str,
) -> None:
    execute = pytest.MonkeyPatch()
    del execute
    observed: list[tuple[bool, bool]] = []
    monkeypatch.setattr(
        govern_ai_capability_catalog,
        "CapabilityCatalogGovernanceService",
        lambda: SimpleNamespace(
            execute=lambda **kwargs: (
                observed.append((kwargs["apply"], kwargs["purge_stale"]))
                or _governance_result(apply=kwargs["apply"])
            )
        ),
    )
    stream = StringIO()
    command = govern_ai_capability_catalog.Command(stdout=stream)

    command.handle(apply=apply, keep_stale=True, format="text")

    assert observed == [(apply, False)]
    assert mode in stream.getvalue()
    assert "unsafe: 2" in stream.getvalue()


def test_govern_command_json_is_machine_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        govern_ai_capability_catalog,
        "CapabilityCatalogGovernanceService",
        lambda: SimpleNamespace(execute=lambda **_kwargs: _governance_result(apply=False)),
    )
    stream = StringIO()

    govern_ai_capability_catalog.Command(stdout=stream).handle(
        apply=False,
        keep_stale=False,
        format="json",
    )

    assert '"changed_count": 4' in stream.getvalue()
    assert '"stale": 1' in stream.getvalue()


def test_init_command_reports_source_details_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        init_ai_capability_catalog,
        "SyncCapabilitiesUseCase",
        lambda: SimpleNamespace(execute=lambda **_kwargs: _sync_result(errors=2)),
    )
    stream = StringIO()

    init_ai_capability_catalog.Command(stdout=stream).handle(force=True)

    output = stream.getvalue()
    assert "Total discovered: 9" in output
    assert "api:" in output
    assert "Completed with 2 error(s)" in output


@pytest.mark.parametrize(
    ("source", "skip_governance", "governed"),
    [
        (None, False, True),
        ("api", False, True),
        ("mcp_tool", True, False),
        ("builtin", False, False),
    ],
)
def test_sync_command_applies_governance_only_to_governed_sources(
    monkeypatch: pytest.MonkeyPatch,
    source: str | None,
    skip_governance: bool,
    governed: bool,
) -> None:
    governance_calls: list[bool] = []
    monkeypatch.setattr(
        sync_ai_capability_catalog,
        "SyncCapabilitiesUseCase",
        lambda: SimpleNamespace(execute=lambda **_kwargs: _sync_result(errors=1)),
    )
    monkeypatch.setattr(
        sync_ai_capability_catalog,
        "CapabilityCatalogGovernanceService",
        lambda: SimpleNamespace(
            execute=lambda **kwargs: (
                governance_calls.append(kwargs["apply"]) or _governance_result(apply=True)
            )
        ),
    )
    stream = StringIO()

    sync_ai_capability_catalog.Command(stdout=stream).handle(
        type="incremental",
        source=source,
        skip_governance=skip_governance,
    )

    assert bool(governance_calls) is governed
    output = stream.getvalue()
    assert "Sync complete" in output
    assert ("Post-sync governance:" in output) is governed
    assert "Completed with 1 error(s)" in output


def test_review_command_json_and_text_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    stats = {
        "total": 3,
        "enabled": 1,
        "disabled": 2,
        "manual_governance": 2,
        "by_source": {"builtin": 0, "mcp_tool": 0, "api": 3},
        "by_route_group": {"unsafe_api": 2},
        "by_review_status": {"pending": 2, "approved": 1},
    }
    monkeypatch.setattr(
        review_ai_capability_catalog,
        "DjangoCapabilityRepository",
        lambda: SimpleNamespace(get_stats=lambda: stats),
    )
    json_stream = StringIO()
    text_stream = StringIO()

    review_ai_capability_catalog.Command(stdout=json_stream).handle(format="json")
    review_ai_capability_catalog.Command(stdout=text_stream).handle(format="text")

    assert '"total": 3' in json_stream.getvalue()
    output = text_stream.getvalue()
    assert "No builtin capabilities found" in output
    assert "No MCP tools found" in output
    assert "2 unsafe API(s) detected" in output
    assert "Review complete" in output
