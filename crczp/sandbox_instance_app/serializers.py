"""
Serializer and validator definitions for database models.

Serializers are used to deserialize (parse) requests
and serialize database queries to responses.
Validators validate single fields or entire objects.

Swagger can utilise type hints to determine type, so use them in your own methods.
"""
from typing import Optional
from rest_framework import serializers
from django.db import transaction
from drf_spectacular.utils import extend_schema_field

from crczp.sandbox_common_lib.serializers import UserSerializer
from crczp.sandbox_definition_app.models import Definition
from crczp.sandbox_definition_app.serializers import DefinitionSerializer
from crczp.sandbox_instance_app import models
from crczp.sandbox_instance_app.lib import pools, requests
from crczp.sandbox_cloud_app import serializers as cloud_serializers


class PoolSerializer(serializers.ModelSerializer):
    size = serializers.SerializerMethodField(
        help_text="Number of allocation units associated with this pool.")
    lock_id = serializers.SerializerMethodField()
    definition = serializers.SerializerMethodField()
    definition_id = serializers.PrimaryKeyRelatedField(source='definition', queryset=Definition.objects.all(),
                                                       write_only=True)
    created_by = serializers.SerializerMethodField()
    hardware_usage = serializers.SerializerMethodField()

    class Meta:
        model = models.Pool
        fields = ('id', 'definition_id', 'size', 'max_size', 'lock_id', 'rev', 'rev_sha', 'comment', 'visible',
                  'created_by', 'hardware_usage', 'definition', 'send_emails')
        read_only_fields = ('id', 'definition_id', 'size', 'lock', 'rev', 'rev_sha', 'created_by', 'hardware_usage',
                            'definition')

    def update(self, instance: Meta.model, validated_data):
        instance.max_size = validated_data.get('max_size', instance.max_size)
        instance.comment = validated_data.get('comment', instance.comment)
        instance.visible = validated_data.get('visible', instance.visible)
        instance.send_emails = validated_data.get('send_emails', instance.send_emails)
        instance.save()
        return instance

    @staticmethod
    def validate_max_size(value):
        """Validate that max_size is greater than 0"""
        if value < 1:
            raise serializers.ValidationError(
                f'Pool max_size value must be greater than 0. Your value: {value}.')
        return value

    @staticmethod
    def get_size(pool: models.Pool) -> int:
        # Required only because of the migration from older versions.
        # For the release after 23.12 remove this method and set size attribute of serialize to
        # IntegerField
        if pool.size == 0:
            with transaction.atomic():
                pool = models.Pool.objects.select_for_update().get(id=pool.id)
                pool.size = pool.allocation_units.count()
                pool.save()

        return pool.size

    @staticmethod
    def get_lock_id(obj: models.Pool) -> Optional[int]:
        return obj.lock.id if hasattr(obj, 'lock') else None

    @extend_schema_field(field=serializers.BooleanField())
    @staticmethod
    def get_created_by(obj: models.Pool) -> bool:
        return UserSerializer(obj.created_by).data

    @extend_schema_field(field=serializers.BooleanField())
    @staticmethod
    def get_hardware_usage(obj: models.Pool) -> bool:
        hardware_usage = pools.get_hardware_usage_of_sandbox(obj)
        return HardwareUsageSerializer(hardware_usage).data

    @extend_schema_field(field=serializers.BooleanField())
    @staticmethod
    def get_definition(obj: models.Pool) -> bool:
        return DefinitionSerializer(obj.definition).data


class PoolSerializerCreate(PoolSerializer):

    class Meta(PoolSerializer.Meta):
        read_only_fields = ('id', 'size')


class RequestSerializer(serializers.ModelSerializer):
    allocation_unit_id = serializers.PrimaryKeyRelatedField(source='allocation_unit',
                                                            read_only=True)
    stages = serializers.SerializerMethodField()

    class Meta:
        fields = ('id', 'allocation_unit_id', 'created', 'stages')
        read_only_fields = ('id', 'allocation_unit_id', 'created', 'stages')


class AllocationRequestSerializer(RequestSerializer):
    @extend_schema_field(field=serializers.BooleanField())
    @staticmethod
    def get_stages(obj) -> bool:
        return requests.get_allocation_request_stages_state(obj)

    class Meta(RequestSerializer.Meta):
        model = models.AllocationRequest


class CleanupRequestSerializer(RequestSerializer):
    @extend_schema_field(field=serializers.BooleanField())
    @staticmethod
    def get_stages(obj) -> bool:
        return requests.get_cleanup_request_stages_state(obj)

    class Meta(RequestSerializer.Meta):
        model = models.CleanupRequest

class PoolCleanupRequestSerializer(serializers.Serializer):
    pool_id = serializers.IntegerField()
    reason = serializers.CharField(required=False)

class PoolCleanupRequestFailedSerializer(serializers.Serializer):
    pool_id = serializers.IntegerField()
    error_message = serializers.CharField()

