"""
Serializer and validator definitions for database models.

Serializers are used to deserialize (parse) requests
and serialize database queries to responses.
Validators validate single fields or entire objects.

Swagger can utilise type hints to determine type, so use them in your own methods.
"""
from rest_framework import serializers

from ..sandbox_instances.serializers import AllocationStageSerializer,\
    CleanupStageSerializer

from . import models


class AnsibleAllocationStageSerializer(AllocationStageSerializer):
    class Meta:
        model = models.AnsibleAllocationStage
        fields = AllocationStageSerializer.Meta.fields + ('repo_url', 'rev')
        read_only_fields = fields


class AnsibleCleanupStageSerializer(CleanupStageSerializer):
    pass


class AnsibleOutputSerializer(serializers.BaseSerializer):
    """Custom serializer to return data as a string"""
    def to_representation(self, instance) -> str:
        return instance.content
