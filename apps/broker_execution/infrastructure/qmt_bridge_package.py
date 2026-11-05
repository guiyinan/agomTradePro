"""Server-local provider for the versioned QMT Agent ZIP artifact."""

from __future__ import annotations

import hashlib
from pathlib import Path

from django.conf import settings

from apps.broker_execution.application.qmt_bridge_package import (
    QmtBridgePackage,
)
from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionValidationError,
)
from qmt_agent import __version__


class DjangoQmtBridgePackageProvider:
    """Read only the exact package associated with the running Agent version."""

    def locate(self) -> QmtBridgePackage | None:
        """Return package metadata after size and optional SHA-256 sidecar verification."""

        filename = f"agom-qmt-agent-windows-{__version__}.zip"
        configured = str(getattr(settings, "QMT_AGENT_PACKAGE_PATH", "") or "").strip()
        path = (
            Path(configured)
            if configured
            else Path(settings.BASE_DIR) / "artifacts" / "qmt-agent" / filename
        )
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        if size <= 0:
            raise BrokerExecutionValidationError("QMT bridge package is empty")
        sha256 = digest.hexdigest()
        sidecar = Path(f"{path}.sha256")
        if sidecar.is_file():
            expected = sidecar.read_text(encoding="utf-8").strip().split(maxsplit=1)[0].lower()
            if expected != sha256:
                raise BrokerExecutionValidationError(
                    "QMT bridge package SHA-256 does not match its sidecar"
                )
        return QmtBridgePackage(
            path=path,
            version=__version__,
            filename=filename,
            size_bytes=size,
            sha256=sha256,
        )
