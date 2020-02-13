import pytest
import os
import jsonpickle
import yaml
from kypo.topology_definition.models import TopologyDefinition

TESTING_DATA_DIR = 'assets'

TESTING_STACK = 'stack.json'
TESTING_INVENTORY = 'inventory.yml'
TESTING_DEFINITION = 'definition.yml'


def data_path_join(file: str, data_dir: str = TESTING_DATA_DIR) -> str:
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), data_dir, file)


@pytest.fixture
def stack():
    """Creates example Stack normally returned by KYPO lib."""
    with open(data_path_join(TESTING_STACK)) as f:
        return jsonpickle.decode(f.read())


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
