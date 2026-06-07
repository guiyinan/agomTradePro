from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_production_requirements_include_mcp_runtime() -> None:
    requirements = (ROOT / "requirements-prod.txt").read_text(encoding="utf-8")

    assert "mcp>=1.20,<2" in requirements


def test_production_lock_keeps_pywin32_windows_only() -> None:
    lock = (ROOT / "requirements-prod.lock").read_text(encoding="utf-8")

    assert "mcp==" in lock
    assert 'pywin32==312 ; sys_platform == "win32"' in lock
    assert "\npywin32==312\n" not in lock
