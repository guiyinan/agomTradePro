"""Export the runtime provider settings snapshot for release rehearsals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.application.interface_services import load_provider_settings_payload


class Command(BaseCommand):
    """Print the exact provider policy payload consumed by the preflight gate.

    The S6 ``production_policy_parity`` stage and the read-only preflight both
    accept ``--provider-settings-json``; this command produces that snapshot
    from the live Config Center runtime profile so the exported bytes are by
    construction identical to what production evaluates. The command is
    strictly read-only: a blocked payload is exported verbatim so the
    preflight reproduces the production block instead of hiding it.
    """

    help = (
        "Export the Config Center provider runtime settings as the JSON "
        "snapshot accepted by preflight_full_market_publication and the S6 "
        "--provider-settings-json input; strictly read-only."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the optional exclusive output path."""

        parser.add_argument(
            "--output",
            type=Path,
            default=None,
            help="Optional snapshot path; created exclusively, never overwritten.",
        )

    def handle(self, *args: object, **options: Any) -> None:
        """Export the snapshot and report raw and canonical sha256 digests."""

        del args
        payload = load_provider_settings_payload()
        raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )
        raw_digest = hashlib.sha256(raw).hexdigest()
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
        canonical_digest = hashlib.sha256(canonical).hexdigest()
        output = options.get("output")
        if output is not None:
            path = Path(output)
            if path.is_symlink() or path.exists():
                raise CommandError(f"snapshot output already exists: {path}")
            with path.open("xb") as stream:
                stream.write(raw)
        else:
            self.stdout.write(raw.decode("utf-8"))
        # Keep stdout machine-consumable: the summary digest goes to stderr so
        # `export_provider_settings_snapshot > provider-settings.json` yields a
        # file that --provider-settings-json accepts verbatim.
        self.stderr.write(
            json.dumps(
                {
                    "outcome": "exported",
                    "provider_settings_raw_file_sha256": raw_digest,
                    "provider_settings_canonical_payload_sha256": canonical_digest,
                    "status": payload.get("status"),
                    **({"output": str(output)} if output is not None else {}),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
