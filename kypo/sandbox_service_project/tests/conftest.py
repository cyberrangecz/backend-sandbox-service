import pytest
import os

TESTING_DATA_DIR = 'assets'

INTEGRATION_TEST_TEMPLATE = "template.yml"


def data_path_join(file: str, data_dir: str = TESTING_DATA_DIR) -> str:
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), data_dir, file)


@pytest.fixture
def jump_template():
    """Creates example Stack normally returned by KYPO lib."""
    with open(data_path_join(INTEGRATION_TEST_TEMPLATE)) as f:
        return f.read()
