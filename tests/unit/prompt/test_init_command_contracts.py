"""Prompt-template initialization command contracts."""

from __future__ import annotations

from contextlib import nullcontext
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management.base import CommandError

from apps.prompt.management.commands import init_prompt_templates


class _Lookup:
    def __init__(self, existing: dict[str, object]) -> None:
        self.existing = existing
        self.name = ""

    def filter(self, **kwargs: object) -> _Lookup:
        self.name = str(kwargs["name"])
        return self

    def first(self) -> object | None:
        return self.existing.get(self.name)


def test_prompt_command_handle_respects_scope_and_dry_run(monkeypatch) -> None:
    """Command-level options keep template and chain loading independently selectable."""
    command = init_prompt_templates.Command(stdout=StringIO())
    monkeypatch.setattr(init_prompt_templates.transaction, "atomic", nullcontext)
    calls: list[tuple[str, bool, bool]] = []
    monkeypatch.setattr(
        command,
        "load_templates",
        lambda force, dry: calls.append(("templates", force, dry)) or (2, 1),
    )
    monkeypatch.setattr(
        command,
        "load_chains",
        lambda force, dry: calls.append(("chains", force, dry)) or (3, 2),
    )
    command.handle(
        force=True,
        chains_only=False,
        templates_only=False,
        dry_run=True,
    )
    assert calls == [("templates", True, True), ("chains", True, True)]
    assert "DRY RUN" in command.stdout.getvalue()
    assert "Prompt模板: 2" in command.stdout.getvalue()
    assert "链配置: 3 个已加载, 2 个已跳过" in command.stdout.getvalue()

    calls.clear()
    command.handle(
        force=False,
        chains_only=True,
        templates_only=False,
        dry_run=False,
    )
    assert calls == [("chains", False, False)]


def test_prompt_and_chain_loaders_cover_create_update_skip_and_dry_run(monkeypatch) -> None:
    """Each fixture row is created, updated, preserved, or previewed deterministically."""
    fixtures = [
        SimpleNamespace(name="existing", value=1),
        SimpleNamespace(name="new", value=2),
    ]
    monkeypatch.setattr(init_prompt_templates, "get_predefined_templates", lambda: fixtures)
    monkeypatch.setattr(init_prompt_templates, "get_predefined_chains", lambda: fixtures)
    existing = {"existing": SimpleNamespace(pk=7)}
    monkeypatch.setattr(
        init_prompt_templates,
        "PromptTemplateORM",
        SimpleNamespace(_default_manager=_Lookup(existing)),
    )
    monkeypatch.setattr(
        init_prompt_templates,
        "ChainConfigORM",
        SimpleNamespace(_default_manager=_Lookup(existing)),
    )
    prompt_calls: list[tuple[str, str]] = []
    chain_calls: list[tuple[str, str]] = []

    class _PromptRepo:
        def update_template(self, template_id: int, template: object) -> object:
            prompt_calls.append(("update", template.name))
            return template

        def create_template(self, template: object) -> None:
            prompt_calls.append(("create", template.name))

    class _ChainRepo:
        def update_chain(self, chain_id: int, chain: object) -> object:
            chain_calls.append(("update", chain.name))
            return chain

        def create_chain(self, chain: object) -> None:
            chain_calls.append(("create", chain.name))

    monkeypatch.setattr(init_prompt_templates, "DjangoPromptRepository", _PromptRepo)
    monkeypatch.setattr(init_prompt_templates, "DjangoChainRepository", _ChainRepo)
    command = init_prompt_templates.Command(stdout=StringIO())

    assert command.load_templates(force=False, dry_run=False) == (1, 1)
    assert prompt_calls == [("create", "new")]
    assert command.load_templates(force=True, dry_run=False) == (2, 0)
    assert ("update", "existing") in prompt_calls
    assert command.load_templates(force=True, dry_run=True) == (2, 0)

    assert command.load_chains(force=False, dry_run=False) == (1, 1)
    assert chain_calls == [("create", "new")]
    assert command.load_chains(force=True, dry_run=False) == (2, 0)
    assert ("update", "existing") in chain_calls
    assert command.load_chains(force=True, dry_run=True) == (2, 0)


def test_prompt_command_rejects_invalid_options_before_loading(monkeypatch) -> None:
    """Dynamic callers cannot bypass boolean and mutually-exclusive CLI contracts."""

    command = init_prompt_templates.Command(stdout=StringIO())
    loaded: list[str] = []
    monkeypatch.setattr(
        command,
        "load_templates",
        lambda force, dry_run: loaded.append("templates") or (0, 0),
    )
    monkeypatch.setattr(
        command,
        "load_chains",
        lambda force, dry_run: loaded.append("chains") or (0, 0),
    )

    with pytest.raises(CommandError, match="force must be a boolean"):
        command.handle(force="yes")
    with pytest.raises(CommandError, match="mutually exclusive"):
        command.handle(chains_only=True, templates_only=True)

    assert loaded == []


def test_prompt_command_failure_is_nonzero_sanitized_and_not_reported_complete(monkeypatch) -> None:
    """A fixture failure propagates without leaking its raw error or printing success."""

    command = init_prompt_templates.Command(stdout=StringIO())
    monkeypatch.setattr(init_prompt_templates.transaction, "atomic", nullcontext)
    monkeypatch.setattr(
        command,
        "load_templates",
        lambda force, dry_run: (_ for _ in ()).throw(RuntimeError("database token=secret")),
    )

    with pytest.raises(CommandError, match=r"failed \(RuntimeError\)") as exc_info:
        command.handle(templates_only=True)

    combined_output = f"{exc_info.value}\n{command.stdout.getvalue()}"
    assert "secret" not in combined_output
    assert "初始化完成" not in combined_output


def test_prompt_compatibility_loaders_delegate_management_command(monkeypatch) -> None:
    """Legacy entry points retain their count contract while delegating initialization."""
    calls: list[tuple[object, ...]] = []
    import django.core.management

    monkeypatch.setattr(
        django.core.management,
        "call_command",
        lambda *args: calls.append(args),
    )
    monkeypatch.setattr(
        init_prompt_templates,
        "get_predefined_templates",
        lambda: [1, 2],
    )
    monkeypatch.setattr(
        init_prompt_templates,
        "get_predefined_chains",
        lambda: [1, 2, 3],
    )
    assert init_prompt_templates.load_predefined_templates(repository=object()) == 2
    assert init_prompt_templates.load_predefined_chains(repository=object()) == 3
    assert calls == [
        ("init_prompt_templates", "--templates-only", "--force"),
        ("init_prompt_templates", "--chains-only", "--force"),
    ]


def test_prompt_compatibility_script_delegates_without_import_side_effect(monkeypatch) -> None:
    """The legacy script owns no fixtures and delegates only when main is called."""

    import django.core.management

    from scripts import init_prompt_templates as compatibility_script

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    setup_calls: list[bool] = []
    monkeypatch.setattr(
        compatibility_script,
        "_setup_django",
        lambda: setup_calls.append(True),
    )
    monkeypatch.setattr(
        django.core.management,
        "call_command",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert setup_calls == []
    compatibility_script.main()

    assert setup_calls == [True]
    assert calls == [(("init_prompt_templates",), {"force": True})]
