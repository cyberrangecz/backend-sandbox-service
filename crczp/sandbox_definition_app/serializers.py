"""
Serializer and validator definitions for database models.

Serializers are used to deserialize (parse) requests
and serialize database queries to responses.
Validators validate single fields or entire objects.

Swagger can utilise type hints to determine type, so use them in your own methods.
"""
from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from crczp.sandbox_common_lib.serializers import UserSerializer
from crczp.sandbox_definition_app import models


class DefinitionSerializer(serializers.ModelSerializer):
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = models.Definition
        fields = ('id', 'name', 'url', 'rev', 'created_by')
        read_only_fields = ('id', 'name', 'created_by')
        validators = [
            UniqueTogetherValidator(
                queryset=models.Definition.objects.all(),
                fields=['url', 'rev']
            )
        ]

    @staticmethod
    def get_created_by(obj: models.Definition):
        return UserSerializer(obj.created_by).data


class DefinitionSerializerCreate(DefinitionSerializer):
    """The name needs to be a readable field, otherwise it is ignored."""
    class Meta(DefinitionSerializer.Meta):
        read_only_fields = ('id',)


class DefinitionRevSerializer(serializers.Serializer):
    name = serializers.CharField()


class LocalVariableSerializer(serializers.Serializer):
    name = serializers.CharField()
    type = serializers.CharField()
    generated_value = serializers.CharField(read_only=True)
    min = serializers.CharField()
    max = serializers.CharField()
    length = serializers.IntegerField()
    prohibited = serializers.ListField()


class LocalSandboxVariablesSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    access_token = serializers.CharField()
