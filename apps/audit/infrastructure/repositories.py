"""Compatibility exports for Audit ORM repositories.

Repository implementations live in focused owner mixins grouped by
persistence responsibility (attribution reports, indicator performance,
validation summaries, and operation logs). Keep this module as the stable
import and patch surface for callers while preventing the former monolith
from regrowing.
"""

from apps.audit.infrastructure.attribution_repositories import (
    AttributionRepositoryMixin,
)
from apps.audit.infrastructure.indicator_repositories import (
    IndicatorRepositoryMixin,
)
from apps.audit.infrastructure.operation_log_repositories import (
    OperationLogRepositoryMixin,
)
from apps.audit.infrastructure.validation_repositories import (
    ValidationRepositoryMixin,
)


class DjangoAuditRepository(
    AttributionRepositoryMixin,
    IndicatorRepositoryMixin,
    ValidationRepositoryMixin,
    OperationLogRepositoryMixin,
):
    """Audit 数据仓储"""


__all__ = ["DjangoAuditRepository"]
