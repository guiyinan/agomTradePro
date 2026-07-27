"""Regression tests for prompt init force-update consistency."""

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management.base import CommandError
from django.test import TestCase

from apps.prompt.infrastructure.fixtures.templates import (
    get_predefined_chains,
    get_predefined_templates,
)
from apps.prompt.infrastructure.models import ChainConfigORM, PromptTemplateORM
from apps.prompt.management.commands import init_prompt_templates


@pytest.mark.django_db
class TestPromptInitCommandConsistency(TestCase):
    """Ensure forced prompt init updates in place instead of delete-then-create."""

    def test_force_template_update_preserves_existing_record_on_failure(self) -> None:
        """A failed force update should keep the original template record intact."""
        template = get_predefined_templates()[0]
        existing = PromptTemplateORM.objects.create(
            name=template.name,
            category=template.category.value,
            version="old",
            template_content="old content",
            system_prompt="old system",
            placeholders=[],
            temperature=0.5,
            max_tokens=100,
            description="old desc",
            is_active=True,
        )
        command = init_prompt_templates.Command(stdout=StringIO())

        with patch.object(
            init_prompt_templates, "get_predefined_templates", return_value=[template]
        ):
            with patch(
                "apps.prompt.management.commands.init_prompt_templates."
                "DjangoPromptRepository.update_template",
                side_effect=RuntimeError("boom"),
            ):
                with pytest.raises(RuntimeError, match="boom"):
                    command.load_templates(force=True, dry_run=False)

        existing.refresh_from_db()

        self.assertEqual(PromptTemplateORM.objects.filter(name=template.name).count(), 1)
        self.assertEqual(existing.template_content, "old content")

    def test_force_chain_update_updates_existing_record_in_place(self) -> None:
        """Forced chain updates should reuse the existing row instead of deleting it."""
        chain = get_predefined_chains()[0]
        existing = ChainConfigORM.objects.create(
            name=chain.name,
            category=chain.category.value,
            description="old chain",
            steps=[],
            execution_mode="serial",
            aggregate_step=None,
            is_active=False,
        )
        command = init_prompt_templates.Command(stdout=StringIO())

        with patch.object(init_prompt_templates, "get_predefined_chains", return_value=[chain]):
            count, skipped = command.load_chains(force=True, dry_run=False)

        existing.refresh_from_db()

        self.assertEqual(count, 1)
        self.assertEqual(skipped, 0)
        self.assertEqual(ChainConfigORM.objects.filter(name=chain.name).count(), 1)
        self.assertEqual(existing.description, chain.description)
        self.assertEqual(existing.execution_mode, chain.execution_mode.value)

    def test_handle_rolls_back_template_update_when_chain_loading_fails(self) -> None:
        """A later chain failure rolls back earlier template writes and stays sanitized."""

        template = get_predefined_templates()[0]
        existing = PromptTemplateORM.objects.create(
            name=template.name,
            category=template.category.value,
            version="old",
            template_content="old content",
            system_prompt="old system",
            placeholders=[],
            temperature=0.5,
            max_tokens=100,
            description="old desc",
            is_active=False,
        )
        command = init_prompt_templates.Command(stdout=StringIO())

        with (
            patch.object(
                init_prompt_templates,
                "get_predefined_templates",
                return_value=[template],
            ),
            patch.object(
                init_prompt_templates,
                "get_predefined_chains",
                side_effect=RuntimeError("database token=secret"),
            ),
        ):
            with pytest.raises(CommandError, match=r"failed \(RuntimeError\)") as exc_info:
                command.handle(force=True)

        existing.refresh_from_db()
        combined_output = f"{exc_info.value}\n{command.stdout.getvalue()}"
        self.assertEqual(existing.template_content, "old content")
        self.assertNotIn("secret", combined_output)
        self.assertNotIn("初始化完成", combined_output)


def test_prompt_interface_package_has_no_management_exports() -> None:
    """Importing the HTTP package root must not expose management or ORM helpers."""

    from apps.prompt import interface

    assert interface.__all__ == ()
    assert not hasattr(interface, "Command")
    assert not hasattr(interface, "DjangoPromptRepository")
