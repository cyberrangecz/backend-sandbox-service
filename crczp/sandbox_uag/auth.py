import hashlib
import json
import requests
import structlog
import yaml

from typing import List, Dict

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.cache import caches
from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed

from . import exceptions
from crczp.sandbox_uag.oidc_jwt import JWTAccessTokenAuthentication

LOG = structlog.get_logger()
authenticator_class = JWTAccessTokenAuthentication()

USER_CACHE_TIMEOUT = 300
CACHE = caches['uag_auth_groups_cache']
UAG_SETTINGS = settings.SANDBOX_UAG


def get_or_create_user(request, user_info):
    """
    Retrieve (or create if non-existent) user from database.
    Set corresponding roles (Django groups).

    :return: User instance
    """
    # noinspection PyPep8Naming
    bearer_token = authenticator_class.get_bearer_token(request)

    first_name = user_info.get('given_name')
    last_name = user_info.get('family_name')
    email = user_info.get('email')
    sub = user_info.get('sub')
    iss = authenticator_class.extract_issuer(bearer_token)

    # username should ALWAYS uniquely identify the user, which is possible only with {sub, iss} pair.
    # the limit for username is 140 characters so this may be a problem for long sub+iss
    username = get_unique_username(sub, iss)

    User = get_user_model()  # this is suggested way of getting User model
    (user, _) = User.objects.update_or_create(username=username, defaults={
        'first_name': first_name,
        'last_name': last_name,
        'email': email
    })

    cache_key = get_cache_key(username, bearer_token)

    cached_value = CACHE.get(cache_key)
    if cached_value is not None:
        (cached_groups, cached_bearer_token) = cached_value
        # if there is a key collision due to SHA-1 clash, this will detect it
        if cached_bearer_token == bearer_token:
            user.groups.set(cached_groups)
            return user

    try:
        user_roles = get_user_roles(UAG_SETTINGS['ROLES_ACQUISITION_URL'], bearer_token)
    except Exception as ex:
        raise AuthenticationFailed(str(ex)) from ex

    LOG.debug("roles:", user_roles=user_roles)
    groups = []
    for group_name in user_roles:
        # We work only with existing predefined groups.
        try:
            group = Group.objects.get(name=group_name)
        except Group.DoesNotExist as ex:
            raise AuthenticationFailed("User {} ({}) has role {}, that is not in database: {}".format(
                user.username, f'{sub},{iss}', group_name, str(ex)))
        groups.append(group)

    user.groups.set(groups)
    value_to_cache = (groups, bearer_token)
    CACHE.set(cache_key, value_to_cache, USER_CACHE_TIMEOUT)

    return user


def get_cache_key(username, bearer_token):
    # Cache key shouldn't be longer than 250 characters, so we need to shorten the bearer token.
    # Since there is a possibility of a hash collision, additional steps are needed after cache-hit.
    # In our case, we check if the bearer tokens actually match.
    hashed_bearer_token = hashlib.sha1(str(bearer_token).encode('UTF-8')).hexdigest()
    # 140 + 40 + 1 < 250
    return f'{username}|{hashed_bearer_token}'


def get_unique_username(sub, iss):
    return f'{str(sub)}|{str(iss)}'


def get_user_roles(url: str, bearer_token: bytes) -> List[str]:
    """Get user roles from User-and-group service."""
    err_msg = "Failed to get User roles from '{}': ".format(url)

    headers = {'Authorization': "Bearer {}".format(bearer_token.decode("ascii"))}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()

    # All request exceptions inherit from requests.RequestException
    except (ConnectionError, requests.RequestException) as ex:
        raise exceptions.NetworkError(err_msg + str(ex))

    try:
        user_roles = [role['role_type'] for role in response.json()['roles']
                      if role['name_of_microservice'] == UAG_SETTINGS['MICROSERVICE_NAME']]
    except ValueError as ex:
        raise ValueError(err_msg + "Invalid JSON returned.") from ex

    return user_roles


def post_user_roles(url: str = UAG_SETTINGS['ROLES_REGISTRATION_URL'],
                    roles_path: str = UAG_SETTINGS['ROLES_DEFINITION_PATH']) -> None:
    """Register roles (Django groups) to User-and-group service."""
    err_msg = "Failed to post User roles to '{}': ".format(url)

    roles = create_roles(roles_path)

    data = json.dumps(create_roles_post_data(roles), indent=2)
    headers = {"Content-Type": "application/json"}
    LOG.debug("Posting roles", data=data, headers=headers, url=url)
    try:
        response = requests.post(url, data=data, headers=headers)
        response.raise_for_status()

    # All request exceptions inherit from requests.RequestException
    except (ConnectionError, requests.RequestException) as ex:
        raise exceptions.NetworkError(err_msg + str(ex))

    LOG.info("Roles successfully posted", url=url)


def create_roles_post_data(roles: List[Dict]) -> Dict:
    """Create body for POST to User-and-group service."""
    return {
        'endpoint': UAG_SETTINGS['ENDPOINT'],
        'name': UAG_SETTINGS['MICROSERVICE_NAME'],
        'roles': [
            {'role_type': get_full_role_name(role['name']),
             'default': role['default']}
            for role in roles
        ]
    }


def create_roles(roles_path: str) -> List[Dict]:
    """Create roles (Django groups) and set permissions to them.
    Permissions MUST EXIST! Unlike groups which are created if do not exist.
    """
    with open(roles_path) as f:
        roles = yaml.full_load(f)
    for role in roles:
        (group, _) = Group.objects.get_or_create(name=get_full_role_name(role['name']))
        permissions = [
            Permission.objects.get(codename=name) for name in role['permissions']
        ]
        group.permissions.set(permissions)
    return roles


def get_full_role_name(name: str,
                       role_prefix: str = UAG_SETTINGS['ROLE_PREFIX'],
                       microservice_name: str = UAG_SETTINGS['MICROSERVICE_NAME'].upper()) -> str:
    """Return fully qualified role name."""
    return "{}_{}_{}".format(role_prefix.upper(),
                             microservice_name.upper(),
                             name.upper())
