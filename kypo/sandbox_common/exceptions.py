"""
Module containing exceptions and custom exception handler
"""
import structlog
from django.conf import settings
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import PermissionDenied

from kypo2_openstack_lib.exceptions import KypoException

# Create logger
LOG = structlog.get_logger()


class ApiException(Exception):
    """
    Base exception class for this project.
    All other exceptions inherit form it.
    """
    pass


class DockerError(ApiException):
    """
    Raised when there is a problem with Docker container.
    """
    pass


class ValidationError(ApiException):
    """
    Raised when request contains invalid values.
    """
    pass


class LimitExceededError(ApiException):
    """
    Raised when internally set limits are exceeded, eg. count of Ansible outputs.
    """
    pass


class NetworkError(ApiException):
    """
    Raised when call to external services fails.
    """
    pass


class GitError(ApiException):
    """
    For Git related errors.
    """
    pass


class AnsibleError(ApiException):
    """
    Raised when there is some error during Ansible.
    """
    pass


class InterruptError(ApiException):
    """
    Raised when there is need to interrupt some action because of unspecified error.
    """
    pass


class ImproperlyConfigured(ApiException):
    """
    Raised when application was not configured properly.
    """
    pass


def custom_exception_handler(exc, context):
    """
    Log all exceptions and handle KYPO exceptions in a special way.
    """
    LOG.error(str(exc), exc_info=True)

    if isinstance(exc, (ApiException, KypoException)):
        return Response({
            'detail': str(exc),
            'parameters': context.get('kwargs')
        }, status=status.HTTP_400_BAD_REQUEST)

    # Call REST framework's default exception handler, to get the standard error response.
    # Handles only Django Errors.
    response = exception_handler(exc, context)

    # Add user-role list to Permission denied error
    if isinstance(exc, PermissionDenied):
        try:
            user = context['request'].user
            user_groups = [g.name for g in user.groups.all()] if user else user
        except KeyError:
            user_groups = None
        return Response({
            'detail': str(exc),
            'parameters': context.get('kwargs'),
            'user_roles': user_groups
        }, status=status.HTTP_400_BAD_REQUEST)

    # Django DEBUG mode does better job on unhandled exceptions.
    # That's why this is used only in production mode.
    if not settings.DEBUG and response is None:
        response = Response({
            'detail': str(exc),
            'parameters': context['kwargs']
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return response
