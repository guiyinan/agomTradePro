from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "check_data_center_provider_credentials.py"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("provider_credential_guard", _SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("provider credential guard cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_credentials_have_zero_plaintext_compatibility_paths() -> None:
    contract = json.loads(
        (_ROOT / "governance" / "data_center_provider_credential_contracts.json").read_text(
            encoding="utf-8"
        )
    )
    assert contract["legacy_plaintext_paths"] == []
    assert contract["credential_owner"] == (
        "apps.config_center.infrastructure.secret_models.ConfigCenterSecretModel"
    )


def test_provider_credential_runtime_files_have_no_legacy_tokens() -> None:
    guard = _load_guard()
    violations = [
        violation for path in guard._production_files() for violation in guard._scan_file(path)
    ]
    assert violations == []
