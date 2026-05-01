"""Dashboard Alpha stock interaction views."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render


def _dashboard_views():
    from apps.dashboard.interface import views as dashboard_views

    return dashboard_views


@login_required(login_url="/account/login/")
def alpha_refresh_htmx(request):
    """Trigger a manual realtime Alpha refresh for today's dashboard universe."""

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    dashboard_views = _dashboard_views()
    try:
        target_date = dashboard_views.django_timezone.localdate()
        top_n = dashboard_views._parse_positive_int_param(
            request.POST.get("top_n", 10),
            field_name="top_n",
            default=10,
        )
        raw_portfolio_id = request.POST.get("portfolio_id")
        pool_mode = dashboard_views._normalize_dashboard_alpha_pool_mode(
            request.POST.get("pool_mode")
        )
        raw_alpha_scope = request.POST.get("alpha_scope")
        alpha_scope = dashboard_views.normalize_alpha_scope(raw_alpha_scope)
        portfolio_id = (
            dashboard_views._parse_positive_int_param(
                raw_portfolio_id,
                field_name="portfolio_id",
                default=0,
            )
            if raw_portfolio_id not in (None, "")
            else None
        )
        if (
            alpha_scope == dashboard_views.ALPHA_SCOPE_PORTFOLIO
            and raw_alpha_scope not in (None, "")
            and portfolio_id is None
        ):
            raise ValueError("账户专属 Alpha 推理必须提供 portfolio_id")

        user_id = dashboard_views._get_request_user_id(request.user)
        raw_universe_id = str(request.POST.get("universe_id") or "").strip() or "csi300"
        resolved_pool = None
        if alpha_scope == dashboard_views.ALPHA_SCOPE_PORTFOLIO and user_id is not None:
            resolved_pool = dashboard_views.PortfolioAlphaPoolResolver().resolve(
                user_id=user_id,
                portfolio_id=portfolio_id,
                trade_date=target_date,
                pool_mode=pool_mode,
            )

        use_sync = request.POST.get("sync") in ("1", "true")
        sync_reason = None
        universe_id = (
            resolved_pool.scope.universe_id if resolved_pool is not None else raw_universe_id
        )
        scope_hash = resolved_pool.scope.scope_hash if resolved_pool is not None else None
        lock_meta_payload = dashboard_views.build_dashboard_alpha_refresh_metadata(
            alpha_scope=alpha_scope,
            target_date=target_date,
            top_n=top_n,
            universe_id=universe_id,
            portfolio_id=portfolio_id,
            pool_mode=resolved_pool.scope.pool_mode if resolved_pool is not None else pool_mode,
            scope_hash=scope_hash,
        )
        lock_key = dashboard_views._build_alpha_refresh_lock_key(
            alpha_scope=alpha_scope,
            target_date=target_date,
            top_n=top_n,
            raw_universe_id=raw_universe_id,
            resolved_pool=resolved_pool,
        )
        lock_meta = dashboard_views._resolve_existing_alpha_refresh_lock(lock_key)
        if lock_meta is not None:
            return dashboard_views._build_alpha_refresh_conflict_response(
                alpha_scope=alpha_scope,
                target_date=target_date,
                top_n=top_n,
                universe_id=universe_id,
                portfolio_id=portfolio_id,
                pool_mode=pool_mode,
                lock_meta=lock_meta,
            )

        if not use_sync:
            celery_health = dashboard_views._get_dashboard_alpha_refresh_celery_health()
            if not bool(celery_health.get("available")):
                use_sync = True
                sync_reason = str(celery_health.get("reason") or "celery_unavailable")

        if use_sync:
            return _alpha_refresh_sync(
                lock_key=lock_key,
                target_date=target_date,
                top_n=top_n,
                raw_universe_id=raw_universe_id,
                alpha_scope=alpha_scope,
                portfolio_id=portfolio_id,
                pool_mode=pool_mode,
                resolved_pool=resolved_pool,
                sync_reason=sync_reason,
            )

        from apps.alpha.application.tasks import qlib_predict_scores

        if resolved_pool is None:
            if not dashboard_views.acquire_dashboard_alpha_refresh_pending_lock(
                lock_key,
                meta=lock_meta_payload,
                timeout=dashboard_views._ALPHA_REFRESH_LOCK_TTL_SECONDS,
            ):
                lock_meta = dashboard_views._resolve_existing_alpha_refresh_lock(lock_key) or {
                    "status": "running",
                    "mode": "async",
                    "task_id": None,
                    "task_state": "PENDING",
                }
                return dashboard_views._build_alpha_refresh_conflict_response(
                    alpha_scope=alpha_scope,
                    target_date=target_date,
                    top_n=top_n,
                    universe_id=universe_id,
                    portfolio_id=portfolio_id,
                    pool_mode=pool_mode,
                    lock_meta=lock_meta,
                )
            task = qlib_predict_scores.delay(raw_universe_id, target_date.isoformat(), top_n)
            dashboard_views.record_pending_task(
                task_id=task.id,
                task_name="apps.alpha.application.tasks.qlib_predict_scores",
                args=(raw_universe_id, target_date.isoformat(), top_n),
            )
            dashboard_views.promote_dashboard_alpha_refresh_task_lock(
                lock_key,
                task_id=task.id,
                timeout=dashboard_views._ALPHA_REFRESH_LOCK_TTL_SECONDS,
            )
            message = (
                "已触发通用 Alpha 刷新任务；结果仅用于研究排名，不作为账户专属建议。"
                if alpha_scope == dashboard_views.ALPHA_SCOPE_GENERAL
                else "已触发 Alpha 实时刷新任务，请稍后刷新查看最新结果。"
            )
            response_payload = {
                "success": True,
                "alpha_scope": alpha_scope,
                "task_id": task.id,
                "universe_id": raw_universe_id,
                "portfolio_id": portfolio_id,
                "scope_hash": None,
                "requested_trade_date": target_date.isoformat(),
                "pool_mode": pool_mode,
                "message": message,
                "poll_after_ms": 5000,
                "must_not_use_for_decision": True,
            }
        else:
            if not dashboard_views.acquire_dashboard_alpha_refresh_pending_lock(
                lock_key,
                meta=lock_meta_payload,
                timeout=dashboard_views._ALPHA_REFRESH_LOCK_TTL_SECONDS,
            ):
                lock_meta = dashboard_views._resolve_existing_alpha_refresh_lock(lock_key) or {
                    "status": "running",
                    "mode": "async",
                    "task_id": None,
                    "task_state": "PENDING",
                }
                return dashboard_views._build_alpha_refresh_conflict_response(
                    alpha_scope=alpha_scope,
                    target_date=target_date,
                    top_n=top_n,
                    universe_id=universe_id,
                    portfolio_id=portfolio_id,
                    pool_mode=pool_mode,
                    lock_meta=lock_meta,
                )
            task = qlib_predict_scores.delay(
                resolved_pool.scope.universe_id,
                target_date.isoformat(),
                top_n,
                scope_payload=resolved_pool.scope.to_dict(),
            )
            dashboard_views.record_pending_task(
                task_id=task.id,
                task_name="apps.alpha.application.tasks.qlib_predict_scores",
                args=(resolved_pool.scope.universe_id, target_date.isoformat(), top_n),
                kwargs={"scope_payload": resolved_pool.scope.to_dict()},
            )
            dashboard_views.promote_dashboard_alpha_refresh_task_lock(
                lock_key,
                task_id=task.id,
                timeout=dashboard_views._ALPHA_REFRESH_LOCK_TTL_SECONDS,
            )
            response_payload = {
                "success": True,
                "alpha_scope": dashboard_views.ALPHA_SCOPE_PORTFOLIO,
                "task_id": task.id,
                "universe_id": resolved_pool.scope.universe_id,
                "portfolio_id": resolved_pool.portfolio_id,
                "scope_hash": resolved_pool.scope.scope_hash,
                "requested_trade_date": target_date.isoformat(),
                "pool_mode": resolved_pool.scope.pool_mode,
                "message": "已触发账户专属 scoped Qlib 推理任务，请稍后刷新查看最新结果。",
                "poll_after_ms": 5000,
                "must_not_use_for_decision": True,
            }
        return JsonResponse(response_payload)
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except Exception as exc:
        if "lock_key" in locals():
            dashboard_views.release_dashboard_alpha_refresh_lock(lock_key)
        dashboard_views.logger.error(
            "Failed to trigger alpha realtime refresh: %s",
            exc,
            exc_info=True,
        )
        return JsonResponse(
            {"success": False, "error": f"触发 Alpha 实时刷新失败: {exc}"},
            status=500,
        )


