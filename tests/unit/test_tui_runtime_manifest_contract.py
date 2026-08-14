"""Release-manifest coverage for the declarative and server-side TUI contract."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config" / "tui" / "agomtui-runtime.manifest.json"


def _digest(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def test_manifest_covers_server_side_tui_contract() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    files = manifest["files"]

    required = {
        "config/tui/ia/tui_information_architecture.v1.json",
        "apps/terminal/application/tui_metadata.py",
        "apps/terminal/application/tui_metadata_constants.py",
        "apps/terminal/application/tui_metadata_field_aliases.py",
        "apps/terminal/infrastructure/tui_information_architecture.py",
        "apps/terminal/infrastructure/tui_metadata_repository.py",
        "apps/terminal/infrastructure/tui_metadata_signals.py",
        "apps/terminal/infrastructure/tui_metadata_runtime_injection_policy.py",
        "apps/terminal/infrastructure/tui_metadata_runtime_injection_signal.py",
        "apps/terminal/infrastructure/tui_metadata_runtime_injection_account_self_service.py",
    }

    assert required <= files.keys()
    assert (
        sum(path.startswith("apps/terminal/infrastructure/tui_metadata_runtime_") for path in files)
        >= 50
    )
    assert all("__pycache__" not in path and not path.endswith(".pyc") for path in files)

    for relative_path, expected_digest in files.items():
        source_path = ROOT / relative_path
        assert source_path.is_file(), relative_path
        assert _digest(source_path) == expected_digest, relative_path

    assert re.fullmatch(r"[0-9a-f]{40}", manifest["upstream_commit"])
