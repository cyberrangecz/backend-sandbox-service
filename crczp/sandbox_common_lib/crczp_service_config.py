"""
REST API configuration file
"""

from yamlize import Attribute, Object, Sequence, StrList, Typed, YamlizingError

from crczp.sandbox_common_lib.crczp_config import CrczpConfiguration
from crczp.sandbox_common_lib.exceptions import ImproperlyConfigured

# StrList default value must be cast to tuple, otherwise
# TypeError: unhashable type: 'list' will be thrown

STACK_NAME_PREFIX = 'default0'
MICROSERVICE_NAME = 'sandbox-service'
DEBUG = True
DJANGO_SECRET_KEY = '-^mu0=6s@*x4jdbrz5yr!++p*02#%m$_4&0uw8h1)&r5u!v=12'
ALLOWED_HOSTS = ['*']  # Allow everyone
CORS_ORIGIN_ALLOW_ALL = True
CORS_ORIGIN_WHITELIST = []
AUTHENTICATED_REST_API = False
ALLOWED_OIDC_PROVIDERS = []


def stack_name_prefix_validator(_, value):
    """Validate that stack_name_prefix is between 1 and 8 characters long."""
    if len(value) < 1 or len(value) > 8:
        raise ValueError('Value stack_name_prefix can have only 1 to 8 characters')


class AllowedOidcProviders(Sequence):
    """Sequence type for allowed OIDC provider configurations."""

    item_type = Typed(dict)


class Authentication(Object):
    """Authentication configuration for the sandbox service."""

    authenticated_rest_api = Attribute(type=bool, default=AUTHENTICATED_REST_API)
    allowed_oidc_providers = Attribute(
        type=AllowedOidcProviders, default=tuple(ALLOWED_OIDC_PROVIDERS)
    )
    roles_registration_url = Attribute(type=str)
    roles_acquisition_url = Attribute(type=str)

    def __init__(
        self,
        authenticated_rest_api,
        allowed_oidc_providers,
        roles_registration_url,
        roles_acquisition_url,
    ):
        self.authenticated_rest_api = authenticated_rest_api
        self.allowed_oidc_providers = allowed_oidc_providers
        self.roles_registration_url = roles_registration_url
        self.roles_acquisition_url = roles_acquisition_url


class CrczpServiceConfig(Object):
    """Top-level service configuration combining Django and app settings."""

    stack_name_prefix = Attribute(
        type=str, default=STACK_NAME_PREFIX, validator=stack_name_prefix_validator
    )
    microservice_name = Attribute(type=str, default=MICROSERVICE_NAME)
    debug = Attribute(type=bool, default=DEBUG)
    django_secret_key = Attribute(type=str, default=DJANGO_SECRET_KEY)
    allowed_hosts = Attribute(type=StrList, default=tuple(ALLOWED_HOSTS))
    cors_origin_allow_all = Attribute(type=bool, default=CORS_ORIGIN_ALLOW_ALL)
    cors_origin_whitelist = Attribute(type=StrList, default=tuple(CORS_ORIGIN_WHITELIST))

    authentication = Attribute(type=Authentication)
    app_config = Attribute(type=CrczpConfiguration, key='application_configuration')

    def __init__(self, **kwargs):
        for key, val in kwargs.items():
            setattr(self, key, val)

    # Override
    @classmethod
    def load(cls, *args, **kwargs) -> 'CrczpServiceConfig':
        """Factory method. Use it to create a new object of this class."""
        try:
            obj = super().load(*args, **kwargs)
        except YamlizingError as ex:
            raise ImproperlyConfigured(ex) from ex
        return obj

    @classmethod
    def from_file(cls, path):
        """Load service configuration from a YAML file."""
        with open(path, encoding='utf-8') as f:
            return cls.load(f)
