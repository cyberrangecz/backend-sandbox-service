"""
Sandbox Service module for Sandbox management.
"""
from typing import Optional
import structlog
from django.db import transaction
from rest_framework.generics import get_object_or_404
from django.conf import settings
from django.core.cache import cache
from kypo.openstack_driver.sandbox_topology import SandboxTopology as Stack

from kypo.sandbox_instance_app.lib.sshconfig import KypoSSHConfig
from kypo.sandbox_instance_app.lib.topology import Topology
from kypo.sandbox_instance_app.models import Sandbox, SandboxLock
from kypo.sandbox_common_lib import exceptions, utils

SANDBOX_CACHE_PREFIX = 'sandbox'
SANDBOX_CACHE_TIMEOUT = None  # Cache indefinitely

LOG = structlog.getLogger()


def get_sandbox(sb_pk: int) -> Sandbox:
    """
    Retrieve sandbox instance from DB (or raises 404)
    and possibly update its state.

    :param sb_pk: Sandbox primary key (ID)
    :return: Sandbox instance from DB
    :raise Http404: if sandbox does not exist
    """
    return get_object_or_404(Sandbox, pk=sb_pk)


def lock_sandbox(sandbox: Sandbox) -> SandboxLock:
    """Lock given sandbox. Raise ValidationError if already locked."""
    with transaction.atomic():
        sandbox = Sandbox.objects.select_for_update().get(pk=sandbox.id)
        if hasattr(sandbox, 'lock'):
            raise exceptions.ValidationError("Sandbox already locked.")
        return SandboxLock.objects.create(sandbox=sandbox)


def get_sandbox_topology(sandbox: Sandbox) -> Topology:
    """Get sandbox topology."""
    client = utils.get_ostack_client()
    stack = client.get_sandbox(sandbox.allocation_unit.get_stack_name())
    topology = Topology(sandbox, stack)
    return topology


def get_user_sshconfig(sandbox: Sandbox) -> KypoSSHConfig:
    """Get user SSH config."""
    stack = get_stack(sandbox)
    return KypoSSHConfig.create_user_config(stack, settings.KYPO_CONFIG)


def get_management_sshconfig(sandbox: Sandbox) -> KypoSSHConfig:
    """Get management SSH config."""
    stack = get_stack(sandbox)
    return KypoSSHConfig.create_management_config(stack, settings.KYPO_CONFIG)


def get_ansible_sshconfig(sandbox: Sandbox, mng_key: str, git_key: str,
                          proxy_key: Optional[str] = None) -> KypoSSHConfig:
    """Get Ansible SSH config."""
    stack = get_stack(sandbox)
    return KypoSSHConfig.create_ansible_config(stack, settings.KYPO_CONFIG,
                                               mng_key, git_key, proxy_key)


def get_cache_key(sandbox: Sandbox, prefix: str = '') -> str:
    """Return key to a cache with given prefix."""
    if prefix:
        return f'{prefix}_{sandbox.id}'
    return str(sandbox.id)


def get_stack(sandbox: Sandbox, prefix: str = SANDBOX_CACHE_PREFIX,
              timeout: Optional[int] = SANDBOX_CACHE_TIMEOUT) -> Stack:
    """Get stack object. This function is cached."""
    key = get_cache_key(sandbox, prefix)
    client = utils.get_ostack_client()
    stack = cache.get_or_set(key,
                             lambda: client.get_sandbox(sandbox.allocation_unit.get_stack_name()),
                             timeout)
    return stack


def clear_cache(sandbox: Sandbox) -> None:
    """Delete cached entries for this sandbox."""
    key = get_cache_key(sandbox, SANDBOX_CACHE_PREFIX)
    if cache.get(key):
        cache.delete(key)
