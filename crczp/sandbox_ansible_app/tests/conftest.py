import io

import pytest
import os
import yaml
from django.core.management import call_command

from crczp.cloud_commons import TopologyInstance, TransformationConfiguration, Image
from ruamel.yaml import YAML

from crczp.sandbox_ansible_app.lib.container import DockerContainer

from crczp.topology_definition.models import TopologyDefinition

from crczp.sandbox_ansible_app.lib.inventory import Inventory
from crczp.sandbox_definition_app.lib.definitions import load_docker_containers

TESTING_DATA_DIR = 'assets'

TESTING_TRC_CONFIG = 'trc-config.yml'
TESTING_LINKS = 'links.yml'
TESTING_TOPOLOGY_INSTANCE = 'topology_instance.json'
TESTING_INVENTORY = 'inventory.yml'
TESTING_INVENTORY_MONITOR = 'inventory-monitoring.yml'
TESTING_DEFINITION = 'definition.yml'
TESTING_DEFINITION_MONITOR = 'definition-monitoring.yml'
TESTING_DATABASE = 'database.yaml'
TESTING_CONTAINERS = 'containers.yml'
TESTING_INVENTORY_CONTAINERS = 'inventory_containers.yml'

def data_path_join(file: str, data_dir: str = TESTING_DATA_DIR) -> str:
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), data_dir, file)


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command('loaddata', data_path_join(TESTING_DATABASE))


@pytest.fixture(autouse=True)
def docker_sys_mock(mocker):
    mocker.patch.object(DockerContainer, 'CLIENT')


@pytest.fixture(autouse=True)
def mock_list_images(mocker):
    """Mock list_images to return test image data matching the test definitions."""
    mock_images = [
        Image(
            os_distro='debian',
            os_type='linux',
            disk_format='qcow2',
            container_format='bare',
            visibility='public',
            size=1000000,
            status='active',
            min_ram=512,
            min_disk=10,
            created_at='2024-01-01',
            updated_at='2024-01-01',
            tags=[],
            default_user='debian',
            name='debian-12-x86_64',
            owner_specified={},
        ),
        Image(
            os_distro='windows',
            os_type='windows',
            disk_format='qcow2',
            container_format='bare',
            visibility='public',
            size=2000000,
            status='active',
            min_ram=2048,
            min_disk=40,
            created_at='2024-01-01',
            updated_at='2024-01-01',
            tags=[],
            default_user='Administrator',
            name='windows-10',
            owner_specified={},
        ),
    ]
    return mocker.patch('crczp.sandbox_ansible_app.lib.inventory.list_images', return_value=mock_images)


@pytest.fixture(scope='session')
def trc_config():
    return TransformationConfiguration.from_file(data_path_join(TESTING_TRC_CONFIG))


@pytest.fixture
def top_def():
    """Creates example topology definition for a sandbox."""
    with open(data_path_join(TESTING_DEFINITION)) as f:
        return TopologyDefinition.load(f)


@pytest.fixture
def top_def_monitoring():
    """Creates example topology definition for a sandbox."""
    with open(data_path_join(TESTING_DEFINITION_MONITOR)) as f:
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
def top_ins_monitoring(top_def_monitoring, trc_config, links):
    """Creates example topology instance."""
    topology_instance = TopologyInstance(top_def_monitoring, trc_config)
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
def inventory_monitoring():
    """Creates example inventory for a Stack."""
    with open(data_path_join(TESTING_INVENTORY_MONITOR)) as f:
        return yaml.full_load(f)


@pytest.fixture
def inventory_containers():
    """Creates a correct example inventory with containers."""
    with open(data_path_join(TESTING_INVENTORY_CONTAINERS)) as f:
        return yaml.full_load(f)


@pytest.fixture
def containers() -> str:
    """Imitates containers.yml file from sandbox-definition git repository."""
    # the ruamel.yaml library keeps the order of the keys in the yaml file
    ruamel_yaml = YAML()
    stream = io.StringIO()

    with open(data_path_join(TESTING_CONTAINERS)) as f:
        ruamel_yaml.dump(ruamel_yaml.load(f), stream)
        return stream.getvalue()


@pytest.fixture
def top_ins_with_containers(top_def, trc_config, links, containers):
    """Creates example topology instance with containers."""
    loaded_containers = load_docker_containers(io.StringIO(containers))
    topology_instance = TopologyInstance(top_def, trc_config, containers=loaded_containers)
    topology_instance.name = 'stack-name'
    topology_instance.ip = '10.10.10.10'

    for link in topology_instance.get_links():
        link.ip = links[link.name]['ip']
        link.mac = links[link.name]['mac']

    return topology_instance
