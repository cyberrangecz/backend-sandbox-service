"""Shared fixtures for sandbox_service_project integration tests."""

import os

TESTING_DATA_DIR = 'assets'


def data_path_join(file: str, data_dir: str = TESTING_DATA_DIR) -> str:
    """Return the absolute path to a test asset file."""
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), data_dir, file)
