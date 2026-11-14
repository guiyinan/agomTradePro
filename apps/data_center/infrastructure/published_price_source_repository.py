"""Read immutable price lineage from existing facts, manifests and raw records."""

from __future__ import annotations

from datetime import date, datetime

from django.db.models import Subquery

from apps.data_center.application.price_response_capture import ExactPriceBarValues
from apps.data_center.application.published_price_source import PublishedPriceSourceFact
from apps.data_center.domain.control_plane import PublicationState
from apps.data_center.domain.entities import RawAudit
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.domain.publication_lanes import M1_REBALANCE_REFERENCE_PUBLICATION_KEY
from apps.data_center.domain.raw_audit_manifest import CandidateRawAuditManifest
from apps.data_center.domain.raw_landing import RawPayload
from core.exceptions import DataValidationError

from .candidate_raw_audit_manifest_repository import DjangoCandidateRawAuditManifestRepository
from .models import PriceBarModel
from .provider_state_repositories import RawAuditRepository
from .publication_fact_evidence import publication_fact_reference_for_dataset
from .publication_rollback_models import CanonicalPublicationModel, PublicationMemberModel
from .raw_landing_repositories import RawLandingRepository


class DjangoPublishedPriceSourceRepository:
    """Provide bounded read-only adapters without reconstructing values from float."""

    def read_facts(
        self, *, asset_code: str, trade_date: date, fact_pks: tuple[str, ...]
    ) -> tuple[PublishedPriceSourceFact, ...]:
        """Read only selected target rows and keep a second row to detect ambiguity."""
        if not fact_pks or any(
            not value.isascii() or not value.isdecimal() or value.startswith("0")
            for value in fact_pks
        ):
            raise DataValidationError(
                "Invalid price member identity", code="PRICE_SOURCE_FACT_PK_INVALID"
            )
        rows = (
            PriceBarModel._default_manager.using("default")
            .filter(pk__in=fact_pks, asset_code=asset_code, bar_date=trade_date)
            .order_by("pk")[:2]
        )
        return tuple(_source_fact(row) for row in rows)

    def select_retained_publication_for_session(
        self, *, asset_code: str, trade_date: date, knowledge_cutoff: datetime
    ) -> str | None:
        """Select the newest activated retained M1 member for an exact session.

        Selection is only discovery. The caller must verify the entire chosen
        publication/source/Audit envelope and must not fall back to an older
        candidate when that verification fails. No current pointer is read.
        """
        fact_ids = tuple(
            PriceBarModel._base_manager.using("default")
            .filter(
                asset_code=asset_code,
                bar_date=trade_date,
                freq="1d",
                adjustment=PriceAdjustment.NONE.value,
                source="tushare",
            )
            .order_by("pk")
            .values_list("pk", flat=True)[:2]
        )
        if len(fact_ids) != 1 or type(fact_ids[0]) is not int or fact_ids[0] <= 0:
            return None
        members = (
            PublicationMemberModel._base_manager.using("default")
            .filter(
                dataset_key="equity.price.bar",
                fact_table=PriceBarModel._meta.db_table,
                fact_pk=str(fact_ids[0]),
                observed_at=cn_market_session_close_utc(trade_date),
            )
            .values("publication_id")
        )
        candidates = tuple(
            CanonicalPublicationModel._base_manager.using("default")
            .filter(
                dataset_key="equity.price.bar",
                publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
                selected_source="tushare",
                publication_id__in=Subquery(members),
                state__in=(PublicationState.PUBLISHED.value, PublicationState.SUPERSEDED.value),
                published_at__lte=knowledge_cutoff,
                created_at__lte=knowledge_cutoff,
            )
            .order_by("-published_at", "publication_id")[:2]
        )
        if not candidates:
            return None
        if len(candidates) > 1 and candidates[0].published_at == candidates[1].published_at:
            raise DataValidationError(
                "Retained session publication is ambiguous",
                code="RETAINED_PRICE_SELECTION_AMBIGUOUS",
            )
        return str(candidates[0].publication_id)

    def read_manifest(self, publication_id: str) -> CandidateRawAuditManifest | None:
        """Use the existing manifest decoder without its write-lock validation path."""
        return DjangoCandidateRawAuditManifestRepository().get_by_publication_id(publication_id)

    def read_audit(self, raw_audit_id: str) -> RawAudit | None:
        """Read the exact immutable audit named by the selected manifest reference."""
        return RawAuditRepository().get_by_id(raw_audit_id)

    def read_payload(self, payload_hash: str) -> RawPayload | None:
        """Read the existing retained response envelope by its precise hash."""
        return RawLandingRepository().get_by_hash(payload_hash)


def _source_fact(row: PriceBarModel) -> PublishedPriceSourceFact:
    """Narrow ORM Decimal columns before exposing an application value object."""
    if row.volume is None or row.amount is None:
        raise DataValidationError(
            "Price source volume or amount is unknown", code="PRICE_SOURCE_VALUES_MISSING"
        )
    return PublishedPriceSourceFact(
        asset_code=row.asset_code,
        trade_date=row.bar_date,
        frequency=row.freq,
        adjustment=PriceAdjustment(row.adjustment),
        values=ExactPriceBarValues(
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            amount=row.amount,
        ),
        ingested_run_id=str(row.ingested_run_id) if row.ingested_run_id else "",
        reference=publication_fact_reference_for_dataset(row, dataset_key="equity.price.bar"),
    )
