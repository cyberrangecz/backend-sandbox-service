"""
Serializers for Quota and QuotaSet objects
"""

from rest_framework import serializers


class QuotaSerializer(serializers.Serializer):
    limit = serializers.IntegerField()
    in_use = serializers.IntegerField()


class QuotaSetSerializer(serializers.Serializer):
    vcpu = QuotaSerializer()
    ram = QuotaSerializer()
    instances = QuotaSerializer()
    network = QuotaSerializer()
    subnet = QuotaSerializer()
    port = QuotaSerializer()
