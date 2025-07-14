"""
Serializer and validator definitions for database models.

Serializers are used to deserialize (parse) requests
and serialize database queries to responses.
Validators validate single fields or entire objects.

Swagger can utilise type hints to determine type, so use them in your own methods.
"""
from rest_framework import serializers

from crczp.sandbox_ansible_app import models


class NetworkingAnsibleAllocationStageSerializer(serializers.ModelSerializer):
    request_id = serializers.PrimaryKeyRelatedField(source='allocation_request', read_only=True)

    class Meta:
        model = models.NetworkingAnsibleAllocationStage
        fields = ('id', 'request_id', 'start', 'end', 'failed', 'error_message',
                  'repo_url', 'rev')
        read_only_fields = fields


class UserAnsibleAllocationStageSerializer(serializers.ModelSerializer):
    request_id = serializers.PrimaryKeyRelatedField(source='allocation_request', read_only=True)

    class Meta:
        model = models.UserAnsibleAllocationStage
        fields = ('id', 'request_id', 'start', 'end', 'failed', 'error_message',
                  'repo_url', 'rev')
        read_only_fields = fields


class NetworkingAnsibleCleanupStageSerializer(serializers.ModelSerializer):
    request_id = serializers.PrimaryKeyRelatedField(source='cleanup_request', read_only=True)

    class Meta:
        model = models.NetworkingAnsibleCleanupStage
        fields = ('id', 'request_id', 'start', 'end', 'failed', 'error_message',
                  )
        read_only_fields = fields


class UserAnsibleCleanupStageSerializer(serializers.ModelSerializer):
    request_id = serializers.PrimaryKeyRelatedField(source='cleanup_request', read_only=True)

    class Meta:
        model = models.UserAnsibleCleanupStage
        fields = ('id', 'request_id', 'start', 'end', 'failed', 'error_message',
                  )
        read_only_fields = fields


class AllocationAnsibleOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.AllocationAnsibleOutput
        fields = ('content',)
        read_only_fields = fields
