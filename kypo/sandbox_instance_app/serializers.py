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
from kypo.sandbox_instance_app.models import SandboxAllocationUnit, Pool, AllocationRequest, \
    CleanupRequest, AllocationStage, Sandbox

MAX_SANDBOXES_PER_POOL = 64


class PoolSerializer(serializers.ModelSerializer):
    size = serializers.SerializerMethodField(
        help_text="Number of allocation units associated with this pool.")
    lock_id = serializers.SerializerMethodField()
    definition_id = serializers.PrimaryKeyRelatedField(
        source='definition', queryset=Definition.objects.all())

    class Meta:
        model = models.Pool
        fields = ('id', 'definition_id', 'size', 'max_size', 'lock_id', 'rev', 'rev_sha')
        read_only_fields = ('id', 'size', 'lock', 'rev_sha')

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
    def get_lock_id(obj) -> Optional[int]:
        return obj.lock.id if hasattr(obj, 'lock') else None


class PoolSerializerCreate(PoolSerializer):
    class Meta(PoolSerializer.Meta):
        read_only_fields = ('id', 'size')


class AllocationRequestSerializer(serializers.ModelSerializer):
    allocation_unit_id = serializers.PrimaryKeyRelatedField(
        source='allocation_unit', queryset=SandboxAllocationUnit.objects.all())

    class Meta:
        model = models.AllocationRequest
        fields = ('id', 'allocation_unit_id', 'created')
        read_only_fields = fields


class CleanupRequestSerializer(AllocationRequestSerializer):
    pass


class SandboxAllocationUnitSerializer(serializers.ModelSerializer):
    allocation_request = AllocationRequestSerializer(read_only=True)
    pool_id = serializers.PrimaryKeyRelatedField(
        source='pool', queryset=Pool.objects.all())

    class Meta:
        model = models.SandboxAllocationUnit
        fields = ('id', 'pool_id', 'allocation_request')
        read_only_fields = ('id', 'pool_id', 'allocation_request')


class AllocationStageSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField(help_text='Type of the stage.')
    request_id = serializers.PrimaryKeyRelatedField(
        source='request', queryset=AllocationRequest.objects.all())

    class Meta:
        model = models.AllocationStage
        fields = ('id', 'request_id', 'type', 'start', 'end', 'failed', 'error_message')
        read_only_fields = fields

    @staticmethod
    def get_type(obj) -> str:
        return obj.type.value


class OpenstackAllocationStageSerializer(AllocationStageSerializer):
    class Meta:
        model = models.StackAllocationStage
        fields = AllocationStageSerializer.Meta.fields + ('status', 'status_reason')
        read_only_fields = fields


class CleanupStageSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField(help_text='Type of the stage.')
    request_id = serializers.PrimaryKeyRelatedField(
        source='request', queryset=CleanupRequest.objects.all())

    class Meta:
        model = models.CleanupStage
        fields = ('id', 'request_id', 'type', 'start', 'end', 'failed', 'error_message')
        read_only_fields = fields

    @staticmethod
    def get_type(obj) -> str:
        return obj.type.value


class OpenstackCleanupStageSerializer(CleanupStageSerializer):
    request_id = serializers.PrimaryKeyRelatedField(
        source='request', queryset=AllocationRequest.objects.all())
    allocation_stage_id = serializers.PrimaryKeyRelatedField(
        source='allocation_stage', queryset=AllocationStage.objects.all())

    class Meta:
        model = models.StackCleanupStage
        fields = AllocationStageSerializer.Meta.fields + ('allocation_stage_id',)
        read_only_fields = fields


class SandboxSerializer(serializers.ModelSerializer):
    lock_id = serializers.SerializerMethodField()
    allocation_unit_id = serializers.PrimaryKeyRelatedField(
        source='allocation_unit', queryset=SandboxAllocationUnit.objects.all())

    class Meta:
        model = models.Sandbox
        fields = ('id', 'lock_id', 'allocation_unit_id')
        read_only_fields = ('id', 'lock', 'allocation_unit_id')

    @staticmethod
    def get_lock_id(obj) -> Optional[int]:
        return obj.lock.id if hasattr(obj, 'lock') else None


class SandboxLockSerializer(serializers.ModelSerializer):
    sandbox_id = serializers.PrimaryKeyRelatedField(
        source='sandbox', queryset=Sandbox.objects.all())

    class Meta:
        model = models.SandboxLock
        fields = ('id', 'sandbox_id',)
        read_only_fields = fields


class PoolLockSerializer(serializers.ModelSerializer):
    pool_id = serializers.PrimaryKeyRelatedField(
        source='pool', queryset=Pool.objects.all())

    class Meta:
        model = models.PoolLock
        fields = ('id', 'pool_id',)
        read_only_fields = fields


class NodeActionSerializer(serializers.Serializer):
    ACTION_CHOICES = ("suspend",
                      "resume",
                      "reboot")
    action = serializers.ChoiceField(choices=ACTION_CHOICES,
                                     help_text='Action you with to perform on the node.')


class PoolKeypairSerializer(serializers.ModelSerializer):
    private = serializers.CharField(source='private_management_key')
    public = serializers.CharField(source='public_management_key')

    class Meta:
        model = models.Pool
        fields = ('private', 'public')


class SandboxKeypairSerializer(serializers.ModelSerializer):
    private = serializers.CharField(source='private_user_key')
    public = serializers.CharField(source='public_user_key')

    class Meta:
        model = models.Sandbox
        fields = ('private', 'public')


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
    time = serializers.CharField(source='e_time')
    name = serializers.CharField(source='r_name')
    status = serializers.CharField(source='r_status')
    status_reason = serializers.CharField(source='r_status_reason')


class SandboxResourceSerializer(serializers.Serializer):
    name = serializers.CharField(source='r_name')
    type = serializers.CharField(source='r_type')
    status = serializers.CharField(source='r_status')
