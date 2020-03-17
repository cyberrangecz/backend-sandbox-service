import structlog
from django.conf import settings
from django.http import Http404
from kypo.openstack_driver.exceptions import KypoException
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from kypo.sandbox_common_lib.exceptions import ApiException

# Create logger
LOG = structlog.get_logger()


def custom_exception_handler(exc, context):
    """Log all exceptions and handle KYPO exceptions in a special way."""

    if isinstance(exc, (ApiException, KypoException)):
        response = handle_kypo_exception(exc, context)
    elif isinstance(exc, PermissionDenied):
        response = handle_permission_denied(exc, context)
    elif isinstance(exc, ValidationError):
        response = handle_model_validation_error(exc, context)
    else:
        # Call REST framework's default exception handler, to get the standard error response.
        # Handles only Django Errors.
        response = exception_handler(exc, context)

        # Django DEBUG mode does better job on unhandled exceptions.
        # That's why this is used only in production mode.
        if not settings.DEBUG and response is None:
            response = Response({
                'detail': str(exc),
                'parameters': context['kwargs']
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    exec_info = not isinstance(exc, (Http404, PermissionDenied))
    LOG.error(repr(exc), data=response.data if response else None, exc_info=exec_info)
    return response


def handle_kypo_exception(exc, context):
    """Handle OpenStack lib and this project exceptions."""
    return Response({
        'detail': str(exc),
        'parameters': context.get('kwargs')
    }, status=status.HTTP_400_BAD_REQUEST)


def handle_permission_denied(exc, context):
    """Add user-role list to Permission denied error."""
    try:
        user = context['request'].user
        user_groups = [g.name for g in user.groups.all()] if user else user
    except KeyError:
        user_groups = None
    return Response({
        'detail': str(exc),
        'parameters': {
            'user_roles': user_groups
        }.update(context.get('kwargs')),
    }, status=status.HTTP_403_FORBIDDEN)


def handle_model_validation_error(exc, context):
    """Fix error message in model validation error."""
    return Response({
        'detail': exc.detail,
        'parameters': context.get('kwargs'),
    }, status=status.HTTP_400_BAD_REQUEST)