def _alpha_refresh_sync(
    *,
    lock_key: str,
    target_date,
    top_n,
    raw_universe_id,
    alpha_scope,
    portfolio_id,
    pool_mode,
    resolved_pool,
    sync_reason: str | None = None,
):
    """Run one scoped Qlib inference inline for dashboard manual refresh."""

    dashboard_views = _dashboard_views()
    from apps.alpha.application.tasks import qlib_predict_scores

    universe_id = raw_universe_id
    scope_hash = None
    scope_payload = None
    if resolved_pool is not None:
        universe_id = resolved_pool.scope.universe_id
        scope_hash = resolved_pool.scope.scope_hash
        scope_payload = resolved_pool.scope.to_dict()

    sync_lock_meta = dashboard_views.build_dashboard_alpha_refresh_metadata(
        alpha_scope=alpha_scope,
        target_date=target_date,
        top_n=top_n,
        universe_id=universe_id,
        portfolio_id=portfolio_id,
        pool_mode=pool_mode,
        scope_hash=scope_hash,
    )
    if not dashboard_views.acquire_dashboard_alpha_refresh_pending_lock(
        lock_key,
        meta=sync_lock_meta,
        timeout=dashboard_views._ALPHA_REFRESH_LOCK_TTL_SECONDS,
    ):
        lock_meta = dashboard_views._resolve_existing_alpha_refresh_lock(lock_key) or {
            "status": "running",
            "mode": "sync",
            "task_id": None,
            "task_state": "RUNNING",
        }
        return dashboard_views._build_alpha_refresh_conflict_response(
            alpha_scope=alpha_scope,
            target_date=target_date,
            top_n=top_n,
            universe_id=universe_id,
            portfolio_id=portfolio_id,
            pool_mode=pool_mode,
            lock_meta=lock_meta,
        )

    try:
        dashboard_views.promote_dashboard_alpha_refresh_task_lock(
            lock_key,
            task_id="__sync__",
            timeout=dashboard_views._ALPHA_REFRESH_LOCK_TTL_SECONDS,
            meta_updates=sync_lock_meta,
        )
        task_result = qlib_predict_scores.apply(
            args=[universe_id, target_date.isoformat(), top_n],
            kwargs={"scope_payload": scope_payload},
        )
        result_payload = task_result.get(propagate=False)
        failed = bool(getattr(task_result, "failed", lambda: False)())

        if failed:
            dashboard_views.logger.warning(
                "Sync alpha inference failed: universe=%s, trade_date=%s, result=%s",
                universe_id,
                target_date.isoformat(),
                result_payload,
            )
            return JsonResponse(
                {"success": False, "error": "同步推理失败，请检查 Qlib 运行状态。"},
                status=500,
            )

        if not isinstance(result_payload, dict) or result_payload.get("status") != "success":
            return JsonResponse(
                {
                    "success": False,
                    "error": "推理完成但无新结果（可能数据不足、数据未更新或非交易日）。",
                    "alpha_scope": alpha_scope,
                    "universe_id": universe_id,
                    "requested_trade_date": target_date.isoformat(),
                },
                status=200,
            )

        if result_payload.get("fallback_used"):
            message = "同步推理完成，但当前仍使用最近可用 Alpha cache；请先补齐 Qlib 基础数据。"
        elif result_payload.get("trade_date_adjusted"):
            effective_trade_date = result_payload.get("effective_trade_date") or result_payload.get(
                "qlib_data_latest_date"
            )
            message = f"同步推理完成，当前基于最近可用交易日 {effective_trade_date} 更新评分。"
        elif sync_reason == "no_active_workers":
            message = "未检测到 Celery worker，已改为同步推理并完成评分更新。"
        elif sync_reason == "unhealthy":
            message = "Celery 当前异常，已改为同步推理并完成评分更新。"
        elif sync_reason == "health_check_failed":
            message = "Celery 健康检查失败，已改为同步推理并完成评分更新。"
        else:
            message = "同步推理完成，已更新评分。"

        return JsonResponse(
            {
                "success": True,
                "alpha_scope": alpha_scope,
                "task_id": None,
                "universe_id": universe_id,
                "portfolio_id": portfolio_id,
                "scope_hash": result_payload.get("scope_hash") or scope_hash,
                "requested_trade_date": target_date.isoformat(),
                "pool_mode": pool_mode,
                "message": message,
                "poll_after_ms": 1000,
                "sync": True,
                "sync_reason": sync_reason,
                "must_not_use_for_decision": True,
            }
        )
    finally:
        dashboard_views.release_dashboard_alpha_refresh_lock(lock_key)


