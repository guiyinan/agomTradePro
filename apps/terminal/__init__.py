"""
Terminal Module - AI CLI Interface

提供终端风格的AI交互界面，支持可配置命令系统。

Architecture (DDD):
- domain: 命令实体、仓储接口
- application: 命令执行用例、服务
- infrastructure: ORM模型、仓储实现
- interface: 视图、API、序列化器
"""

default_app_config = 'apps.terminal.apps.TerminalConfig'
