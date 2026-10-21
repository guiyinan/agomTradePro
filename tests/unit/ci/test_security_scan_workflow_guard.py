from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "security-scan.yml"
TWISTED_PATTERN_MARKER = "twisted\\.mail"
IGNORED_ADVISORIES = ("PYSEC-2024-277", "GHSA-8pqf-f4m5-798g")


def _extract_guard_program() -> str:
    """Extract the actual Python heredoc used by the pinned workflow guard."""
    lines = WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()
    marker_index = next(index for index, line in enumerate(lines) if TWISTED_PATTERN_MARKER in line)
    heredoc_start = max(
        index
        for index, line in enumerate(lines[:marker_index])
        if line.strip() == "python3 - <<'PY'"
    )
    heredoc_end = next(
        index for index in range(marker_index + 1, len(lines)) if lines[index].strip() == "PY"
    )
    return textwrap.dedent("\n".join(lines[heredoc_start + 1 : heredoc_end])) + "\n"


def _make_source_roots(root: Path, *, missing: str | None = None) -> None:
    """Create the four source roots expected by the workflow guard."""
    for name in ("apps", "config", "shared"):
        if name != missing:
            (root / name).mkdir()
    (root / "manage.py").write_text("# source fixture\n", encoding="utf-8")


def _run_guard(root: Path, *, inject_read_error: bool = False) -> subprocess.CompletedProcess[str]:
    """Run the extracted production guard against an isolated fixture tree."""
    script = _extract_guard_program()
    if inject_read_error:
        script = (
            "from pathlib import Path\n"
            "_original_path_open = Path.open\n"
            "def _guard_test_open(path, *args, **kwargs):\n"
            "    if path.name == 'unreadable.py':\n"
            "        raise OSError('injected read failure')\n"
            "    return _original_path_open(path, *args, **kwargs)\n"
            "Path.open = _guard_test_open\n"
        ) + script
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
        timeout=5,
    )


def test_clean_source_roots_pass_the_actual_workflow_guard(tmp_path: Path) -> None:
    """A readable source tree with no IMAP markers passes the guard."""
    _make_source_roots(tmp_path)
    (tmp_path / "apps" / "ordinary.py").write_text(
        "from twisted.internet import reactor\n", encoding="utf-8"
    )

    result = _run_guard(tmp_path)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize(
    "source",
    (
        "import twisted.mail\n",
        "from\t twisted import\t mail\n",
        "client = imap4\n",
        "factory = IMAP4Server\n",
        "factory = IMAP4Factory\n",
        "method = listMailboxes\n",
    ),
)
def test_matching_source_fails_the_actual_workflow_guard(tmp_path: Path, source: str) -> None:
    """Each guarded Twisted IMAP pattern blocks the workflow scan."""
    _make_source_roots(tmp_path)
    (tmp_path / "apps" / "match.py").write_text(source, encoding="utf-8")

    result = _run_guard(tmp_path)

    assert result.returncode == 1
    assert "Twisted IMAP usage invalidates" in result.stdout


@pytest.mark.parametrize(
    "relative_path",
    ("config/match.py", "shared/match.py", "manage.py"),
)
def test_guard_scans_every_declared_source_root(tmp_path: Path, relative_path: str) -> None:
    """Each separately configured root is included in the workflow scan."""
    _make_source_roots(tmp_path)
    (tmp_path / relative_path).write_text("import twisted.mail\n", encoding="utf-8")

    result = _run_guard(tmp_path)

    assert result.returncode == 1
    assert "Twisted IMAP usage invalidates" in result.stdout


def test_missing_source_root_fails_closed(tmp_path: Path) -> None:
    """A missing scanned root is an error rather than a clean scan."""
    _make_source_roots(tmp_path, missing="shared")

    result = _run_guard(tmp_path)

    assert result.returncode == 1
    assert "Could not verify the Twisted IMAP" in result.stderr


def test_source_read_error_fails_closed(tmp_path: Path) -> None:
    """An unreadable source file cannot be mistaken for a clean scan."""
    _make_source_roots(tmp_path)
    (tmp_path / "apps" / "unreadable.py").write_text("value = 1\n", encoding="utf-8")

    result = _run_guard(tmp_path, inject_read_error=True)

    assert result.returncode == 1
    assert "Could not verify the Twisted IMAP" in result.stderr
    assert "OSError" in result.stderr


def test_invalid_utf8_source_fails_closed(tmp_path: Path) -> None:
    """A source read/decode failure cannot be treated as no match."""
    _make_source_roots(tmp_path)
    (tmp_path / "apps" / "invalid.py").write_bytes(b"\xff")

    result = _run_guard(tmp_path)

    assert result.returncode == 1
    assert "UnicodeDecodeError" in result.stderr


def test_workflow_keeps_the_two_exact_pip_audit_ignores() -> None:
    """The guard test does not broaden the existing advisory exceptions."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    ignore_arguments = re.findall(
        r"--ignore-vuln(?:[ \t]+|=)([^\s\\]+)",
        workflow,
    )
    assert ignore_arguments == list(IGNORED_ADVISORIES)
    assert len(re.findall(r"(?m)^[ \t]+pip-audit \\\s*$", workflow)) == 1
