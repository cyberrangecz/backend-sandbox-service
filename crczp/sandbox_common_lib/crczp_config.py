"""
Django Apps configuration file
"""

import os
from enum import Enum
from typing import Any, cast

from yamlize import Attribute, Map, Object, Typed, YamlizingError

from crczp.cloud_commons import TransformationConfiguration
from crczp.sandbox_common_lib import crczp_config_validation
from crczp.sandbox_common_lib.exceptions import ImproperlyConfigured

HEAD_IP = '0.0.0.0'  # nosec B104
LOG_FILE = 'sandbox-service.log'
LOG_LEVEL = 'INFO'
GIT_TOKEN = '<default_token>'  # nosec B105
GIT_SERVER = 'gitlab.com'
GIT_SSH_PORT = 22
GIT_REST_SERVER = 'https://gitlab.com/'
GIT_USER = 'git'
GIT_PRIVATE_KEY = os.path.expanduser('~/.ssh/git_rsa_key')
ANSIBLE_NETWORKING_REV = 'master'
SANDBOX_BUILD_TIMEOUT = 3600 * 2
SANDBOX_DELETE_TIMEOUT = 3600
SANDBOX_ANSIBLE_TIMEOUT = 3600 * 2
VOLUMES_PATH = '/tmp/crczp'  # nosec B108
PERSISTENT_VOLUME_CLAIM_NAME = 'sandbox-service'
ANSIBLE_DOCKER_IMAGE = 'ghcr.io/cyberrangecz/crczp-ansible-runner:1.4.1'
ANSIBLE_DOCKER_NETWORK = 'bridge'
ANSWERS_STORAGE_API = 'http://answers-storage:8087/answers-storage/api/v1'
SSL_CA_CERTIFICATE_VERIFY = '/etc/ssl/certs'
DATABASE_ENGINE = 'django.db.backends.postgresql'
DATABASE_HOST = 'localhost'
DATABASE_NAME = 'postgres'
DATABASE_PASSWORD = 'postgres'  # nosec B105
DATABASE_PORT = '5432'
DATABASE_USER = 'postgres'
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_TIMEOUT = 86400 * 30


class ProxyJump(Object):  # type: ignore[misc]
    """SSH ProxyJump configuration for connecting to managed nodes."""

    # pylint: disable=invalid-name
    Host = Attribute(type=str)
    User = Attribute(type=str)
    Port = Attribute(type=int, default=22)
    IdentityFile = Attribute(type=str)

    def __init__(self, host: str, user: str, identity_file: str, port: int = 22) -> None:
        self.Host = host
        self.User = user
        self.Port = port
        self.IdentityFile = identity_file


class TerraformConfiguration(Object):  # type: ignore[misc]
    """Terraform backend configuration settings."""

    backend_type = Attribute(type=str)


class AnsibleRunnerSettings(Object):  # type: ignore[misc]
    """Settings for the Ansible runner backend (Docker or Kubernetes)."""

    backend = Attribute(type=str, default='docker')
    namespace = Attribute(type=str, default='crczp')
    volumes_path = Attribute(type=str, default=VOLUMES_PATH)
    persistent_volume_claim_name = Attribute(type=str, default=PERSISTENT_VOLUME_CLAIM_NAME)


class Database(Object):  # type: ignore[misc]
    """Database connection configuration."""

    engine = Attribute(type=str, default=DATABASE_ENGINE)
    host = Attribute(type=str, default=DATABASE_HOST)
    name = Attribute(type=str, default=DATABASE_NAME)
    password = Attribute(type=str, default=DATABASE_PASSWORD)
    port = Attribute(type=str, default=DATABASE_PORT)
    user = Attribute(type=str, default=DATABASE_USER)

    def __init__(self, **kwargs: Any) -> None:
        for key, val in kwargs.items():
            setattr(self, key, val)


