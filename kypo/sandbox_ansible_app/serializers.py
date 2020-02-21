"""
Serializer and validator definitions for database models.

Serializers are used to deserialize (parse) requests
and serialize database queries to responses.
Validators validate single fields or entire objects.

Swagger can utilise type hints to determine type, so use them in your own methods.
"""
from rest_framework import serializers

from kypo.sandbox_instance_app.serializers import AllocationStageSerializer, CleanupStageSerializer

from kypo.sandbox_ansible_app import models


class AnsibleAllocationStageSerializer(AllocationStageSerializer):
    class Meta:
        model = models.AnsibleAllocationStage
        fields = AllocationStageSerializer.Meta.fields + ('repo_url', 'rev')
        read_only_fields = fields


class AnsibleCleanupStageSerializer(CleanupStageSerializer):
    class Meta:
        model = models.AnsibleCleanupStage
        fields = CleanupStageSerializer.Meta.fields + ('allocation_stage',)
        read_only_fields = fields


class AnsibleOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.AnsibleOutput
        fields = ('content',)
        read_only_fields = fields
