from kypo.sandbox_common_lib import utils
from django.core.cache import cache

IMAGE_LIST_CACHE_KEY = 'image_list'
IMAGE_LIST_CACHE_TIMEOUT = 60 * 60 * 24


def get_quota_set():
    """
    Get QuotaSet object.
    """
    client = utils.get_terraform_client()
    return client.get_quota_set()


def get_project_name():
    """
    Get current project name
    """
    client = utils.get_terraform_client()
    return client.get_project_name()


def list_images(cached=True):
    """
    Get list of images as generator
    """
    if cached:
        image_set = cache.get(IMAGE_LIST_CACHE_KEY)
        if image_set is not None:
            return image_set

    client = utils.get_terraform_client()
    image_set = client.list_images()
    cache.set(IMAGE_LIST_CACHE_KEY, image_set, IMAGE_LIST_CACHE_TIMEOUT)
    return image_set


def get_project_limits():
    """
    Get Absolute limits of OpenStack project.
    """
    client = utils.get_terraform_client()
    return client.get_project_limits()
