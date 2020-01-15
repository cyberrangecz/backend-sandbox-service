"""
Serializer and validator definitions for database models.

Serializers are used to deserialize (parse) requests
and serialize database queries to responses.
Validators validate single fields or entire objects.

Swagger can utilise type hints to determine type, so use them in your own methods.
"""
from typing import Optional

from rest_framework import serializers

from ..sandbox_common.config import config
from .services import pool_service
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

    @staticmethod
    def get_size(obj: models.Pool) -> int:
        return pool_service.get_pool_size(obj)


class AllocationRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.AllocationRequest
        fields = ('id', 'allocation_unit', 'created')
        read_only_fields = fields


class CleanupRequestSerializer(AllocationRequestSerializer):
    pass


class SandboxAllocationUnitSerializer(serializers.ModelSerializer):
    allocation_request = AllocationRequestSerializer(read_only=True)

    class Meta:
        model = models.SandboxAllocationUnit
        fields = ('id', 'pool', 'allocation_request')
        read_only_fields = ('id', 'pool', 'allocation_request')


class AllocationStageSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()

    class Meta:
        model = models.AllocationStage
        fields = ('id', 'request', 'type', 'start', 'end', 'failed', 'error_message')
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
    type = serializers.SerializerMethodField()

    class Meta:
        model = models.CleanupStage
        fields = ('id', 'request', 'type', 'start', 'end', 'failed', 'error_message')
        read_only_fields = fields

    @staticmethod
    def get_type(obj) -> str:
        return obj.type.value


class OpenstackCleanupStageSerializer(CleanupStageSerializer):
    class Meta:
        model = models.StackCleanupStage
        fields = AllocationStageSerializer.Meta.fields + ('allocation_stage',)
        read_only_fields = fields


class SandboxSerializer(serializers.ModelSerializer):
    lock = serializers.SerializerMethodField()

    class Meta:
        model = models.Sandbox
        fields = ('id', 'lock',)
        read_only_fields = ('id', 'lock',)

    @staticmethod
    def get_lock(obj) -> Optional[int]:
        return obj.lock.id if hasattr(obj, 'lock') else None


class LockSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Lock
        fields = ('id', 'sandbox',)
        read_only_fields = ('id', 'sandbox',)


class NodeActionSerializer(serializers.Serializer):
    ACTION_CHOICES = ("suspend",
                      "resume",
                      "reboot")
    action = serializers.ChoiceField(choices=ACTION_CHOICES)


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
    flavor_id = serializers.CharField()


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
