"""
Django Apps configuration file
"""
import os
from enum import Enum

from kypo.cloud_commons import TransformationConfiguration
from yamlize import Attribute, Object, YamlizingError, Typed, Map

from kypo.sandbox_common_lib import kypo_config_validation
from kypo.sandbox_common_lib.exceptions import ImproperlyConfigured

KYPO_HEAD_IP = '0.0.0.0'
LOG_FILE = 'kypo-sandbox-service.log'
LOG_LEVEL = 'INFO'
GIT_TOKEN = '<default_token>'
GIT_SERVER = 'gitlab.com'
GIT_SSH_PORT = 22
GIT_REST_SERVER = 'https://gitlab.com/'
GIT_USER = 'git'
GIT_PRIVATE_KEY = os.path.expanduser('~/.ssh/git_rsa_key')
ANSIBLE_NETWORKING_REV = 'master'
SANDBOX_BUILD_TIMEOUT = 3600 * 2
SANDBOX_DELETE_TIMEOUT = 3600
SANDBOX_ANSIBLE_TIMEOUT = 3600 * 2
VOLUMES_PATH = '/tmp/kypo'
PERSISTENT_VOLUME_CLAIM_NAME = 'sandbox-service'
ANSIBLE_DOCKER_IMAGE = 'csirtmu/kypo-ansible-runner'
ANSIBLE_DOCKER_NETWORK = 'bridge'
ANSWERS_STORAGE_API = 'http://answers-storage:8087/kypo-answers-storage/api/v1'
SSL_CA_CERTIFICATE_VERIFY = '/etc/ssl/certs'
DATABASE_ENGINE = "django.db.backends.postgresql"
DATABASE_HOST = "localhost"
DATABASE_NAME = "postgres"
DATABASE_PASSWORD = "postgres"
DATABASE_PORT = "5432"
DATABASE_USER = "postgres"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_TIMEOUT = 86400 * 30


class ProxyJump(Object):
    Host = Attribute(type=str)
    User = Attribute(type=str)
    IdentityFile = Attribute(type=str)

    def __init__(self, host, user, identity_file):
        self.Host = host
        self.User = user
        self.IdentityFile = identity_file


class TerraformConfiguration(Object):
    backend_type = Attribute(type=str)


class AnsibleRunnerSettings(Object):
    backend = Attribute(type=str, default='docker')
    namespace = Attribute(type=str, default='kypo')
    volumes_path = Attribute(type=str, default=VOLUMES_PATH)
    persistent_volume_claim_name = Attribute(type=str, default=PERSISTENT_VOLUME_CLAIM_NAME)


class Database(Object):
    engine = Attribute(type=str, default=DATABASE_ENGINE)
    host = Attribute(type=str, default=DATABASE_HOST)
    name = Attribute(type=str, default=DATABASE_NAME)
    password = Attribute(type=str, default=DATABASE_PASSWORD)
    port = Attribute(type=str, default=DATABASE_PORT)
    user = Attribute(type=str, default=DATABASE_USER)

    def __init__(self, **kwargs):
        for key, val in kwargs.items():
            setattr(self, key, val)


class Redis(Object):
    host = Attribute(type=str, default=REDIS_HOST)
    port = Attribute(type=int, default=REDIS_PORT)
    db = Attribute(type=int, default=REDIS_DB)
    default_cache_timeout = Attribute(type=int, default=REDIS_TIMEOUT)
    uag_cache_timeout = Attribute(type=int, default=REDIS_TIMEOUT)
    topology_cache_timeout = Attribute(type=int, default=REDIS_TIMEOUT)


class GitType(Enum):
    GITLAB = 1
    INTERNAL = 2  # DEPRECATED


class OpenStackConsoleType(Enum):
    NOVNC = 'novnc'
    XVPVNC = 'xvpvnc'
    SPICE_HTML5 = 'spice-html5'
    RDP_HTML5 = 'rdp-html5'
    SERIAL = 'serial'
    WEBMKS = 'webmks'

    @classmethod
    def create(cls, value: str) -> None:
        try:
            return cls[value.upper().replace('-', '_')]
        except KeyError:
            raise ValueError(f'Invalid value for OpenStackConsoleType: {value}')


class NamingStrategy(Object):
    pattern = Attribute(type=str)
    replace = Attribute(type=str, default='')


class FlavorMapping(Map):
    key_type = Typed(str)
    value_type = Typed(str)


class GitProviders(Map):
    key_type = Typed(str)
    value_type = Typed(str)


