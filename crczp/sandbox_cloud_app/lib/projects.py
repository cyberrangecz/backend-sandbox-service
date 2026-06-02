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
    project_name: str = client.get_project_name()
    return project_name


def list_images(cached: bool = True) -> list[Image]:
    """
    Get list of images as generator
    """
    if cached:
        cached_images: list[Image] | None = cache.get(IMAGE_LIST_CACHE_KEY)
        if cached_images is not None:
            return cached_images

    client = utils.get_terraform_client()
    image_set: list[Image] = client.list_images()
    cache.set(IMAGE_LIST_CACHE_KEY, image_set, IMAGE_LIST_CACHE_TIMEOUT)
    return image_set


def get_project_limits() -> Limits:
    """
    Get Absolute limits of OpenStack project.
    """
    client = utils.get_terraform_client()
    return client.get_project_limits()
