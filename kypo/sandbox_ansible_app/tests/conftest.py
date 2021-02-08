import pytest
import os
import yaml
from django.core.management import call_command

from kypo.openstack_driver import TopologyInstance, TransformationConfiguration

from kypo.topology_definition.models import TopologyDefinition

TESTING_DATA_DIR = 'assets'

TESTING_TRC_CONFIG = 'trc-config.yml'
TESTING_LINKS = 'links.yml'
TESTING_TOPOLOGY_INSTANCE = 'topology_instance.json'
TESTING_INVENTORY = 'inventory.yml'
TESTING_DEFINITION = 'definition.yml'
TESTING_DATABASE = 'database.yaml'


def data_path_join(file: str, data_dir: str = TESTING_DATA_DIR) -> str:
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), data_dir, file)


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command('loaddata', data_path_join(TESTING_DATABASE))


@pytest.fixture
def trc_config():
    return TransformationConfiguration.from_file(data_path_join(TESTING_TRC_CONFIG))


@pytest.fixture
def top_def():
    """Creates example topology definition for a sandbox."""
    with open(data_path_join(TESTING_DEFINITION)) as f:
        return TopologyDefinition.load(f)


@pytest.fixture
def links():
    """Creates example links definition"""
    with open(data_path_join(TESTING_LINKS)) as f:
        return yaml.full_load(f)


@pytest.fixture
def top_ins(top_def, trc_config, links):
    """Creates example topology instance."""
    topology_instance = TopologyInstance(top_def, trc_config)
    topology_instance.name = 'stack-name'
    topology_instance.ip = '10.10.10.10'

    for link in topology_instance.get_links():
        link.ip = links[link.name]['ip']
        link.mac = links[link.name]['mac']

    return topology_instance


@pytest.fixture
def inventory():
    """Creates example inventory for a Stack."""
    with open(data_path_join(TESTING_INVENTORY)) as f:
        return yaml.full_load(f)


@pytest.fixture
def top_def():
    """Creates example topology definition."""
    with open(data_path_join(TESTING_DEFINITION)) as f:
        return TopologyDefinition.load(f)
