"""Celery Beat schedule for AgomTradePro."""

from celery.schedules import crontab

# Celery Beat 定时任务配置
CELERY_BEAT_SCHEDULE = {
    "terminal-agent-reaper": {
        "task": "apps.agent_runtime.application.tasks.reap_stale_terminal_agent_runs",
        "schedule": crontab(minute="*"),
        "options": {"expire_seconds": 50, "queue": "celery"},
    },
    "broker-execution-maintenance": {
        "task": "broker_execution.run_maintenance",
        "schedule": crontab(minute="*"),
        "options": {"expire_seconds": 50},
    },
    "broker-execution-reconciliation-intraday": {
        "task": "broker_execution.generate_reconciliation_runs",
        "schedule": crontab(minute="*/5", hour="9-11,13-14", day_of_week="mon-fri"),
        "options": {"expire_seconds": 240},
    },
    "broker-execution-reconciliation-eod": {
        "task": "broker_execution.generate_reconciliation_runs",
        "schedule": crontab(hour=16, minute=20, day_of_week="mon-fri"),
        "options": {"expire_seconds": 1800},
    },
    "daily-sync-and-calculate": {
        "task": "apps.regime.application.orchestration.sync_macro_then_refresh_regime",
        "schedule": crontab(hour=8, minute=5),  # 每天 8:05 执行
        "kwargs": {
            "source": "akshare",
            "indicator": None,
            "days_back": 60,
            "use_pit": True,
        },
    },
    "check-data-freshness": {
        "task": "apps.macro.application.tasks.check_data_freshness",
        "schedule": crontab(hour="*/6", minute=0),  # 每 6 小时执行一次
    },
    "auto-sync-due-macro-indicators": {
        "task": "apps.macro.application.tasks.auto_sync_due_macro_indicators",
        "schedule": crontab(hour=8, minute=20),  # 每天 8:20 执行一次
    },
    "send-database-backup-email": {
        "task": "apps.account.application.tasks.send_database_backup_email_task",
        "schedule": crontab(hour=8, minute=10),
    },
    "check-regime-health": {
        "task": "apps.regime.application.tasks.check_regime_health",
        "schedule": crontab(hour="*/6"),  # 每 6 小时执行一次
    },
    # ========== Signal 证伪自动检查 ==========
    "daily-signal-invalidation": {
        "task": "signal.check_all_invalidations",
        "schedule": crontab(hour=2, minute=0),  # 每天凌晨 2:00
        "options": {
            "expire_seconds": 3600,  # 1 小时超时
        },
    },
    # 可选：每日信号摘要
    "daily-signal-summary": {
        "task": "signal.daily_summary",
        "schedule": crontab(hour=9, minute=0),  # 每天上午 9:00
    },
    # ============================================
    # ========== Phase 1: 高频数据同步（日度Regime信号）==========
    "high-frequency-sync-bonds": {
        "task": "apps.macro.application.tasks.sync_high_frequency_bonds",
        "schedule": crontab(
            hour=16, minute=30, day_of_week="mon-fri"
        ),  # 每个交易日 16:30（收盘后）
        "kwargs": {
            "source": "akshare",
            "years_back": 1,
        },
        "options": {
            "expire_seconds": 3600,  # 1 小时超时
        },
    },
    "high-frequency-sync-commodities": {
        "task": "apps.macro.application.tasks.sync_high_frequency_commodities",
        "schedule": crontab(hour=16, minute=35, day_of_week="mon-fri"),  # 每个交易日 16:35
        "kwargs": {
            "source": "akshare",
            "years_back": 1,
        },
        "options": {
            "expire_seconds": 3600,
        },
    },
    "high-frequency-generate-signal": {
        "task": "apps.regime.application.orchestration.generate_daily_regime_signal",
        "schedule": crontab(hour=17, minute=0, day_of_week="mon-fri"),  # 每个交易日 17:00
        "options": {
            "expire_seconds": 1800,  # 30 分钟超时
        },
    },
    "high-frequency-recalculate-regime": {
        "task": "apps.regime.application.orchestration.recalculate_regime_with_daily_signal",
        "schedule": crontab(hour=17, minute=5, day_of_week="mon-fri"),  # 每个交易日 17:05
        "kwargs": {
            "use_pit": True,
        },
        "options": {
            "expire_seconds": 1800,
        },
    },
    "market-thermometer-refresh-post-close": {
        "task": "apps.data_center.application.tasks.refresh_market_thermometer_task",
        "schedule": crontab(hour="17-18", minute=20, day_of_week="mon-fri"),
        "options": {
            "expire_seconds": 1800,
        },
    },
    # ============================================================
    # ========== 模拟盘自动交易 ==========
    "simulated-daily-auto-trading": {
        "task": "apps.simulated_trading.application.tasks.daily_auto_trading_task",
        "schedule": crontab(hour=15, minute=30, day_of_week="mon-fri"),  # 每个交易日 15:30
        "options": {
            "expire_seconds": 7200,  # 2 小时超时
        },
    },
    "simulated-update-prices": {
        "task": "apps.simulated_trading.application.tasks.update_position_prices_task",
        "schedule": crontab(hour=16, minute=0, day_of_week="mon-fri"),  # 每个交易日 16:00
    },
    "simulated-weekly-performance": {
        "task": "apps.simulated_trading.application.tasks.calculate_all_performance_task",
        "schedule": crontab(hour=2, minute=0, day_of_week="sun"),  # 每周日凌晨 2:00
    },
    "simulated-cleanup-accounts": {
        "task": "apps.simulated_trading.application.tasks.cleanup_inactive_accounts_task",
        "schedule": crontab(hour=3, minute=0, day_of_week="sun"),  # 每周日凌晨 3:00
    },
    "simulated-daily-summary": {
        "task": "apps.simulated_trading.application.tasks.send_performance_summary_task",
        "schedule": crontab(hour=17, minute=0, day_of_week="mon-fri"),  # 每个交易日 17:00
    },
    "account-check-stop-loss-take-profit-intraday": {
        "task": "apps.account.application.tasks.check_stop_loss_and_take_profit_task",
        "schedule": crontab(hour="10-15", minute="*/30", day_of_week="mon-fri"),
        "options": {
            "expire_seconds": 1800,
        },
    },
    "simulated-daily-inspection": {
        "task": "simulated.daily_portfolio_inspection",
        "schedule": crontab(hour=17, minute=10, day_of_week="mon-fri"),  # 每个交易日 17:10
        "kwargs": {
            "account_id": 679,
            "strategy_id": 4,
        },
        "options": {
            "expire_seconds": 1800,
        },
    },
    # ============================================
    # ========== 持仓证伪检查 ==========
    "simulated-check-position-invalidation-morning": {
        "task": "apps.simulated_trading.application.tasks.check_position_invalidation_task",
        "schedule": crontab(hour=10, minute=0, day_of_week="mon-fri"),  # 每个交易日 10:00
        "options": {
            "expire_seconds": 1800,  # 30 分钟超时
        },
    },
    "simulated-check-position-invalidation-afternoon": {
        "task": "apps.simulated_trading.application.tasks.check_position_invalidation_task",
        "schedule": crontab(hour=14, minute=0, day_of_week="mon-fri"),  # 每个交易日 14:00
        "options": {
            "expire_seconds": 1800,  # 30 分钟超时
        },
    },
    "simulated-notify-invalidated-positions": {
        "task": "apps.simulated_trading.application.tasks.notify_invalidated_positions_task",
        "schedule": crontab(hour=10, minute=5, day_of_week="mon-fri"),  # 每个交易日 10:05
        "options": {
            "expire_seconds": 600,  # 10 分钟超时
        },
    },
    # ============================================
    # ========== 实时价格监控 ==========
    "realtime-update-prices-after-close": {
        "task": "apps.simulated_trading.application.tasks.update_all_prices_after_close",
        "schedule": crontab(hour=16, minute=30, day_of_week="mon-fri"),  # 每个交易日 16:30
        "options": {
            "expire_seconds": 3600,  # 1 小时超时
        },
    },
    # ============================================
    # ========== Alpha Qlib 推理任务 ==========
    "qlib-daily-scoped-inference": {
        "task": "apps.alpha.application.tasks.qlib_daily_scoped_inference",
        "schedule": crontab(hour=17, minute=40, day_of_week="mon-fri"),  # 每个交易日 17:40
        "kwargs": {
            "top_n": 30,
            "portfolio_limit": 0,
            "pool_mode": "price_covered",
            "refresh_data": True,
            "lookback_days": 120,
            "only_missing": True,
        },
        "options": {
            "expire_seconds": 7200,  # 2 小时超时
        },
    },
    "qlib-post-close-scoped-inference-recovery": {
        "task": "apps.alpha.application.tasks.qlib_daily_scoped_inference",
        "schedule": crontab(hour="18", minute="*/10", day_of_week="mon-fri"),
        "kwargs": {
            "top_n": 30,
            "portfolio_limit": 0,
            "pool_mode": "price_covered",
            "refresh_data": True,
            "lookback_days": 120,
            "only_missing": True,
        },
        "options": {
            "expire_seconds": 1800,  # 30 分钟超时
        },
    },
    "personal-readiness-daily-evidence": {
        "task": "apps.operational_readiness.application.tasks.run_personal_readiness_daily_task",
        "schedule": crontab(hour=16, minute=10, day_of_week="mon-fri"),
        "kwargs": {
            "calendar_source": "auto",
            "run_workspace_refresh": True,
            "include_weekly_advisor": True,
            "repair_accounts": False,
            "allow_unclosed_target_date": False,
        },
        "options": {
            "expire_seconds": 7200,
        },
    },
    "qlib-weekly-cache-refresh": {
        "task": "apps.alpha.application.tasks.qlib_refresh_cache",
        "schedule": crontab(hour=2, minute=0, day_of_week="sun"),  # 每周日凌晨 2:00
        "kwargs": {
            "universe_id": "csi300",
            "days_back": 7,
        },
        "options": {
            "expire_seconds": 14400,  # 4 小时超时
        },
    },
    # ============================================
    # ========== Phase 4: 监控和告警任务 ==========
    "alpha-evaluate-alerts": {
        "task": "alpha.monitor.evaluate_alerts",
        "schedule": crontab(minute="*/1"),  # 每分钟执行一次
        "options": {
            "expire_seconds": 60,  # 1 分钟超时
        },
    },
    "alpha-update-provider-metrics": {
        "task": "alpha.monitor.update_provider_metrics",
        "schedule": crontab(minute="*/5"),  # 每 5 分钟执行一次
        "options": {
            "expire_seconds": 300,  # 5 分钟超时
        },
    },
    "alpha-check-queue-lag": {
        "task": "alpha.monitor.check_queue_lag",
        "schedule": crontab(minute="*/1"),  # 每分钟执行一次
        "options": {
            "expire_seconds": 60,
        },
    },
    "alpha-calculate-ic-drift": {
        "task": "alpha.monitor.calculate_ic_drift",
        "schedule": crontab(hour=2, minute=0, day_of_week="sun"),  # 每周日凌晨 2:00
        "options": {
            "expire_seconds": 1800,  # 30 分钟超时
        },
    },
    "alpha-daily-report": {
        "task": "alpha.monitor.generate_daily_report",
        "schedule": crontab(hour=8, minute=0),  # 每天 8:00
        "options": {
            "expire_seconds": 600,  # 10 分钟超时
        },
    },
    "alpha-cleanup-metrics": {
        "task": "alpha.monitor.cleanup_old_metrics",
        "schedule": crontab(hour=3, minute=0, day_of_week="sun"),  # 每周日凌晨 3:00
        "kwargs": {
            "days": 30,  # 保留 30 天
        },
        "options": {
            "expire_seconds": 3600,  # 1 小时超时
        },
    },
    # ============================================
    # ========== 任务监控清理 ==========
    "task-monitor-cleanup": {
        "task": "apps.task_monitor.application.tasks.cleanup_old_task_records",
        "schedule": crontab(hour=4, minute=0),  # 每天凌晨 4:00
        "kwargs": {
            "days_to_keep": 30,  # 保留 30 天
        },
        "options": {
            "expire_seconds": 3600,  # 1 小时超时
        },
    },
    # ========== Data Center retention preview (dry-run only) ==========
    "data-center-retention-preview-asset-master": {
        "task": "apps.data_center.application.tasks.plan_retention_task",
        "schedule": crontab(hour=4, minute=20),
        "kwargs": {"dataset_key": "asset.master", "limit": 500},
        "options": {"expire_seconds": 900},
    },
    "data-center-retention-preview-price-bars": {
        "task": "apps.data_center.application.tasks.plan_retention_task",
        "schedule": crontab(hour=4, minute=21),
        "kwargs": {"dataset_key": "equity.price.bar", "limit": 500},
        "options": {"expire_seconds": 900},
    },
    "data-center-retention-preview-quote-snapshot": {
        "task": "apps.data_center.application.tasks.plan_retention_task",
        "schedule": crontab(hour=4, minute=22),
        "kwargs": {"dataset_key": "equity.quote.snapshot", "limit": 500},
        "options": {"expire_seconds": 900},
    },
    "data-center-retention-preview-fund-nav": {
        "task": "apps.data_center.application.tasks.plan_retention_task",
        "schedule": crontab(hour=4, minute=23),
        "kwargs": {"dataset_key": "fund.nav", "limit": 500},
        "options": {"expire_seconds": 900},
    },
    "data-center-retention-preview-macro-fact": {
        "task": "apps.data_center.application.tasks.plan_retention_task",
        "schedule": crontab(hour=4, minute=24),
        "kwargs": {"dataset_key": "macro.fact", "limit": 500},
        "options": {"expire_seconds": 900},
    },
    "data-center-retention-preview-financial-fact": {
        "task": "apps.data_center.application.tasks.plan_retention_task",
        "schedule": crontab(hour=4, minute=25),
        "kwargs": {"dataset_key": "equity.financial.fact", "limit": 500},
        "options": {"expire_seconds": 900},
    },
    "data-center-retention-preview-valuation-fact": {
        "task": "apps.data_center.application.tasks.plan_retention_task",
        "schedule": crontab(hour=4, minute=26),
        "kwargs": {"dataset_key": "equity.valuation.fact", "limit": 500},
        "options": {"expire_seconds": 900},
    },
    "data-center-retention-preview-sector-membership": {
        "task": "apps.data_center.application.tasks.plan_retention_task",
        "schedule": crontab(hour=4, minute=27),
        "kwargs": {"dataset_key": "sector.membership", "limit": 500},
        "options": {"expire_seconds": 900},
    },
    "data-center-retention-preview-market-news": {
        "task": "apps.data_center.application.tasks.plan_retention_task",
        "schedule": crontab(hour=4, minute=28),
        "kwargs": {"dataset_key": "market.news", "limit": 500},
        "options": {"expire_seconds": 900},
    },
    "data-center-retention-preview-capital-flow": {
        "task": "apps.data_center.application.tasks.plan_retention_task",
        "schedule": crontab(hour=4, minute=29),
        "kwargs": {"dataset_key": "market.capital_flow", "limit": 500},
        "options": {"expire_seconds": 900},
    },
    "data-center-storage-budget-check": {
        "task": "apps.data_center.application.tasks.verify_storage_budget_task",
        "schedule": crontab(minute="*/15"),
        "options": {"expire_seconds": 300},
    },
    "config-center-storage-capacity-profile-hourly": {
        "task": "apps.config_center.application.tasks.collect_storage_capacity_profile_task",
        "schedule": crontab(minute=10),
        "options": {"expire_seconds": 300},
    },
    # ============================================
    # ========== P1-2: 数据库备份 ==========
    "database-daily-backup": {
        "task": "apps.task_monitor.application.tasks.backup_database_task",
        "schedule": crontab(hour=3, minute=0),  # 每天凌晨 3:00
        "kwargs": {
            "compress": True,
        },
        "options": {
            "expire_seconds": 3600,  # 1 小时超时
        },
    },
    # ============================================
    # ========== Policy Workbench 任务 ==========
    "policy-fetch-rss-sources": {
        "task": "apps.policy.application.tasks.fetch_rss_sources",
        "schedule": crontab(hour="*/6", minute=0),  # 每 6 小时
        "options": {
            "expire_seconds": 3600,  # 1 小时超时
        },
    },
    "policy-review-auto-assign": {
        "task": "apps.policy.application.tasks.auto_assign_pending_audits_task",
        "schedule": crontab(minute="*/15"),  # 每 15 分钟
        "options": {
            "expire_seconds": 600,  # 10 分钟超时
        },
    },
    "policy-sla-monitor": {
        "task": "apps.policy.application.tasks.monitor_sla_exceeded_task",
        "schedule": crontab(minute="*/10"),  # 每 10 分钟
        "options": {
            "expire_seconds": 300,  # 5 分钟超时
        },
    },
    "policy-gate-refresh": {
        "task": "apps.policy.application.tasks.refresh_gate_constraints_task",
        "schedule": crontab(minute="*/5"),  # 每 5 分钟
        "options": {
            "expire_seconds": 180,  # 3 分钟超时
        },
    },
    "sentiment-refresh-current-index": {
        "task": "sentiment.refresh_current_sentiment_index",
        "schedule": crontab(
            minute=15,
            hour="9-11,13-15,18,23",
            day_of_week="mon-fri",
        ),
        "options": {
            "expire_seconds": 3300,
        },
    },
    "decision-readiness-fail-closed-audit": {
        "task": (
            "apps.config_center.application.decision_readiness_guard_tasks."
            "audit_decision_readiness_task"
        ),
        "schedule": crontab(hour=18, minute=30),
        "options": {
            "expire_seconds": 3600,
        },
    },
    # ============================================
    # ========== Pulse 脉搏层 ==========
    "pulse-weekly-calculate": {
        "task": "pulse.calculate_weekly",
        "schedule": crontab(hour=17, minute=15, day_of_week="fri"),  # 每周五 17:15
        "options": {
            "expire_seconds": 1800,  # 30 分钟超时
        },
    },
    # ============================================
}
