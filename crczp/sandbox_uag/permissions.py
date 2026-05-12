"""Permission classes for sandbox REST API endpoint access control."""

from enum import Enum

from django.conf import settings
from rest_framework import permissions

from crczp.sandbox_uag.auth import get_user_roles
from crczp.sandbox_uag.oidc_jwt import JWTAccessTokenAuthentication

authenticator_class = JWTAccessTokenAuthentication()
UAG_SETTINGS = settings.SANDBOX_UAG


class EndpointPermissionClass(permissions.BasePermission):
    """Base permission class that checks user roles against required access levels."""

    class AccessLevel(Enum):
        """Enumeration of available access levels for sandbox endpoints."""

        TRAINEE = 1
        DESIGNER = 2
        ORGANIZER = 3
        ADMIN = 4

    @staticmethod
    def get_role_string(level: AccessLevel):
        """Return the full role string for a given access level."""
        return f'ROLE_SANDBOX-SERVICE_{level.name}'

    @staticmethod
    def has_access_level(request, level: AccessLevel):
        """Check whether the request bearer token grants the required access level."""
        if not settings.CRCZP_SERVICE_CONFIG.authentication.authenticated_rest_api:
            return True

        bearer_token = authenticator_class.get_bearer_token(request)
        users_roles_names = get_user_roles(UAG_SETTINGS['ROLES_ACQUISITION_URL'], bearer_token)
        role_name = EndpointPermissionClass.get_role_string(level)
        return role_name in users_roles_names


class TraineePermission(EndpointPermissionClass):
    """Permission class granting access to users with the TRAINEE role."""

    def has_permission(self, request, view):
        """Return True if the request user has at least TRAINEE access level."""
        return self.has_access_level(request, self.AccessLevel.TRAINEE)


class DesignerPermission(EndpointPermissionClass):
    """Permission class granting access to users with the DESIGNER role."""

    def has_permission(self, request, view):
        """Return True if the request user has at least DESIGNER access level."""
        return self.has_access_level(request, self.AccessLevel.DESIGNER)


class OrganizerPermission(EndpointPermissionClass):
    """Permission class granting access to users with the ORGANIZER role."""

    def has_permission(self, request, view):
        """Return True if the request user has at least ORGANIZER access level."""
        return self.has_access_level(request, self.AccessLevel.ORGANIZER)


class AdminPermission(EndpointPermissionClass):
    """Permission class granting access to users with the ADMIN role."""

    def has_permission(self, request, view):
        """Return True if the request user has at least ADMIN access level."""
        return self.has_access_level(request, self.AccessLevel.ADMIN)
