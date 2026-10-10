"""Secret-free transport contract for the scheduled renewal adapter."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import cast

import pytest

import apps.audit.infrastructure.system_audit_authority_renewal_executor as renewal_executor


@pytest.mark.parametrize(
    "reason_code",
    [
        "authority_renewal_envelope_consumed",
        "authority_renewal_predecessor_changed",
        "recovery_envelope_consumed",
        "recovery_identity_conflict",
    ],
)
def test_adapter_preserves_only_stable_recovery_blocker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reason_code: str,
) -> None:
    request_path = tmp_path / "renewal.json"
    request_path.touch()
    monkeypatch.setenv("AGOM_SYSTEM_AUDIT_RENEWAL_REQUEST_PATH", str(request_path))

    def call_command(_command: str, **kwargs: object) -> None:
        output = cast(io.StringIO, kwargs["stdout"])
        output.write(
            json.dumps(
                {
                    "outcome": "blocked",
                    "block_reason_code": reason_code,
                    "diagnostic": "secret detail must not escape",
                }
            )
        )

    monkeypatch.setattr(renewal_executor, "call_command", call_command)

    result = renewal_executor.execute_configured_system_audit_authority_renewal()

    assert result == {
        "outcome": "blocked",
        "success": False,
        "stage": "renewal",
        "requested": 1,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "block_reason_code": reason_code,
    }


def test_adapter_redacts_ungoverned_blocked_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "renewal.json"
    request_path.touch()
    monkeypatch.setenv("AGOM_SYSTEM_AUDIT_RENEWAL_REQUEST_PATH", str(request_path))

    def call_command(_command: str, **kwargs: object) -> None:
        output = cast(io.StringIO, kwargs["stdout"])
        output.write(
            json.dumps(
                {
                    "outcome": "blocked",
                    "blocked_reason": "database secret token abc123",
                }
            )
        )

    monkeypatch.setattr(renewal_executor, "call_command", call_command)

    result = renewal_executor.execute_configured_system_audit_authority_renewal()

    assert result["block_reason_code"] == "renewal_command_failed"
    assert "abc123" not in json.dumps(result)
