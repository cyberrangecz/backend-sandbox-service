import structlog
from django.conf import settings
from django.http import Http404
from crczp.cloud_commons import CrczpException
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from crczp.sandbox_common_lib.exceptions import ApiException

# Create logger
LOG = structlog.get_logger()


def custom_exception_handler(exc, context):
    """Log all exceptions and handle CRCZP exceptions in a special way."""

    if isinstance(exc, PermissionDenied):
        response = handle_permission_denied(exc, context)
    elif isinstance(exc, ValidationError):
        response = handle_model_validation_error(exc, context)
    elif isinstance(exc, (ApiException, CrczpException)):
        response = handle_crczp_exception(exc, context)
    elif isinstance(exc, Http404):
        response = handle_not_found(exc, context)
    else:
        # Call REST framework's default exception handler, to get the standard error response.
        # Handles only Django Errors.
        response = exception_handler(exc, context)

        if response is None:
            response = Response({
                'detail': str(exc),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    exc_info = settings.DEBUG or not isinstance(exc, (Http404,
                                                      PermissionDenied,
                                                      ValidationError,))
    LOG.error(repr(exc), data=response.data if response else None, exc_info=exc_info)
    return response


def handle_crczp_exception(exc, context):
    """Handle OpenStack lib and this project exceptions."""
    return Response({
        'detail': str(exc),
    }, status=status.HTTP_400_BAD_REQUEST)


def handle_permission_denied(exc, context):
    """Add user-role list to Permission denied error."""
    try:
        user = context['request'].user
        user_groups = [g.name for g in user.groups.all()] if user else user
    except KeyError:
        user_groups = None
    return Response({
        'detail': f'{str(exc)} User roles: {str(user_groups)}'
    }, status=status.HTTP_403_FORBIDDEN)


def handle_model_validation_error(exc, context):
    """Fix error message in model validation error."""
    return Response({
        'detail': str(exc.detail),
    }, status=status.HTTP_400_BAD_REQUEST)


def handle_not_found(exc, context):
    """Fix error message in 404 not found."""
    return Response({
        'detail': str(exc),
    }, status=status.HTTP_404_NOT_FOUND)
