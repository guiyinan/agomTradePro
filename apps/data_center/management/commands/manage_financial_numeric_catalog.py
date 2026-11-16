"""Apply or revoke one exact financial numeric qualification as an authenticated Owner."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from getpass import getpass
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS

from apps.data_center.application.egress_service import execute_provider_document_request
from apps.data_center.application.financial_numeric_catalog import (
    CaptureFinancialNumericSourceDocumentUseCase,
    FinancialNumericSourceCatalogUseCase,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
    FinancialNumericSourceQualification,
)
from apps.data_center.infrastructure.financial_numeric_catalog_capture_repository import (
    DjangoFinancialNumericSourceCaptureRepository,
)
from apps.data_center.infrastructure.financial_numeric_catalog_repository import (
    DjangoFinancialMetricSourceCatalogRepository,
)
from apps.data_center.infrastructure.statutory_source_body_store import (
    StatutorySourceBodyStore,
)
from core.exceptions import DataFetchError, DataValidationError


class _AuthenticatedOwnerAccount(Protocol):
    """Minimal user shape returned by Django's configured authentication backend."""

    pk: object
    is_active: bool
    is_superuser: bool

    def get_username(self) -> str:
        """Return the exact configured Django username field."""
        ...


class Command(BaseCommand):
    """Record an immutable Owner apply/revoke event for one exact qualification."""

    help = "Apply or revoke one exact native financial metric source qualification."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Require the event action, exact payload identity, and Django login name."""

        parser.add_argument("action", choices=("capture", "apply", "revoke"))
        parser.add_argument(
            "--owner",
            required=True,
            help="Exact Django username used for interactive credential authentication",
        )
        parser.add_argument("--qualification-file")
        parser.add_argument("--provider-id", type=int)
        parser.add_argument("--dataset-key")
        parser.add_argument("--deployment-region")
        parser.add_argument("--issuer")
        parser.add_argument("--document-id")
        parser.add_argument("--url")
        parser.add_argument("--max-bytes", type=int)
        parser.add_argument("--media-type", action="append")
        parser.add_argument("--entry-id")
        parser.add_argument("--qualification-identity")
        parser.add_argument("--qualification-sha256")
        parser.add_argument("--database", default=DEFAULT_DB_ALIAS)

    def handle(self, *args: object, **options: object) -> str:
        """Authenticate an active superuser, then append exactly one catalog event."""

        del args
        action = options.get("action")
        owner = options.get("owner")
        database = options.get("database")
        if (
            type(action) is not str
            or action not in {"capture", "apply", "revoke"}
            or type(owner) is not str
            or not owner
            or owner != owner.strip()
            or type(database) is not str
            or not database
            or database != database.strip()
        ):
            raise CommandError("financial numeric catalog command input is invalid")
        if database != DEFAULT_DB_ALIAS:
            raise CommandError(
                "financial numeric catalog Owner authentication is only supported on the default database"
            )
        owner_user = self._authenticate_owner(owner)
        actor_id = owner_user.pk
        if type(actor_id) is not int:
            raise CommandError("financial numeric catalog requires an integer Django user id")
        if action == "capture":
            reference = self._capture_document(options, database)
            return json.dumps(
                reference.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        service = self._service(database)
        if action == "apply":
            qualification_file = options.get("qualification_file")
            if type(qualification_file) is not str or not qualification_file.strip():
                raise CommandError(
                    "apply requires --qualification-file with exact qualification JSON"
                )
            qualification = self._read_qualification(Path(qualification_file))
            entry_id = service.apply(
                qualification,
                actor_id=actor_id,
                actor_username=owner_user.get_username(),
            )
            return f"Applied exact financial numeric qualification entry {entry_id}."

        entry_id = self._uuid_option(options, "entry_id")
        identity = options.get("qualification_identity")
        body_hash = options.get("qualification_sha256")
        if (
            type(identity) is not str
            or not identity
            or identity != identity.strip()
            or type(body_hash) is not str
            or len(body_hash) != 64
            or any(character not in "0123456789abcdef" for character in body_hash)
        ):
            raise CommandError("revoke requires exact qualification identity and SHA-256")
        event_id = service.revoke(
            entry_id,
            expected_qualification_identity=identity,
            expected_qualification_sha256=body_hash,
            actor_id=actor_id,
            actor_username=owner_user.get_username(),
        )
        return f"Recorded financial numeric qualification revocation event {event_id}."

    def _authenticate_owner(self, username: str) -> _AuthenticatedOwnerAccount:
        """Authenticate the exact named Django account and require active superuser status."""

        user_model = get_user_model()
        username_field = user_model.USERNAME_FIELD
        try:
            password = getpass("Financial numeric catalog Owner password: ")
        except (EOFError, OSError) as error:
            raise CommandError("Owner event requires interactive Django authentication") from error
        authenticated: object = authenticate(
            request=None,
            **{username_field: username, "password": password},
        )
        if authenticated is None:
            raise CommandError(
                "financial numeric Owner event requires the exact active authenticated superuser"
            )
        owner_user = cast(_AuthenticatedOwnerAccount, authenticated)
        if (
            type(owner_user.is_active) is not bool
            or owner_user.is_active is not True
            or type(owner_user.is_superuser) is not bool
            or owner_user.is_superuser is not True
            or owner_user.get_username() != username
        ):
            raise CommandError(
                "financial numeric Owner event requires the exact active authenticated superuser"
            )
        return owner_user

    @staticmethod
    def _uuid_option(options: dict[str, object], key: str) -> UUID:
        """Parse one canonical UUID without coercing unrelated option values."""

        raw_value = options.get(key)
        if type(raw_value) is not str:
            raise CommandError(f"revoke requires --{key.replace('_', '-')} as a canonical UUID")
        try:
            value = UUID(raw_value)
        except ValueError as error:
            raise CommandError(f"--{key.replace('_', '-')} must be a canonical UUID") from error
        if str(value) != raw_value:
            raise CommandError(f"--{key.replace('_', '-')} must be a canonical UUID")
        return value

    @staticmethod
    def _read_qualification(path: Path) -> FinancialNumericSourceQualification:
        """Read a strict versioned payload; no payload field can assert Owner approval."""

        try:
            with path.open("r", encoding="utf-8") as stream:
                raw_payload: object = json.load(stream)
            qualification = FinancialNumericSourceQualification.from_payload(raw_payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise CommandError(
                "qualification JSON is missing, malformed, or unsupported"
            ) from error
        return qualification

    @staticmethod
    def _service(database: str) -> FinancialNumericSourceCatalogUseCase:
        """Build the command-only service from explicit retained-body settings."""

        raw_root: object = getattr(settings, "FINANCIAL_NUMERIC_SOURCE_BODY_ROOT", None)
        raw_limit: object = getattr(settings, "FINANCIAL_NUMERIC_SOURCE_BODY_MAX_BYTES", None)
        if (
            not isinstance(raw_root, (str, Path))
            or not str(raw_root).strip()
            or type(raw_limit) is not int
            or raw_limit <= 0
        ):
            raise CommandError(
                "financial numeric retained-body root and positive byte limit are not configured"
            )
        body_store = StatutorySourceBodyStore(Path(raw_root), max_body_bytes=raw_limit)
        capture_repository = DjangoFinancialNumericSourceCaptureRepository(
            body_store=body_store,
            using=database,
        )
        repository = DjangoFinancialMetricSourceCatalogRepository(
            capture_repository=capture_repository,
            using=database,
        )
        return FinancialNumericSourceCatalogUseCase(repository)

    @staticmethod
    def _capture_document(
        options: dict[str, object],
        database: str,
    ) -> FinancialNumericSourceDocumentCaptureReference:
        """Capture a documentation URL only through the configured egress service."""

        provider_id = options.get("provider_id")
        dataset_key = options.get("dataset_key")
        deployment_region = options.get("deployment_region")
        issuer = options.get("issuer")
        document_id = options.get("document_id")
        canonical_url = options.get("url")
        max_bytes = options.get("max_bytes")
        raw_media_types = options.get("media_type")
        if (
            type(provider_id) is not int
            or type(dataset_key) is not str
            or type(deployment_region) is not str
            or type(issuer) is not str
            or type(document_id) is not str
            or type(canonical_url) is not str
            or type(max_bytes) is not int
            or type(raw_media_types) is not list
            or any(type(media_type) is not str for media_type in raw_media_types)
        ):
            raise CommandError(
                "capture requires provider, dataset, region, issuer, document id, URL, byte limit, and media type"
            )
        root_raw: object = getattr(settings, "FINANCIAL_NUMERIC_SOURCE_BODY_ROOT", None)
        store_limit: object = getattr(settings, "FINANCIAL_NUMERIC_SOURCE_BODY_MAX_BYTES", None)
        if (
            not isinstance(root_raw, (str, Path))
            or not str(root_raw).strip()
            or type(store_limit) is not int
            or store_limit <= 0
            or max_bytes > store_limit
        ):
            raise CommandError(
                "financial numeric retained-body root or sufficient positive byte limit is not configured"
            )
        body_store = StatutorySourceBodyStore(Path(root_raw), max_body_bytes=store_limit)
        capture_repository = DjangoFinancialNumericSourceCaptureRepository(
            body_store=body_store,
            using=database,
        )
        use_case = CaptureFinancialNumericSourceDocumentUseCase(
            document_fetch=execute_provider_document_request,
            capture_repository=capture_repository,
            provider_id=provider_id,
            dataset_key=dataset_key,
            deployment_region=deployment_region,
        )
        try:
            return use_case.execute(
                issuer=issuer,
                document_id=document_id,
                canonical_url=canonical_url,
                max_bytes=max_bytes,
                allowed_media_types=frozenset(cast(list[str], raw_media_types)),
            )
        except (DataFetchError, DataValidationError, OSError, ValueError) as error:
            raise CommandError("controlled document capture was blocked") from error


__all__ = ["Command"]
