"""Share API and page views."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views import View
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.decision_rhythm.infrastructure.models import (
    DecisionRequestModel,
    DecisionResponseModel,
)
from apps.share.application.use_cases import (
    ShareAccessUseCases,
    ShareLinkUseCases,
    ShareSnapshotUseCases,
)
from apps.share.infrastructure.models import ShareDisclaimerConfigModel, ShareLinkModel, ShareSnapshotModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from apps.share.interface.serializers import (
    CreateShareLinkSerializer,
    PublicShareLinkSerializer,
    ShareAccessRequestSerializer,
    ShareLinkSerializer,
    ShareSnapshotSerializer,
    UpdateShareLinkSerializer,
)


DECISION_STATUS_DISPLAY = {
    "pending": "待处理",
    "approved": "已批准",
    "rejected": "已拒绝",
    "executed": "已执行",
    "failed": "执行失败",
    "cancelled": "已取消",
}


def _normalize_portfolio_type(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"real", "live", "实盘", "实仓"}:
        return "real"
    return "simulated"


class ShareVisibilityMixin:
    """Shared helpers for public share access."""

    @staticmethod
    def _password_session_key(share_link_id: int) -> str:
        return f"share_verified_{share_link_id}"

    def _is_password_verified(self, request, share_link: ShareLinkModel) -> bool:
        return bool(request.session.get(self._password_session_key(share_link.id), False))

    def _mark_password_verified(self, request, share_link: ShareLinkModel) -> None:
        request.session[self._password_session_key(share_link.id)] = True
        request.session.modified = True

    def _clear_password_verified(self, request, share_link: ShareLinkModel) -> None:
        request.session.pop(self._password_session_key(share_link.id), None)
        request.session.modified = True

    def _get_client_ip(self, request) -> str:
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")

    def _log_access(self, share_link_id: int, request, result_status: str, is_verified: bool = False):
        ShareAccessUseCases().log_access(
            share_link_id=share_link_id,
            ip_address=self._get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            referer=request.META.get("HTTP_REFERER", ""),
            result_status=result_status,
            is_verified=is_verified,
        )

    def _filter_snapshot_by_visibility(self, snapshot: dict, share_link: ShareLinkModel) -> dict:
        result = {
            "generated_at": snapshot["generated_at"],
            "source_range_start": snapshot.get("source_range_start"),
            "source_range_end": snapshot.get("source_range_end"),
        }

        summary = dict(snapshot.get("summary", {}) or {})
        if not share_link.show_amounts:
            summary = {
                k: v
                for k, v in summary.items()
                if not any(
                    money_word in k.lower()
                    for money_word in ["amount", "value", "cash", "capital", "profit", "loss"]
                )
            }
        result["summary"] = summary

        if share_link.show_amounts:
            result["performance"] = snapshot.get("performance", {})

        if share_link.show_positions:
            positions = dict(snapshot.get("positions", {}) or {})
            if not share_link.show_amounts and isinstance(positions.get("items"), list):
                positions["items"] = [
                    {
                        k: v
                        for k, v in item.items()
                        if not any(
                            money_word in k.lower()
                            for money_word in ["amount", "value", "cost", "price", "pnl"]
                        )
                    }
                    for item in positions["items"]
                ]
            result["positions"] = positions

        if share_link.show_transactions:
            transactions = dict(snapshot.get("transactions", {}) or {})
            if not share_link.show_amounts and isinstance(transactions.get("items"), list):
                transactions["items"] = [
                    {
                        k: v
                        for k, v in item.items()
                        if not any(
                            money_word in k.lower()
                            for money_word in ["amount", "value", "cost", "price"]
                        )
                    }
                    for item in transactions["items"]
                ]
            result["transactions"] = transactions

        if share_link.show_decision_summary or share_link.show_decision_evidence:
            decisions = dict(snapshot.get("decisions", {}) or {})
            if not share_link.show_decision_evidence:
                decisions.pop("evidence", None)
            if not share_link.show_invalidation_logic:
                decisions.pop("invalidation_logic", None)
            result["decisions"] = decisions

        return result

    def _build_public_context(
        self,
        share_link: ShareLinkModel,
        filtered_snapshot: dict | None,
        *,
        requires_password: bool = False,
        password_error: str = "",
    ) -> dict:
        snapshot = filtered_snapshot or {}
        summary = snapshot.get("summary", {}) or {}
        performance = snapshot.get("performance", {}) or {}
        positions = snapshot.get("positions", {}) or {}
        transactions = snapshot.get("transactions", {}) or {}
        decisions = snapshot.get("decisions", {}) or {}

        def first_of(*keys, source=None, default=None):
            src = source if source is not None else {}
            for key in keys:
                if key in src and src[key] is not None:
                    return src[key]
            return default

        disclaimer_config = ShareDisclaimerConfigModel.get_solo()
        disclaimer_lines = list(disclaimer_config.lines or [])
        if _normalize_portfolio_type(summary.get("portfolio_type")) == "simulated":
            disclaimer_lines = [
                *disclaimer_lines[:3],
                "本账户为模拟交易账户，非真实资金运作。",
                *disclaimer_lines[3:],
            ]

        return {
            "portfolio_name": share_link.title,
            "portfolio_description": share_link.subtitle,
            "share_theme": share_link.theme,
            "portfolio_type": _normalize_portfolio_type(summary.get("portfolio_type")),
            "is_private": share_link.requires_password(),
            "requires_password": requires_password,
            "password_error": password_error,
            "owner_name": (
                share_link.owner.get_full_name().strip()
                or getattr(share_link.owner, "username", "")
                or getattr(share_link.owner, "email", "")
            ),
            "created_at": share_link.created_at,
            "is_simulated": _normalize_portfolio_type(summary.get("portfolio_type")) == "simulated",
            "last_updated": first_of("generated_at", default=share_link.last_snapshot_at, source=snapshot),
            "total_return": first_of("total_return", "total_return_pct", source=performance, default=summary.get("total_return")),
            "return_7d": first_of("return_7d", "seven_day_return", source=performance),
            "return_30d": first_of("return_30d", "thirty_day_return", source=performance),
            "current_position": first_of("current_position", "position_ratio", source=summary),
            "inception_date": first_of("inception_date", source=summary),
            "annualized_return": first_of("annualized_return", source=performance),
            "max_drawdown": first_of("max_drawdown", source=performance),
            "sharpe_ratio": first_of("sharpe_ratio", source=performance),
            "win_rate": first_of("win_rate", source=performance),
            "total_trades": first_of("total_trades", source=transactions, default=len(transactions.get("items", []) or [])),
            "position_count": first_of("position_count", source=positions, default=len(positions.get("items", []) or [])),
            "positions": positions.get("items", []),
            "position_summary": positions.get("summary", {}),
            "recent_transactions": transactions.get("items", []),
            "decisions": decisions.get("items", decisions if isinstance(decisions, list) else []),
            "regime_info": decisions.get("regime_info") if isinstance(decisions, dict) else None,
            "benchmark_name": first_of("benchmark_name", source=performance, default="沪深300"),
            "chart_dates": first_of("chart_dates", "dates", source=performance, default=[]),
            "portfolio_values": first_of("portfolio_values", "returns", "series", source=performance, default=[]),
            "benchmark_values": first_of("benchmark_values", "benchmark_series", source=performance, default=[]),
            "disclaimer_enabled": disclaimer_config.is_enabled,
            "disclaimer_modal_enabled": disclaimer_config.modal_enabled,
            "disclaimer_modal_title": disclaimer_config.modal_title,
            "disclaimer_modal_confirm_text": disclaimer_config.modal_confirm_text,
            "disclaimer_lines": disclaimer_lines,
        }


def _as_float(value) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _as_iso_datetime(value) -> str | None:
    if not value:
        return None
    return value.isoformat()


def _non_empty(*values):
    for value in values:
        if value not in (None, "", [], {}, ()):
            return value
    return None


def _direction_label(direction: str) -> str:
    mapping = {
        "BUY": "买入",
        "SELL": "卖出",
        "HOLD": "持有",
        "buy": "买入",
        "sell": "卖出",
        "hold": "持有",
    }
    return mapping.get(direction or "", direction or "观察")


def _asset_type_label(asset_type: str | None) -> str:
    mapping = {
        "equity": "股票",
        "fund": "基金",
        "bond": "债券",
        "cash": "现金",
    }
    return mapping.get((asset_type or "").strip().lower(), "其他")


def _decision_response(decision_request: DecisionRequestModel):
    try:
        return decision_request.response
    except (DecisionResponseModel.DoesNotExist, ObjectDoesNotExist):
        return None


def _decision_status(decision_request: DecisionRequestModel, response) -> tuple[str, str]:
    if decision_request.execution_status == "executed":
        return "executed", DECISION_STATUS_DISPLAY["executed"]
    if decision_request.execution_status == "failed":
        return "failed", DECISION_STATUS_DISPLAY["failed"]
    if decision_request.execution_status == "cancelled":
        return "cancelled", DECISION_STATUS_DISPLAY["cancelled"]
    if response is not None:
        if response.approved:
            return "approved", DECISION_STATUS_DISPLAY["approved"]
        return "rejected", DECISION_STATUS_DISPLAY["rejected"]
    return "pending", DECISION_STATUS_DISPLAY["pending"]


def _build_decision_chain(account, asset_codes: set[str], positions_by_code: dict[str, object]) -> tuple[list[dict], list[dict]]:
    if not asset_codes:
        return [], []

    decision_requests = list(
        DecisionRequestModel.objects.filter(asset_code__in=asset_codes)
        .filter(
            Q(unified_recommendation__account_id=str(account.id))
            | Q(unified_recommendation__account_id=account.id)
            | Q(execution_ref__account_id=account.id)
            | Q(execution_ref__account_id=str(account.id))
        )
        .select_related(
            "response",
            "feature_snapshot",
            "unified_recommendation",
            "unified_recommendation__feature_snapshot",
        )
        .order_by("-requested_at")[:12]
    )

    decision_items = []
    evidence_items = []

    for decision_request in decision_requests:
        response = _decision_response(decision_request)
        recommendation = decision_request.unified_recommendation
        feature_snapshot = decision_request.feature_snapshot or getattr(recommendation, "feature_snapshot", None)
        position = positions_by_code.get(decision_request.asset_code)
        status, status_display = _decision_status(decision_request, response)
        reason_codes = list(getattr(recommendation, "reason_codes", []) or [])
        invalidation_logic = _non_empty(
            position.invalidation_description if position else None,
            (
                f"止损价 {float(recommendation.stop_loss_price):.4f}"
                if recommendation and recommendation.stop_loss_price and recommendation.stop_loss_price > Decimal("0")
                else None
            ),
        )

        item = {
            "title": f"{_direction_label(_non_empty(decision_request.direction, getattr(recommendation, 'side', '')))} {decision_request.asset_code}",
            "status": status,
            "get_status_display": status_display,
            "description": _non_empty(
                decision_request.reason,
                response.approval_reason if response else None,
                response.rejection_reason if response else None,
                getattr(recommendation, "human_rationale", None),
            ),
            "rationale": _non_empty(
                getattr(recommendation, "human_rationale", None),
                response.approval_reason if response else None,
                response.rejection_reason if response else None,
                decision_request.reason,
            ),
            "asset_code": decision_request.asset_code,
            "created_at": _as_iso_datetime(decision_request.requested_at),
            "responded_at": _as_iso_datetime(response.responded_at) if response else None,
            "executed_at": _as_iso_datetime(decision_request.executed_at),
            "confidence": _non_empty(
                _as_float(getattr(recommendation, "confidence", None)),
                _as_float(decision_request.expected_confidence),
            ),
            "reason_codes": reason_codes,
            "execution_target": decision_request.execution_target,
            "execution_status": decision_request.execution_status,
            "execution_ref": decision_request.execution_ref or {},
            "invalidation_logic": invalidation_logic,
        }
        decision_items.append(item)

        evidence_items.append(
            {
                "asset_code": decision_request.asset_code,
                "requested_at": decision_request.requested_at.isoformat() if decision_request.requested_at else None,
                "responded_at": _as_iso_datetime(response.responded_at) if response else None,
                "executed_at": _as_iso_datetime(decision_request.executed_at),
                "request_reason": decision_request.reason,
                "approval_reason": response.approval_reason if response else "",
                "rejection_reason": response.rejection_reason if response else "",
                "cooldown_status": response.cooldown_status if response else "",
                "quota_status": response.quota_status if response else None,
                "alternative_suggestions": response.alternative_suggestions if response else None,
                "reason_codes": reason_codes,
                "confidence": item["confidence"],
                "regime": _non_empty(
                    getattr(feature_snapshot, "regime", None),
                    getattr(recommendation, "regime", None),
                ),
                "regime_confidence": _non_empty(
                    _as_float(getattr(feature_snapshot, "regime_confidence", None)),
                    _as_float(getattr(recommendation, "regime_confidence", None)),
                ),
                "policy_level": _non_empty(
                    getattr(feature_snapshot, "policy_level", None),
                    getattr(recommendation, "policy_level", None),
                ),
                "beta_gate_passed": _non_empty(
                    getattr(feature_snapshot, "beta_gate_passed", None),
                    getattr(recommendation, "beta_gate_passed", None),
                ),
                "sentiment_score": _non_empty(
                    _as_float(getattr(feature_snapshot, "sentiment_score", None)),
                    _as_float(getattr(recommendation, "sentiment_score", None)),
                ),
                "flow_score": _non_empty(
                    _as_float(getattr(feature_snapshot, "flow_score", None)),
                    _as_float(getattr(recommendation, "flow_score", None)),
                ),
                "technical_score": _non_empty(
                    _as_float(getattr(feature_snapshot, "technical_score", None)),
                    _as_float(getattr(recommendation, "technical_score", None)),
                ),
                "fundamental_score": _non_empty(
                    _as_float(getattr(feature_snapshot, "fundamental_score", None)),
                    _as_float(getattr(recommendation, "fundamental_score", None)),
                ),
                "alpha_model_score": _non_empty(
                    _as_float(getattr(feature_snapshot, "alpha_model_score", None)),
                    _as_float(getattr(recommendation, "alpha_model_score", None)),
                ),
                "entry_price_low": _as_float(getattr(recommendation, "entry_price_low", None)) if recommendation else None,
                "entry_price_high": _as_float(getattr(recommendation, "entry_price_high", None)) if recommendation else None,
                "target_price_low": _as_float(getattr(recommendation, "target_price_low", None)) if recommendation else None,
                "target_price_high": _as_float(getattr(recommendation, "target_price_high", None)) if recommendation else None,
                "stop_loss_price": _as_float(getattr(recommendation, "stop_loss_price", None)) if recommendation else None,
                "position_pct": _as_float(getattr(recommendation, "position_pct", None)) if recommendation else None,
                "execution_target": decision_request.execution_target,
                "execution_status": decision_request.execution_status,
                "execution_ref": decision_request.execution_ref or {},
                "invalidation_logic": invalidation_logic,
            }
        )

    return decision_items, evidence_items


class ShareLinkViewSet(viewsets.ModelViewSet):
    """Authenticated management API for share links."""

    serializer_class = ShareLinkSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ShareLinkModel.objects.filter(owner=self.request.user).order_by("-created_at")

    def create(self, request, *args, **kwargs):
        serializer = CreateShareLinkSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            entity = ShareLinkUseCases().create_share_link(
                owner_id=request.user.id,
                account_id=data["account_id"],
                title=data["title"],
                subtitle=data.get("subtitle"),
                theme=data.get("theme", "bloomberg"),
                share_level=data.get("share_level", "snapshot"),
                password=data.get("password"),
                expires_at=data.get("expires_at"),
                max_access_count=data.get("max_access_count"),
                allow_indexing=data.get("allow_indexing", False),
                show_amounts=data.get("show_amounts", False),
                show_positions=data.get("show_positions", True),
                show_transactions=data.get("show_transactions", True),
                show_decision_summary=data.get("show_decision_summary", True),
                show_decision_evidence=data.get("show_decision_evidence", False),
                show_invalidation_logic=data.get("show_invalidation_logic", False),
            )
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        model = ShareLinkModel.objects.get(id=entity.id)
        return Response(
            ShareLinkSerializer(model, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = UpdateShareLinkSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            entity = ShareLinkUseCases().update_share_link(
                share_link_id=instance.id,
                owner_id=request.user.id,
                title=data.get("title"),
                subtitle=data.get("subtitle"),
                theme=data.get("theme"),
                share_level=data.get("share_level"),
                password=data.get("password"),
                expires_at=data.get("expires_at"),
                max_access_count=data.get("max_access_count"),
                allow_indexing=data.get("allow_indexing"),
                show_amounts=data.get("show_amounts"),
                show_positions=data.get("show_positions"),
                show_transactions=data.get("show_transactions"),
                show_decision_summary=data.get("show_decision_summary"),
                show_decision_evidence=data.get("show_decision_evidence"),
                show_invalidation_logic=data.get("show_invalidation_logic"),
            )
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not entity:
            return Response({"error": "更新失败"}, status=status.HTTP_400_BAD_REQUEST)

        model = ShareLinkModel.objects.get(id=entity.id)
        return Response(ShareLinkSerializer(model, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        success = ShareLinkUseCases().revoke_share_link(pk, request.user.id)
        if success:
            return Response({"status": "revoked"})
        return Response({"error": "撤销失败"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["get"])
    def snapshots(self, request, pk=None):
        instance = self.get_object()
        snapshots = instance.snapshots.order_by("-snapshot_version")
        return Response(ShareSnapshotSerializer(snapshots, many=True).data)

    @action(detail=True, methods=["get"])
    def logs(self, request, pk=None):
        instance = self.get_object()
        logs = ShareAccessUseCases().get_access_logs(instance.id, limit=100)
        return Response(logs)

    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):
        instance = self.get_object()
        stats = ShareAccessUseCases().get_access_stats(instance.id)
        return Response(stats)


class PublicShareViewSet(ShareVisibilityMixin, viewsets.ViewSet):
    """Anonymous API for public share links."""

    permission_classes = []

    def retrieve(self, request, short_code=None):
        entity = ShareLinkUseCases().get_share_link_by_code(short_code)
        if not entity:
            return Response({"error": "分享链接不存在"}, status=status.HTTP_404_NOT_FOUND)

        is_accessible, result_status = entity.is_accessible(timezone.now())
        if not is_accessible:
            return Response({"error": result_status.value}, status=status.HTTP_403_FORBIDDEN)

        model = ShareLinkModel.objects.get(id=entity.id)
        if entity.requires_password() and not self._is_password_verified(request, model):
            self._log_access(model.id, request, "password_required", is_verified=False)
            return Response({"requires_password": True, "title": entity.title}, status=status.HTTP_401_UNAUTHORIZED)

        snapshot = _get_live_share_snapshot(model)
        if snapshot:
            snapshot = self._filter_snapshot_by_visibility(snapshot, model)
        return Response(PublicShareLinkSerializer(model).data)

    @action(detail=False, methods=["post"], url_path="(?P<short_code>[^/.]+)/access")
    def access(self, request, short_code=None):
        entity = ShareLinkUseCases().get_share_link_by_code(short_code)
        if not entity:
            return Response({"error": "分享链接不存在"}, status=status.HTTP_404_NOT_FOUND)

        is_accessible, result_status = entity.is_accessible(timezone.now())
        if not is_accessible:
            return Response({"error": result_status.value}, status=status.HTTP_403_FORBIDDEN)

        serializer = ShareAccessRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        password = serializer.validated_data.get("password")
        model = ShareLinkModel.objects.get(id=entity.id)

        if entity.requires_password():
            if not password:
                self._log_access(model.id, request, "password_required", is_verified=False)
                return Response(
                    {"requires_password": True, "error": "请输入密码"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            if not ShareLinkUseCases().verify_password(entity.id, password):
                self._clear_password_verified(request, model)
                self._log_access(model.id, request, "password_invalid", is_verified=False)
                return Response({"error": "密码错误"}, status=status.HTTP_401_UNAUTHORIZED)
            self._mark_password_verified(request, model)

        self._log_access(model.id, request, "success", is_verified=entity.requires_password())
        model.increment_access_count()
        snapshot = _get_live_share_snapshot(model)
        if snapshot:
            snapshot = self._filter_snapshot_by_visibility(snapshot, model)

        return Response({"share_link": PublicShareLinkSerializer(model).data, "snapshot": snapshot})

    @action(detail=False, methods=["get"], url_path="(?P<short_code>[^/.]+)/snapshot")
    def snapshot(self, request, short_code=None):
        entity = ShareLinkUseCases().get_share_link_by_code(short_code)
        if not entity:
            return Response({"error": "分享链接不存在"}, status=status.HTTP_404_NOT_FOUND)

        is_accessible, result_status = entity.is_accessible(timezone.now())
        if not is_accessible:
            return Response({"error": result_status.value}, status=status.HTTP_403_FORBIDDEN)

        model = ShareLinkModel.objects.get(id=entity.id)
        if entity.requires_password() and not self._is_password_verified(request, model):
            self._log_access(model.id, request, "password_required", is_verified=False)
            return Response({"error": "需要密码验证"}, status=status.HTTP_401_UNAUTHORIZED)

        snapshot = _get_live_share_snapshot(model)
        if not snapshot:
            return Response({"error": "快照不存在"}, status=status.HTTP_404_NOT_FOUND)

        self._log_access(model.id, request, "success", is_verified=entity.requires_password())
        model.increment_access_count()
        return Response(self._filter_snapshot_by_visibility(snapshot, model))


class PublicSharePageView(ShareVisibilityMixin, View):
    """Server-rendered public share page."""

    template_name = "share/public_share.html"

    def _get_share_link(self, short_code: str) -> ShareLinkModel:
        share_link = get_object_or_404(ShareLinkModel, short_code=short_code)
        if not share_link.is_accessible():
            raise Http404("分享链接不可访问")
        return share_link

    def get(self, request, short_code: str):
        share_link = self._get_share_link(short_code)
        if share_link.requires_password() and not self._is_password_verified(request, share_link):
            context = self._build_public_context(share_link, None, requires_password=True)
            return render(request, self.template_name, context, status=401)

        snapshot = _get_live_share_snapshot(share_link)
        filtered_snapshot = self._filter_snapshot_by_visibility(snapshot, share_link) if snapshot else None
        context = self._build_public_context(share_link, filtered_snapshot, requires_password=False)
        self._log_access(
            share_link.id,
            request,
            "success",
            is_verified=share_link.requires_password(),
        )
        share_link.increment_access_count()
        return render(request, self.template_name, context)

    def post(self, request, short_code: str):
        share_link = self._get_share_link(short_code)
        if not share_link.requires_password():
            return redirect("share:public_share", short_code=short_code)

        password = request.POST.get("password", "")
        if not ShareLinkUseCases().verify_password(share_link.id, password):
            self._clear_password_verified(request, share_link)
            self._log_access(share_link.id, request, "password_invalid", is_verified=False)
            context = self._build_public_context(
                share_link,
                None,
                requires_password=True,
                password_error="密码错误，请重试",
            )
            return render(request, self.template_name, context, status=401)

        self._mark_password_verified(request, share_link)
        self._log_access(share_link.id, request, "success", is_verified=True)
        return redirect("share:public_share", short_code=short_code)


def _build_share_snapshot_from_account(share_link: ShareLinkModel) -> int | None:
    """Generate a snapshot directly from the current account state."""
    account = get_object_or_404(
        SimulatedAccountModel.objects.prefetch_related("positions", "trades"),
        id=share_link.account_id,
        user=share_link.owner,
    )
    positions = list(account.positions.all().order_by("-market_value"))
    trades = list(account.trades.all().order_by("-execution_date", "-execution_time")[:20])
    positions_by_code = {position.asset_code: position for position in positions}
    asset_codes = {
        asset_code
        for asset_code in [*(position.asset_code for position in positions), *(trade.asset_code for trade in trades)]
        if asset_code
    }

    total_assets = float(account.total_value or 0)
    market_value = float(account.current_market_value or 0)
    cash_value = float(account.current_cash or 0)
    current_position = round((market_value / total_assets) * 100, 2) if total_assets else 0.0
    allocation_by_type: dict[str, dict] = {}

    position_items = []
    for position in positions:
        asset_type = (position.asset_type or "").strip().lower() or "other"
        position_market_value = float(position.market_value or 0)
        weight = round((float(position.market_value or 0) / total_assets) * 100, 2) if total_assets else 0.0
        bucket = allocation_by_type.setdefault(
            asset_type,
            {
                "key": asset_type,
                "label": _asset_type_label(asset_type),
                "value": 0.0,
                "count": 0,
            },
        )
        bucket["value"] += position_market_value
        bucket["count"] += 1
        position_items.append({
            "asset_code": position.asset_code,
            "asset_name": position.asset_name,
            "asset_type": asset_type,
            "asset_type_label": _asset_type_label(asset_type),
            "quantity": position.quantity,
            "avg_cost": float(position.avg_cost or 0),
            "current_price": float(position.current_price or 0),
            "market_value": position_market_value,
            "pnl": float(position.unrealized_pnl or 0),
            "return_pct": position.unrealized_pnl_pct,
            "weight": weight,
            "entry_reason": position.entry_reason,
            "invalidation_logic": position.invalidation_description,
        })

    if cash_value > 0:
        allocation_by_type["cash"] = {
            "key": "cash",
            "label": _asset_type_label("cash"),
            "value": cash_value,
            "count": 1,
        }

    asset_allocation = []
    for bucket in sorted(
        allocation_by_type.values(),
        key=lambda item: item["value"],
        reverse=True,
    ):
        asset_allocation.append(
            {
                **bucket,
                "pct": round((bucket["value"] / total_assets) * 100, 2) if total_assets else 0.0,
            }
        )

    transaction_items = []
    for trade in trades:
        transaction_items.append({
            "asset_code": trade.asset_code,
            "asset_name": trade.asset_name,
            "action": trade.action,
            "quantity": trade.quantity,
            "price": float(trade.price or 0),
            "amount": float(trade.amount or 0),
            "reason": trade.reason,
            "created_at": _as_iso_datetime(trade.execution_time),
        })

    decision_items, evidence_items = _build_decision_chain(account, asset_codes, positions_by_code)
    if not decision_items:
        for trade in trades[:10]:
            if trade.reason:
                position = positions_by_code.get(trade.asset_code)
                decision_items.append({
                    "title": f"{'买入' if trade.action == 'buy' else '卖出'} {trade.asset_name or trade.asset_code}",
                    "status": "executed",
                    "get_status_display": DECISION_STATUS_DISPLAY["executed"],
                    "description": trade.reason,
                    "rationale": trade.reason,
                    "asset_code": trade.asset_code,
                    "created_at": _as_iso_datetime(trade.execution_time),
                    "execution_status": trade.status,
                    "invalidation_logic": position.invalidation_description if position else None,
                })

    summary_payload = {
        "account_name": account.account_name,
        "portfolio_type": _normalize_portfolio_type(account.account_type),
        "current_position": current_position,
        "inception_date": account.start_date.isoformat() if account.start_date else None,
        "total_assets": total_assets,
        "cash_balance": cash_value,
    }
    performance_payload = {
        "total_return": account.total_return,
        "annualized_return": account.annual_return,
        "max_drawdown": account.max_drawdown,
        "sharpe_ratio": account.sharpe_ratio,
        "win_rate": account.win_rate,
        "return_7d": None,
        "return_30d": None,
        "benchmark_name": "沪深300",
        "chart_dates": [],
        "portfolio_values": [],
        "benchmark_values": [],
    }
    positions_payload = {
        "items": position_items,
        "summary": {
            "total_value": market_value,
            "total_pnl": float(sum(float(p.unrealized_pnl or 0) for p in positions)),
            "cash_balance": cash_value,
            "total_assets": total_assets,
            "position_count": len(position_items),
            "asset_allocation": asset_allocation,
        },
        "position_count": len(position_items),
    }
    transactions_payload = {
        "items": transaction_items,
        "total_trades": account.total_trades,
    }
    decision_payload = {
        "items": decision_items,
        "evidence": evidence_items,
    }

    return ShareSnapshotUseCases().create_snapshot(
        share_link_id=share_link.id,
        summary_payload=summary_payload,
        performance_payload=performance_payload,
        positions_payload=positions_payload,
        transactions_payload=transactions_payload,
        decision_payload=decision_payload,
        source_range_start=account.start_date,
        source_range_end=timezone.now().date(),
    )


def _get_live_share_snapshot(share_link: ShareLinkModel) -> dict | None:
    try:
        _build_share_snapshot_from_account(share_link)
    except Exception:
        pass
    return ShareSnapshotUseCases().get_latest_snapshot(share_link.id)


@login_required
def share_manage_page(request, share_link_id: int | None = None):
    """Management page for creating and reviewing share links."""
    accounts = SimulatedAccountModel.objects.filter(user=request.user).order_by("-created_at")
    selected_account_id = request.GET.get("account_id") or request.POST.get("account_id")
    edit_share_link = None
    edit_share_link_id = share_link_id or request.GET.get("edit")
    if edit_share_link_id:
        edit_share_link = get_object_or_404(ShareLinkModel, id=edit_share_link_id, owner=request.user)
        selected_account_id = edit_share_link.account_id

    if request.method == "POST":
        share_link_id = request.POST.get("share_link_id")
        account_id = request.POST.get("account_id")
        title = (request.POST.get("title") or "").strip()
        subtitle = (request.POST.get("subtitle") or "").strip() or None
        share_level = request.POST.get("share_level") or "snapshot"
        theme = request.POST.get("theme") or "bloomberg"
        password = request.POST.get("password") or None
        expires_at_raw = request.POST.get("expires_at") or None
        max_access_count_raw = request.POST.get("max_access_count") or None

        expires_at = None
        if expires_at_raw:
            parsed = parse_datetime(expires_at_raw)
            if parsed is not None:
                expires_at = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed

        max_access_count = int(max_access_count_raw) if max_access_count_raw else None

        try:
            use_case = ShareLinkUseCases()
            if share_link_id:
                entity = use_case.update_share_link(
                    share_link_id=int(share_link_id),
                    owner_id=request.user.id,
                    title=title,
                    subtitle=subtitle,
                    theme=theme,
                    share_level=share_level,
                    password=password if password is not None else None,
                    expires_at=expires_at,
                    max_access_count=max_access_count,
                    show_amounts=bool(request.POST.get("show_amounts")),
                    show_positions=bool(request.POST.get("show_positions")),
                    show_transactions=bool(request.POST.get("show_transactions")),
                    show_decision_summary=bool(request.POST.get("show_decision_summary")),
                    show_decision_evidence=bool(request.POST.get("show_decision_evidence")),
                    show_invalidation_logic=bool(request.POST.get("show_invalidation_logic")),
                )
                if entity is None:
                    raise ValueError("分享链接不存在")
                _build_share_snapshot_from_account(ShareLinkModel.objects.get(id=entity.id))
                messages.success(request, "分享链接已更新")
            else:
                entity = use_case.create_share_link(
                    owner_id=request.user.id,
                    account_id=int(account_id),
                    title=title,
                    subtitle=subtitle,
                    theme=theme,
                    share_level=share_level,
                    password=password,
                    expires_at=expires_at,
                    max_access_count=max_access_count,
                    show_amounts=bool(request.POST.get("show_amounts")),
                    show_positions=bool(request.POST.get("show_positions")),
                    show_transactions=bool(request.POST.get("show_transactions")),
                    show_decision_summary=bool(request.POST.get("show_decision_summary")),
                    show_decision_evidence=bool(request.POST.get("show_decision_evidence")),
                    show_invalidation_logic=bool(request.POST.get("show_invalidation_logic")),
                )
                _build_share_snapshot_from_account(ShareLinkModel.objects.get(id=entity.id))
                messages.success(request, "分享链接已创建")
            return redirect("share:manage")
        except Exception as exc:
            messages.error(request, f"创建分享链接失败：{exc}")
            selected_account_id = account_id

    share_links = (
        ShareLinkModel.objects.filter(owner=request.user)
        .select_related("owner")
        .order_by("-created_at")
    )
    account_map = {account.id: account for account in accounts}
    for link in share_links:
        account = account_map.get(link.account_id)
        link.account_name = account.account_name if account else str(link.account_id)

    return render(
        request,
        "share/manage.html",
        {
            "accounts": accounts,
            "share_links": share_links,
            "selected_account_id": int(selected_account_id) if selected_account_id else None,
            "edit_share_link": edit_share_link,
        },
    )


@login_required
def revoke_share_link_page(request, share_link_id: int):
    """Revoke a share link from management page."""
    if request.method != "POST":
        raise Http404()

    success = ShareLinkUseCases().revoke_share_link(share_link_id, request.user.id)
    if success:
        messages.success(request, "分享链接已撤销")
    else:
        messages.error(request, "撤销失败")
    return redirect("share:manage")


@login_required
def refresh_share_link_page(request, share_link_id: int):
    """Sync the cached share snapshot from current account data."""
    if request.method != "POST":
        raise Http404()

    share_link = get_object_or_404(ShareLinkModel, id=share_link_id, owner=request.user)
    try:
        _build_share_snapshot_from_account(share_link)
        messages.success(request, "分享页缓存已同步，公开页默认也会实时更新")
    except Exception as exc:
        messages.error(request, f"同步失败：{exc}")
    return redirect("share:manage")


@login_required
def share_disclaimer_manage_page(request):
    """Frontend management page for global share disclaimer config."""
    if not request.user.is_staff:
        raise PermissionDenied("只有管理员可以修改分享页风险提示配置")

    config = ShareDisclaimerConfigModel.get_solo()

    if request.method == "POST":
        lines = [
            line.strip()
            for line in (request.POST.get("lines") or "").splitlines()
            if line.strip()
        ]
        if not lines:
            messages.error(request, "风险提示内容不能为空")
        else:
            config.is_enabled = bool(request.POST.get("is_enabled"))
            config.modal_enabled = bool(request.POST.get("modal_enabled"))
            config.modal_title = (request.POST.get("modal_title") or "重要声明").strip() or "重要声明"
            config.modal_confirm_text = (
                (request.POST.get("modal_confirm_text") or "我已知悉").strip() or "我已知悉"
            )
            config.lines = lines
            config.save(
                update_fields=[
                    "is_enabled",
                    "modal_enabled",
                    "modal_title",
                    "modal_confirm_text",
                    "lines",
                    "updated_at",
                ]
            )
            messages.success(request, "分享页风险提示配置已更新")
            return redirect("share:manage_disclaimer")

    return render(
        request,
        "share/disclaimer_manage.html",
        {
            "config": config,
            "lines_text": "\n".join(config.lines or []),
        },
    )
