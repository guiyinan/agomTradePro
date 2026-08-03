"""SDK contract actions for the equity API."""

import re

from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.data_center.application.public import (
    get_decision_publication_gate,
    get_published_financial_facts,
)
from apps.equity.application.query_services import list_stock_financial_payloads

from .serializers import FinancialHistoryQuerySerializer

_STOCK_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")

_CANONICAL_FINANCIAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("revenue", "revenue"),
    ("net_profit", "net_profit"),
    ("total_assets", "total_assets"),
    ("total_liabilities", "total_liabilities"),
    ("equity", "equity"),
    ("roe", "roe"),
    ("roa", "roa"),
    ("debt_ratio", "debt_ratio"),
    ("revenue_growth", "revenue_growth"),
    ("net_profit_growth", "net_profit_growth"),
)


def _canonical_financial_rows(
    payload: object,
    *,
    stock_code: str,
    report_type: str,
    limit: int,
) -> list[dict[str, object]]:
    """Format publication-gated canonical facts as period snapshots.

    The historical endpoint exposes one row per reporting period.  Canonical
    Data Center facts are metric rows, so group them by period without falling
    back to the retired equity financial projection.
    """

    if not isinstance(payload, dict):
        return []
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        return []

    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            continue
        period_end = str(raw_row.get("period_end") or "").strip()
        period_kind = str(raw_row.get("period_type") or "").strip()
        if not period_end or not period_kind:
            continue
        if report_type != "all" and period_kind != report_type:
            continue
        group = grouped.setdefault(
            (period_end, period_kind),
            {
                "stock_code": stock_code,
                "period_end": period_end,
                "report_date": str(raw_row.get("report_date") or period_end),
                "period_type": period_kind,
                "source": str(raw_row.get("source") or ""),
            },
        )
        report_date = str(raw_row.get("report_date") or "").strip()
        if report_date and report_date > str(group.get("report_date") or ""):
            group["report_date"] = report_date
        fetched_at = str(raw_row.get("fetched_at") or "").strip()
        if fetched_at and fetched_at > str(group.get("fetched_at") or ""):
            group["fetched_at"] = fetched_at
        metric_code = str(raw_row.get("metric_code") or "").strip()
        value = raw_row.get("value")
        for canonical_code, output_key in _CANONICAL_FINANCIAL_FIELDS:
            if metric_code == canonical_code:
                group[output_key] = (
                    str(value)
                    if canonical_code
                    in {
                        "revenue",
                        "net_profit",
                        "total_assets",
                        "total_liabilities",
                        "equity",
                    }
                    and value is not None
                    else value
                )
                break

    rows = sorted(
        grouped.values(),
        key=lambda row: (str(row.get("period_end") or ""), str(row.get("period_type") or "")),
        reverse=True,
    )
    return rows[:limit]


class EquitySDKContractActionsMixin:
    """Expose equity endpoints required by the public SDK contract."""

    @action(
        detail=False,
        methods=["get"],
        url_path="financials/(?P<stock_code>[^/]+)",
        permission_classes=[IsAuthenticated],
    )
    def financials(self, request: Request, stock_code: str) -> Response:
        """Return persisted financial snapshots for one stock."""

        normalized_code = stock_code.strip().upper()
        if _STOCK_CODE_PATTERN.fullmatch(normalized_code) is None:
            raise ValidationError({"stock_code": ["Invalid stock code."]})
        query = FinancialHistoryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        mode = str(query.validated_data["mode"])
        publication_key = str(query.validated_data["publication_key"])
        publication = None
        canonical_payload: dict[str, object] | None = None
        if mode == "published":
            publication = get_decision_publication_gate(
                "equity.financial.fact",
                publication_key,
            )
            if publication is None or bool(publication.get("must_not_use_for_decision")):
                return Response(
                    {
                        "stock_code": normalized_code,
                        "report_type": query.validated_data["report_type"],
                        "results": [],
                        "count": 0,
                        "status": "blocked",
                        "mode": mode,
                        "publication_key": publication_key,
                        "publication": publication,
                        "publication_id": (
                            publication.get("publication_id") if publication else None
                        ),
                        "must_not_use_for_decision": True,
                        "blocked_reason": (
                            publication.get("blocked_reason")
                            if publication
                            else "canonical_publication_missing"
                        ),
                    },
                    status=200,
                )
        report_type = str(query.validated_data["report_type"])
        limit = int(query.validated_data["limit"])
        if mode == "published":
            canonical_payload = get_published_financial_facts(
                normalized_code,
                limit=max(limit * len(_CANONICAL_FINANCIAL_FIELDS), limit),
                publication_key=publication_key,
            )
            if bool(canonical_payload.get("must_not_use_for_decision")):
                return Response(
                    {
                        "stock_code": normalized_code,
                        "report_type": report_type,
                        "results": [],
                        "count": 0,
                        "status": "blocked",
                        "mode": mode,
                        "publication_key": publication_key,
                        "publication": canonical_payload,
                        "publication_id": canonical_payload.get("publication_id"),
                        "must_not_use_for_decision": True,
                        "blocked_reason": canonical_payload.get(
                            "blocked_reason", "canonical_publication_missing"
                        ),
                    },
                    status=200,
                )
            results = _canonical_financial_rows(
                canonical_payload,
                stock_code=normalized_code,
                report_type=report_type,
                limit=limit,
            )
        else:
            results = list_stock_financial_payloads(
                stock_code=normalized_code,
                report_type=report_type,
                limit=limit,
            )
        response_payload: dict[str, object] = {
            "stock_code": normalized_code,
            "report_type": query.validated_data["report_type"],
            "results": results,
            "count": len(results),
            "mode": mode,
            "publication_key": publication_key,
            "publication": publication,
        }
        if canonical_payload is not None:
            for key in (
                "publication_id",
                "must_not_use_for_decision",
                "blocked_reason",
                "freshness_status",
                "observed_at",
                "age_seconds",
                "max_age_seconds",
            ):
                if key in canonical_payload:
                    response_payload[key] = canonical_payload[key]
        return Response(response_payload)
