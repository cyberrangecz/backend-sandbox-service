from rest_framework import serializers

class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    sub = serializers.CharField()
    full_name = serializers.CharField()
    given_name = serializers.CharField()
    family_name = serializers.CharField()
    mail = serializers.CharField()


class HardwareUsageSerializer(serializers.Serializer):
    vcpu = serializers.CharField()
    ram = serializers.CharField()
    instances = serializers.CharField()
    network = serializers.CharField()
    subnet = serializers.CharField()
    port = serializers.CharField()


class SandboxDefinitionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    url = serializers.CharField(help_text='SSH git URL of the definition')
    rev = serializers.CharField(help_text='Git revision used')
    created_by = UserSerializer()


class DefinitionRequestSerializer(serializers.Serializer):
    url = serializers.CharField(help_text='SSH git URL of the definition')
    rev = serializers.CharField(help_text='Git revision used')


class PoolResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    definition_id = serializers.IntegerField(help_text='Sandbox definition ID')
    size = serializers.IntegerField(
        read_only=True,
        default=0,
        help_text='Current number of SandboxAllocationUnits'
    )
    max_size = serializers.IntegerField(
        help_text='Maximum number of SandboxAllocationUnits'
    )
    lock_id = serializers.IntegerField(read_only=True)
    rev = serializers.CharField(
        read_only=True,
        help_text='Name of used git branch'
    )
    rev_sha = serializers.CharField(
        read_only=True,
        help_text='SHA of used git branch'
    )
    created_by = UserSerializer()
    hardware_usage = HardwareUsageSerializer()
    definition = SandboxDefinitionSerializer()


class PoolRequestSerializer(serializers.Serializer):
    definition_id = serializers.IntegerField(help_text='Sandbox definition ID')
    max_size = serializers.IntegerField(help_text='Maximum number of SandboxAllocationUnits')
    send_emails = serializers.BooleanField(
        help_text='Send email notifications of allocation progress.',
        required=False
    )


# Optional: paginated list response serializer
def get_paginated_response_serializer(item_serializer_class):
    class PaginatedSerializer(serializers.Serializer):
        page = serializers.IntegerField()
        page_size = serializers.IntegerField()
        page_count = serializers.IntegerField()
        count = serializers.IntegerField()
        total_count = serializers.IntegerField()
        results = item_serializer_class(many=True)

    return PaginatedSerializer
