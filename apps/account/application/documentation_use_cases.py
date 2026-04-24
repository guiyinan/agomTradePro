"""Application use cases for account-owned documentation management."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class DocumentationDTO:
    """Documentation record exposed to interface code without leaking ORM models."""

    id: int
    title: str
    slug: str
    category: str
    category_display: str
    content: str
    summary: str
    order: int
    is_published: bool
    created_at: datetime
    updated_at: datetime

    def get_category_display(self) -> str:
        """Return display label used by existing templates."""

        return self.category_display


@dataclass(frozen=True)
class DocumentationFormData:
    """Validated documentation input from interface forms."""

    title: str
    slug: str
    category: str
    content: str
    summary: str
    order: int
    is_published: bool


@dataclass(frozen=True)
class DocumentationStats:
    """Aggregate counts for the documentation admin page."""

    total: int
    published: int
    draft: int
    by_category: dict[str, int]


@dataclass(frozen=True)
class DocumentationImportResult:
    """Result returned after a bulk import."""

    created: int
    updated: int


class DocumentationNotFound(LookupError):
    """Raised when a documentation record cannot be found."""


class DocumentationRepository(Protocol):
    """Persistence contract for documentation use cases."""

    def list_docs(
        self,
        category: str = "",
        status: str = "",
        search_query: str = "",
    ) -> list[DocumentationDTO]:
        """List documentation records for the admin page."""

    def list_all_docs(self) -> list[DocumentationDTO]:
        """List all documentation records for export."""

    def list_published_docs(self) -> list[DocumentationDTO]:
        """List all published documentation records."""

    def get_doc(self, doc_id: int) -> DocumentationDTO:
        """Return one documentation record by id."""

    def get_published_doc_by_slug(self, slug: str) -> DocumentationDTO:
        """Return one published documentation record by slug."""

    def save_doc(self, data: DocumentationFormData, doc_id: int | None = None) -> DocumentationDTO:
        """Create or update one documentation record."""

    def delete_doc(self, doc_id: int) -> str:
        """Delete one documentation record and return its title."""

    def upsert_doc(self, data: DocumentationFormData) -> bool:
        """Create or update by slug. Returns True when created."""

    def get_category_choices(self) -> list[tuple[str, str]]:
        """Return available category code/display pairs."""

    def get_stats(self) -> DocumentationStats:
        """Return documentation aggregate counts."""


class DocumentationService:
    """Application service for documentation management."""

    def __init__(self, repository: DocumentationRepository):
        self.repository = repository

    def list_admin_docs(
        self,
        category: str = "",
        status: str = "",
        search_query: str = "",
    ) -> list[DocumentationDTO]:
        """List docs using admin filters."""

        return self.repository.list_docs(category=category, status=status, search_query=search_query)

    def get_doc(self, doc_id: int) -> DocumentationDTO:
        """Return one documentation record."""

        return self.repository.get_doc(doc_id)

    def save_doc(self, data: DocumentationFormData, doc_id: int | None = None) -> DocumentationDTO:
        """Create or update one documentation record."""

        return self.repository.save_doc(data=data, doc_id=doc_id)

    def delete_doc(self, doc_id: int) -> str:
        """Delete one documentation record and return its title."""

        return self.repository.delete_doc(doc_id)

    def list_all_docs(self) -> list[DocumentationDTO]:
        """List all documentation records."""

        return self.repository.list_all_docs()

    def list_published_docs(self) -> list[DocumentationDTO]:
        """List all published documentation records."""

        return self.repository.list_published_docs()

    def get_published_doc_by_slug(self, slug: str) -> DocumentationDTO:
        """Return one published documentation record by slug."""

        return self.repository.get_published_doc_by_slug(slug)

    def get_category_choices(self) -> list[tuple[str, str]]:
        """Return category choices."""

        return self.repository.get_category_choices()

    def get_stats(self) -> DocumentationStats:
        """Return documentation stats."""

        return self.repository.get_stats()

    def import_json_text(self, raw_text: str) -> DocumentationImportResult:
        """Import documentation records from JSON text."""

        payload = json.loads(raw_text)
        created = 0
        updated = 0

        for item in payload:
            slug = item.get("slug")
            if not slug:
                continue

            form_data = DocumentationFormData(
                title=item.get("title", ""),
                slug=slug,
                category=item.get("category", "user_guide"),
                content=item.get("content", ""),
                summary=item.get("summary", ""),
                order=int(item.get("order", 0)),
                is_published=bool(item.get("is_published", True)),
            )
            if self.repository.upsert_doc(form_data):
                created += 1
            else:
                updated += 1

        return DocumentationImportResult(created=created, updated=updated)

    def import_csv_text(self, raw_text: str) -> DocumentationImportResult:
        """Import documentation records from CSV text."""

        reader = csv.DictReader(raw_text.splitlines())
        category_map = {
            "用户指南": "user_guide",
            "概念说明": "concept",
            "API 文档": "api",
            "开发文档": "development",
            "其他": "other",
        }
        created = 0
        updated = 0

        for row in reader:
            slug = row.get("Slug")
            if not slug:
                continue

            category = row.get("分类", "user_guide")
            if category in category_map:
                category = category_map[category]

            form_data = DocumentationFormData(
                title=row.get("标题", ""),
                slug=slug,
                category=category,
                content=row.get("内容", "").replace("\\n", "\n"),
                summary=row.get("摘要", ""),
                order=int(row.get("排序", 0)),
                is_published=row.get("是否发布", "True") == "True",
            )
            if self.repository.upsert_doc(form_data):
                created += 1
            else:
                updated += 1

        return DocumentationImportResult(created=created, updated=updated)


_documentation_repository: DocumentationRepository | None = None


def configure_documentation_repository(repository: DocumentationRepository) -> None:
    """Register the documentation repository from the Django composition root."""

    global _documentation_repository
    _documentation_repository = repository


def get_documentation_service() -> DocumentationService:
    """Return the configured documentation service."""

    if _documentation_repository is None:
        raise RuntimeError("Documentation repository is not configured")
    return DocumentationService(_documentation_repository)
