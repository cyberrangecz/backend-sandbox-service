"""
REST API configuration file
"""
import os

from django.conf import settings
from kypo.openstack_driver.transformation_configuration import\
    TransformationConfiguration
from yamlize import Attribute, Object, YamlizingError

from kypo.sandbox_common_lib.exceptions import ImproperlyConfigured

CONFIG_FILE_VARIABLE = 'KYPO_DJANGO_OPENSTACK_CONFIG'

LOG_FILE = 'django-openstack.log'
LOG_LEVEL = 'INFO'
GIT_SERVER = 'gitlab.ics.muni.cz'
GIT_USER = 'git'
GIT_PRIVATE_KEY = os.path.expanduser('~/.ssh/git_rsa_key')
GIT_REPOSITORIES = '/tmp'
ANSIBLE_NETWORKING_REV = 'master'
SANDBOX_BUILD_TIMEOUT = 3600 * 2
SANDBOX_DELETE_TIMEOUT = 3600
SANDBOX_ANSIBLE_TIMEOUT = 3600 * 2
ANSIBLE_DOCKER_VOLUMES = '/tmp/kypo'
ANSIBLE_DOCKER_IMAGE = 'csirtmu/kypo-ansible-runner'
PROXY_JUMP_TO_MAN = None
SSL_CA_CERTIFICATE_VERIFY = ''


class ProxyJump(Object):
    Host = Attribute(type=str)
    User = Attribute(type=str)
    IdentityFile = Attribute(type=str)

    def __init__(self, host, user, identity_file):
        self.Host = host
        self.User = user
        self.IdentityFile = identity_file


class KypoConfiguration(Object):
    os_auth_url = Attribute(type=str)
    os_application_credential_id = Attribute(type=str)
    os_application_credential_secret = Attribute(type=str)

    log_file = Attribute(type=str, default=LOG_FILE)
    log_level = Attribute(type=str, default=LOG_LEVEL)

    # Sandbox creation configuration
    git_server = Attribute(type=str, default=GIT_SERVER)
    git_user = Attribute(type=str, default=GIT_USER)
    git_private_key = Attribute(type=str, default=GIT_PRIVATE_KEY)
    git_repositories = Attribute(type=str, default=GIT_REPOSITORIES)

    ansible_networking_url = Attribute(type=str)
    ansible_networking_rev = Attribute(type=str, default=ANSIBLE_NETWORKING_REV)

    proxy_jump_to_man = Attribute(type=ProxyJump, default=PROXY_JUMP_TO_MAN)

    sandbox_build_timeout = Attribute(type=int, default=SANDBOX_BUILD_TIMEOUT)
    sandbox_delete_timeout = Attribute(type=int, default=SANDBOX_DELETE_TIMEOUT)
    sandbox_ansible_timeout = Attribute(type=int, default=SANDBOX_ANSIBLE_TIMEOUT)

    ansible_docker_volumes = Attribute(type=str, default=ANSIBLE_DOCKER_VOLUMES)
    ansible_docker_image = Attribute(type=str, default=ANSIBLE_DOCKER_IMAGE)

    ssl_ca_certificate_verify = Attribute(type=str, default=SSL_CA_CERTIFICATE_VERIFY)

    trc = Attribute(type=TransformationConfiguration, key='sandbox_configuration')

    def __init__(self, **kwargs):
        for key, val in kwargs.items():
            setattr(self, key, val)

    # Override
    @classmethod
    def load(cls, *args, **kwargs) -> 'KypoConfiguration':
        """Factory method. Use it to create a new object of this class."""
        try:
            obj = super().load(*args, **kwargs)
        except YamlizingError as ex:
            raise ImproperlyConfigured(ex)
        os.environ['REQUESTS_CA_BUNDLE'] = obj.ssl_ca_certificate_verify
        return obj


class KypoConfigurationManager:
    """Lazy configuration loader and manager."""
    _config = None

    @classmethod
    def config(cls) -> KypoConfiguration:
        if not cls._config:
            with open(getattr(settings, CONFIG_FILE_VARIABLE)) as f:
                cls._config = KypoConfiguration.load(f)
        return cls._config
