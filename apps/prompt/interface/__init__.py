"""
Prompt interface compatibility exports.

Keep the historical ``apps.prompt.interface`` import surface stable for tests
and callers that still reference the init command from this package root.
"""

from apps.prompt.infrastructure.fixtures.templates import (
    get_predefined_chains,
    get_predefined_templates,
)
from apps.prompt.infrastructure.repositories import (
    DjangoChainRepository,
    DjangoPromptRepository,
)
from apps.prompt.management.commands import init_prompt_templates as _command_module


class Command(_command_module.Command):
    """Compatibility wrapper around the prompt init management command."""

    def _sync_dependencies(self) -> None:
        _command_module.get_predefined_templates = get_predefined_templates
        _command_module.get_predefined_chains = get_predefined_chains
        _command_module.DjangoPromptRepository = DjangoPromptRepository
        _command_module.DjangoChainRepository = DjangoChainRepository

    def handle(self, *args, **options):
        self._sync_dependencies()
        return super().handle(*args, **options)

    def load_templates(self, force: bool, dry_run: bool) -> tuple:
        self._sync_dependencies()
        return super().load_templates(force=force, dry_run=dry_run)

    def load_chains(self, force: bool, dry_run: bool) -> tuple:
        self._sync_dependencies()
        return super().load_chains(force=force, dry_run=dry_run)


__all__ = [
    "Command",
    "DjangoChainRepository",
    "DjangoPromptRepository",
    "get_predefined_chains",
    "get_predefined_templates",
]
