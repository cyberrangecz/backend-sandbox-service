"""
Serializer and validator definitions for database models.

Serializers are used to deserialize (parse) requests
and serialize database queries to responses.
Validators validate single fields or entire objects.

Swagger can utilise type hints to determine type, so use them in your own methods.
"""
from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from . import models


class DefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Definition
        fields = ('id', 'name', 'url', 'rev')
        read_only_fields = ('id', 'name')

        validators = [
            UniqueTogetherValidator(
                queryset=models.Definition.objects.all(),
                fields=['url', 'rev']
            )
        ]


class DefinitionSerializerCreate(DefinitionSerializer):
    """The name needs to be a readable field, otherwise it is ignored."""
    class Meta(DefinitionSerializer.Meta):
        read_only_fields = ('id',)
