from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_production_requirements_include_mcp_runtime() -> None:
    requirements = (ROOT / "requirements-prod.txt").read_text(encoding="utf-8")

    assert "mcp>=1.20,<2" in requirements


def test_production_lock_keeps_pywin32_windows_only() -> None:
    from importlib.metadata import distribution

    from packaging.markers import default_environment
    from packaging.requirements import Requirement

    lock = (ROOT / "requirements-prod.lock").read_text(encoding="utf-8")

    assert "mcp==" in lock
    # This lock feeds the Linux/Python 3.11 production wheelhouse; MCP owns its Windows dependency.
    assert not any(line.strip().lower().startswith("pywin32") for line in lock.splitlines())

    mcp_requirements = [Requirement(value) for value in (distribution("mcp").requires or [])]
    pywin32_requirements = [
        requirement for requirement in mcp_requirements if requirement.name.lower() == "pywin32"
    ]
    assert pywin32_requirements
    markers = [requirement.marker for requirement in pywin32_requirements]
    assert all(marker is not None for marker in markers)
    linux_environment = {
        **default_environment(),
        "sys_platform": "linux",
        "platform_system": "Linux",
        "os_name": "posix",
    }
    windows_environment = {
        **default_environment(),
        "sys_platform": "win32",
        "platform_system": "Windows",
        "os_name": "nt",
    }
    assert all(not marker.evaluate(linux_environment) for marker in markers if marker is not None)
    assert any(marker.evaluate(windows_environment) for marker in markers if marker is not None)
