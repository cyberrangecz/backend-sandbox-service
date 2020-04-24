import json

import pytest
import os
import jsonpickle
from django.core.management import call_command

from kypo.topology_definition.models import TopologyDefinition

TESTING_DATA_DIR = 'assets'

TESTING_DATABASE = 'database.yaml'
TESTING_TOPOLOGY_INSTANCE = 'topology_instance.json'
TESTING_SSH_CONFIG_USER = 'ssh_config_user'
TESTING_SSH_CONFIG_MANAGEMENT = 'ssh_config_management'
TESTING_SSH_CONFIG_ANSIBLE = 'ssh_config_ansible'
TESTING_DEFINITION = 'definition.yml'
TESTING_TOPOLOGY = 'topology.json'
TESTING_TOPOLOGY_HIDDEN = 'topology-hidden.json'


def data_path_join(file: str, data_dir: str = TESTING_DATA_DIR) -> str:
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), data_dir, file)


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command('loaddata', data_path_join(TESTING_DATABASE))


@pytest.fixture
def top_ins():
    """Creates example topology instance."""
    with open(data_path_join(TESTING_TOPOLOGY_INSTANCE)) as f:
        return jsonpickle.decode(f.read())


@pytest.fixture
def user_ssh_config():
    """Creates example User ssh config for a sandbox."""
    with open(data_path_join(TESTING_SSH_CONFIG_USER)) as f:
        return f.read()


@pytest.fixture
def management_ssh_config():
    """Creates example Management ssh config for a sandbox."""
    with open(data_path_join(TESTING_SSH_CONFIG_MANAGEMENT)) as f:
        return f.read()


@pytest.fixture
def ansible_ssh_config():
    """Creates example Management ssh config for a sandbox."""
    with open(data_path_join(TESTING_SSH_CONFIG_ANSIBLE)) as f:
        return f.read()


@pytest.fixture
def topology():
    """Creates example topology for a sandbox."""
    with open(data_path_join(TESTING_TOPOLOGY)) as f:
        return json.load(f)


@pytest.fixture
def topology_hidden():
    """Creates example topology for a sandbox."""
    with open(data_path_join(TESTING_TOPOLOGY_HIDDEN)) as f:
        return json.load(f)


@pytest.fixture
def top_def():
    """Creates example topology definition for a sandbox."""
    with open(data_path_join(TESTING_DEFINITION)) as f:
        return TopologyDefinition.load(f)
