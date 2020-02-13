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


class AttributeDict(Attribute):
    """Attribute subclass for (immutable!) dict since they are not hashable by default."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __hash__(self):
        return sum(hash(getattr(self, attr_name))
                   for attr_name in self.__class__.__slots__
                   if not isinstance(getattr(self, attr_name), dict))


class Settings(Object):
    OPENSTACK_QUEUE = 'openstack'
    ANSIBLE_QUEUE = 'ansible'
    MNG_PRIVATE_KEY_FILENAME = 'pool_mng_key'
    ANSIBLE_DOCKER_WORKING_DIR = '/app'
    ANSIBLE_DOCKER_VOLUMES_MAPPING = {
        'SSH_DIR': {
            'bind': '/root/.ssh',
            'mode': 'rw'
        },
        'INVENTORY_PATH': {
            'bind': os.path.join(ANSIBLE_DOCKER_WORKING_DIR, 'inventory.yml'),
            'mode': 'ro'
        },
        'LOCAL_REPO': {
            'bind': 'path',
            'mode': 'ro'
        }
    }

    OS_AUTH_URL = Attribute(type=str)
    OS_APPLICATION_CREDENTIAL_ID = Attribute(type=str)
    OS_APPLICATION_CREDENTIAL_SECRET = Attribute(type=str)

    LOG_FILE = Attribute(type=str, default=LOG_FILE)
    LOG_LEVEL = Attribute(type=str, default=LOG_LEVEL)

    # Sandbox creation configuration
    GIT_SERVER = Attribute(type=str, default=GIT_SERVER)
    GIT_USER = Attribute(type=str, default=GIT_USER)
    GIT_PRIVATE_KEY = Attribute(type=str, default=GIT_PRIVATE_KEY)
    GIT_REPOSITORIES = Attribute(type=str, default=GIT_REPOSITORIES)

    ANSIBLE_NETWORKING_URL = Attribute(type=str)
    ANSIBLE_NETWORKING_REV = Attribute(type=str, default=ANSIBLE_NETWORKING_REV)

    PROXY_JUMP_TO_MAN_SSH_OPTIONS = AttributeDict(type=dict, default={})

    SANDBOX_BUILD_TIMEOUT = Attribute(type=int, default=SANDBOX_BUILD_TIMEOUT)
    SANDBOX_DELETE_TIMEOUT = Attribute(type=int, default=SANDBOX_DELETE_TIMEOUT)
    SANDBOX_ANSIBLE_TIMEOUT = Attribute(type=int, default=SANDBOX_ANSIBLE_TIMEOUT)

    ANSIBLE_DOCKER_VOLUMES = Attribute(type=str, default=ANSIBLE_DOCKER_VOLUMES)
    ANSIBLE_DOCKER_IMAGE = Attribute(type=str, default=ANSIBLE_DOCKER_IMAGE)

    SSL_CA_CERTIFICATE_VERIFY = Attribute(type=str, default='')

    TRC = Attribute(type=TransformationConfiguration, key='SANDBOX_CONFIGURATION')

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
