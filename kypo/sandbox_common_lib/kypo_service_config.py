"""
REST API configuration file
"""
from yamlize import Attribute, Object, YamlizingError, StrList

from kypo.sandbox_common_lib.exceptions import ImproperlyConfigured
from kypo.sandbox_common_lib.kypo_config import KypoConfiguration

STACK_NAME_PREFIX = 'default-prefix-0'
MICROSERVICE_NAME = 'kypo-sandbox-service'
DEBUG = True
ALLOWED_HOSTS = ('*',)  # Allow everyone
CORS_ORIGIN_ALLOW_ALL = True
CORS_ORIGIN_WHITELIST = ()
AUTHENTICATED_REST_API = False
ALLOWED_OIDC_PROVIDERS = tuple()


class Authentication(Object):
    authenticated_rest_api = Attribute(type=bool, default=AUTHENTICATED_REST_API)
    allowed_oidc_providers = Attribute(type=StrList, default=ALLOWED_OIDC_PROVIDERS)
    roles_registration_url = Attribute(type=str)
    roles_acquisition_url = Attribute(type=str)

    def __init__(self, authenticated_rest_api, allowed_oidc_providers,
                 roles_registration_url, roles_acquisition_url):
        self.authenticated_rest_api = authenticated_rest_api
        self.allowed_oidc_providers = allowed_oidc_providers
        self.roles_registration_url = roles_registration_url
        self.roles_acquisition_url = roles_acquisition_url


class KypoServiceConfig(Object):
    stack_name_prefix = Attribute(type=str, default=STACK_NAME_PREFIX)
    microservice_name = Attribute(type=str, default=MICROSERVICE_NAME)
    debug = Attribute(type=bool, default=DEBUG)
    allowed_hosts = Attribute(type=StrList, default=ALLOWED_HOSTS)
    cors_origin_allow_all = Attribute(type=bool, default=CORS_ORIGIN_ALLOW_ALL)
    cors_origin_whitelist = Attribute(type=StrList, default=CORS_ORIGIN_WHITELIST)

    authentication = Attribute(type=Authentication)
    app_config = Attribute(type=KypoConfiguration, key='application_configuration')

    def __init__(self, **kwargs):
        for key, val in kwargs.items():
            setattr(self, key, val)

    # Override
    @classmethod
    def load(cls, *args, **kwargs) -> 'KypoServiceConfig':
        """Factory method. Use it to create a new object of this class."""
        try:
            obj = super().load(*args, **kwargs)
        except YamlizingError as ex:
            raise ImproperlyConfigured(ex)
        return obj

    @classmethod
    def from_file(cls, path):
        with open(path) as f:
            return cls.load(f)
