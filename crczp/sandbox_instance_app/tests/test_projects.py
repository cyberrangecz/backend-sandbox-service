import pytest
from unittest import mock
from django.core.cache import cache
from crczp.sandbox_common_lib.common_cloud import list_images

IMAGE_LIST_CACHE_KEY = 'image_list'


@pytest.fixture
def mock_terraform_client():
    client = mock.Mock()
    client.list_images.return_value = ['image1', 'image2', 'image3']
    return client


@pytest.fixture
def setup_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_list_images_cached(mock_terraform_client, setup_cache):
    with mock.patch('crczp.sandbox_common_lib.utils.get_terraform_client', return_value=mock_terraform_client):
        images = list_images(cached=True)
        assert images == ['image1', 'image2', 'image3']

        mock_terraform_client.list_images.return_value = ['image4', 'image5']

        images = list_images(cached=True)
        assert images == ['image1', 'image2', 'image3']


@pytest.mark.django_db
def test_list_images_not_cached(mock_terraform_client, setup_cache):
    with mock.patch('crczp.sandbox_common_lib.utils.get_terraform_client', return_value=mock_terraform_client):
        images = list_images(cached=False)
        assert images == ['image1', 'image2', 'image3']

        mock_terraform_client.list_images.return_value = ['image4', 'image5']

        images = list_images(cached=False)
        assert images == ['image4', 'image5']
