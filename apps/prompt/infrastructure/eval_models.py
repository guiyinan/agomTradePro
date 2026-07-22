"""Immutable prompt versions and evaluation evidence."""

from django.core.exceptions import ValidationError
from django.db import models


class PromptVersion(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("candidate", "Candidate"),
        ("evaluated", "Evaluated"),
        ("active", "Active"),
        ("retired", "Retired"),
    ]
    version_id = models.CharField(max_length=64, primary_key=True)
    template = models.ForeignKey("prompt.PromptTemplateORM", on_delete=models.PROTECT, related_name="immutable_versions")
    version = models.CharField(max_length=32)
    content = models.TextField()
    system_prompt = models.TextField(blank=True)
    required_variables = models.JSONField(default=list)
    output_schema = models.JSONField(default=dict)
    allowed_tools = models.JSONField(default=list)
    content_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="draft", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "prompt_version"
        constraints = [models.UniqueConstraint(fields=["template", "version"], name="prompt_template_version_uniq")]

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk:
            original = type(self)._default_manager.filter(pk=self.pk).first()
            if original and any(
                getattr(original, field) != getattr(self, field)
                for field in ("content", "system_prompt", "required_variables", "output_schema", "allowed_tools", "content_hash")
            ):
                raise ValidationError("PromptVersion content is immutable; create a new version.")
        return super().save(*args, **kwargs)


class PromptEvalDataset(models.Model):
    dataset_id = models.CharField(max_length=64, primary_key=True)
    name = models.CharField(max_length=128)
    version = models.CharField(max_length=32)
    content_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "prompt_eval_dataset"
        constraints = [models.UniqueConstraint(fields=["name", "version"], name="prompt_eval_dataset_version_uniq")]

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("PromptEvalDataset is immutable; create a new version.")
        return super().save(*args, **kwargs)


class PromptEvalCase(models.Model):
    case_id = models.CharField(max_length=64, primary_key=True)
    dataset = models.ForeignKey(PromptEvalDataset, on_delete=models.PROTECT, related_name="cases")
    input_variables = models.JSONField(default=dict)
    expected_schema = models.JSONField(default=dict)
    allowed_tools = models.JSONField(default=list)
    assertions = models.JSONField(default=list)

    class Meta:
        db_table = "prompt_eval_case"

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("PromptEvalCase is immutable.")
        return super().save(*args, **kwargs)


class PromptEvalRun(models.Model):
    run_id = models.CharField(max_length=64, primary_key=True)
    prompt_version = models.ForeignKey(PromptVersion, on_delete=models.PROTECT, related_name="eval_runs")
    dataset = models.ForeignKey(PromptEvalDataset, on_delete=models.PROTECT)
    evaluation_type = models.CharField(max_length=16)
    provider = models.CharField(max_length=64, blank=True)
    model = models.CharField(max_length=64, blank=True)
    temperature = models.FloatField(default=0.0)
    status = models.CharField(max_length=24, default="running", db_index=True)
    max_cost = models.DecimalField(max_digits=12, decimal_places=6)
    actual_cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    max_tokens = models.PositiveIntegerField()
    actual_tokens = models.PositiveIntegerField(default=0)
    max_cases = models.PositiveIntegerField()
    executed_cases = models.PositiveIntegerField(default=0)
    failure_summary = models.JSONField(default=list)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "prompt_eval_run"

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk:
            original = type(self)._default_manager.filter(pk=self.pk).first()
            if original and original.status != "running":
                raise ValidationError("Completed PromptEvalRun evidence is immutable.")
        return super().save(*args, **kwargs)


class PromptEvalAssertion(models.Model):
    run = models.ForeignKey(PromptEvalRun, on_delete=models.CASCADE, related_name="assertion_results")
    case = models.ForeignKey(PromptEvalCase, on_delete=models.PROTECT)
    assertion_type = models.CharField(max_length=32)
    passed = models.BooleanField()
    critical = models.BooleanField(default=True)
    details = models.JSONField(default=dict)
    latency_ms = models.PositiveIntegerField(default=0)
    tokens = models.PositiveIntegerField(default=0)
    cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)

    class Meta:
        db_table = "prompt_eval_assertion"

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("PromptEvalAssertion is immutable.")
        return super().save(*args, **kwargs)


class PromptPromotionDecision(models.Model):
    decision_id = models.CharField(max_length=64, primary_key=True)
    prompt_version = models.OneToOneField(PromptVersion, on_delete=models.PROTECT, related_name="promotion_decision")
    eval_run = models.ForeignKey(PromptEvalRun, on_delete=models.PROTECT)
    decision = models.CharField(max_length=16)
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "prompt_promotion_decision"

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("PromptPromotionDecision is immutable.")
        return super().save(*args, **kwargs)