class Redis(Object):  # type: ignore[misc]
    """Redis connection and cache timeout configuration."""

    host = Attribute(type=str, default=REDIS_HOST)
    port = Attribute(type=int, default=REDIS_PORT)
    db = Attribute(type=int, default=REDIS_DB)
    default_cache_timeout = Attribute(type=int, default=REDIS_TIMEOUT)
    uag_cache_timeout = Attribute(type=int, default=REDIS_TIMEOUT)
    topology_cache_timeout = Attribute(type=int, default=REDIS_TIMEOUT)


class GitType(Enum):
    """Supported Git provider types."""

    GITLAB = 1
    INTERNAL = 2  # DEPRECATED
    GITHUB = 3


class OpenStackConsoleType(Enum):
    """Supported OpenStack console types."""

    NOVNC = 'novnc'
    XVPVNC = 'xvpvnc'
    SPICE_HTML5 = 'spice-html5'
    RDP_HTML5 = 'rdp-html5'
    SERIAL = 'serial'
    WEBMKS = 'webmks'

    @classmethod
    def create(cls, value: str) -> 'OpenStackConsoleType':
        """Create an OpenStackConsoleType from a string value."""
        try:
            return cls[value.upper().replace('-', '_')]
        except KeyError:
            raise ValueError(f'Invalid value for OpenStackConsoleType: {value}') from None


class AwsConfiguration(Object):  # type: ignore[misc]
    """AWS cloud provider configuration."""

    access_key_id = Attribute(type=str, default='')
    secret_access_key = Attribute(type=str, default='')
    region = Attribute(type=str, default='')
    availability_zone = Attribute(type=str, default='')
    base_vpc = Attribute(type=str, default='Base VPC')
    base_subnet = Attribute(type=str, default='Base Subnet')


class NamingStrategy(Object):  # type: ignore[misc]
    """Naming strategy for OpenStack resource names."""

    pattern = Attribute(type=str)
    replace = Attribute(type=str, default='')


class FlavorMapping(Map):  # type: ignore[misc]
    """Mapping from sandbox flavor keys to OpenStack flavor names."""

    key_type = Typed(str)
    value_type = Typed(str)


class GitProviders(Map):  # type: ignore[misc]
    """Mapping from Git server base URLs to access tokens."""

    key_type = Typed(str)
    value_type = Typed(str)


class SMTPEncryption(Enum):
    """Supported SMTP encryption modes."""

    TSL = 1
    SSL = 2
    INSECURE = 3


class NetbirdConfiguration(Object):  # type: ignore[misc]
    """NetBird VPN management configuration."""

    management_url = Attribute(type=str)
    client_management_url = Attribute(type=str, default=None)
    # Path to a file containing the service user PAT. The file is read fresh on
    # every Netbird client creation so a rotated secret (e.g. a volume-mounted
    # Kubernetes Secret) is picked up without restarting the service.
    service_user_pat_file = Attribute(type=str)
    key_expiry_seconds = Attribute(
        type=int, default=1209600, validator=crczp_config_validation.validate_netbird_key_expiry
    )
    # Upper bound (seconds) on the time spent tearing down a single sandbox's
    # Netbird resources during cleanup. Teardown runs synchronously in the
    # request thread, so a slow or unreachable Netbird endpoint must not block
    # the cleanup path indefinitely; once the budget is exceeded the remaining
    # resources are left behind (best-effort teardown).
    teardown_budget_seconds = Attribute(type=int, default=60)


class TopologyCacheMode(Enum):
    """How GitHub sandbox-definition topology is cached (GitHub provider only)."""

    AGGRESSIVE = 1  # cache key stable per branch; topology served until TTL expires
    FRESH = 2  # resolve branch HEAD to commit SHA; cache key tracks the branch
    FRESH_IMPORT = 3  # branch-keyed cache, but (re)import bypasses the cache and refreshes it

    @classmethod
    def create(cls, value: str) -> 'TopologyCacheMode':
        """Create a TopologyCacheMode from a string value."""
        try:
            return cls[value.upper().replace('-', '_')]
        except KeyError:
            valid = ', '.join(mode.name for mode in cls)
            raise ValueError(
                f'Invalid value for topology_cache_mode: {value}. Expected one of: {valid}.'
            ) from None