@login_required(login_url="/account/login/")
def alpha_stocks_htmx(request):
    """Return the dashboard Alpha stock table payload."""

    dashboard_views = _dashboard_views()
    try:
        top_n = dashboard_views._parse_positive_int_param(
            request.GET.get("top_n", 10),
            field_name="top_n",
            default=10,
        )
        selected_exit_asset_code = (
            str(request.GET.get("exit_asset_code") or "").strip().upper() or None
        )
        raw_exit_account_id = request.GET.get("exit_account_id")
        selected_exit_account_id = (
            dashboard_views._parse_positive_int_param(
                raw_exit_account_id,
                field_name="exit_account_id",
                default=0,
            )
            if raw_exit_account_id not in (None, "")
            else None
        )
        raw_portfolio_id = request.GET.get("portfolio_id")
        pool_mode = dashboard_views._normalize_dashboard_alpha_pool_mode(
            request.GET.get("pool_mode")
        )
        alpha_scope = dashboard_views.normalize_alpha_scope(request.GET.get("alpha_scope"))
        portfolio_id = (
            dashboard_views._parse_positive_int_param(
                raw_portfolio_id,
                field_name="portfolio_id",
                default=0,
            )
            if raw_portfolio_id not in (None, "")
            else None
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    scores_payload = dashboard_views._get_alpha_stock_scores_payload(
        top_n=top_n,
        user=request.user,
        portfolio_id=None if alpha_scope == dashboard_views.ALPHA_SCOPE_GENERAL else portfolio_id,
        pool_mode=pool_mode,
        alpha_scope=alpha_scope,
    )
    scores = scores_payload["items"]
    meta = scores_payload["meta"]
    pool = scores_payload["pool"]
    actionable_candidates = scores_payload["actionable_candidates"]
    exit_watchlist = dashboard_views._mark_alpha_exit_watchlist_selection(
        scores_payload.get("exit_watchlist", []),
        account_id=selected_exit_account_id,
        asset_code=selected_exit_asset_code,
    )
    exit_watch_summary = scores_payload.get("exit_watch_summary", {})
    pending_requests = scores_payload["pending_requests"]
    recent_runs = scores_payload["recent_runs"]
    contract = dashboard_views._build_alpha_readiness_contract(
        meta=meta,
        top_candidates=scores,
        actionable_candidates=actionable_candidates,
        pending_requests=pending_requests,
    )

    if request.GET.get("format") == "json":
        return JsonResponse(
            {
                "success": True,
                "data": {
                    "items": scores,
                    "top_candidates": scores,
                    "actionable_candidates": actionable_candidates,
                    "exit_watchlist": exit_watchlist,
                    "exit_watch_summary": exit_watch_summary,
                    "pending_requests": pending_requests,
                    "meta": meta,
                    "pool": pool,
                    "recent_runs": recent_runs,
                    "history_run_id": scores_payload["history_run_id"],
                    "contract": contract,
                    "alpha_scope": alpha_scope,
                    "count": len(scores),
                    "top_n": top_n,
                },
            }
        )

    if "HX-Request" not in request.headers:
        return redirect("dashboard:index")

    context = {
        "alpha_stocks": scores,
        "alpha_meta": meta,
        "alpha_pool": pool,
        "alpha_actionable_candidates": actionable_candidates,
        "alpha_exit_watchlist": exit_watchlist,
        "alpha_exit_watch_summary": exit_watch_summary,
        "alpha_exit_selected_asset_code": selected_exit_asset_code or "",
        "alpha_exit_selected_account_id": selected_exit_account_id or "",
        "alpha_pending_requests": pending_requests,
        "alpha_recent_runs": recent_runs,
        "alpha_history_run_id": scores_payload["history_run_id"],
        "selected_portfolio_id": portfolio_id or pool.get("portfolio_id"),
        "selected_alpha_pool_mode": pool_mode or pool.get("pool_mode"),
        "alpha_scope": alpha_scope,
        "alpha_pool_mode_choices": dashboard_views.get_alpha_pool_mode_choices(),
        "top_n": top_n,
    }
    return render(request, "dashboard/partials/alpha_stocks_table.html", context)


@login_required(login_url="/account/login/")
def alpha_factor_panel_htmx(request):
    """HTMX factor panel for a selected alpha stock."""

    dashboard_views = _dashboard_views()
    if "HX-Request" not in request.headers:
        return redirect("dashboard:index")

    stock_code = (request.GET.get("code") or "").strip()
    source = (request.GET.get("source") or "").strip() or None
    raw_portfolio_id = request.GET.get("portfolio_id")
    pool_mode = dashboard_views._normalize_dashboard_alpha_pool_mode(
        request.GET.get("pool_mode")
    )
    alpha_scope = dashboard_views.normalize_alpha_scope(request.GET.get("alpha_scope"))
    try:
        top_n = dashboard_views._parse_positive_int_param(
            request.GET.get("top_n", 10),
            field_name="top_n",
            default=10,
        )
        portfolio_id = (
            dashboard_views._parse_positive_int_param(
                raw_portfolio_id,
                field_name="portfolio_id",
                default=0,
            )
            if raw_portfolio_id not in (None, "")
            else None
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    if not stock_code:
        return render(
            request,
            "dashboard/partials/alpha_factor_panel.html",
            {
                "stock": None,
                "stock_code": "",
                "provider": source or "unknown",
                "factor_origin": "",
                "factors": [],
                "factor_count": 0,
                "empty_reason": "请选择左侧一只股票查看因子暴露。",
                "alpha_scope": alpha_scope,
                "alpha_meta": {},
                "alpha_pool": {},
                "recommendation_basis": {},
                "factor_basis": [],
                "buy_reasons": [],
                "no_buy_reasons": [],
                "risk_snapshot": {},
            },
        )

    context = dashboard_views._build_alpha_factor_panel(
        stock_code=stock_code,
        source=source,
        top_n=top_n,
        user=request.user,
        portfolio_id=portfolio_id,
        pool_mode=pool_mode,
        alpha_scope=alpha_scope,
    )
    return render(request, "dashboard/partials/alpha_factor_panel.html", context)


@login_required(login_url="/account/login/")
def alpha_exit_panel_htmx(request):
    """HTMX sidebar detail panel for one exit-watchlist item."""

    dashboard_views = _dashboard_views()
    if "HX-Request" not in request.headers:
        return redirect("dashboard:index")

    asset_code = (request.GET.get("asset_code") or "").strip().upper()
    raw_account_id = request.GET.get("account_id")
    raw_portfolio_id = request.GET.get("portfolio_id")
    pool_mode = dashboard_views._normalize_dashboard_alpha_pool_mode(
        request.GET.get("pool_mode")
    )
    alpha_scope = dashboard_views.normalize_alpha_scope(request.GET.get("alpha_scope"))
    try:
        top_n = dashboard_views._parse_positive_int_param(
            request.GET.get("top_n", 10),
            field_name="top_n",
            default=10,
        )
        account_id = (
            dashboard_views._parse_positive_int_param(
                raw_account_id,
                field_name="account_id",
                default=0,
            )
            if raw_account_id not in (None, "")
            else None
        )
        portfolio_id = (
            dashboard_views._parse_positive_int_param(
                raw_portfolio_id,
                field_name="portfolio_id",
                default=0,
            )
            if raw_portfolio_id not in (None, "")
            else None
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    payload = dashboard_views._get_alpha_stock_scores_payload(
        top_n=top_n,
        user=request.user,
        portfolio_id=None if alpha_scope == dashboard_views.ALPHA_SCOPE_GENERAL else portfolio_id,
        pool_mode=pool_mode,
        alpha_scope=alpha_scope,
    )
    context = dashboard_views._build_alpha_exit_detail_panel_context(
        exit_watchlist=payload.get("exit_watchlist", []),
        account_id=account_id,
        asset_code=asset_code,
    )
    return render(request, "dashboard/partials/alpha_exit_detail_panel.html", context)
