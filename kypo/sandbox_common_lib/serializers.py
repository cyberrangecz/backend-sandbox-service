"""
Serializer and validator definitions for database models.

Serializers are used to deserialize (parse) requests
and serialize database queries to responses.
Validators validate single fields or entire objects.

Swagger can utilise type hints to determine type, so use them in your own methods.
"""
from rest_framework import serializers
from django.contrib.auth.models import User


class UserSerializer(serializers.ModelSerializer):
    sub = serializers.CharField(source='username')
    full_name = serializers.SerializerMethodField()
    mail = serializers.CharField(source='email')

    class Meta:
        model = User
        fields = ('id', 'sub', 'full_name', 'mail')
        read_only_fields = ('id', 'sub', 'full_name', 'mail')

    @staticmethod
    def get_full_name(obj: User):
        return f'{obj.first_name} {obj.last_name}'.lstrip()
