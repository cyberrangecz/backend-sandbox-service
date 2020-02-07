import pytest
import os
import re
import jsonpickle

TESTING_DATA_DIR = 'assets'

TESTING_STACK = "stack.json"
TESTING_SSH_CONFIG_USER = "ssh_config_user"
TESTING_SSH_CONFIG_MANAGEMENT = "ssh_config_management"
TESTING_SSH_CONFIG_ANSIBLE = "ssh_config_ansible"


def data_path_join(file: str, data_dir: str = TESTING_DATA_DIR) -> str:
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), data_dir, file)


@pytest.fixture
def stack():
    """Creates example Stack normally returned by KYPO lib."""
    with open(data_path_join(TESTING_STACK)) as f:
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
