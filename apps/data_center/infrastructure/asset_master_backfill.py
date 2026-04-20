"""
Data Center asset master backfill services.

Centralises legacy-to-master enrichment so feature modules do not need
to duplicate security-name recovery logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import requests

from apps.data_center.domain.entities import AssetAlias, AssetMaster
from apps.data_center.domain.enums import AssetType, MarketExchange
from apps.data_center.domain.rules import normalize_asset_code
from apps.data_center.infrastructure.repositories import AssetRepository


@dataclass(frozen=True)
class AssetMasterBackfillReport:
    """Summary of one backfill run."""

    requested_codes: list[str]
    touched_codes: list[str]
    unresolved_codes: list[str]
    alias_count: int

    def to_dict(self) -> dict[str, object]:
        """Return a serialisable report payload."""
        return {
            "requested_codes": self.requested_codes,
            "touched_codes": self.touched_codes,
            "unresolved_codes": self.unresolved_codes,
            "asset_count": len(self.touched_codes),
            "alias_count": self.alias_count,
        }


@dataclass(frozen=True)
class _AssetRecord:
    """Internal transfer object for backfill candidates."""

    asset: AssetMaster
    aliases: set[str]


class AssetMasterBackfillService:
    """Backfill missing asset master rows from legacy sources and remote metadata."""

    _EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
    _EASTMONEY_METADATA_FIELDS = "f43,f57,f58"

    def __init__(self, asset_repo: AssetRepository | None = None) -> None:
        self._asset_repo = asset_repo or AssetRepository()

    def backfill_codes(
        self,
        codes: Iterable[str],
        include_remote: bool = False,
    ) -> AssetMasterBackfillReport:
        """Backfill a bounded set of asset codes."""
        requested_codes = self._normalize_requested_codes(codes)
        if not requested_codes:
            return AssetMasterBackfillReport(
                requested_codes=[],
                touched_codes=[],
                unresolved_codes=[],
                alias_count=0,
            )

        touched_codes: set[str] = set()
        alias_count = 0
        for record in self._iter_local_records(requested_codes):
            alias_count += self._upsert_asset_record(record)
            touched_codes.add(record.asset.code)

        unresolved_codes = self._collect_unresolved_codes(requested_codes)
        if include_remote and unresolved_codes:
            for code in list(unresolved_codes):
                remote_record = self._build_remote_record(code)
                if remote_record is None:
                    continue
                alias_count += self._upsert_asset_record(remote_record)
                touched_codes.add(remote_record.asset.code)
            unresolved_codes = self._collect_unresolved_codes(requested_codes)

        return AssetMasterBackfillReport(
            requested_codes=requested_codes,
            touched_codes=sorted(touched_codes),
            unresolved_codes=unresolved_codes,
            alias_count=alias_count,
        )

    def backfill_all(self, include_remote: bool = False) -> AssetMasterBackfillReport:
        """Backfill all discoverable legacy asset codes."""
        return self.backfill_codes(self._collect_all_candidate_codes(), include_remote=include_remote)

    def _collect_all_candidate_codes(self) -> list[str]:
        from apps.asset_analysis.infrastructure.models import AssetPoolEntry
        from apps.equity.infrastructure.models import StockInfoModel
        from apps.fund.infrastructure.models import FundHoldingModel, FundInfoModel
        from apps.rotation.infrastructure.models import AssetClassModel

        codes: list[str] = []
        codes.extend(
            StockInfoModel._default_manager.exclude(stock_code__isnull=True).values_list(
                "stock_code", flat=True
            )
        )
        codes.extend(
            FundInfoModel._default_manager.exclude(fund_code__isnull=True).values_list(
                "fund_code", flat=True
            )
        )
        codes.extend(
            FundHoldingModel._default_manager.exclude(stock_code__isnull=True).values_list(
                "stock_code", flat=True
            )
        )
        codes.extend(
            AssetClassModel._default_manager.filter(is_active=True).exclude(code__isnull=True).values_list(
                "code", flat=True
            )
        )
        codes.extend(
            AssetPoolEntry._default_manager.exclude(asset_code__isnull=True).values_list(
                "asset_code", flat=True
            )
        )
        return self._normalize_requested_codes(codes)

    def _iter_local_records(self, requested_codes: list[str]) -> list[_AssetRecord]:
        from apps.asset_analysis.infrastructure.models import AssetPoolEntry
        from apps.equity.infrastructure.models import StockInfoModel
        from apps.fund.infrastructure.models import FundHoldingModel, FundInfoModel
        from apps.rotation.infrastructure.models import AssetClassModel

        code_aliases = self._build_code_aliases(requested_codes)
        lookup_codes = sorted({alias for aliases in code_aliases.values() for alias in aliases})
        base_codes = sorted({code.split(".", 1)[0] for code in lookup_codes})

        records: list[_AssetRecord] = []
        seen_holding_codes: set[str] = set()
        seen_pool_codes: set[str] = set()

        stock_rows = StockInfoModel._default_manager.filter(stock_code__in=lookup_codes).values(
            "stock_code",
            "name",
            "sector",
            "market",
        )
        for row in stock_rows:
            raw_code = str(row["stock_code"] or "").strip().upper()
            canonical_code = self._canonicalize_legacy_code(raw_code)
            name = str(row.get("name") or "").strip()
            if not canonical_code or not name:
                continue
            records.append(
                _AssetRecord(
                    asset=AssetMaster(
                        code=canonical_code,
                        name=name,
                        short_name=name,
                        asset_type=AssetType.STOCK,
                        exchange=self._infer_exchange(canonical_code),
                        sector=str(row.get("sector") or ""),
                        industry=str(row.get("sector") or ""),
                        extra={"legacy_market": str(row.get("market") or "")},
                    ),
                    aliases=self._build_aliases(canonical_code, {raw_code}),
                )
            )

        fund_rows = FundInfoModel._default_manager.filter(fund_code__in=base_codes).values(
            "fund_code",
            "fund_name",
            "fund_type",
            "investment_style",
        )
        for row in fund_rows:
            base_code = str(row["fund_code"] or "").strip().upper()
            name = str(row.get("fund_name") or "").strip()
            if not base_code or not name:
                continue
            canonical_code = self._canonicalize_legacy_code(base_code)
            fund_type = str(row.get("fund_type") or "")
            asset_type = AssetType.ETF if "ETF" in fund_type.upper() or "ETF" in name.upper() else AssetType.FUND
            records.append(
                _AssetRecord(
                    asset=AssetMaster(
                        code=canonical_code,
                        name=name,
                        short_name=name,
                        asset_type=asset_type,
                        exchange=self._infer_exchange(canonical_code),
                        industry=str(row.get("investment_style") or ""),
                        extra={"legacy_fund_type": fund_type},
                    ),
                    aliases=self._build_aliases(canonical_code, {base_code}),
                )
            )

        holding_rows = (
            FundHoldingModel._default_manager.filter(stock_code__in=lookup_codes)
            .order_by("stock_code", "-report_date")
            .values("stock_code", "stock_name")
        )
        for row in holding_rows:
            candidate_code = str(row["stock_code"] or "").strip().upper()
            name = str(row.get("stock_name") or "").strip()
            if not candidate_code or not name or candidate_code in seen_holding_codes:
                continue
            seen_holding_codes.add(candidate_code)
            canonical_code = self._canonicalize_legacy_code(candidate_code)
            records.append(
                _AssetRecord(
                    asset=AssetMaster(
                        code=canonical_code,
                        name=name,
                        short_name=name,
                        asset_type=AssetType.STOCK,
                        exchange=self._infer_exchange(canonical_code),
                    ),
                    aliases=self._build_aliases(canonical_code, {candidate_code}),
                )
            )

        rotation_rows = AssetClassModel._default_manager.filter(code__in=base_codes, is_active=True).values(
            "code",
            "name",
            "category",
            "currency",
        )
        for row in rotation_rows:
            base_code = str(row["code"] or "").strip().upper()
            name = str(row.get("name") or "").strip()
            if not base_code or not name:
                continue
            canonical_code = self._canonicalize_legacy_code(base_code)
            records.append(
                _AssetRecord(
                    asset=AssetMaster(
                        code=canonical_code,
                        name=name,
                        short_name=name,
                        asset_type=self._infer_asset_type_from_rotation(str(row.get("category") or "")),
                        exchange=self._infer_exchange(canonical_code),
                        currency=str(row.get("currency") or "CNY"),
                        extra={"legacy_rotation_category": str(row.get("category") or "")},
                    ),
                    aliases=self._build_aliases(canonical_code, {base_code}),
                )
            )

        pool_rows = (
            AssetPoolEntry._default_manager.filter(asset_code__in=lookup_codes)
            .order_by("asset_code", "-entry_date")
            .values("asset_code", "asset_name", "asset_category")
        )
        for row in pool_rows:
            candidate_code = str(row["asset_code"] or "").strip().upper()
            if not candidate_code or candidate_code in seen_pool_codes:
                continue
            seen_pool_codes.add(candidate_code)
            name = str(row.get("asset_name") or "").strip()
            if not name:
                continue
            canonical_code = self._canonicalize_legacy_code(candidate_code)
            records.append(
                _AssetRecord(
                    asset=AssetMaster(
                        code=canonical_code,
                        name=name,
                        short_name=name,
                        asset_type=self._infer_asset_type_from_pool(str(row.get("asset_category") or "")),
                        exchange=self._infer_exchange(canonical_code),
                        extra={"legacy_asset_category": str(row.get("asset_category") or "")},
                    ),
                    aliases=self._build_aliases(canonical_code, {candidate_code}),
                )
            )

        return records

    def _build_remote_record(self, code: str) -> _AssetRecord | None:
        canonical_code = self._canonicalize_legacy_code(code)
        name = self._fetch_remote_name(canonical_code)
        if not name:
            return None
        return _AssetRecord(
            asset=AssetMaster(
                code=canonical_code,
                name=name,
                short_name=name,
                asset_type=self._infer_asset_type_from_code(canonical_code),
                exchange=self._infer_exchange(canonical_code),
                extra={"name_source": "eastmoney"},
            ),
            aliases=self._build_aliases(canonical_code, {code}),
        )

    def _fetch_remote_name(self, code: str) -> str:
        params = {
            "secid": self._to_eastmoney_secid(code),
            "fields": self._EASTMONEY_METADATA_FIELDS,
            "invt": "2",
            "fltt": "1",
        }
        try:
            with requests.Session() as session:
                session.trust_env = False
                session.headers.update(
                    {
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/133.0.0.0 Safari/537.36"
                        ),
                        "Accept": "application/json,text/plain,*/*",
                        "Referer": "https://quote.eastmoney.com/",
                    }
                )
                response = session.get(self._EASTMONEY_QUOTE_URL, params=params, timeout=15)
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return ""

        data = payload.get("data") or {}
        return str(data.get("f58") or "").strip()

    def _upsert_asset_record(self, record: _AssetRecord) -> int:
        asset = self._asset_repo.upsert(record.asset)
        alias_count = 0
        for alias_code in sorted(record.aliases):
            if not alias_code or alias_code == asset.code:
                continue
            self._asset_repo.upsert_alias(
                AssetAlias(
                    asset_code=asset.code,
                    provider_name="legacy",
                    alias_code=alias_code,
                )
            )
            alias_count += 1
        return alias_count

    def _collect_unresolved_codes(self, requested_codes: list[str]) -> list[str]:
        unresolved_codes: list[str] = []
        for code in requested_codes:
            if self._asset_repo.get_by_code(code) is None:
                unresolved_codes.append(code)
        return unresolved_codes

    @staticmethod
    def _normalize_requested_codes(codes: Iterable[str]) -> list[str]:
        normalized_codes: list[str] = []
        seen: set[str] = set()
        for code in codes:
            normalized = str(code or "").strip().upper()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_codes.append(normalized)
        return normalized_codes

    def _build_code_aliases(self, codes: list[str]) -> dict[str, set[str]]:
        aliases: dict[str, set[str]] = {}
        for raw_code in codes:
            normalized = str(raw_code or "").strip().upper()
            if not normalized:
                continue
            code_aliases = {normalized}
            canonical = self._canonicalize_legacy_code(normalized)
            if canonical:
                code_aliases.add(canonical)
            base_code = normalized.split(".", 1)[0]
            if base_code:
                code_aliases.add(base_code)
                code_aliases.add(self._canonicalize_legacy_code(base_code))
            aliases[normalized] = {alias for alias in code_aliases if alias}
        return aliases

    @staticmethod
    def _build_aliases(canonical_code: str, raw_codes: set[str]) -> set[str]:
        aliases = {canonical_code.split(".", 1)[0]}
        for raw_code in raw_codes:
            normalized = str(raw_code or "").strip().upper()
            if not normalized:
                continue
            aliases.add(normalized)
            aliases.add(normalized.split(".", 1)[0])
        return {alias for alias in aliases if alias and alias != canonical_code}

    @staticmethod
    def _canonicalize_legacy_code(code: str) -> str:
        normalized = str(code or "").strip().upper()
        if not normalized:
            return normalized
        if "." in normalized or normalized[:2] in {"SH", "SZ", "BJ", "HK"}:
            return normalize_asset_code(normalized, "tushare")
        if normalized.startswith(("6", "5", "9")):
            return f"{normalized}.SH"
        if normalized.startswith(("0", "1", "3")):
            return f"{normalized}.SZ"
        if normalized.startswith(("4", "8")):
            return f"{normalized}.BJ"
        return normalized

    @staticmethod
    def _infer_exchange(code: str) -> MarketExchange:
        normalized = str(code or "").strip().upper()
        if normalized.endswith(".SH"):
            return MarketExchange.SSE
        if normalized.endswith(".SZ"):
            return MarketExchange.SZSE
        if normalized.endswith(".BJ"):
            return MarketExchange.BSE
        return MarketExchange.OTHER

    @staticmethod
    def _infer_asset_type_from_rotation(category: str) -> AssetType:
        normalized = category.strip().lower()
        if normalized == "equity":
            return AssetType.ETF
        if normalized == "bond":
            return AssetType.BOND
        if normalized == "commodity":
            return AssetType.FUTURES
        return AssetType.OTHER

    @staticmethod
    def _infer_asset_type_from_pool(asset_category: str) -> AssetType:
        normalized = asset_category.strip().lower()
        if normalized == "equity":
            return AssetType.STOCK
        if normalized == "fund":
            return AssetType.FUND
        if normalized == "bond":
            return AssetType.BOND
        if normalized == "index":
            return AssetType.INDEX
        if normalized == "commodity":
            return AssetType.FUTURES
        return AssetType.OTHER

    @staticmethod
    def _infer_asset_type_from_code(code: str) -> AssetType:
        normalized = str(code or "").strip().upper()
        base_code = normalized.split(".", 1)[0]
        if base_code.startswith(("5", "1")):
            return AssetType.ETF
        if base_code.startswith(("0", "3", "4", "6", "8", "9")):
            return AssetType.STOCK
        return AssetType.OTHER

    @staticmethod
    def _to_eastmoney_secid(stock_code: str) -> str:
        code = stock_code.strip().upper()
        symbol = code.split(".", 1)[0]
        if code.endswith(".SH") or symbol.startswith(("5", "6", "9")):
            return f"1.{symbol}"
        return f"0.{symbol}"
