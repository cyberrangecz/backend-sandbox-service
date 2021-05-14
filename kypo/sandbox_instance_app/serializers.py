"""
Serializer and validator definitions for database models.

Serializers are used to deserialize (parse) requests
and serialize database queries to responses.
Validators validate single fields or entire objects.

Swagger can utilise type hints to determine type, so use them in your own methods.
"""
from typing import Optional
from rest_framework import serializers

from kypo.sandbox_definition_app.models import Definition
from kypo.sandbox_instance_app import models
from kypo.sandbox_instance_app.lib import pools

MAX_SANDBOXES_PER_POOL = 64


class PoolSerializer(serializers.ModelSerializer):
    size = serializers.SerializerMethodField(
        help_text="Number of allocation units associated with this pool.")
    lock_id = serializers.SerializerMethodField()
    definition_id = serializers.PrimaryKeyRelatedField(
        source='definition', queryset=Definition.objects.all()
    )

    class Meta:
        model = models.Pool
        fields = ('id', 'definition_id', 'size', 'max_size', 'lock_id', 'rev', 'rev_sha')
        read_only_fields = ('id', 'size', 'lock', 'rev', 'rev_sha')

    @staticmethod
    def validate_max_size(value):
        """Validate that max_size is in [1, MAX_SANDBOXES_PER_POOL]"""
        if not 1 <= value <= MAX_SANDBOXES_PER_POOL:
            raise serializers.ValidationError(
                f'Pool max_size value must be in interval [1, {MAX_SANDBOXES_PER_POOL}].'
                f' Your value: {value}.')
        return value

    @staticmethod
    def get_size(obj: models.Pool) -> int:
        return pools.get_pool_size(obj)

    @staticmethod
    def get_lock_id(obj: models.Pool) -> Optional[int]:
        return obj.lock.id if hasattr(obj, 'lock') else None


class PoolSerializerCreate(PoolSerializer):
    class Meta(PoolSerializer.Meta):
        read_only_fields = ('id', 'size')


class AllocationRequestSerializer(serializers.ModelSerializer):
    allocation_unit_id = serializers.PrimaryKeyRelatedField(
        source='allocation_unit', read_only=True)

    class Meta:
        model = models.AllocationRequest
        fields = ('id', 'allocation_unit_id', 'created')
        read_only_fields = ('id', 'allocation_unit_id', 'created')


class CleanupRequestSerializer(AllocationRequestSerializer):
    pass


class SandboxAllocationUnitSerializer(serializers.ModelSerializer):
    allocation_request = AllocationRequestSerializer(read_only=True)
    pool_id = serializers.PrimaryKeyRelatedField(source='pool', read_only=True)

    class Meta:
        model = models.SandboxAllocationUnit
        fields = ('id', 'pool_id', 'allocation_request')
        read_only_fields = ('id', 'pool_id', 'allocation_request')


class OpenstackAllocationStageSerializer(serializers.ModelSerializer):
    request_id = serializers.PrimaryKeyRelatedField(
        source='allocation_request', read_only=True)

    class Meta:
        model = models.StackAllocationStage
        fields = ('id', 'request_id', 'start', 'end', 'failed', 'error_message',
                  'status', 'status_reason')
        read_only_fields = fields


class OpenstackCleanupStageSerializer(serializers.ModelSerializer):
    request_id = serializers.PrimaryKeyRelatedField(source='cleanup_request', read_only=True)
    allocation_stage_id = serializers.PrimaryKeyRelatedField(
        source='allocation_stage', read_only=True)

    class Meta:
        model = models.StackCleanupStage
        fields = ('id', 'request_id', 'start', 'end', 'failed', 'error_message',
                  'allocation_stage_id',)
        read_only_fields = fields


class SandboxSerializer(serializers.ModelSerializer):
    lock_id = serializers.SerializerMethodField()
    allocation_unit_id = serializers.PrimaryKeyRelatedField(source='allocation_unit',
                                                            read_only=True)

    class Meta:
        model = models.Sandbox
        fields = ('id', 'lock_id', 'allocation_unit_id')
        read_only_fields = ('id', 'lock', 'allocation_unit_id')

    @staticmethod
    def get_lock_id(obj: models.Sandbox) -> Optional[int]:
        return obj.lock.id if hasattr(obj, 'lock') else None


class SandboxLockSerializer(serializers.ModelSerializer):
    sandbox_id = serializers.PrimaryKeyRelatedField(source='sandbox', read_only=True)

    class Meta:
        model = models.SandboxLock
        fields = ('id', 'sandbox_id',)
        read_only_fields = fields


class PoolLockSerializer(serializers.ModelSerializer):
    pool_id = serializers.PrimaryKeyRelatedField(source='pool', read_only=True)

    class Meta:
        model = models.PoolLock
        fields = ('id', 'pool_id')
        read_only_fields = ('id', 'pool_id')


class NodeActionSerializer(serializers.Serializer):
    ACTION_CHOICES = ("suspend",
                      "resume",
                      "reboot")
    action = serializers.ChoiceField(choices=ACTION_CHOICES,
                                     help_text='Action you with to perform on the node.')


##########################################
# KYPO OpenStack lib classes serializers #
##########################################

class LibHostSerializer(serializers.Serializer):
    """KYPO OS lib Host topology serializer"""
    name = serializers.CharField()


class LibRouterSerializer(serializers.Serializer):
    """KYPO OS lib Router topology serializer"""
    name = serializers.CharField()
    cidr = serializers.CharField()


class LibNetworkSerializer(serializers.Serializer):
    """KYPO OS lib Network topology serializer"""
    name = serializers.CharField()
    cidr = serializers.CharField()


class LinkSerializer(serializers.Serializer):
    port_a = serializers.SerializerMethodField()
    port_b = serializers.SerializerMethodField()

    @staticmethod
    def get_port_a(obj) -> str:
        return obj.real_port.name

    @staticmethod
    def get_port_b(obj) -> str:
        return obj.dummy_port.name


class PortSerializer(serializers.Serializer):
    ip = serializers.CharField()
    mac = serializers.CharField()
    parent = serializers.CharField()
    name = serializers.CharField()


class TopologySerializer(serializers.Serializer):
    """Serializer for topology"""
    hosts = LibHostSerializer(many=True)
    routers = LibRouterSerializer(many=True)
    switches = LibNetworkSerializer(many=True)
    links = LinkSerializer(many=True)
    ports = PortSerializer(many=True)


class NodeSerializer(serializers.Serializer):
    """KYPO OS lib Instance serializer"""
    name = serializers.CharField()
    id = serializers.CharField()
    status = serializers.CharField()
    creation_time = serializers.DateTimeField()
    update_time = serializers.DateTimeField()
    image_id = serializers.CharField()
    flavor_name = serializers.CharField()


class NodeConsoleSerializer(serializers.Serializer):
    url = serializers.CharField()


class SandboxEventSerializer(serializers.Serializer):
    time = serializers.CharField(source='event_time')
    name = serializers.CharField(source='resource_name')
    status = serializers.CharField(source='resource_status')
    status_reason = serializers.CharField(source='resource_status_reason')


class SandboxResourceSerializer(serializers.Serializer):
    name = serializers.CharField(source='resource_name')
    type = serializers.CharField(source='resource_type')
    status = serializers.CharField(source='resource_status')
