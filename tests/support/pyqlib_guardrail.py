from dataclasses import dataclass
from importlib import metadata
from pathlib import Path


@dataclass(frozen=True)
class PyQlibStatus:
    available: bool
    reason: str
    misconfigured: bool
    module_file: Path | None = None
    version: str | None = None


def locate_pyqlib_init(dist: metadata.Distribution) -> Path | None:
    if not dist.files:
        return None

    for entry in dist.files:
        if str(entry).replace("\\", "/").endswith("qlib/__init__.py"):
            return Path(dist.locate_file(entry)).resolve()
    return None


def resolve_pyqlib_status(repo_root: Path) -> PyQlibStatus:
    """
    Validate that `import qlib` resolves to the installed Microsoft `pyqlib`.

    The guardrail allows unrelated test suites to run when pyqlib is absent,
    but must fail fast when `qlib` imports from a fake or shadowed location.
    """
    try:
        import qlib
    except ImportError:
        return PyQlibStatus(
            available=False,
            reason="Microsoft pyqlib is not installed",
            misconfigured=False,
        )

    module_file = Path(qlib.__file__).resolve()

    try:
        dist = metadata.distribution("pyqlib")
    except metadata.PackageNotFoundError:
        return PyQlibStatus(
            available=False,
            reason="import qlib succeeded, but the official pyqlib distribution is missing",
            misconfigured=True,
            module_file=module_file,
        )

    if repo_root in module_file.parents:
        return PyQlibStatus(
            available=False,
            reason=f"qlib resolved inside the repository ({module_file}); expected installed pyqlib",
            misconfigured=True,
            module_file=module_file,
            version=dist.version,
        )

    expected_init = locate_pyqlib_init(dist)
    if expected_init is not None and module_file != expected_init:
        return PyQlibStatus(
            available=False,
            reason=f"qlib resolved to {module_file}, expected pyqlib at {expected_init}",
            misconfigured=True,
            module_file=module_file,
            version=dist.version,
        )

    return PyQlibStatus(
        available=True,
        reason=f"Using pyqlib {dist.version} from {module_file}",
        misconfigured=False,
        module_file=module_file,
        version=dist.version,
    )
