"""Runtime contracts for Celery broker visibility and task time limits."""

from __future__ import annotations

import ast
from collections import deque
from pathlib import Path

import pytest
from django.conf import settings

_TASK_DECORATOR_NAMES = {"shared_task", "typed_shared_task", "_typed_shared_task"}


def _positive_literal_int(node: ast.expr) -> int | None:
    """Return one positive integer constant without accepting booleans."""

    if isinstance(node, ast.Constant) and type(node.value) is int and node.value > 0:
        return node.value
    return None


def _imported_sibling_modules(source_path: Path, tree: ast.Module) -> dict[str, Path]:
    """Map explicitly imported sibling modules without importing project code."""

    modules: dict[str, Path] = {}
    for statement in tree.body:
        if (
            not isinstance(statement, ast.ImportFrom)
            or statement.level != 1
            or statement.module is not None
        ):
            continue
        for alias in statement.names:
            if alias.name == "*" or not alias.name.isidentifier():
                continue
            module_path = source_path.parent / f"{alias.name}.py"
            if module_path.is_file():
                modules[alias.asname or alias.name] = module_path
    return modules


def _owner_module_literal_int(
    module_path: Path,
    constant_name: str,
    *,
    owner_module_trees: dict[Path, ast.Module] | None = None,
) -> int | None:
    """Read one module-level integer assignment from an explicitly imported file."""

    tree = owner_module_trees.get(module_path) if owner_module_trees is not None else None
    if tree is None:
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        if owner_module_trees is not None:
            owner_module_trees[module_path] = tree
    values: list[ast.expr] = []
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == constant_name
                for target in statement.targets
            ):
                values.append(statement.value)
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == constant_name
            and statement.value is not None
        ):
            values.append(statement.value)
    if len(values) != 1:
        return None
    return _positive_literal_int(values[0])


def _literal_int(
    node: ast.expr,
    *,
    imported_modules: dict[str, Path] | None = None,
    owner_module_trees: dict[Path, ast.Module] | None = None,
) -> int | None:
    """Resolve positive literals, literal ``getattr`` defaults, and imported owner constants."""

    value = _positive_literal_int(node)
    if value is not None:
        return value
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) == 3
    ):
        return _positive_literal_int(node.args[2])
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and imported_modules is not None
    ):
        module_path = imported_modules.get(node.value.id)
        if module_path is not None:
            return _owner_module_literal_int(
                module_path, node.attr, owner_module_trees=owner_module_trees
            )
    return None


def _decorator_name(node: ast.expr) -> str | None:
    """Return the final name of a task decorator expression."""

    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _statement_nodes(tree: ast.Module) -> list[ast.stmt]:
    """Return statements in ast.walk order without visiting expression subtrees."""

    pending: deque[ast.AST] = deque([tree])
    statements: list[ast.stmt] = []
    suite_nodes = (ast.Module, ast.stmt, ast.ExceptHandler, ast.match_case)
    while pending:
        node = pending.popleft()
        if isinstance(node, ast.stmt):
            statements.append(node)
        if isinstance(node, suite_nodes):
            pending.extend(
                child for child in ast.iter_child_nodes(node) if isinstance(child, suite_nodes)
            )
    return statements


