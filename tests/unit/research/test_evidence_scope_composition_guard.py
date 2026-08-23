"""Regression tests for the production Evidence composition guard."""

from __future__ import annotations

from pathlib import Path

from scripts.check_evidence_scope_composition import scan_evidence_scope_composition


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _valid_api_views() -> str:
    return """
from apps.research.evidence_composition import make_evidence_read_facade

class _StaffExactEvidenceReadView:
    pass

class EvidenceDetailView(_StaffExactEvidenceReadView):
    def get(self):
        return make_evidence_read_facade()
"""


def test_current_production_evidence_reads_use_the_composition_root() -> None:
    assert scan_evidence_scope_composition() == ()


def test_guard_rejects_direct_repository_import_and_construction(tmp_path: Path) -> None:
    _write(tmp_path, "apps/research/evidence_composition.py", "DjangoEvidenceRepository()\n")
    _write(tmp_path, "apps/research/interface/evidence_api_views.py", _valid_api_views())
    _write(
        tmp_path,
        "apps/example.py",
        "from apps.research.infrastructure.evidence_repository import DjangoEvidenceRepository\n"
        "repository = DjangoEvidenceRepository()\n",
    )

    violations = scan_evidence_scope_composition(tmp_path)

    assert len(violations) == 2
    assert all("DjangoEvidenceRepository" in violation.message for violation in violations)
    assert {violation.line for violation in violations} == {1, 2}


def test_guard_requires_each_staff_scoped_api_view_to_call_the_factory(tmp_path: Path) -> None:
    _write(tmp_path, "apps/research/evidence_composition.py", "")
    _write(
        tmp_path,
        "apps/research/interface/evidence_api_views.py",
        "from apps.research.evidence_composition import make_evidence_read_facade\n"
        "class _StaffExactEvidenceReadView: pass\n"
        "class EvidenceDetailView(_StaffExactEvidenceReadView):\n"
        "    def get(self):\n"
        "        return None\n",
    )

    violations = scan_evidence_scope_composition(tmp_path)

    assert len(violations) == 1
    assert "must call make_evidence_read_facade" in violations[0].message


def test_guard_rejects_wildcard_imports_from_evidence_implementation_modules(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "apps/research/evidence_composition.py", "")
    _write(tmp_path, "apps/research/interface/evidence_api_views.py", _valid_api_views())
    _write(
        tmp_path,
        "apps/example.py",
        "from apps.research.infrastructure.evidence_repository import *\n",
    )

    violations = scan_evidence_scope_composition(tmp_path)

    assert len(violations) == 1
    assert "wildcard import" in violations[0].message
