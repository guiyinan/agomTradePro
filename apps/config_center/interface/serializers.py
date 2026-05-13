"""DRF serializers for config center."""

from __future__ import annotations

from rest_framework import serializers


class QlibRuntimeConfigSerializer(serializers.Serializer):
    configured = serializers.BooleanField(read_only=True)
    enabled = serializers.BooleanField(required=False)
    provider_uri = serializers.CharField(required=False, allow_blank=True)
    region = serializers.CharField(required=False, max_length=10)
    model_root = serializers.CharField(required=False, allow_blank=True)
    default_universe = serializers.CharField(required=False, max_length=50)
    default_feature_set_id = serializers.CharField(required=False, max_length=50)
    default_label_id = serializers.CharField(required=False, max_length=50)
    train_queue_name = serializers.CharField(required=False, max_length=64)
    infer_queue_name = serializers.CharField(required=False, max_length=64)
    allow_auto_activate = serializers.BooleanField(required=False)
    alpha_fixed_provider = serializers.CharField(required=False, allow_blank=True, max_length=20)
    alpha_pool_mode = serializers.CharField(required=False, max_length=32)
    active_model = serializers.DictField(read_only=True)
    training_task_running = serializers.BooleanField(read_only=True)
    latest_run_status = serializers.CharField(read_only=True, allow_null=True)
    validation_errors = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )


class QlibTrainingProfileSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    profile_key = serializers.CharField(max_length=64)
    name = serializers.CharField(max_length=120)
    model_name = serializers.CharField(max_length=100)
    model_type = serializers.CharField(max_length=50)
    universe = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    start_date = serializers.DateField(required=False, allow_null=True, default=None)
    end_date = serializers.DateField(required=False, allow_null=True, default=None)
    feature_set_id = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    label_id = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    learning_rate = serializers.FloatField(required=False, allow_null=True, default=None)
    epochs = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=1)
    model_params = serializers.DictField(required=False, default=dict)
    extra_train_config = serializers.DictField(required=False, default=dict)
    activate_after_train = serializers.BooleanField(required=False, default=False)
    is_active = serializers.BooleanField(required=False, default=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class QlibTrainingRunTriggerSerializer(serializers.Serializer):
    profile_key = serializers.CharField(required=False, allow_blank=True, default="")
    model_name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    model_type = serializers.CharField(required=False, allow_blank=True, max_length=50)
    universe = serializers.CharField(required=False, allow_blank=True, max_length=50)
    start_date = serializers.DateField(required=False, allow_null=True, default=None)
    end_date = serializers.DateField(required=False, allow_null=True, default=None)
    feature_set_id = serializers.CharField(required=False, allow_blank=True, max_length=50)
    label_id = serializers.CharField(required=False, allow_blank=True, max_length=50)
    learning_rate = serializers.FloatField(required=False, allow_null=True, default=None)
    epochs = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=1)
    model_params = serializers.DictField(required=False, default=dict)
    extra_train_config = serializers.DictField(required=False, default=dict)
    activate = serializers.BooleanField(required=False)

