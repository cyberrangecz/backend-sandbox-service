import base64
import json
import re
from enum import Enum
from urllib.parse import unquote
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied
import structlog

from django.conf import settings
from crczp.sandbox_uag.auth import get_user_roles
from crczp.sandbox_uag.oidc_jwt import JWTAccessTokenAuthentication

LOG = structlog.get_logger()
authenticator_class = JWTAccessTokenAuthentication()
UAG_SETTINGS = settings.SANDBOX_UAG


def _sub_from_jwt_in_request(request):
    """
    Extract the OIDC 'sub' claim from the Bearer JWT in the request.
    Matches what the training-service sends as created_by_sub (JWT sub claim).
    Handles string or numeric sub; returns value as string for comparison.
    Returns None if no token or sub not found.
    """
    try:
        bearer = authenticator_class.get_bearer_token(request)
        if not bearer:
            return None
        token_decoded = bearer.decode('ascii') if isinstance(bearer, bytes) else bearer
        parts = token_decoded.split('.')
        if len(parts) < 2:
            return None
        payload_part = parts[1]
        pad = 4 - len(payload_part) % 4
        if pad and pad < 4:
            payload_part += '=' * pad
        payload_bytes_decoded = base64.urlsafe_b64decode(payload_part.encode('ascii'))
        payload_string = payload_bytes_decoded.decode('utf-8')
        try:
            payload = json.loads(payload_string)
            sub = payload.get('sub')
            if sub is not None:
                return str(sub).strip()
        except (json.JSONDecodeError, TypeError):
            pass
        # Fallback: string or numeric sub in raw payload (e.g. non-standard encoding)
        for pattern in [r'"sub"\s*:\s*"([^"]*)"', r'"sub"\s*:\s*(\d+)']:
            match = re.search(pattern, payload_string)
            if match:
                return match.group(1).strip() if isinstance(match.group(1), str) else str(match.group(1))
        return None
    except Exception:
        return None


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


class CreateAllocationUnitForSelfOrOrganizerAdminPermission(permissions.BasePermission):
    """
    Allow POST to create sandbox allocation unit when:
    - caller has Organizer or Admin (any creation), or
    - caller has Trainee and body has created_by_sub matching the JWT sub and count is 1 (single-sandbox-per-user).
    Allow GET when caller has Organizer, Admin, or Trainee (Trainee can list pool allocation units for managed
    instances where sandboxes are allocated by Admin and assigned from the pool).
    """

    def has_permission(self, request, view):
        if not settings.CRCZP_SERVICE_CONFIG.authentication.authenticated_rest_api:
            return True
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return (
                EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ORGANIZER)
                or EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ADMIN)
                or EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.TRAINEE)
            )
        if request.method != 'POST':
            return False
        if EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ORGANIZER):
            return True
        if EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ADMIN):
            return True
        # Trainee: allow only when creating for self (created_by_sub == caller's sub) and count is 1 or absent
        if not EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.TRAINEE):
            return False
        caller_sub = self._caller_sub(request)
        if not caller_sub:
            return False
        data = getattr(request, 'data', None) or {}
        if not isinstance(data, dict):
            return False
        created_by_sub = (data.get('created_by_sub') or '').strip()
        if created_by_sub != caller_sub:
            return False
        count_param = request.GET.get('count')
        if count_param is not None:
            try:
                if int(count_param) != 1:
                    return False
            except (ValueError, TypeError):
                return False
        return True

    @staticmethod
    def _caller_sub(request):
        if not request.user or not getattr(request.user, 'is_authenticated', False) or not request.user.is_authenticated:
            return None
        username = getattr(request.user, 'username', None) or ''
        if '|' in username:
            return username.split('|', 1)[0].strip()
        return username.strip() or None


class ListAllocationUnitsByCreatorForSelfOrOrganizerAdminPermission(permissions.BasePermission):
    """
    Allow GET to list sandbox allocation units by creator when:
    - caller has Organizer or Admin (any query), or
    - caller has Trainee and (created_by_sub is missing, or created_by_sub matches the caller's sub).
    Trainee may only list their own; we accept sub from username (sub|iss) or from JWT payload so we
    match what the training-service sends (JWT sub claim).
    """

    def has_permission(self, request, view):
        if not settings.CRCZP_SERVICE_CONFIG.authentication.authenticated_rest_api:
            return True
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            return False
        if EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ORGANIZER):
            return True
        if EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ADMIN):
            return True
        if not EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.TRAINEE):
            return False
        created_by_sub_raw = (request.query_params.get('created_by_sub') or '').strip()
        # Missing param: allow (view returns empty list)
        if not created_by_sub_raw:
            return True
        # Training-service URL-encodes the sub (e.g. @ -> %40); decode so it matches JWT sub
        created_by_sub_norm = str(unquote(created_by_sub_raw)).strip()
        caller_sub = CreateAllocationUnitForSelfOrOrganizerAdminPermission._caller_sub(request)
        if caller_sub and str(caller_sub).strip() == created_by_sub_norm:
            return True
        # Training-service forwards trainee JWT; sub may be string or number in payload
        jwt_sub = _sub_from_jwt_in_request(request)
        if jwt_sub and jwt_sub == created_by_sub_norm:
            return True
        return False


