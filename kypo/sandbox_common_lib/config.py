"""
REST API configuration file
"""
import os

from django.conf import settings
from kypo.openstack_driver.transformation_configuration import\
    TransformationConfiguration
from yamlize import Attribute, Object, YamlizingError

from .exceptions import ImproperlyConfigured

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
SSL_CA_CERTIFICATE_VERIFY = ''


# TODO maybe remove after yamlize hashing problems are resolved
class AttributeDict(Attribute):
    """Attribute subclass for (immutable!) dict since they are not hashable by default."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __hash__(self):
        return sum(hash(getattr(self, attr_name))
                   for attr_name in self.__class__.__slots__
                   if not isinstance(getattr(self, attr_name), dict))


class Settings(Object):
    os_auth_url = Attribute(type=str)
    os_application_credential_id = Attribute(type=str)
    os_application_credential_secret = Attribute(type=str)

    log_file = Attribute(type=str, default=LOG_FILE)
    log_level = Attribute(type=str, default=LOG_LEVEL)

    # Sandbox creation configuration
    git_server = Attribute(type=str, default=GIT_SERVER)
    git_user = Attribute(type=str, default=GIT_USER)
    git_private_key = Attribute(type=str, default=GIT_PRIVATE_KEY)
    git_reposotories = Attribute(type=str, default=GIT_REPOSITORIES)

    ansible_networking_url = Attribute(type=str)
    ansible_networking_rev = Attribute(type=str, default=ANSIBLE_NETWORKING_REV)

    proxy_jump_to_man = AttributeDict(type=dict, default={})

    sandbox_build_timeout = Attribute(type=int, default=SANDBOX_BUILD_TIMEOUT)
    sandbox_delete_timeout = Attribute(type=int, default=SANDBOX_DELETE_TIMEOUT)
    sandbox_ansible_timeout = Attribute(type=int, default=SANDBOX_ANSIBLE_TIMEOUT)

    ansible_docker_volumes = Attribute(type=str, default=ANSIBLE_DOCKER_VOLUMES)
    ansible_docker_image = Attribute(type=str, default=ANSIBLE_DOCKER_IMAGE)

    ssl_ca_certificate_verify = Attribute(type=str, default=SSL_CA_CERTIFICATE_VERIFY)

    trc = Attribute(type=TransformationConfiguration, key='sandbox_configuration')

    # Override
    @classmethod
    def load(cls, *args, **kwargs):
        """Factory method. Use it to create a new object of this class."""
        try:
            obj = super().load(*args, **kwargs)
        except YamlizingError as ex:
            raise ImproperlyConfigured(ex)
        os.environ['REQUESTS_CA_BUNDLE'] = obj.SSL_CA_CERTIFICATE_VERIFY
        return obj


with open(getattr(settings, CONFIG_FILE_VARIABLE)) as f:
    config = Settings.load(f)