class CrczpConfiguration(Object):  # type: ignore[misc]
    """Top-level CRCZP application configuration loaded from a YAML file."""

    head_host = Attribute(type=str, default=HEAD_IP)
    syslog_destination_port = Attribute(type=int, default=515)

    os_auth_url = Attribute(type=str, default=None)
    os_application_credential_id = Attribute(type=str, default=None)
    os_application_credential_secret = Attribute(type=str, default=None)
    os_console_type = Attribute(
        type=Typed(
            OpenStackConsoleType,
            from_yaml=(
                lambda loader, node, _: OpenStackConsoleType.create(loader.construct_object(node))
            ),
            to_yaml=(lambda dumper, data, rtd: dumper.represent_data(data.name)),
        ),
        default=OpenStackConsoleType.SPICE_HTML5,
    )

    aws = Attribute(type=AwsConfiguration, default=None)

    log_file = Attribute(type=str, default=LOG_FILE)
    log_level = Attribute(type=str, default=LOG_LEVEL)

    man_port = Attribute(type=int, default=4822)

    # Sandbox creation configuration
    git_user = Attribute(type=str, default=GIT_USER)
    git_providers = Attribute(type=GitProviders, default=GitProviders())

    # Deprecated git values
    git_access_token = Attribute(type=str, default=GIT_TOKEN)
    git_server = Attribute(type=str, default=GIT_SERVER)
    git_ssh_port = Attribute(type=int, default=GIT_SSH_PORT)
    git_rest_server = Attribute(
        type=str, default=GIT_REST_SERVER, validator=crczp_config_validation.validate_git_rest_url
    )
    git_private_key = Attribute(type=str, default=GIT_PRIVATE_KEY)
    git_type = Attribute(
        type=Typed(
            GitType,
            from_yaml=(lambda loader, node, rtd: GitType[loader.construct_object(node)]),
            to_yaml=(lambda dumper, data, rtd: dumper.represent_data(data.name)),
        ),
        default=GitType.GITLAB,
    )

    git_skip_ssl_verification = Attribute(type=bool, default=False)

    topology_cache_mode = Attribute(
        type=Typed(
            TopologyCacheMode,
            from_yaml=(
                lambda loader, node, rtd: TopologyCacheMode.create(loader.construct_object(node))
            ),
            to_yaml=(lambda dumper, data, rtd: dumper.represent_data(data.name)),
        ),
        default=TopologyCacheMode.AGGRESSIVE,
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
    smtp_encryption = Attribute(
        type=Typed(
            SMTPEncryption,
            from_yaml=(lambda loader, node, rtd: SMTPEncryption[loader.construct_object(node)]),
            to_yaml=(lambda dumper, data, rtd: dumper.represent_data(data.name)),
        ),
        default=SMTPEncryption.INSECURE,
    )

    sender_email = Attribute(type=str, default='sandbox.service@cyberrange.cz')
    sender_email_password = Attribute(type=str, default=None)

    netbird = Attribute(type=NetbirdConfiguration, default=None)

    def __init__(self, **kwargs: Any) -> None:
        for key, val in kwargs.items():
            setattr(self, key, val)

    # Note: overrides yamlize Object.load to add error handling
    # Override
    @classmethod
    def load(cls, *args: Any, **kwargs: Any) -> 'CrczpConfiguration':
        """Factory method. Use it to create a new object of this class."""
        try:
            obj = super().load(*args, **kwargs)
        except YamlizingError as ex:
            raise ImproperlyConfigured(ex) from ex

        # Note: absolute paths required for ProxyJump IdentityFile
        # Key-paths need to be absolute
        obj.proxy_jump_to_man.IdentityFile = os.path.abspath(
            os.path.expanduser(obj.proxy_jump_to_man.IdentityFile)
        )

        # Note: set REQUESTS_CA_BUNDLE for SSL verification
        os.environ['REQUESTS_CA_BUNDLE'] = obj.ssl_ca_certificate_verify
        return cast('CrczpConfiguration', obj)

    @classmethod
    def from_file(cls, path: str) -> 'CrczpConfiguration':
        """Load configuration from a YAML file at the given path."""
        with open(path, encoding='utf-8') as f:
            return cls.load(f)
