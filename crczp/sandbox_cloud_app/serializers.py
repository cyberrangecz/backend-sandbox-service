"""
Serializers for ostack_proxy_elements classes.
"""

from rest_framework import serializers

from crczp.cloud_commons import Image

OPENSTACK_OWNER_SPECIFIED_PREFIX = 'owner_specified.openstack.'


class QuotaSerializer(serializers.Serializer):
    """Serializer for a single OpenStack quota value."""

    limit = serializers.FloatField()
    in_use = serializers.FloatField()


class QuotaSetSerializer(serializers.Serializer):
    """Serializer for a complete set of OpenStack project quotas."""

    vcpu = QuotaSerializer()
    ram = QuotaSerializer()
    instances = QuotaSerializer()
    network = QuotaSerializer()
    subnet = QuotaSerializer()
    port = QuotaSerializer()


class ImageSerializer(serializers.Serializer):
    """Serializer for an OpenStack image."""

    os_distro = serializers.CharField()
    os_type = serializers.CharField()
    disk_format = serializers.CharField()
    container_format = serializers.CharField()
    visibility = serializers.CharField()
    size = serializers.SerializerMethodField()
    status = serializers.CharField()
    min_ram = serializers.IntegerField()
    min_disk = serializers.IntegerField()
    created_at = serializers.CharField()
    updated_at = serializers.CharField()
    tags = serializers.ListField()
    default_user = serializers.CharField()
    name = serializers.CharField()
    owner_specified = serializers.SerializerMethodField()

    @staticmethod
    def get_size(obj: Image) -> int | None:
        """Return image size in GiB, or None if not set."""
        if obj.size is None:
            return None
        return obj.size / 1024**3

    @staticmethod
    def get_owner_specified(obj: Image) -> dict:
        """Return owner_specified metadata with the OpenStack prefix stripped."""
        return {
            (
                key[len(OPENSTACK_OWNER_SPECIFIED_PREFIX) :]
                if key.startswith(OPENSTACK_OWNER_SPECIFIED_PREFIX)
                else key
            ): value
            for (key, value) in obj.owner_specified.items()
        }


class ProjectLimitsSerializer(serializers.Serializer):
    """Serializer for OpenStack project absolute limits."""

    vcpu = serializers.IntegerField()
    ram = serializers.FloatField()
    instances = serializers.IntegerField()
    network = serializers.IntegerField()
    subnet = serializers.IntegerField()
    port = serializers.IntegerField()
