"""
Serializer and validator definitions for database models.

Serializers are used to deserialize (parse) requests
and serialize database queries to responses.
Validators validate single fields or entire objects.

Swagger can utilise type hints to determine type, so use them in your own methods.
"""
from rest_framework import serializers

from ..common.config import config
from . import models


class PoolSerializer(serializers.ModelSerializer):
    size = serializers.SerializerMethodField()

    class Meta:
        model = models.Pool
        fields = ('id', 'definition', 'size', 'max_size')
        read_only_fields = ('id', 'size')

    @staticmethod
    def validate_max_size(value):
        """Validate that max_size is in [1, MAX_SANDBOXES_PER_POOL]"""
        if value < 1 or value > config.MAX_SANDBOXES_PER_POOL:
            raise serializers.ValidationError("Pool max_size value must be in interval [1, %s]."
                                              "Your value: %s."
                                              % (config.MAX_SANDBOXES_PER_POOL, value))
        return value

    # FIXME
    @staticmethod
    def get_size(obj) -> int:
        return obj.sandboxcreaterequests.count()


class SandboxAllocationUnit(serializers.ModelSerializer):
    class Meta:
        model = models.SandboxAllocationUnit
        fields = ('id', 'pool',)
        read_only_fields = ('id', 'pool')