def _repository_hard_limits() -> list[int]:
    """Collect explicit hard limits from every application task source file."""

    limits: list[int] = []
    owner_module_trees: dict[Path, ast.Module] = {}
    for source_path in Path("apps").glob("*/application/**/*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        imported_modules = _imported_sibling_modules(source_path, tree)
        for node in _statement_nodes(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if _decorator_name(decorator) not in _TASK_DECORATOR_NAMES:
                    continue
                if not isinstance(decorator, ast.Call):
                    continue
                for keyword in decorator.keywords:
                    if keyword.arg == "time_limit":
                        value = _literal_int(
                            keyword.value,
                            imported_modules=imported_modules,
                            owner_module_trees=owner_module_trees,
                        )
                        if value is None:
                            raise AssertionError(
                                f"{source_path}:{node.lineno} task time_limit must expose "
                                "a positive literal, literal getattr default, or "
                                "explicitly imported owner-module constant"
                            )
                        limits.append(value)
    return limits


def test_statement_nodes_matches_ast_walk_for_nested_compound_suites() -> None:
    """Visit nested async, exception-group, and match-case function suites in ast.walk order."""

    tree = ast.parse("""
def outer():
    class Nested:
        async def method(self):
            if flag:
                def if_branch(): return 1
            try:
                def try_body(): return 2
            except* ValueError:
                def except_star_body(): return 3
            match value:
                case 1:
                    def match_body(): return 4
            return 0
""")
    expected = [
        (type(node), node.name, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    actual = [
        (type(node), node.name, node.lineno)
        for node in _statement_nodes(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    assert actual == expected


def test_owner_ast_cache_is_limited_to_explicit_siblings_and_scan_local(
    tmp_path: Path,
) -> None:
    """Reuse only explicitly referenced owner modules, then refresh on the next scan."""

    task_path = tmp_path / "tasks.py"
    first_owner = tmp_path / "limits.py"
    second_owner = tmp_path / "policy.py"
    unrelated = tmp_path / "unrelated.py"
    task_path.write_text("from . import limits, policy\n", encoding="utf-8")
    first_owner.write_text("HARD_LIMIT = 5700\n", encoding="utf-8")
    second_owner.write_text("HARD_LIMIT = 5701\n", encoding="utf-8")
    unrelated.write_text("VALUE = 1\n", encoding="utf-8")
    imports = _imported_sibling_modules(task_path, ast.parse(task_path.read_text(encoding="utf-8")))
    first_limit = ast.parse("limits.HARD_LIMIT").body[0].value
    second_limit = ast.parse("policy.HARD_LIMIT").body[0].value
    owner_module_trees: dict[Path, ast.Module] = {}

    assert (
        _literal_int(first_limit, imported_modules=imports, owner_module_trees=owner_module_trees)
        == 5700
    )
    assert set(owner_module_trees) == {first_owner}
    assert (
        _literal_int(second_limit, imported_modules=imports, owner_module_trees=owner_module_trees)
        == 5701
    )
    assert set(owner_module_trees) == {first_owner, second_owner}
    assert unrelated not in owner_module_trees

    first_owner.write_text("HARD_LIMIT = 5702\n", encoding="utf-8")
    assert (
        _literal_int(first_limit, imported_modules=imports, owner_module_trees=owner_module_trees)
        == 5700
    )
    next_scan_cache: dict[Path, ast.Module] = {}
    assert (
        _literal_int(first_limit, imported_modules=imports, owner_module_trees=next_scan_cache)
        == 5702
    )
    assert set(next_scan_cache) == {first_owner}


def test_repository_hard_limits_keeps_syntax_and_dynamic_limit_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not skip invalid non-task source or accept an unresolved task limit."""

    application = tmp_path / "apps" / "demo" / "application"
    application.mkdir(parents=True)
    task_path = application / "tasks.py"
    task_path.write_text(
        "@shared_task(time_limit=runtime_limit)\ndef task(): pass\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(AssertionError, match="task time_limit must expose"):
        _repository_hard_limits()

    task_path.write_text("def unrelated(): pass\n", encoding="utf-8")
    (application / "broken.py").write_text("def invalid(:\n    pass\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        _repository_hard_limits()


def test_task_limit_ast_reader_follows_only_explicit_sibling_constants(
    tmp_path: Path,
) -> None:
    """Resolve a literal owner constant while rejecting dynamic and unknown values."""

    task_path = tmp_path / "tasks.py"
    owner_path = tmp_path / "lease.py"
    task_path.write_text("from . import lease\n", encoding="utf-8")
    owner_path.write_text("HARD_LIMIT = 5700\n", encoding="utf-8")
    task_tree = ast.parse(task_path.read_text(encoding="utf-8"), filename=str(task_path))
    imported_modules = _imported_sibling_modules(task_path, task_tree)
    owner_limit = ast.Attribute(
        value=ast.Name(id="lease", ctx=ast.Load()),
        attr="HARD_LIMIT",
        ctx=ast.Load(),
    )

    assert _literal_int(ast.Constant(value=5700)) == 5700
    assert _literal_int(owner_limit, imported_modules=imported_modules) == 5700
    assert _literal_int(ast.Constant(value=True)) is None
    assert _literal_int(ast.Constant(value=0)) is None
    assert _literal_int(ast.Name(id="runtime_limit", ctx=ast.Load())) is None
    assert (
        _literal_int(
            ast.Attribute(
                value=ast.Name(id="unimported", ctx=ast.Load()),
                attr="HARD_LIMIT",
                ctx=ast.Load(),
            ),
            imported_modules=imported_modules,
        )
        is None
    )

    owner_path.write_text("HARD_LIMIT = resolve_limit()\n", encoding="utf-8")
    assert _literal_int(owner_limit, imported_modules=imported_modules) is None


def test_redis_visibility_timeout_exceeds_every_repository_task_hard_limit() -> None:
    """Redis must not redeliver an acknowledged-late task before its hard limit."""

    transport_options = settings.CELERY_BROKER_TRANSPORT_OPTIONS
    visibility_timeout = transport_options["visibility_timeout"]
    hard_limits = [settings.CELERY_TASK_TIME_LIMIT, *_repository_hard_limits()]

    assert visibility_timeout == settings.CELERY_BROKER_VISIBILITY_TIMEOUT
    assert max(hard_limits) == settings.CELERY_REPOSITORY_TASK_HARD_LIMIT
    assert max(hard_limits) <= settings.CELERY_TASK_MAX_HARD_LIMIT
    assert visibility_timeout > max(hard_limits)


def test_full_market_task_limits_leave_strict_authority_finalization_headroom() -> None:
    """The full-market task and authority window move together as one contract."""

    from apps.data_center.application import tasks

    task = tasks.refresh_full_market_publications_task
    authority_seconds = tasks._FULL_MARKET_AUTHORITY_WINDOW.total_seconds()
    finalization_seconds = tasks._AUTHORITY_FINALIZATION_WINDOW.total_seconds()

    assert task.soft_time_limit == 5400
    assert task.time_limit == 5700
    assert authority_seconds > task.time_limit + finalization_seconds
