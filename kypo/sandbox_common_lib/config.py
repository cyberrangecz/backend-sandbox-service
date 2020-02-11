"""
REST API configuration file
"""
import logging
import os

import yaml
from django.conf import settings
from kypo.openstack_driver.transformation_configuration import TransformationConfiguration

from .exceptions import ImproperlyConfigured


class Settings:
    """
    Container of kypo2-django-openstack configuration.
    """
    config_filename = None
    config_file_variable_name = 'KYPO_DJANGO_OPENSTACK_CONFIG'

    PROJECT_NAME = 'kypo-sandbox-service'

    VERSION = "v1"
    MAX_SANDBOXES_PER_POOL = 64
    ANSIBLE_OUTPUT_COUNT_LIMIT = 5000
    SSH_PROXY_USERNAME = "user-access"

    OPENSTACK_QUEUE = "openstack"
    ANSIBLE_QUEUE = "ansible"

    ANSIBLE_INVENTORY_FILENAME = 'inventory.yml'
    USER_PRIVATE_KEY_FILENAME = 'user_key'
    USER_PUBLIC_KEY_FILENAME = 'user_key.pub'
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

    UAN_NETWORK_NAME = "uan-network"
    BR_NETWORK_NAME = "br-network"

    def _get_required_attribute(self, configuration, key):
        """
        Retrieve value from configuration dict and raise exception if it does not exist.

        :param configuration: Configuration as a dict object
        :param key: Key of the value
        :return: Requested value
        :raise: exceptions.ImproperlyConfigured
        """
        if key not in configuration or configuration[key] is None:
            raise ImproperlyConfigured('Required setting {0} is missing in your \'{1}\' file.'
                                       .format(key, self.config_filename))
        return configuration[key]

    def __init__(self):
        try:
            self.config_filename = getattr(settings, self.config_file_variable_name)
        except AttributeError:
            raise ImproperlyConfigured('Required setting {0} is missing in your \'settings.py\' file.'
                                       .format(self.config_file_variable_name))
        try:
            with open(self.config_filename) as file:
                configuration = yaml.full_load(file)
        except OSError:
            raise ImproperlyConfigured('Configuration file \'{0}\' does not exist'.format(self.config_filename))

        self.OS_CREDENTIALS = {
            'auth_url': self._get_required_attribute(configuration, 'OS_AUTH_URL'),
            'app_creds_id': self._get_required_attribute(configuration, 'OS_APPLICATION_CREDENTIAL_ID'),
            'app_creds_secret': self._get_required_attribute(configuration, 'OS_APPLICATION_CREDENTIAL_SECRET'),
        }

        self.URL_PREFIX = "{PROJECT_NAME}/api/{VERSION}/".format(
            PROJECT_NAME=self.PROJECT_NAME.replace("_", "-"),  # URLs should use dashes, not underscores
            VERSION=self.VERSION)

        self.LOG_FILE = configuration.get('LOG_FILE', 'django-openstack.log')
        self.LOG_LEVEL = logging.getLevelName(configuration.get('LOG_LEVEL', 'INFO'))

        self.MAN_USERNAME = configuration.get('MAN_USERNAME', 'root')
        self.PROXY_JUMP_TO_MAN_SSH_OPTIONS = configuration.get('PROXY_JUMP_TO_MAN_SSH_OPTIONS', None)
        self.PROXY_JUMP_TO_MAN_PRIVATE_KEY = os.path.expanduser(configuration.get('PROXY_JUMP_TO_MAN_PRIVATE_KEY',
                                                                                  '~/.ssh/id_rsa'))

        # Timeouts
        self.SANDBOX_BUILD_TIMEOUT = configuration.get('SANDBOX_BUILD_TIMEOUT', 3600 * 2)
        self.SANDBOX_DELETE_TIMEOUT = configuration.get('SANDBOX_DELETE_TIMEOUT', 3600)
        self.SANDBOX_ANSIBLE_TIMEOUT = configuration.get('SANDBOX_ANSIBLE_TIMEOUT', 3600 * 2)

        # Sandbox definition configuration
        self.GIT_SERVER = configuration.get('GIT_SERVER', 'gitlab.ics.muni.cz')
        self.GIT_USER = configuration.get('GIT_USER', 'git')
        self.GIT_PRIVATE_KEY = os.path.expanduser(configuration.get('GIT_PRIVATE_KEY', '~/.ssh/git_rsa_key'))
        self.GIT_REPOSITORIES = configuration.get('GIT_REPOSITORIES', '/tmp')
        self.SANDBOX_DEFINITION_FILENAME = configuration.get('SANDBOX_DEFINITION_FILENAME', 'sandbox.yml')
        self.ANSIBLE_DIRECTORY_PATH = configuration.get('ANSIBLE_DIRECTORY_PATH', 'provisioning')
        self.ANSIBLE_PLAYBOOK_FILENAME = configuration.get('ANSIBLE_PLAYBOOK_FILENAME', 'playbook.yml')
        self.ANSIBLE_REQUIREMENTS_FILENAME = configuration.get('ANSIBLE_REQUIREMENTS_FILENAME', 'requirements.yml')

        self.ANSIBLE_NETWORKING_URL = self._get_required_attribute(configuration, 'ANSIBLE_NETWORKING_URL')
        self.ANSIBLE_NETWORKING_REV = configuration.get('ANSIBLE_NETWORKING_REV', 'master')

        # Docker
        self.ANSIBLE_DOCKER_VOLUMES = configuration.get('ANSIBLE_DOCKER_VOLUMES', '/tmp/kypo')
        self.ANSIBLE_DOCKER_IMAGE = configuration.get('ANSIBLE_DOCKER_IMAGE', 'csirtmu/kypo-ansible-runner')

        # Authentication configuration
        self.SSL_CA_CERTIFICATE_VERIFY = configuration.get('SSL_CA_CERTIFICATE_VERIFY', "")

        self.trc = TransformationConfiguration(**{
            'base_network': configuration.get('BASE_NETWORK', 'base_network'),
            'sb_man_cidr': configuration.get('SANDBOX_MNG_CIDR', '192.168.128.0/17'),
            'sb_uan_cidr': configuration.get('SANDBOX_UAN_CIDR', '192.168.0.0/28'),
            'sb_br_cidr': configuration.get('SANDBOX_BR_CIDR', '192.168.0.16/28'),
            'dns_name_servers': configuration.get('DNS_NAMESERVERS', []),

            'extra_nodes_image': self._get_required_attribute(configuration, 'MNG_IMAGE'),
            'extra_nodes_flavor': self._get_required_attribute(configuration, 'MNG_FLAVOR'),
            'extra_nodes_user': self._get_required_attribute(configuration, 'MNG_USER'),
        })

        # Global setting of CA_BUNDLE for request package
        os.environ['REQUESTS_CA_BUNDLE'] = self.SSL_CA_CERTIFICATE_VERIFY


config = Settings()
