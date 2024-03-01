from enum import Enum
from rest_framework import permissions

from django.conf import settings
from crczp.sandbox_uag.auth import get_user_roles
from crczp.sandbox_uag.oidc_jwt import JWTAccessTokenAuthentication

authenticator_class = JWTAccessTokenAuthentication()
UAG_SETTINGS = settings.SANDBOX_UAG


class EndpointPermissionClass(permissions.BasePermission):
    class AccessLevel(Enum):
        TRAINEE = 1
        DESIGNER = 2
        ORGANIZER = 3
        ADMIN = 4

    @staticmethod
    def get_role_string(level: AccessLevel):
        return f'ROLE_SANDBOX-SERVICE_{level.name}'

    @staticmethod
    def has_access_level(request, level: AccessLevel):
        if not settings.CRCZP_SERVICE_CONFIG.authentication.authenticated_rest_api:
            return True

        bearer_token = authenticator_class.get_bearer_token(request)
        users_roles_names = get_user_roles(UAG_SETTINGS['ROLES_ACQUISITION_URL'], bearer_token)
        role_name = EndpointPermissionClass.get_role_string(level)
        return role_name in users_roles_names


class TraineePermission(EndpointPermissionClass):
    def has_permission(self, request, view):
        return self.has_access_level(request, self.AccessLevel.TRAINEE)


class DesignerPermission(EndpointPermissionClass):
    def has_permission(self, request, view):
        return self.has_access_level(request, self.AccessLevel.DESIGNER)


class OrganizerPermission(EndpointPermissionClass):
    def has_permission(self, request, view):
        return self.has_access_level(request, self.AccessLevel.ORGANIZER)


class AdminPermission(EndpointPermissionClass):
    def has_permission(self, request, view):
        return self.has_access_level(request, self.AccessLevel.ADMIN)
