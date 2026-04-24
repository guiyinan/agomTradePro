"""Share API and page views."""

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views import View
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.share.application.interface_services import (
    build_share_manage_context,
    build_share_snapshot_from_account,
    get_live_share_snapshot,
    get_owner_share_link,
    get_public_share_link_model,
    get_share_disclaimer_config,
    get_share_disclaimer_lines,
    get_share_link_model,
    get_share_link_queryset,
    increment_share_link_access_count,
    list_share_snapshots,
    update_share_disclaimer_config,
)
from apps.share.application.use_cases import (
    ShareAccessUseCases,
    ShareLinkUseCases,
)
from apps.share.interface.serializers import (
    CreateShareLinkSerializer,
    PublicShareLinkSerializer,
    ShareAccessRequestSerializer,
    ShareLinkSerializer,
    ShareSnapshotSerializer,
    UpdateShareLinkSerializer,
)


def _normalize_portfolio_type(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"real", "live", "实盘", "实仓"}:
        return "real"
    return "simulated"


class ShareVisibilityMixin:
    """Shared helpers for public share access."""

    _MONEY_WORDS = ("amount", "value", "cash", "capital", "profit", "loss")
    _POSITION_MONEY_WORDS = ("amount", "value", "cost", "price", "pnl")
    _TRANSACTION_MONEY_WORDS = ("amount", "value", "cost", "price")

    @staticmethod
    def _password_session_key(share_link_id: int) -> str:
        return f"share_verified_{share_link_id}"

    def _is_password_verified(self, request, share_link: Any) -> bool:
        return bool(request.session.get(self._password_session_key(share_link.id), False))

    def _mark_password_verified(self, request, share_link: Any) -> None:
        request.session[self._password_session_key(share_link.id)] = True
        request.session.modified = True

    def _clear_password_verified(self, request, share_link: Any) -> None:
        request.session.pop(self._password_session_key(share_link.id), None)
        request.session.modified = True

    def _get_client_ip(self, request) -> str:
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")

    def _log_access(
        self, share_link_id: int, request, result_status: str, is_verified: bool = False
    ):
        ShareAccessUseCases().log_access(
            share_link_id=share_link_id,
            ip_address=self._get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            referer=request.META.get("HTTP_REFERER", ""),
            result_status=result_status,
            is_verified=is_verified,
        )

    def _filter_snapshot_by_visibility(self, snapshot: dict, share_link: Any) -> dict:
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
                    money_word in k.lower() for money_word in self._MONEY_WORDS
                )
            }
        result["summary"] = summary

        performance = dict(snapshot.get("performance", {}) or {})
        if not share_link.show_amounts:
            performance = {
                k: v
                for k, v in performance.items()
                if not any(
                    money_word in k.lower() for money_word in self._MONEY_WORDS
                )
            }
        result["performance"] = performance

        if share_link.show_positions:
            positions = dict(snapshot.get("positions", {}) or {})
            if not share_link.show_amounts and isinstance(positions.get("items"), list):
                positions["items"] = [
                    {
                        k: v
                        for k, v in item.items()
                        if not any(
                            money_word in k.lower() for money_word in self._POSITION_MONEY_WORDS
                        )
                    }
                    for item in positions["items"]
                ]
            if not share_link.show_amounts and isinstance(positions.get("summary"), dict):
                position_summary = dict(positions["summary"])
                position_summary = {
                    k: v
                    for k, v in position_summary.items()
                    if not any(
                        money_word in k.lower()
                        for money_word in (*self._POSITION_MONEY_WORDS, *self._MONEY_WORDS)
                    )
                }
                for hidden_key in ("total_assets",):
                    position_summary.pop(hidden_key, None)
                if isinstance(position_summary.get("asset_allocation"), list):
                    position_summary["asset_allocation"] = [
                        {k: v for k, v in item.items() if k != "value"}
                        for item in position_summary["asset_allocation"]
                    ]
                positions["summary"] = position_summary
            result["positions"] = positions

        if share_link.show_transactions:
            transactions = dict(snapshot.get("transactions", {}) or {})
            if not share_link.show_amounts and isinstance(transactions.get("items"), list):
                transactions["items"] = [
                    {
                        k: v
                        for k, v in item.items()
                        if not any(
                            money_word in k.lower() for money_word in self._TRANSACTION_MONEY_WORDS
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
        share_link: Any,
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

        disclaimer_config = get_share_disclaimer_config()
        disclaimer_lines = get_share_disclaimer_lines(summary.get("portfolio_type"))

        return {
            "portfolio_name": share_link.title,
            "portfolio_description": share_link.subtitle,
            "share_theme": share_link.theme,
            "portfolio_type": _normalize_portfolio_type(summary.get("portfolio_type")),
            "is_private": share_link.requires_password(),
            "requires_password": requires_password,
            "password_error": password_error,
            "show_amounts": share_link.show_amounts,
            "owner_name": (
                share_link.owner.get_full_name().strip()
                or getattr(share_link.owner, "username", "")
                or getattr(share_link.owner, "email", "")
            ),
            "created_at": share_link.created_at,
            "is_simulated": _normalize_portfolio_type(summary.get("portfolio_type")) == "simulated",
            "last_updated": first_of(
                "generated_at", default=share_link.last_snapshot_at, source=snapshot
            ),
            "total_return": first_of(
                "total_return",
                "total_return_pct",
                source=performance,
                default=summary.get("total_return"),
            ),
            "return_7d": first_of("return_7d", "seven_day_return", source=performance),
            "return_30d": first_of("return_30d", "thirty_day_return", source=performance),
            "current_position": first_of("current_position", "position_ratio", source=summary),
            "inception_date": first_of("inception_date", source=summary),
            "annualized_return": first_of("annualized_return", source=performance),
            "max_drawdown": first_of("max_drawdown", source=performance),
            "sharpe_ratio": first_of("sharpe_ratio", source=performance),
            "win_rate": first_of("win_rate", source=performance),
            "total_trades": first_of(
                "total_trades",
                source=transactions,
                default=len(transactions.get("items", []) or []),
            ),
            "position_count": first_of(
                "position_count", source=positions, default=len(positions.get("items", []) or [])
            ),
            "positions": positions.get("items", []),
            "position_summary": positions.get("summary", {}),
            "recent_transactions": transactions.get("items", []),
            "decisions": decisions.get("items", decisions if isinstance(decisions, list) else []),
            "regime_info": decisions.get("regime_info") if isinstance(decisions, dict) else None,
            "benchmark_name": first_of("benchmark_name", source=performance, default="沪深300"),
            "chart_dates": first_of("chart_dates", "dates", source=performance, default=[]),
            "portfolio_values": first_of(
                "portfolio_values", "returns", "series", source=performance, default=[]
            ),
            "benchmark_values": first_of(
                "benchmark_values", "benchmark_series", source=performance, default=[]
            ),
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


class ShareLinkViewSet(viewsets.ModelViewSet):
    """Authenticated management API for share links."""

    serializer_class = ShareLinkSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return get_share_link_queryset(self.request.user.id)

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

        model = get_share_link_model(entity.id)
        if model is None:
            return Response({"error": "创建后的分享链接不存在"}, status=status.HTTP_400_BAD_REQUEST)
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

        model = get_share_link_model(entity.id)
        if model is None:
            return Response({"error": "更新后的分享链接不存在"}, status=status.HTTP_400_BAD_REQUEST)
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
        snapshots = list_share_snapshots(instance.id)
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
        model = get_public_share_link_model(short_code)
        if not entity or model is None:
            return Response({"error": "分享链接不存在"}, status=status.HTTP_404_NOT_FOUND)

        is_accessible, result_status = entity.is_accessible(timezone.now())
        if not is_accessible:
            return Response({"error": result_status.value}, status=status.HTTP_403_FORBIDDEN)

        if entity.requires_password() and not self._is_password_verified(request, model):
            self._log_access(model.id, request, "password_required", is_verified=False)
            return Response(
                {"requires_password": True, "title": entity.title},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        snapshot = get_live_share_snapshot(share_link_id=model.id)
        if snapshot:
            snapshot = self._filter_snapshot_by_visibility(snapshot, model)
        return Response(PublicShareLinkSerializer(model).data)

    @action(detail=False, methods=["post"], url_path="(?P<short_code>[^/.]+)/access")
    def access(self, request, short_code=None):
        entity = ShareLinkUseCases().get_share_link_by_code(short_code)
        model = get_public_share_link_model(short_code)
        if not entity or model is None:
            return Response({"error": "分享链接不存在"}, status=status.HTTP_404_NOT_FOUND)

        is_accessible, result_status = entity.is_accessible(timezone.now())
        if not is_accessible:
            return Response({"error": result_status.value}, status=status.HTTP_403_FORBIDDEN)

        serializer = ShareAccessRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        password = serializer.validated_data.get("password")

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
        increment_share_link_access_count(share_link_id=model.id)
        snapshot = get_live_share_snapshot(share_link_id=model.id)
        if snapshot:
            snapshot = self._filter_snapshot_by_visibility(snapshot, model)

        return Response({"share_link": PublicShareLinkSerializer(model).data, "snapshot": snapshot})

    @action(detail=False, methods=["get"], url_path="(?P<short_code>[^/.]+)/snapshot")
    def snapshot(self, request, short_code=None):
        entity = ShareLinkUseCases().get_share_link_by_code(short_code)
        model = get_public_share_link_model(short_code)
        if not entity or model is None:
            return Response({"error": "分享链接不存在"}, status=status.HTTP_404_NOT_FOUND)

        is_accessible, result_status = entity.is_accessible(timezone.now())
        if not is_accessible:
            return Response({"error": result_status.value}, status=status.HTTP_403_FORBIDDEN)

        if entity.requires_password() and not self._is_password_verified(request, model):
            self._log_access(model.id, request, "password_required", is_verified=False)
            return Response({"error": "需要密码验证"}, status=status.HTTP_401_UNAUTHORIZED)

        snapshot = get_live_share_snapshot(share_link_id=model.id)
        if not snapshot:
            return Response({"error": "快照不存在"}, status=status.HTTP_404_NOT_FOUND)

        self._log_access(model.id, request, "success", is_verified=entity.requires_password())
        increment_share_link_access_count(share_link_id=model.id)
        return Response(self._filter_snapshot_by_visibility(snapshot, model))


class PublicSharePageView(ShareVisibilityMixin, View):
    """Server-rendered public share page."""

    template_name = "share/public_share.html"

    def _get_share_link(self, short_code: str):
        share_link = get_public_share_link_model(short_code)
        if share_link is None:
            raise Http404("分享链接不存在")
        if not share_link.is_accessible():
            raise Http404("分享链接不可访问")
        return share_link

    def get(self, request, short_code: str):
        share_link = self._get_share_link(short_code)
        if share_link.requires_password() and not self._is_password_verified(request, share_link):
            context = self._build_public_context(share_link, None, requires_password=True)
            return render(request, self.template_name, context, status=401)

        snapshot = get_live_share_snapshot(share_link_id=share_link.id)
        filtered_snapshot = (
            self._filter_snapshot_by_visibility(snapshot, share_link) if snapshot else None
        )
        context = self._build_public_context(share_link, filtered_snapshot, requires_password=False)
        self._log_access(
            share_link.id,
            request,
            "success",
            is_verified=share_link.requires_password(),
        )
        increment_share_link_access_count(share_link_id=share_link.id)
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


@login_required
def share_manage_page(request, share_link_id: int | None = None):
    """Management page for creating and reviewing share links."""
    selected_account_id_raw = request.GET.get("account_id") or request.POST.get("account_id")
    selected_account_id = int(selected_account_id_raw) if str(selected_account_id_raw or "").isdigit() else None
    edit_share_link_id_raw = share_link_id or request.GET.get("edit")
    edit_share_link_id = int(edit_share_link_id_raw) if str(edit_share_link_id_raw or "").isdigit() else None

    if request.method == "POST":
        share_link_id_raw = request.POST.get("share_link_id")
        account_id = request.POST.get("account_id")
        title = (request.POST.get("title") or "").strip()
        subtitle = (request.POST.get("subtitle") or "").strip() or None
        share_level = request.POST.get("share_level") or "snapshot"
        theme = request.POST.get("theme") or "bloomberg"
        password_enabled = bool(request.POST.get("password_enabled"))
        raw_password = request.POST.get("password")
        password = (raw_password or "").strip()
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
            if share_link_id_raw:
                password_value = password if password_enabled else ""
                entity = use_case.update_share_link(
                    share_link_id=int(share_link_id_raw),
                    owner_id=request.user.id,
                    title=title,
                    subtitle=subtitle,
                    theme=theme,
                    share_level=share_level,
                    password=password_value,
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
                build_share_snapshot_from_account(share_link_id=entity.id)
                messages.success(request, "分享链接已更新")
            else:
                password_value = password if password_enabled and password else None
                entity = use_case.create_share_link(
                    owner_id=request.user.id,
                    account_id=int(account_id),
                    title=title,
                    subtitle=subtitle,
                    theme=theme,
                    share_level=share_level,
                    password=password_value,
                    expires_at=expires_at,
                    max_access_count=max_access_count,
                    show_amounts=bool(request.POST.get("show_amounts")),
                    show_positions=bool(request.POST.get("show_positions")),
                    show_transactions=bool(request.POST.get("show_transactions")),
                    show_decision_summary=bool(request.POST.get("show_decision_summary")),
                    show_decision_evidence=bool(request.POST.get("show_decision_evidence")),
                    show_invalidation_logic=bool(request.POST.get("show_invalidation_logic")),
                )
                build_share_snapshot_from_account(share_link_id=entity.id)
                messages.success(request, "分享链接已创建")
            return redirect("share:manage")
        except Exception as exc:
            messages.error(request, f"创建分享链接失败：{exc}")
            selected_account_id = int(account_id) if str(account_id or "").isdigit() else None

    context = build_share_manage_context(
        owner_id=request.user.id,
        selected_account_id=selected_account_id,
        edit_share_link_id=edit_share_link_id,
    )
    return render(
        request,
        "share/manage.html",
        context,
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

    share_link = get_owner_share_link(request.user.id, share_link_id)
    if share_link is None:
        raise Http404()
    try:
        build_share_snapshot_from_account(share_link_id=share_link.id)
        messages.success(request, "分享页缓存已同步，公开页默认也会实时更新")
    except Exception as exc:
        messages.error(request, f"同步失败：{exc}")
    return redirect("share:manage")


@login_required
def share_disclaimer_manage_page(request):
    """Frontend management page for global share disclaimer config."""
    if not request.user.is_staff:
        raise PermissionDenied("只有管理员可以修改分享页风险提示配置")

    config = get_share_disclaimer_config()

    if request.method == "POST":
        lines = [
            line.strip() for line in (request.POST.get("lines") or "").splitlines() if line.strip()
        ]
        if not lines:
            messages.error(request, "风险提示内容不能为空")
        else:
            config = update_share_disclaimer_config(
                is_enabled=bool(request.POST.get("is_enabled")),
                modal_enabled=bool(request.POST.get("modal_enabled")),
                modal_title=(request.POST.get("modal_title") or "重要声明").strip() or "重要声明",
                modal_confirm_text=(
                    request.POST.get("modal_confirm_text") or "我已知悉"
                ).strip()
                or "我已知悉",
                lines=lines,
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