class KypoConfiguration(Object):
    kypo_head_ip = Attribute(type=str, default=KYPO_HEAD_IP,
                             validator=kypo_config_validation.validate_kypo_head_ip)

    os_auth_url = Attribute(type=str)
    os_application_credential_id = Attribute(type=str)
    os_application_credential_secret = Attribute(type=str)
    os_console_type = Attribute(
        type=Typed(
            OpenStackConsoleType,
            from_yaml=(lambda loader, node, _:
                       OpenStackConsoleType.create(loader.construct_object(node))),
            to_yaml=(lambda dumper, data, rtd: dumper.represent_data(data.name)),
        ),
        default=OpenStackConsoleType.SPICE_HTML5,
    )

    log_file = Attribute(type=str, default=LOG_FILE)
    log_level = Attribute(type=str, default=LOG_LEVEL)

    # Sandbox creation configuration
    git_user = Attribute(type=str, default=GIT_USER)
    git_providers = Attribute(type=GitProviders, default=GitProviders())

    # Deprecated git values
    git_access_token = Attribute(type=str, default=GIT_TOKEN)
    git_server = Attribute(type=str, default=GIT_SERVER)
    git_ssh_port = Attribute(type=int, default=GIT_SSH_PORT)
    git_rest_server = Attribute(type=str, default=GIT_REST_SERVER,
                                validator=kypo_config_validation.validate_git_rest_url)
    git_private_key = Attribute(type=str, default=GIT_PRIVATE_KEY)
    git_type = Attribute(
        type=Typed(
            GitType,
            from_yaml=(lambda loader, node, rtd: GitType[loader.construct_object(node)]),
            to_yaml=(lambda dumper, data, rtd: dumper.represent_data(data.name))
        ),
        default=GitType.GITLAB
    )

    ansible_networking_url = Attribute(type=str)
    ansible_networking_rev = Attribute(type=str, default=ANSIBLE_NETWORKING_REV)

    image_naming_strategy = Attribute(type=NamingStrategy, default=None)
    flavor_mapping = Attribute(type=FlavorMapping, default=None)

    proxy_jump_to_man = Attribute(type=ProxyJump)
    terraform_configuration = Attribute(type=TerraformConfiguration)
    database = Attribute(type=Database)
    redis = Attribute(type=Redis, default=())

    sandbox_build_timeout = Attribute(type=int, default=SANDBOX_BUILD_TIMEOUT)
    sandbox_delete_timeout = Attribute(type=int, default=SANDBOX_DELETE_TIMEOUT)
    sandbox_ansible_timeout = Attribute(type=int, default=SANDBOX_ANSIBLE_TIMEOUT)

    ansible_docker_image = Attribute(type=str, default=ANSIBLE_DOCKER_IMAGE)
    ansible_docker_network = Attribute(type=str, default=ANSIBLE_DOCKER_NETWORK)

    ansible_runner_settings = Attribute(type=AnsibleRunnerSettings, default=AnsibleRunnerSettings())

    answers_storage_api = Attribute(type=str, default=ANSWERS_STORAGE_API)

    ssl_ca_certificate_verify = Attribute(type=str, default=SSL_CA_CERTIFICATE_VERIFY)

    trc = Attribute(type=TransformationConfiguration, key='sandbox_configuration')

    # Email allocation notifications
    smtp_server = Attribute(type=str, default=None)
    # Port of the used encryption protocol, ex. ssl, tsl
    smtp_port = Attribute(type=int, default=25)
    sender_email = Attribute(type=str, default="sandbox.service@kypo.cz")
    sender_email_password = Attribute(type=str, default=None)

    def __init__(self, **kwargs):
        for key, val in kwargs.items():
            setattr(self, key, val)

    # TODO get rid of this horror
    # Override
    @classmethod
    def load(cls, *args, **kwargs) -> 'KypoConfiguration':
        """Factory method. Use it to create a new object of this class."""
        try:
            obj = super().load(*args, **kwargs)
        except YamlizingError as ex:
            raise ImproperlyConfigured(ex)

        # TODO deal with absolute paths in ProxyJump object validation
        # Key-paths need to be absolute
        obj.proxy_jump_to_man.IdentityFile = os.path.abspath(
            os.path.expanduser(obj.proxy_jump_to_man.IdentityFile))

        # TODO move this somewhere
        os.environ['REQUESTS_CA_BUNDLE'] = obj.ssl_ca_certificate_verify
        return obj

    @classmethod
    def from_file(cls, path):
        with open(path) as f:
            return cls.load(f)
