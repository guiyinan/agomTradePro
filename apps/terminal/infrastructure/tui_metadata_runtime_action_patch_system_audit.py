"""Runtime action patches for system and audit TUI actions."""

from __future__ import annotations

from typing import Any

RUNTIME_ACTION_PATCHES_SYSTEM_AUDIT: dict[str, dict[str, Any]] = {'auto.api.get.api.system.list': {'view_type': 'datagrid',
                                  'view_model': {'rows_path': 'items', 'total_path': 'total'}},
 'param.api.get.api.audit.operation-logs.str.log_id': {'fields': [{'key': 'log_id',
                                                                   'label': '日志 ID',
                                                                   'input_type': 'text',
                                                                   'required': True,
                                                                   'default': '',
                                                                   'placeholder': '输入日志 ID',
                                                                   'binding': 'path',
                                                                   'value_type': 'string'}]},
 'param.api.get.api.audit.decision-traces.str.request_id': {'fields': [{'key': 'request_id',
                                                                        'label': '请求ID',
                                                                        'input_type': 'text',
                                                                        'required': True,
                                                                        'default': '',
                                                                        'placeholder': '请输入请求ID',
                                                                        'binding': 'path',
                                                                        'value_type': 'string'}]}}
