"""Business logic for retrieving OpenStack project information."""

from django.core.cache import cache

from crczp.cloud_commons import Image, Limits, QuotaSet
from crczp.sandbox_common_lib import utils

IMAGE_LIST_CACHE_KEY = 'image_list'
IMAGE_LIST_CACHE_TIMEOUT = 60 * 60 * 24


def get_quota_set() -> QuotaSet:
    """
    Get QuotaSet object.
    """
    client = utils.get_terraform_client()
    return client.get_quota_set()


def get_project_name() -> str:
    """
    Get current project name
    """
    client = utils.get_terraform_client()
    return client.get_project_name()  # type: ignore[no-any-return]


def list_images(cached: bool = True) -> list[Image]:
    """
    Get list of images as generator
    """
    if cached:
        image_set = cache.get(IMAGE_LIST_CACHE_KEY)
        if image_set is not None:
            return image_set  # type: ignore[no-any-return]

    client = utils.get_terraform_client()
    image_set = client.list_images()
    cache.set(IMAGE_LIST_CACHE_KEY, image_set, IMAGE_LIST_CACHE_TIMEOUT)
    return image_set  # type: ignore[no-any-return]


def get_project_limits() -> Limits:
    """
    Get Absolute limits of OpenStack project.
    """
    client = utils.get_terraform_client()
    return client.get_project_limits()
