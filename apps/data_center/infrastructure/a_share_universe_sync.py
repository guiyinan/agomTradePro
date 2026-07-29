"""A-share universe synchronization from market metadata providers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from apps.data_center.domain.entities import AssetAlias, AssetMaster
from apps.data_center.domain.enums import AssetType, MarketExchange
from apps.data_center.infrastructure.orm_retry import retry_sqlite_locked_operation
from apps.data_center.infrastructure.repositories import AssetRepository


class AShareCodeNameProvider(Protocol):
    """Provider contract for current A-share code-name rows."""

    def load_code_names(self) -> list[dict[str, str]]:
        """Return rows with ``code`` and ``name`` keys."""


@dataclass(frozen=True)
class AShareUniverseSyncReport:
    """Summary of an A-share universe synchronization run."""

    source: str
    fetched_count: int
    active_count: int
    touched_count: int
    deactivated_count: int
    skipped_count: int
    sample_codes: list[str]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable payload."""

        return {
            "source": self.source,
            "fetched_count": self.fetched_count,
            "active_count": self.active_count,
            "touched_count": self.touched_count,
            "deactivated_count": self.deactivated_count,
            "skipped_count": self.skipped_count,
            "sample_codes": self.sample_codes,
        }


class AkshareAshareCodeNameProvider:
    """Load A-share code-name rows through AKShare."""

    source_name = "akshare.stock_info_a_code_name"

    def load_code_names(self) -> list[dict[str, str]]:
        """Fetch the A-share code-name table."""

        import akshare as ak

        frame = ak.stock_info_a_code_name()
        if frame is None or frame.empty:
            return []
        rows: list[dict[str, str]] = []
        for row in frame.to_dict("records"):
            rows.append(
                {
                    "code": str(row.get("code") or "").strip(),
                    "name": str(row.get("name") or "").strip(),
                }
            )
        return rows


class JsonFileAshareCodeNameProvider:
    """Load A-share code-name rows from a local JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.source_name = f"json_file:{self.path.name}"

    def load_code_names(self) -> list[dict[str, str]]:
        """Read code-name rows from a JSON file."""

        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("A-share universe input file must contain a row list")
        return [
            {
                "code": str(row.get("code") or "").strip(),
                "name": str(row.get("name") or "").strip(),
            }
            for row in rows
            if isinstance(row, dict)
        ]


class AShareUniverseSyncService:
    """Synchronize the Data Center active A-share universe."""

    def __init__(
        self,
        *,
        provider: AShareCodeNameProvider | None = None,
        asset_repo: AssetRepository | None = None,
    ) -> None:
        self._provider = provider or AkshareAshareCodeNameProvider()
        self._asset_repo = asset_repo or AssetRepository()

    def sync(self, *, deactivate_missing: bool = False) -> AShareUniverseSyncReport:
        """Upsert active A-share master rows and optionally deactivate stale rows."""

        source = getattr(self._provider, "source_name", self._provider.__class__.__name__)
        rows = self._provider.load_code_names()
        touched_codes: set[str] = set()
        skipped_count = 0

        for row in rows:
            code = self._canonicalize_a_share_code(str(row.get("code") or ""))
            name = str(row.get("name") or "").strip()
            if not code or not name or self._looks_delisted(name):
                skipped_count += 1
                continue
            asset = AssetMaster(
                code=code,
                name=name,
                short_name=name,
                asset_type=AssetType.STOCK,
                exchange=self._infer_exchange(code),
                is_active=True,
                extra={"universe_source": source},
            )

            def upsert_asset(asset_to_save: AssetMaster = asset) -> AssetMaster:
                return self._asset_repo.upsert(asset_to_save)

            retry_sqlite_locked_operation(upsert_asset)

            def upsert_alias(asset_code: str = code) -> AssetAlias:
                return self._asset_repo.upsert_alias(
                    AssetAlias(
                        asset_code=asset_code,
                        provider_name="akshare",
                        alias_code=asset_code.split(".", 1)[0],
                    )
                )

            retry_sqlite_locked_operation(upsert_alias)
            touched_codes.add(code)

        deactivated_count = 0
        if deactivate_missing:
            deactivated_count = self._deactivate_missing(touched_codes)

        return AShareUniverseSyncReport(
            source=source,
            fetched_count=len(rows),
            active_count=len(touched_codes),
            touched_count=len(touched_codes),
            deactivated_count=deactivated_count,
            skipped_count=skipped_count,
            sample_codes=sorted(touched_codes)[:20],
        )

    @staticmethod
    def _canonicalize_a_share_code(raw_code: str) -> str:
        base = str(raw_code or "").strip().upper()
        if not base:
            return ""
        if "." in base:
            base = base.split(".", 1)[0]
        if base.startswith("SH") or base.startswith("SZ") or base.startswith("BJ"):
            prefix = base[:2]
            symbol = base[2:]
            suffix = {"SH": "SH", "SZ": "SZ", "BJ": "BJ"}[prefix]
            return f"{symbol.zfill(6)}.{suffix}"
        symbol = base.zfill(6)
        if symbol.startswith(("600", "601", "603", "605", "688", "689", "900")):
            return f"{symbol}.SH"
        if symbol.startswith(("000", "001", "002", "003", "200", "300", "301")):
            return f"{symbol}.SZ"
        if symbol.startswith(("4", "8", "920")):
            return f"{symbol}.BJ"
        return ""

    @staticmethod
    def _infer_exchange(code: str) -> MarketExchange:
        if code.endswith(".SH"):
            return MarketExchange.SSE
        if code.endswith(".SZ"):
            return MarketExchange.SZSE
        if code.endswith(".BJ"):
            return MarketExchange.BSE
        return MarketExchange.OTHER

    @staticmethod
    def _looks_delisted(name: str) -> bool:
        normalized = str(name or "").strip()
        return normalized.endswith("退") or "退市" in normalized

    @staticmethod
    def _deactivate_missing(active_codes: set[str]) -> int:
        from apps.data_center.infrastructure.models import AssetMasterModel

        if not active_codes:
            return 0
        queryset = AssetMasterModel._default_manager.filter(
            asset_type="stock",
            exchange__in=["SSE", "SZSE", "BSE"],
            is_active=True,
        ).exclude(code__in=active_codes)
        return int(queryset.update(is_active=False))
