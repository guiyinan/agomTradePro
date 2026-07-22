"""HTTP validation and presentation for PIT manifests."""

from rest_framework import serializers

from apps.data_center.domain.pit import PITDatasetManifest


class BuildPITManifestSerializer(serializers.Serializer[dict[str, object]]):
    """Validate manifest build requests."""

    as_of_time = serializers.DateTimeField()
    knowledge_scope = serializers.ChoiceField(choices=["public", "system"])
    calendar_version = serializers.CharField(max_length=64)
    query_spec = serializers.DictField(child=serializers.DictField(), allow_empty=False)
    required_keys = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()), required=False, default=dict
    )


def serialize_pit_manifest(manifest: PITDatasetManifest) -> dict[str, object]:
    """Convert a PIT manifest value object into JSON-safe primitives."""

    return {
        "manifest_id": manifest.manifest_id,
        "as_of_time": manifest.as_of_time.isoformat(),
        "knowledge_scope": manifest.knowledge_scope.value,
        "calendar_version": manifest.calendar_version,
        "query_spec": manifest.query_spec,
        "selected_versions": list(manifest.selected_versions),
        "coverage": manifest.coverage,
        "missing": list(manifest.missing),
        "estimated": list(manifest.estimated),
        "unknown": list(manifest.unknown),
        "manifest_hash": manifest.manifest_hash,
        "is_verified": manifest.is_verified,
    }
