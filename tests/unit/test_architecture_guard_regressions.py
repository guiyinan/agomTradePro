from pathlib import Path


def test_historical_architecture_guard_regression_imports_removed() -> None:
    """Guard the files that triggered the 2026-03-29 layer-guard failure."""
    root = Path(__file__).resolve().parents[2]
    banned_imports = {
        root / "apps" / "macro" / "interface" / "serializers.py": (
            "apps.macro.infrastructure.models",
        ),
        root / "apps" / "macro" / "interface" / "views" / "config_api.py": (
            "apps.macro.infrastructure.models",
        ),
        root / "apps" / "simulated_trading" / "application" / "unified_position_service.py": (
            "apps.simulated_trading.infrastructure.models",
        ),
    }
    account_iface = root / "apps" / "account" / "interface"
    if account_iface.exists():
        for py in account_iface.glob("*.py"):
            if py.name == "__init__.py":
                continue
            banned_imports[py] = (
                "apps.simulated_trading.infrastructure.models",
                "apps.simulated_trading.management.commands.migrate_account_ledger",
            )

    for path, patterns in banned_imports.items():
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        for pattern in patterns:
            assert pattern not in content, f"{path} should not import {pattern}"
