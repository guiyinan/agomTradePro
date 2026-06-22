"""Export Django model and domain dataclass contracts for AgomTUI compile time."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand

from apps.terminal.infrastructure.tui_contract_export import (
    DEFAULT_TUI_CONTRACT_APP_LABELS,
    DEFAULT_TUI_DOMAIN_CLASS_PATHS,
    write_tui_django_contract_manifest,
)


class Command(BaseCommand):
    """Write one machine-readable contract manifest for AgomTUI collectors."""

    help = (
        "Export Django model and DDD dataclass contracts as JSON evidence for "
        "AgomTUI compile-time metadata generation."
    )

    def add_arguments(self, parser) -> None:
        """Register command-line arguments."""

        parser.add_argument(
            "--output",
            required=True,
            help="Output JSON path for the generated contract manifest.",
        )
        parser.add_argument(
            "--app-label",
            action="append",
            default=list(DEFAULT_TUI_CONTRACT_APP_LABELS),
            help="Django app label to scan for ORM models. Repeatable.",
        )
        parser.add_argument(
            "--model",
            action="append",
            default=[],
            help="Optional dotted Django model path. Repeatable and overrides app scan scope when provided.",
        )
        parser.add_argument(
            "--domain-class",
            action="append",
            default=list(DEFAULT_TUI_DOMAIN_CLASS_PATHS),
            help="Dotted dataclass path exported as a DDD aggregate contract. Repeatable.",
        )
        parser.add_argument(
            "--indent",
            type=int,
            default=2,
            help="Pretty-print JSON indentation width.",
        )

    def handle(self, *args, **options) -> None:
        """Export the requested manifest and print a concise summary."""

        output_path = Path(options["output"]).resolve()
        payload = write_tui_django_contract_manifest(
            output_path,
            app_labels=list(options["app_label"] or []),
            model_paths=list(options["model"] or []),
            domain_class_paths=list(options["domain_class"] or []),
            indent=int(options["indent"]),
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Exported AgomTUI Django contracts "
                f"to {output_path} "
                f"(models={len(payload['models'])}, aggregates={len(payload['aggregates'])})"
            )
        )
