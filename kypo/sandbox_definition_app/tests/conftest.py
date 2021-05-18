import pytest
import os
import io

TESTING_DATA_DIR = 'assets'

TESTING_DEFINITION = 'definition.yml'


def data_path_join(file: str, data_dir: str = TESTING_DATA_DIR) -> str:
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), data_dir, file)


@pytest.fixture
def topology_definition_stream():
    """Creates example topology definition for a sandbox."""
    with open(data_path_join(TESTING_DEFINITION)) as f:
        return io.StringIO(f.read())
