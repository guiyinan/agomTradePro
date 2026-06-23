"""Publish reviewed AgomTradePro TUI metadata JSON to the database registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _file_hash(root: Path, value: str) -> str:
    if not value:
        return ""
    path = (root / value).resolve() if not Path(value).is_absolute() else Path(value)
    if not path.exists():
        print(f"Source evidence file not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish reviewed TUI metadata to the DB registry.")
    parser.add_argument("path", help="Path to reviewed TUI metadata JSON")
    parser.add_argument("--registry-key", default="default")
    parser.add_argument("--approved-by-username", default="")
    parser.add_argument("--generation-source", choices=("ai", "manual", "mixed"), default="mixed")
    parser.add_argument("--backend-version", default="")
    parser.add_argument("--source-evidence-path", default="")
    parser.add_argument("--review-note", required=True)
    parser.add_argument("--approve", action="store_true", help="Required guard flag for DB writes")
    args = parser.parse_args()

    if not args.approve:
        print("Refusing to write DB registry without --approve", file=sys.stderr)
        return 2
    if len(args.review_note.strip()) < 8:
        print("Refusing to publish without a meaningful --review-note", file=sys.stderr)
        return 2

    root = _repo_root()
    sys.path.insert(0, str(root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development_sqlite")

    import django

    django.setup()

    from django.contrib.auth import get_user_model

    from apps.terminal.infrastructure.tui_metadata_repository import PublishedTuiMetadataRepository

    path = (root / args.path).resolve() if not Path(args.path).is_absolute() else Path(args.path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    user = None
    if args.approved_by_username:
        user = get_user_model()._default_manager.filter(username=args.approved_by_username).first()
        if user is None:
            print(f"Approved-by user not found: {args.approved_by_username}", file=sys.stderr)
            return 2

    model = PublishedTuiMetadataRepository().publish_payload(
        payload=payload,
        registry_key=args.registry_key,
        approved_by=user,
        review_note=args.review_note,
        generation_source=args.generation_source,
        backend_version=args.backend_version,
        source_evidence_hash=_file_hash(root, args.source_evidence_path),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "registry_id": model.pk,
                "registry_key": model.registry_key,
                "status": model.status,
                "schema_version": model.schema_version,
                "generation_source": model.generation_source,
                "backend_version": model.backend_version,
                "source_hash": model.source_hash,
                "source_evidence_hash": model.source_evidence_hash,
                "changed_fields": model.changed_fields,
                "published_at": model.published_at.isoformat() if model.published_at else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
