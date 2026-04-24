"""Django repository for account documentation management."""

from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404

from apps.account.application.documentation_use_cases import (
    DocumentationDTO,
    DocumentationFormData,
    DocumentationNotFound,
    DocumentationStats,
)

from .models import DocumentationModel


class DjangoDocumentationRepository:
    """ORM-backed documentation repository."""

    def list_docs(
        self,
        category: str = "",
        status: str = "",
        search_query: str = "",
    ) -> list[DocumentationDTO]:
        """List documentation records for the admin page."""

        queryset = DocumentationModel._default_manager.all()

        if category:
            queryset = queryset.filter(category=category)

        if status == "published":
            queryset = queryset.filter(is_published=True)
        elif status == "draft":
            queryset = queryset.filter(is_published=False)

        if search_query:
            queryset = queryset.filter(Q(title__icontains=search_query) | Q(content__icontains=search_query))

        queryset = queryset.order_by("category", "order", "-updated_at")
        return [self._to_dto(model) for model in queryset]

    def list_all_docs(self) -> list[DocumentationDTO]:
        """List all documentation records for export."""

        queryset = DocumentationModel._default_manager.all()
        return [self._to_dto(model) for model in queryset]

    def list_published_docs(self) -> list[DocumentationDTO]:
        """List all published documentation records."""

        queryset = DocumentationModel._default_manager.filter(is_published=True).order_by("category", "order")
        return [self._to_dto(model) for model in queryset]

    def get_doc(self, doc_id: int) -> DocumentationDTO:
        """Return one documentation record by id."""

        return self._to_dto(get_object_or_404(DocumentationModel, id=doc_id))

    def get_published_doc_by_slug(self, slug: str) -> DocumentationDTO:
        """Return one published documentation record by slug."""

        try:
            model = DocumentationModel._default_manager.get(slug=slug, is_published=True)
        except DocumentationModel.DoesNotExist as exc:
            raise DocumentationNotFound(slug) from exc
        return self._to_dto(model)

    def save_doc(self, data: DocumentationFormData, doc_id: int | None = None) -> DocumentationDTO:
        """Create or update one documentation record."""

        if doc_id is None:
            model = DocumentationModel._default_manager.create(
                title=data.title,
                slug=data.slug,
                category=data.category,
                content=data.content,
                summary=data.summary,
                order=data.order,
                is_published=data.is_published,
            )
            return self._to_dto(model)

        model = get_object_or_404(DocumentationModel, id=doc_id)
        model.title = data.title
        model.slug = data.slug
        model.category = data.category
        model.content = data.content
        model.summary = data.summary
        model.order = data.order
        model.is_published = data.is_published
        model.save()
        return self._to_dto(model)

    def delete_doc(self, doc_id: int) -> str:
        """Delete one documentation record and return its title."""

        model = get_object_or_404(DocumentationModel, id=doc_id)
        title = model.title
        model.delete()
        return title

    def upsert_doc(self, data: DocumentationFormData) -> bool:
        """Create or update by slug. Returns True when created."""

        _, created = DocumentationModel._default_manager.update_or_create(
            slug=data.slug,
            defaults={
                "title": data.title,
                "category": data.category,
                "content": data.content,
                "summary": data.summary,
                "order": data.order,
                "is_published": data.is_published,
            },
        )
        return created

    def get_category_choices(self) -> list[tuple[str, str]]:
        """Return available category code/display pairs."""

        return list(DocumentationModel.CATEGORY_CHOICES)

    def get_stats(self) -> DocumentationStats:
        """Return documentation aggregate counts."""

        by_category: dict[str, int] = {}
        for cat_code, cat_name in DocumentationModel.CATEGORY_CHOICES:
            by_category[cat_name] = DocumentationModel._default_manager.filter(category=cat_code).count()

        return DocumentationStats(
            total=DocumentationModel._default_manager.count(),
            published=DocumentationModel._default_manager.filter(is_published=True).count(),
            draft=DocumentationModel._default_manager.filter(is_published=False).count(),
            by_category=by_category,
        )

    def _to_dto(self, model: DocumentationModel) -> DocumentationDTO:
        return DocumentationDTO(
            id=model.id,
            title=model.title,
            slug=model.slug,
            category=model.category,
            category_display=model.get_category_display(),
            content=model.content,
            summary=model.summary,
            order=model.order,
            is_published=model.is_published,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
