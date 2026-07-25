import ast
from pathlib import Path

from scripts import check_changed_python_file_size
from scripts.check_changed_python_file_size import (
    ChangedPythonFile,
    FileSizeGrowth,
    count_non_empty_lines,
    find_growth_violations,
    is_production_python_file,
    parse_name_status,
)


def test_count_non_empty_lines_ignores_blank_lines():
    assert count_non_empty_lines("first\n\n  \nsecond\n") == 2


def test_production_filter_excludes_migrations_and_tests():
    assert is_production_python_file("apps/strategy/application/use_cases.py")
    assert not is_production_python_file("apps/strategy/migrations/0001_initial.py")
    assert not is_production_python_file("apps/strategy/tests/test_services.py")
    assert not is_production_python_file("tests/unit/test_strategy.py")


def test_parse_name_status_preserves_rename_base_path():
    changes = parse_name_status(
        "\n".join(
            [
                "M\tapps/strategy/infrastructure/repositories.py",
                "A\tapps/strategy/infrastructure/new_repository.py",
                "R100\tapps/old.py\tapps/new.py",
                "M\tdocs/INDEX.md",
            ]
        )
    )

    assert changes == [
        ChangedPythonFile(
            base_path="apps/strategy/infrastructure/repositories.py",
            head_path="apps/strategy/infrastructure/repositories.py",
        ),
        ChangedPythonFile(
            base_path=None,
            head_path="apps/strategy/infrastructure/new_repository.py",
        ),
        ChangedPythonFile(base_path="apps/old.py", head_path="apps/new.py"),
    ]


def test_growth_guard_rejects_growth_beyond_limit(monkeypatch):
    sources = {
        ("base", "apps/example.py"): "old\n" * 1000,
        ("head", "apps/example.py"): "new\n" * 1001,
    }
    monkeypatch.setattr(
        check_changed_python_file_size,
        "read_revision_file",
        lambda revision, path: sources[(revision, path)],
    )

    violations = find_growth_violations(
        [
            ChangedPythonFile(
                base_path="apps/example.py",
                head_path="apps/example.py",
            )
        ],
        base="base",
        head="head",
        growth_limit=1000,
    )

    assert violations == [
        FileSizeGrowth(
            path="apps/example.py",
            base_non_empty_lines=1000,
            head_non_empty_lines=1001,
        )
    ]


def test_growth_guard_allows_large_file_to_shrink(monkeypatch):
    sources = {
        ("base", "apps/example.py"): "old\n" * 1100,
        ("head", "apps/example.py"): "new\n" * 1050,
    }
    monkeypatch.setattr(
        check_changed_python_file_size,
        "read_revision_file",
        lambda revision, path: sources[(revision, path)],
    )

    violations = find_growth_violations(
        [
            ChangedPythonFile(
                base_path="apps/example.py",
                head_path="apps/example.py",
            )
        ],
        base="base",
        head="head",
        growth_limit=1000,
    )

    assert violations == []


def test_broker_and_strategy_repository_splits_remain_bounded():
    repository_root = Path(__file__).resolve().parents[2]
    budgets = {
        "apps/broker_execution/infrastructure/repositories.py": 300,
        "apps/broker_execution/infrastructure/broker_repository_contract.py": 120,
        "apps/broker_execution/infrastructure/broker_repository_access.py": 800,
        "apps/broker_execution/infrastructure/broker_repository_order_control.py": 350,
        "apps/broker_execution/infrastructure/broker_repository_agent_runtime.py": 850,
        "apps/broker_execution/infrastructure/broker_repository_agent_administration.py": 500,
        "apps/broker_execution/infrastructure/broker_repository_reconciliation.py": 700,
        "apps/strategy/infrastructure/repositories.py": 950,
        "apps/strategy/infrastructure/strategy_interface_repository.py": 550,
    }
    owner_paths = [path for path in budgets if not path.endswith("/repositories.py")]

    for relative_path, budget in budgets.items():
        source = (repository_root / relative_path).read_text(encoding="utf-8")
        assert count_non_empty_lines(source) <= budget, relative_path
    for relative_path in owner_paths:
        tree = ast.parse((repository_root / relative_path).read_text(encoding="utf-8"))
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert "repositories" not in imported_modules, relative_path