class RetrieveAllocationUnitForSelfOrOrganizerAdminPermission(permissions.BasePermission):
    """
    Allow GET to retrieve a sandbox allocation unit when:
    - caller has Organizer or Admin, or
    - caller has Trainee and (the unit's created_by_sub matches the JWT sub, OR the unit's pool is locked;
      used for managed instances where the unit was created by Admin and training-service needs to read it).
    Allow PATCH only for Organizer or Admin.
    """

    def has_permission(self, request, view):
        if not settings.CRCZP_SERVICE_CONFIG.authentication.authenticated_rest_api:
            return True
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return (
                EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ORGANIZER)
                or EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ADMIN)
                or EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.TRAINEE)
            )
        if request.method == 'PATCH':
            return (
                EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ORGANIZER)
                or EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ADMIN)
            )
        return False

    def has_object_permission(self, request, view, obj):
        if EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ORGANIZER):
            return True
        if EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ADMIN):
            return True
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            return False
        if not EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.TRAINEE):
            return False
        caller_sub = CreateAllocationUnitForSelfOrOrganizerAdminPermission._caller_sub(request)
        jwt_sub = _sub_from_jwt_in_request(request)
        unit_sub = (getattr(obj, 'created_by_sub', None) or '').strip()
        # Prefer JWT sub (same source training-service uses for created_by_sub); fallback to caller (username).
        effective_sub = (jwt_sub or caller_sub or '').strip()
        if effective_sub and unit_sub and str(unit_sub) == str(effective_sub):
            return True
        # Managed instance: unit was created by Admin; allow if the unit's pool is locked (training in progress).
        pool = getattr(obj, 'pool', None)
        if pool is None:
            return False
        lock = getattr(pool, 'lock', None)
        if lock is not None:
            return True
        # Deny with a distinct message so clients can tell "unlocked pool" from other permission errors.
        raise PermissionDenied(
            'Pool is not locked. Access is only allowed for your own allocations '
            'or when the pool is locked for a managed training instance.'
        )


class RetrieveSandboxForSelfOrOrganizerAdminPermission(permissions.BasePermission):
    """
    Allow GET to retrieve a sandbox (detail or topology) when:
    - caller has Organizer or Admin, or
    - caller has Trainee and (sandbox's allocation_unit.created_by_sub matches the JWT sub, OR
      the sandbox's pool is locked to a training and request has header X-Training-Access-Token matching that lock;
      used for managed instances where the sandbox was allocated by Admin).
    No extra config or outbound calls: the client only receives one sandbox id from the run response.
    """

    TRAINING_ACCESS_TOKEN_HEADER = 'X-Training-Access-Token'

    def has_permission(self, request, view):
        if not settings.CRCZP_SERVICE_CONFIG.authentication.authenticated_rest_api:
            return True
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            return False
        return (
            EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ORGANIZER)
            or EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ADMIN)
            or EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.TRAINEE)
        )

    def has_object_permission(self, request, view, obj):
        if EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ORGANIZER):
            return True
        if EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ADMIN):
            return True
        if not EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.TRAINEE):
            return False
        caller_sub = CreateAllocationUnitForSelfOrOrganizerAdminPermission._caller_sub(request)
        if not caller_sub:
            return False
        allocation_unit = getattr(obj, 'allocation_unit', None)
        if allocation_unit is None:
            return False
        unit_sub = (getattr(allocation_unit, 'created_by_sub', None) or '').strip()
        if unit_sub == caller_sub:
            return True
        # Managed instance: sandbox was allocated by Admin; allow if pool is locked to this training token.
        # The client only ever receives one sandbox id (from the run response), so no extra verification needed.
        token = (request.headers.get(self.TRAINING_ACCESS_TOKEN_HEADER) or '').strip()
        if not token:
            return False
        pool = getattr(allocation_unit, 'pool', None)
        if pool is None:
            return False
        lock = getattr(pool, 'lock', None)
        if lock is None:
            return False
        lock_token = (getattr(lock, 'training_access_token', None) or '').strip()
        return lock_token == token


class CreateCleanupRequestForSelfOrOrganizerAdminPermission(permissions.BasePermission):
    """
    Allow GET/POST/DELETE on sandbox-allocation-units/{id}/cleanup-request when:
    - caller has Organizer or Admin (any unit), or
    - caller has Trainee and the allocation unit's created_by_sub matches the JWT sub (request cleanup for own sandbox).
    """

    def has_permission(self, request, view):
        if not settings.CRCZP_SERVICE_CONFIG.authentication.authenticated_rest_api:
            return True
        if request.method not in ('GET', 'HEAD', 'OPTIONS', 'POST', 'DELETE'):
            return False
        return (
            EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ORGANIZER)
            or EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ADMIN)
            or EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.TRAINEE)
        )

    def has_object_permission(self, request, view, obj):
        if EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ORGANIZER):
            return True
        if EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.ADMIN):
            return True
        if not EndpointPermissionClass.has_access_level(request, EndpointPermissionClass.AccessLevel.TRAINEE):
            return False
        caller_sub = CreateAllocationUnitForSelfOrOrganizerAdminPermission._caller_sub(request)
        if not caller_sub:
            return False
        unit_sub = (getattr(obj, 'created_by_sub', None) or '').strip()
        return unit_sub == caller_sub
