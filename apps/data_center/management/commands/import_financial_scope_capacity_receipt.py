"""Import one validated S6 financial capacity bundle into the production ledger."""

from __future__ import annotations

from argparse import ArgumentParser
from getpass import getpass
from pathlib import Path

from django.contrib.auth import authenticate, get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.data_center.application.financial_scope_capacity_import import (
    FinancialScopeCapacityImportError,
)
from apps.data_center.infrastructure.financial_scope_capacity_import_runtime import (
    import_financial_scope_capacity_bundle,
)


class Command(BaseCommand):
    """Revalidate and append a copied S6 evidence graph without refreshing facts."""

    help = "Import one current full-scope S6 financial capacity evidence bundle."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Require an exact bundle directory and separately authenticated operator."""

        parser.add_argument("--bundle-dir", required=True, type=Path)
        parser.add_argument("--actor", required=True, help="Username of the governance superuser")

    def handle(
        self,
        *args: object,
        bundle_dir: Path,
        actor: str,
        **options: object,
    ) -> str:
        """Authenticate the operator and append one immutable import ledger record."""

        actor_name = self._authenticate_actor(actor)
        try:
            imported = import_financial_scope_capacity_bundle(
                bundle_dir=bundle_dir,
                imported_by=actor_name,
            )
        except FinancialScopeCapacityImportError as exc:
            raise CommandError(exc.code.lower()) from None
        except (OSError, RuntimeError, TypeError, ValueError):
            raise CommandError("financial scope capacity import was rejected") from None
        message = (
            "Imported S6 financial scope capacity evidence "
            f"{imported.import_id} ({imported.record_sha256})."
        )
        self.stdout.write(self.style.SUCCESS(message))
        return message

    @staticmethod
    def _authenticate_actor(actor: str) -> str:
        """Require a valid interactive Django superuser without recording credentials."""

        user_model = get_user_model()
        try:
            password = getpass("Superuser password: ")
        except (EOFError, OSError) as exc:
            raise CommandError(
                "financial scope capacity import requires interactive superuser auth"
            ) from exc
        user = authenticate(
            request=None,
            **{user_model.USERNAME_FIELD: actor, "password": password},
        )
        if user is None or user.is_superuser is not True:
            raise CommandError("financial scope capacity import requires a Django superuser")
        return user.get_username()


__all__ = ["Command"]
