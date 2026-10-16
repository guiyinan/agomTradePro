"""Bounded Agent declarations of wire schemas, without execution authority."""

from __future__ import annotations

import re
from dataclasses import dataclass

EXECUTION_CONSTRAINT_SCHEMA_V2: str = "a-share-execution-constraints.v2"
_SCHEMA_NAME = re.compile(r"[a-z][a-z0-9._-]{0,95}")


@dataclass(frozen=True, slots=True)
class AgentExecutionContracts:
    """Self-reported parser capabilities; these do not prove broker readiness."""

    schemas: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject malformed or ambiguous capability declarations."""

        if type(self.schemas) is not tuple or len(self.schemas) > 8:
            raise ValueError("execution_constraint_schemas must contain at most eight schemas")
        if any(
            type(value) is not str or _SCHEMA_NAME.fullmatch(value) is None
            for value in self.schemas
        ):
            raise ValueError("execution_constraint_schemas contains an invalid schema name")
        if len(set(self.schemas)) != len(self.schemas):
            raise ValueError("execution_constraint_schemas cannot contain duplicates")

    @property
    def supports_submission_v2(self) -> bool:
        """Report explicit v2 support without inferring it from a package version."""

        self.__post_init__()
        return EXECUTION_CONSTRAINT_SCHEMA_V2 in self.schemas
