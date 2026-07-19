"""
系统文档 ORM 模型

存储面向用户的 Markdown 文档内容。
"""

from django.db import models  # type: ignore[import-untyped]

__all__ = [
    "DocumentationModel",
]


class DocumentationModel(models.Model):  # type: ignore[misc]
    """
    文档表

    存储系统文档，支持 Markdown 格式。
    """

    CATEGORY_CHOICES = [
        ("user_guide", "用户指南"),
        ("concept", "概念说明"),
        ("api", "API 文档"),
        ("development", "开发文档"),
        ("other", "其他"),
    ]

    title = models.CharField(max_length=200, verbose_name="标题")
    slug = models.SlugField(max_length=100, unique=True, db_index=True, verbose_name="URL标识")
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default="user_guide", verbose_name="分类"
    )
    content = models.TextField(verbose_name="内容（Markdown）")
    summary = models.TextField(blank=True, verbose_name="摘要")
    order = models.IntegerField(default=0, verbose_name="排序（数字越小越靠前）")
    is_published = models.BooleanField(default=True, verbose_name="是否发布")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "documentation"
        ordering = ["order", "-created_at"]
        verbose_name = "文档"
        verbose_name_plural = "文档"
        indexes = [
            models.Index(fields=["slug", "is_published"]),
            models.Index(fields=["category", "is_published"]),
        ]

    def __str__(self) -> str:
        return str(self.title)
