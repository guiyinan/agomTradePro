"""Runtime action patches for account, portfolio, and execution TUI actions."""

from __future__ import annotations

from typing import Any

RUNTIME_ACTION_PATCHES_EXECUTION: dict[str, dict[str, Any]] = {'auto.api.get.api.account.accounts': {'task_group': '01 账户清单',
                                       'sequence': 100,
                                       'task_tier': 'primary',
                                       'view_model': {'rows_path': 'accounts',
                                                      'total_path': 'count'}},
 'auto.api.get.api.account.positions': {'screen_key': 'execution.accounts',
                                        'task_group': '02 当前持仓',
                                        'sequence': 110,
                                        'task_tier': 'primary'},
 'param.api.get.api.account.accounts.int.account_id.positions': {'screen_key': 'execution.accounts',
                                                                 'task_group': '03 单账户持仓',
                                                                 'sequence': 120,
                                                                 'task_tier': 'primary'},
 'param.api.get.api.account.accounts.int.account_id.performance': {'screen_key': 'execution.accounts'},
 'param.api.get.api.account.accounts.int.account_id.performance-report': {'screen_key': 'execution.accounts'},
 'param.api.get.api.account.accounts.int.account_id.valuation-snapshot': {'screen_key': 'execution.accounts'},
 'param.api.get.api.account.accounts.int.account_id.valuation-timeline': {'screen_key': 'execution.accounts'},
 'param.api.get.api.account.accounts.int.account_id.benchmarks': {'screen_key': 'execution.accounts'},
 'param.api.get.api.account.accounts.int.account_id.equity-curve': {'screen_key': 'execution.accounts'},
 'param.api.get.api.account.accounts.int.account_id.inspections': {'screen_key': 'execution.accounts'},
 'auto.api.get.api.strategy.assignments.by_portfolio': {'screen_key': 'execution.portfolio-performance'},
 'auto.api.get.api.strategy.execution-logs.by_portfolio': {'screen_key': 'execution.portfolio-performance'}}
