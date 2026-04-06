from pathlib import Path

MODULES_DIR = Path(__file__).resolve().parents[2] / "agomtradepro" / "modules"


def test_sdk_modules_do_not_use_removed_resource_routes():
    banned_patterns = [
        '"/macro/api',
        '"/policy/',
        '"stocks/',
        '"recommendations/"',
        '"hot-sectors/"',
        '"compare/"',
        '"/api/market-data',
    ]
    allowed_files = {
        "dashboard.py",
    }

    violations: list[str] = []
    for path in MODULES_DIR.glob("*.py"):
        if path.name in allowed_files:
            continue
        content = path.read_text(encoding="utf-8")
        for pattern in banned_patterns:
            if pattern in content:
                violations.append(f"{path.name}: {pattern}")

    assert not violations, "Found legacy SDK route patterns:\n" + "\n".join(violations)