class SandboxAllocationUnitSerializer(serializers.ModelSerializer):
    allocation_request = AllocationRequestSerializer(read_only=True)
    cleanup_request = CleanupRequestSerializer()
    pool_id = serializers.PrimaryKeyRelatedField(source='pool', read_only=True)
    created_by = serializers.SerializerMethodField()
    locked = serializers.SerializerMethodField()

    class Meta:
        model = models.SandboxAllocationUnit
        fields = ('id', 'pool_id', 'allocation_request', 'cleanup_request', 'created_by', 'locked', 'comment')
        read_only_fields = ('id', 'pool_id', 'allocation_request', 'cleanup_request', 'created_by',
                            'locked')

    def update(self, instance: Meta.model, validated_data):
        instance.comment = validated_data.get('comment', instance.comment)
        instance.save()
        return instance

    @extend_schema_field(field=serializers.BooleanField())
    @staticmethod
    def get_created_by(obj: models.SandboxAllocationUnit) -> bool:
        return UserSerializer(obj.created_by).data

    @extend_schema_field(field=serializers.BooleanField())
    @staticmethod
    def get_locked(obj: models.SandboxAllocationUnit) -> bool:
        return hasattr(obj, 'sandbox') and hasattr(obj.sandbox, 'lock')

class SandboxAllocationUnitIdListSerializer(serializers.Serializer):
    unit_ids = serializers.ListField(child=serializers.IntegerField())


class TerraformAllocationStageSerializer(serializers.ModelSerializer):
    request_id = serializers.PrimaryKeyRelatedField(
        source='allocation_request', read_only=True)

    class Meta:
        model = models.StackAllocationStage
        fields = ('id', 'request_id', 'start', 'end', 'failed', 'error_message',
                  'status', 'status_reason')
        read_only_fields = fields


class TerraformCleanupStageSerializer(serializers.ModelSerializer):
    request_id = serializers.PrimaryKeyRelatedField(source='cleanup_request', read_only=True)
    #allocation_stage_id = serializers.PrimaryKeyRelatedField(
    #    source='allocation_stage', read_only=True)

    class Meta:
        model = models.StackCleanupStage
        fields = ('id', 'request_id', 'start', 'end', 'failed', 'error_message',
                  #'allocation_stage_id',
                  )
        read_only_fields = fields


class AllocationTerraformOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.AllocationTerraformOutput
        fields = ('content',)
        read_only_fields = fields


class SandboxSerializer(serializers.ModelSerializer):
    lock_id = serializers.SerializerMethodField()
    allocation_unit_id = serializers.PrimaryKeyRelatedField(source='allocation_unit',
                                                            read_only=True)

    class Meta:
        model = models.Sandbox
        fields = ('id', 'lock_id', 'allocation_unit_id', 'ready')
        read_only_fields = ('id', 'lock', 'allocation_unit_id', 'ready')

    @staticmethod
    def get_lock_id(obj: models.Sandbox) -> Optional[int]:
        return obj.lock.id if hasattr(obj, 'lock') else None


class SandboxLockSerializer(serializers.ModelSerializer):
    sandbox_id = serializers.PrimaryKeyRelatedField(source='sandbox', read_only=True)

    class Meta:
        model = models.SandboxLock
        fields = ('id', 'sandbox_id', 'created_by')
        read_only_fields = fields


class PoolLockSerializer(serializers.ModelSerializer):
    pool_id = serializers.PrimaryKeyRelatedField(source='pool', read_only=True)

    class Meta:
        model = models.PoolLock
        fields = ('id', 'pool_id')
        read_only_fields = ('id', 'pool_id')
        write_only_fields = ('training_access_token',)


class NodeActionSerializer(serializers.Serializer):
    ACTION_CHOICES = ("suspend",
                      "resume",
                      "reboot")
    action = serializers.ChoiceField(choices=ACTION_CHOICES,
                                     help_text='Action you with to perform on the node.')


##########################################
# CRCZP OpenStack lib classes serializers #
##########################################

class HostSerializer(serializers.Serializer):
    """CRCZP OS lib Host and Router topology serializer"""
    name = serializers.CharField()
    os_type = serializers.CharField()
    gui_access = serializers.BooleanField()
    ip = serializers.CharField()

class SubnetSerializer(serializers.Serializer):
    name = serializers.CharField()
    cidr = serializers.CharField()
    hosts = HostSerializer(many=True)


class RouterSerializer(serializers.Serializer):
    """CRCZP OS lib Host and Router topology serializer"""
    name = serializers.CharField()
    os_type = serializers.CharField()
    gui_access = serializers.BooleanField()
    subnets = SubnetSerializer(many=True)


class LibNetworkSerializer(serializers.Serializer):
    """CRCZP OS lib Network topology serializer"""
    name = serializers.CharField()
    cidr = serializers.CharField()

class TopologySerializer(serializers.Serializer):
    """Serializer for topology"""
    routers = RouterSerializer(many=True)


class NodeSerializer(serializers.Serializer):
    """CRCZP OS lib Instance serializer"""
    name = serializers.CharField()
    id = serializers.CharField()
    status = serializers.CharField()
    image = cloud_serializers.ImageSerializer()
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


class HardwareUsageSerializer(serializers.Serializer):
    vcpu = serializers.DecimalField(decimal_places=3, max_digits=7)
    ram = serializers.DecimalField(decimal_places=3, max_digits=7)
    instances = serializers.DecimalField(decimal_places=3, max_digits=7)
    network = serializers.DecimalField(decimal_places=3, max_digits=7)
    subnet = serializers.DecimalField(decimal_places=3, max_digits=7)
    port = serializers.DecimalField(decimal_places=3, max_digits=7)
