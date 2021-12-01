"""
Serializers for ostack_proxy_elements classes.
"""

from rest_framework import serializers


class QuotaSerializer(serializers.Serializer):
    limit = serializers.FloatField()
    in_use = serializers.FloatField()


class QuotaSetSerializer(serializers.Serializer):
    vcpu = QuotaSerializer()
    ram = QuotaSerializer()
    instances = QuotaSerializer()
    network = QuotaSerializer()
    subnet = QuotaSerializer()
    port = QuotaSerializer()


class ImageSerializer(serializers.Serializer):
    os_distro = serializers.CharField()
    os_type = serializers.CharField()
    disk_format = serializers.CharField()
    container_format = serializers.CharField()
    visibility = serializers.CharField()
    size = serializers.IntegerField()
    status = serializers.CharField()
    min_ram = serializers.IntegerField()
    min_disk = serializers.IntegerField()
    created_at = serializers.CharField()
    updated_at = serializers.CharField()
    tags = serializers.ListField()
    default_user = serializers.CharField()
    name = serializers.CharField()
    owner_specified = serializers.DictField()


class ProjectLimitsSerializer(serializers.Serializer):
    vcpu = serializers.IntegerField()
    ram = serializers.FloatField()
    instances = serializers.IntegerField()
    network = serializers.IntegerField()
    subnet = serializers.IntegerField()
    port = serializers.IntegerField()
