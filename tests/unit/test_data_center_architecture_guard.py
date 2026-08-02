"""Architecture compliance guard for the data_center unification.

Rules enforced:
1. Only apps/data_center/infrastructure/ may import external data-provider SDKs
   (tushare, akshare, xtquant).  Any file outside this boundary that contains
   such imports must be listed in _LEGACY_SDK_VIOLATIONS below.  The list is
   a ratchet — it can only shrink.  Adding new files to the list is a test
   failure; removing a file from the list while it still imports an SDK is
   also a test failure.

2. No module may import DataSourceConfig or DataProviderSettings from
   apps.macro.infrastructure.models (these classes have been deleted).
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

_SCAN_DIRS = [
    _ROOT / "apps",
    _ROOT / "core",
]

# ---------------------------------------------------------------------------
# Rule 1 — SDK imports must only live in data_center/infrastructure
# ---------------------------------------------------------------------------

_SDK_ONLY_ALLOWED_DIR = _ROOT / "apps" / "data_center" / "infrastructure"

# Match actual import lines (not string literals in comments or test code).
_SDK_IMPORT_RE = re.compile(
    r"^[ \t]*(?:import|from)\s+(tushare|akshare|xtquant)\b",
    re.MULTILINE,
)

# No legacy exceptions remain. Any SDK import outside apps/data_center/infrastructure
# is now a hard failure.
_LEGACY_SDK_VIOLATIONS: set[Path] = set()

# One legacy macro compatibility repository still owns a CRUD facade while
# its application replacement is staged.  This is a ratchet: new files may
# not be added and the exception should disappear in the destructive phase.
_LEGACY_DATA_CENTER_ORM_VIOLATIONS = {
    _ROOT / "apps" / "macro" / "infrastructure" / "data_center_fact_repository.py",
}


def _is_in_allowed_dir(path: Path) -> bool:
    try:
        path.relative_to(_SDK_ONLY_ALLOWED_DIR)
        return True
    except ValueError:
        return False


def _iter_py_files():
    for scan_dir in _SCAN_DIRS:
        if scan_dir.exists():
            for py in scan_dir.rglob("*.py"):
                if "__pycache__" not in py.parts:
                    yield py


def test_no_new_sdk_imports_outside_data_center() -> None:
    """No file outside data_center/infrastructure may import tushare/akshare/xtquant
    unless it is listed in _LEGACY_SDK_VIOLATIONS.  The legacy list is a ratchet."""
    new_violations: list[str] = []
    cleaned_violations: list[str] = []

    for py in _iter_py_files():
        if _is_in_allowed_dir(py):
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        has_sdk = bool(_SDK_IMPORT_RE.search(content))
        in_legacy = py in _LEGACY_SDK_VIOLATIONS

        if has_sdk and not in_legacy:
            new_violations.append(str(py.relative_to(_ROOT)))
        elif not has_sdk and in_legacy and py.exists():
            cleaned_violations.append(str(py.relative_to(_ROOT)))

    errors: list[str] = []
    if new_violations:
        errors.append(
            "NEW SDK imports outside data_center/infrastructure (add to migration backlog, "
            "do NOT add to _LEGACY_SDK_VIOLATIONS):\n"
            + "\n".join(f"  {v}" for v in sorted(new_violations))
        )
    if cleaned_violations:
        errors.append(
            "These files were in _LEGACY_SDK_VIOLATIONS but no longer import SDKs — "
            "remove them from the list:\n"
            + "\n".join(f"  {v}" for v in sorted(cleaned_violations))
        )

    assert not errors, "\n\n".join(errors)


# ---------------------------------------------------------------------------
# Rule 2 — Legacy macro DataSourceConfig / DataProviderSettings banned
# ---------------------------------------------------------------------------

_LEGACY_IMPORT_RE = re.compile(
    r"from\s+apps\.macro\.infrastructure\.models\s+import\s+[^\n]*"
    r"\b(DataSourceConfig|DataProviderSettings)\b",
    re.MULTILINE,
)

_LEGACY_MACRO_EXEMPT = {
    _ROOT / "apps" / "macro" / "infrastructure" / "models.py",
    _ROOT / "apps" / "macro" / "migrations",
    Path(__file__).resolve(),
}


def _is_legacy_exempt(path: Path) -> bool:
    for exempt in _LEGACY_MACRO_EXEMPT:
        if path == exempt:
            return True
        try:
            path.relative_to(exempt)
            return True
        except ValueError:
            pass
    return False


def test_legacy_macro_datasource_models_not_imported() -> None:
    """DataSourceConfig and DataProviderSettings must not be imported from macro."""
    violations: list[str] = []
    all_dirs = _SCAN_DIRS + [_ROOT / "tests"]
    for scan_dir in all_dirs:
        if not scan_dir.exists():
            continue
        for py in scan_dir.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            if _is_legacy_exempt(py):
                continue
            try:
                content = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            match = _LEGACY_IMPORT_RE.search(content)
            if match:
                violations.append(
                    f"{py.relative_to(_ROOT)}: '{match.group(0)[:80].strip()}'"
                )

    assert not violations, (
        "Legacy macro DataSourceConfig/DataProviderSettings imports found:\n"
        + "\n".join(violations)
    )


def test_data_center_has_no_reverse_bridge_or_shared_provider_client() -> None:
    """Data Center owns provider transport and must not depend on old bridges."""

    forbidden = (
        "core.integration.data_center_business_sources",
        "shared.infrastructure.tushare_client",
        "shared.infrastructure.sdk_bridge",
    )
    violations: list[str] = []
    for py in (_ROOT / "apps" / "data_center").rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        content = py.read_text(encoding="utf-8", errors="ignore")
        for marker in forbidden:
            if marker in content:
                violations.append(f"{py.relative_to(_ROOT)}: {marker}")
    assert not violations, "Data Center reverse/provider bridge imports found:\n" + "\n".join(
        violations
    )


def test_business_apps_do_not_import_data_center_orm_outside_ratchet() -> None:
    """Business apps must use Application Public Ports instead of Data Center ORM."""

    violations: list[str] = []
    for py in (_ROOT / "apps").rglob("*.py"):
        if "__pycache__" in py.parts or "data_center" in py.parts or "tests" in py.parts:
            continue
        content = py.read_text(encoding="utf-8", errors="ignore")
        if "apps.data_center.infrastructure.models" in content:
            if py not in _LEGACY_DATA_CENTER_ORM_VIOLATIONS:
                violations.append(str(py.relative_to(_ROOT)))
    assert not violations, "New cross-app Data Center ORM imports found:\n" + "\n".join(
        sorted(violations)
    )
