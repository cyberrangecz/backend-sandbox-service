"""Cloud utility functions for accessing OpenStack cloud resources."""

from types import SimpleNamespace
from typing import Any

from django.core.cache import cache

from crczp.sandbox_common_lib import utils

IMAGE_LIST_CACHE_KEY = 'image_list'
IMAGE_LIST_CACHE_TIMEOUT = 60 * 60 * 24
FLAVOR_LIST_CACHE_KEY = 'flavor_list'
FLAVOR_LIST_CACHE_TIMEOUT = 60 * 60 * 24


def list_images(cached: bool = True) -> Any:
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


def _flavor_object(flavor: Any) -> SimpleNamespace:
    """Convert a Nova/OpenStack flavor object to serializer-compatible shape."""
    return SimpleNamespace(
        name=getattr(flavor, 'name', None),
        ram=getattr(flavor, 'ram', None),
        disk=getattr(flavor, 'disk', None),
        ephemeral=getattr(flavor, 'ephemeral', None),
        vcpus=getattr(flavor, 'vcpus', None),
        is_public=getattr(flavor, 'is_public', None),
    )


def _flavors_from_nova(client: Any) -> list[SimpleNamespace] | None:
    """Read flavors directly from the underlying Nova client when OpenStack is used."""
    cloud_client = getattr(client, 'cloud_client', None)
    open_stack_proxy = getattr(cloud_client, 'open_stack_proxy', None)
    nova = getattr(open_stack_proxy, 'nova', None)
    flavors_api = getattr(nova, 'flavors', None)
    if flavors_api is None or not hasattr(flavors_api, 'list'):
        return None
    return [_flavor_object(flavor) for flavor in flavors_api.list()]


def _flavors_from_dict(flavor_dict: dict[str, Any]) -> list[SimpleNamespace]:
    """Convert the legacy flavor dictionary to serializer-compatible objects."""
    flavors = []
    for name, values in flavor_dict.items():
        flavor_values = values if isinstance(values, dict) else {}
        ram = flavor_values.get('ram')
        # Older get_flavors_dict() returns RAM in GB. The flavor endpoint exposes MB,
        # matching Nova flavor.ram and the newer list_flavors() implementation.
        if isinstance(ram, float) and ram < 128:
            ram = int(round(ram * 1000))
        flavors.append(
            SimpleNamespace(
                name=name,
                ram=ram,
                disk=flavor_values.get('disk'),
                ephemeral=flavor_values.get('ephemeral'),
                vcpus=flavor_values.get('vcpus', flavor_values.get('vcpu')),
                is_public=flavor_values.get('is_public'),
            )
        )
    return flavors


def list_flavors(cached: bool = True) -> Any:
    """
    Get list of flavors as generator
    """
    if cached:
        flavor_set = cache.get(FLAVOR_LIST_CACHE_KEY)
        if flavor_set is not None:
            return flavor_set

    client = utils.get_terraform_client()
    flavor_set = _flavors_from_nova(client)
    if flavor_set is None and hasattr(client, 'list_flavors'):
        flavor_set = client.list_flavors()
    if (
        flavor_set is None
        and hasattr(client, 'cloud_client')
        and hasattr(client.cloud_client, 'list_flavors')
    ):
        flavor_set = client.cloud_client.list_flavors()
    if flavor_set is None:
        flavor_set = _flavors_from_dict(client.get_flavors_dict())
    cache.set(FLAVOR_LIST_CACHE_KEY, flavor_set, FLAVOR_LIST_CACHE_TIMEOUT)
    return flavor_set
