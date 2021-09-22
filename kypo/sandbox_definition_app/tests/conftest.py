import pytest
import os
import io

from django.contrib.auth.models import User

TESTING_DATA_DIR = 'assets'

TESTING_DEFINITION = 'definition.yml'


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
