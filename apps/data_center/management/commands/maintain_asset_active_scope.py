"""Apply an exact, hash-bound five-row maintenance plan as a real Django Owner."""

from __future__ import annotations

import json
import os
import stat
from argparse import ArgumentParser
from dataclasses import asdict
from pathlib import Path

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.management.base import BaseCommand, CommandError

from apps.data_center.application.asset_active_maintenance import AssetActiveMaintenanceError
from apps.data_center.domain.asset_active_maintenance import AssetActiveMaintenanceContractError
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceSourceContractError,
)
from apps.data_center.infrastructure.asset_active_maintenance_plan import decode_plan
from core.integration.asset_active_maintenance_composition import (
    create_asset_active_maintenance_use_case,
)


class Command(BaseCommand):
    """Run the explicit maintenance plan without provider requests or migrations."""

    help = "Apply one exact five-row AssetMaster active-scope maintenance plan."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Require an exact plan hash and normal Owner credentials over a private FD."""

        parser.add_argument("--plan-file", required=True)
        parser.add_argument("--plan-sha256", required=True)
        parser.add_argument("--owner", required=True)
        parser.add_argument("--password-fd", required=True, type=int)

    def handle(self, *args: object, **options: object) -> str:
        """Authenticate, verify the immutable plan bytes, then execute the guarded UOW."""

        del args
        owner = _text_option(options, "owner")
        plan_path = Path(_text_option(options, "plan_file"))
        plan_hash = _text_option(options, "plan_sha256")
        password = _read_password(options.get("password_fd"))
        try:
            user_object: object = authenticate(
                request=None,
                **{get_user_model().USERNAME_FIELD: owner, "password": password},
            )
        finally:
            del password
        if not isinstance(user_object, AbstractBaseUser):
            raise CommandError("asset maintenance Owner authentication failed")
        user = user_object
        if (
            user.get_username() != owner
            or not user.is_active
            or not user.is_authenticated
            or type(user.pk) is not int
            or user.pk <= 0
        ):
            raise CommandError("asset maintenance Owner authentication failed")
        try:
            plan = decode_plan(_read_plan(plan_path), expected_sha256=plan_hash)
            result = create_asset_active_maintenance_use_case(authenticated_user=user).execute(
                plan,
                expected_plan_file_sha256=plan_hash,
            )
        except (
            AssetActiveMaintenanceContractError,
            AssetActiveMaintenanceError,
            InstrumentReferenceSourceContractError,
        ) as error:
            raise CommandError(f"asset maintenance blocked: {error.code}") from error
        return json.dumps(asdict(result), sort_keys=True, separators=(",", ":"))


def _text_option(options: dict[str, object], name: str) -> str:
    """Narrow a required exact text option without coercion or whitespace edits."""

    value = options.get(name)
    if type(value) is not str or not value or value != value.strip():
        raise CommandError(f"asset maintenance option invalid: {name}")
    return value


def _read_password(descriptor: object) -> str:
    """Consume and close a bounded anonymous pipe/socket, never a file or stdio FD."""

    if type(descriptor) is not int or descriptor < 3:
        raise CommandError("asset maintenance requires a private password FD >= 3")
    try:
        mode = os.fstat(descriptor).st_mode
        if not (stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode)):
            raise CommandError("asset maintenance password FD must be a pipe or socket")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            raw = stream.read(4097)
        if not raw or len(raw) > 4096 or b"\x00" in raw:
            raise CommandError("asset maintenance password input invalid")
        return raw.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as error:
        raise CommandError("asset maintenance password input unavailable") from error


def _read_plan(path: Path) -> bytes:
    """Read a single bounded regular plan file and avoid symlink substitution."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= 64 * 1024:
                raise CommandError("asset maintenance plan file invalid")
            raw = stream.read(64 * 1024 + 1)
        if len(raw) != metadata.st_size:
            raise CommandError("asset maintenance plan file changed during read")
        return raw
    except OSError as error:
        raise CommandError("asset maintenance plan file unavailable") from error
