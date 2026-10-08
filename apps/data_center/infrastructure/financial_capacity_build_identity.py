"""Read the built image's immutable source revision for financial capacity binding."""

from __future__ import annotations

import json
import re
from pathlib import Path

from apps.data_center.application.financial_publication_capacity import (
    FinancialCapacityBuildIdentitySource,
    FinancialCapacityWorkflowError,
)

_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_APP_VERSION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,63}")
_MAX_IDENTITY_BYTES = 16 * 1024


class FileFinancialCapacityBuildIdentitySource(FinancialCapacityBuildIdentitySource):
    """Read and validate the source commit embedded in the running image."""

    def __init__(self, path: Path) -> None:
        """Use one injected identity path, normally ``/app/.agom-build-identity.json``."""

        self._path = path

    def source_commit(self) -> str:
        """Return the exact build source commit, rejecting absent or malformed identity."""

        try:
            content = self._path.read_bytes()
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FinancialCapacityWorkflowError(
                "financial capacity runtime build identity is unavailable"
            ) from exc
        if not content or len(content) > _MAX_IDENTITY_BYTES:
            raise FinancialCapacityWorkflowError(
                "financial capacity runtime build identity size is invalid"
            )
        try:
            payload: object = json.loads(content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FinancialCapacityWorkflowError(
                "financial capacity runtime build identity is invalid"
            ) from exc
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version",
            "app_version",
            "source_commit",
        }:
            raise FinancialCapacityWorkflowError(
                "financial capacity runtime build identity shape is invalid"
            )
        source_commit = payload.get("source_commit")
        app_version = payload.get("app_version")
        if (
            type(payload.get("schema_version")) is not int
            or payload.get("schema_version") != 1
            or type(app_version) is not str
            or _APP_VERSION_RE.fullmatch(app_version) is None
            or type(source_commit) is not str
            or _COMMIT_RE.fullmatch(source_commit) is None
        ):
            raise FinancialCapacityWorkflowError(
                "financial capacity runtime build identity is invalid"
            )
        return source_commit


__all__ = ["FileFinancialCapacityBuildIdentitySource"]
