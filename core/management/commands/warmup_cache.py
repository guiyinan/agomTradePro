"""Warm critical deployment caches with verified all-or-restore semantics."""

from __future__ import annotations

import time
from dataclasses import dataclass

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError, CommandParser

ALLOWED_TARGETS = frozenset({"regime", "macro", "alpha"})
TARGET_ORDER = ("regime", "macro", "alpha")
MACRO_LIMIT = 50
ALPHA_LIMIT = 100
CACHE_TIMEOUT_SECONDS = 3600
_MISSING = object()


@dataclass(frozen=True)
class CacheEntry:
    """One validated cache write prepared before mutation begins."""

    key: str
    value: object
    timeout: int = CACHE_TIMEOUT_SECONDS


@dataclass(frozen=True)
class WarmupTargetResult:
    """Prepared entries and user-facing target summary."""

    target: str
    entries: tuple[CacheEntry, ...]
    summary: str


class Command(BaseCommand):
    """Prepare and verify selected critical caches after deployment."""

    help = "Warm caches for regime state, macro indicators, and alpha scores."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register strict target and intentional-empty options."""

        parser.add_argument(
            "--only",
            type=str,
            default="",
            help="Comma-separated targets: regime, macro, alpha. Default: all.",
        )
        parser.add_argument(
            "--allow-empty",
            action="store_true",
            help="Allow selected sources with no rows during an intentional cold start.",
        )

    def handle(self, *args: object, **options: object) -> None:
        """Prepare every target, then write all entries with rollback on failure."""

        del args
        targets = self._parse_targets(options.get("only", ""))
        allow_empty = options.get("allow_empty", False)
        if not isinstance(allow_empty, bool):
            raise CommandError("--allow-empty must be a boolean")

        self.stdout.write(self.style.MIGRATE_HEADING("Cache Warmup"))
        prepared: list[WarmupTargetResult] = []
        for target in TARGET_ORDER:
            if target not in targets:
                continue
            start = time.monotonic()
            try:
                result = self._prepare_target(target)
            except Exception as exc:
                raise CommandError(
                    f"{target} cache warmup preparation failed: {type(exc).__name__}"
                ) from exc
            if not result.entries and not allow_empty:
                raise CommandError(f"{target} cache warmup has no data")
            elapsed = time.monotonic() - start
            status = "SKIP" if not result.entries else "READY"
            self.stdout.write(f"  {target}: {status} ({elapsed:.1f}s) - {result.summary}")
            prepared.append(result)

        entries = tuple(entry for result in prepared for entry in result.entries)
        self._validate_unique_keys(entries)
        self._write_entries(entries)
        self.stdout.write(self.style.SUCCESS("\nCache warmup complete."))

    @staticmethod
    def _parse_targets(raw_value: object) -> set[str]:
        """Return a validated target set without silently ignoring unknown names."""

        if not isinstance(raw_value, str):
            raise CommandError("--only must be a comma-separated string")
        requested = {part.strip().lower() for part in raw_value.split(",") if part.strip()}
        targets = requested or set(ALLOWED_TARGETS)
        unknown = targets.difference(ALLOWED_TARGETS)
        if unknown:
            raise CommandError(f"unknown cache warmup target: {sorted(unknown)[0]}")
        return targets

    def _prepare_target(self, target: str) -> WarmupTargetResult:
        """Dispatch one target preparation function."""

        if target == "regime":
            return self._prepare_regime()
        if target == "macro":
            return self._prepare_macro()
        if target == "alpha":
            return self._prepare_alpha()
        raise ValueError(f"unsupported cache target: {target}")

    @staticmethod
    def _prepare_regime() -> WarmupTargetResult:
        """Prepare the current Regime cache payload."""

        from apps.regime.application.query_services import get_latest_regime_cache_payload

        latest = get_latest_regime_cache_payload()
        if latest is None:
            return WarmupTargetResult("regime", (), "no regime data")
        if not isinstance(latest, dict):
            raise TypeError("regime payload must be a dictionary")
        regime = latest.get("regime")
        if not isinstance(regime, str) or not regime.strip():
            raise ValueError("regime payload must include a non-empty regime")
        return WarmupTargetResult(
            "regime",
            (CacheEntry("regime:current", dict(latest)),),
            regime,
        )

    @staticmethod
    def _prepare_macro() -> WarmupTargetResult:
        """Prepare latest canonical macro indicator cache entries."""

        from apps.data_center.application.query_services import (
            list_latest_macro_indicator_payloads,
        )

        rows = list(list_latest_macro_indicator_payloads(limit=MACRO_LIMIT))
        entries: list[CacheEntry] = []
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError("macro payload must be a dictionary")
            indicator_code = row.get("indicator_code")
            if not isinstance(indicator_code, str) or not indicator_code.strip():
                raise ValueError("macro payload must include indicator_code")
            entries.append(
                CacheEntry(
                    f"macro:latest:{indicator_code.strip().upper()}",
                    {
                        "value": row.get("value"),
                        "date": row.get("reporting_period"),
                    },
                )
            )
        return WarmupTargetResult("macro", tuple(entries), f"{len(entries)} indicators")

    @staticmethod
    def _prepare_alpha() -> WarmupTargetResult:
        """Prepare recent Alpha score-cache summaries."""

        from apps.alpha.application.query_services import (
            list_recent_alpha_score_cache_payloads,
        )

        rows = list(list_recent_alpha_score_cache_payloads(limit=ALPHA_LIMIT))
        entries: list[CacheEntry] = []
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError("alpha payload must be a dictionary")
            universe_id = row.get("universe_id")
            if not isinstance(universe_id, str) or not universe_id.strip():
                raise ValueError("alpha payload must include universe_id")
            entries.append(
                CacheEntry(
                    f"alpha:score:{universe_id.strip()}",
                    {
                        "provider": row.get("provider"),
                        "asof_date": row.get("asof_date"),
                        "status": row.get("status"),
                    },
                )
            )
        return WarmupTargetResult("alpha", tuple(entries), f"{len(entries)} scores")

    @staticmethod
    def _validate_unique_keys(entries: tuple[CacheEntry, ...]) -> None:
        """Reject ambiguous overwrite order before touching the cache."""

        seen: set[str] = set()
        for entry in entries:
            if entry.key in seen:
                raise CommandError(f"duplicate cache warmup key: {entry.key}")
            seen.add(entry.key)

    @staticmethod
    def _write_entries(entries: tuple[CacheEntry, ...]) -> None:
        """Write and round-trip verify entries, restoring prior values on failure."""

        previous: dict[str, object] = {}
        try:
            for entry in entries:
                previous[entry.key] = cache.get(entry.key, _MISSING)
        except Exception as exc:
            raise CommandError(f"cache warmup snapshot failed: {type(exc).__name__}") from exc

        written: list[str] = []
        try:
            for entry in entries:
                written.append(entry.key)
                cache.set(entry.key, entry.value, timeout=entry.timeout)
                if cache.get(entry.key, _MISSING) != entry.value:
                    raise RuntimeError(f"cache round-trip verification failed for {entry.key}")
        except Exception as exc:
            rollback_error: Exception | None = None
            for key in reversed(written):
                old_value = previous[key]
                try:
                    if old_value is _MISSING:
                        cache.delete(key)
                        if cache.get(key, _MISSING) is not _MISSING:
                            raise RuntimeError(f"cache rollback delete failed for {key}")
                    else:
                        cache.set(key, old_value, timeout=CACHE_TIMEOUT_SECONDS)
                        if cache.get(key, _MISSING) != old_value:
                            raise RuntimeError(f"cache rollback restore failed for {key}")
                except Exception as restore_exc:
                    if rollback_error is None:
                        rollback_error = restore_exc
            if rollback_error is not None:
                raise CommandError(
                    "cache warmup write failed: "
                    f"{type(exc).__name__}; rollback failed: "
                    f"{type(rollback_error).__name__}"
                ) from exc
            raise CommandError(f"cache warmup write failed: {type(exc).__name__}") from exc
