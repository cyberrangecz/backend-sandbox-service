import pytest
import os
import io

from crczp.cloud_commons import Image
from ruamel.yaml import YAML

from django.contrib.auth.models import User

TESTING_DATA_DIR = 'assets'

TESTING_DEFINITION = 'definition.yml'
TESTING_CORRECT_TOPOLOGY = 'correct_topology.yml'


def data_path_join(file: str, data_dir: str = TESTING_DATA_DIR) -> str:
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), data_dir, file)


@pytest.fixture
def created_by():
    return User.objects.create(username='test-user', first_name='test-first-name',
                               last_name='test-last-name', email='test@email.com')


@pytest.fixture
def topology_definition_stream():
    """Creates example topology definition for a sandbox."""
    with open(data_path_join(TESTING_DEFINITION)) as f:
        return io.StringIO(f.read())


@pytest.fixture
def image():
    return Image(os_distro=None, os_type="debian",
                 disk_format=None, container_format=None,
                 visibility=None, size=None, status=None,
                 min_ram=None, min_disk=None,
                 created_at=None, updated_at=None, tags=[],
                 default_user=None, name="debian-12-x86_64",
                 owner_specified={"": ""})


@pytest.fixture
def get_terraform_client(mocker, image):
    mock_client = mocker.MagicMock()
    mock_client.get_flavors_dict.return_value = {"standard.large": "", "standard.small": "", "standard.medium": ""}
    mock_client.list_images.return_value = [image]

    mocker.patch('crczp.sandbox_common_lib.utils.get_terraform_client', return_value=mock_client)
    return mock_client


@pytest.fixture
def correct_topology() -> str:
    """Imitates topology.yml file from sandbox-definition git repository."""
    # the ruamel.yaml library keeps the order of the keys in the yaml file
    yaml = YAML()
    stream = io.StringIO()

    with open(data_path_join(TESTING_CORRECT_TOPOLOGY)) as f:
        yaml.dump(yaml.load(f), stream)
        return stream.getvalue()
