"""
Sandbox Service module for Sandbox management.
"""
from typing import Iterable, List
import structlog
from django.db import transaction
from rest_framework.generics import get_object_or_404

from kypo2_openstack_lib.stack import Event, Resource
from ....sandbox_common import utils, exceptions
from ....sandbox_common.sshconfig import Config

from ...models import Sandbox
from .topology import Topology
from .sshconfig import SandboxSSHConfigCreator

LOG = structlog.getLogger()


def get_sandbox(sb_pk: int) -> Sandbox:
    """
    Retrieves sandbox instance from DB (or raises 404)
    and possibly updates its state.

    :param sb_pk: Sandbox primary key (ID)
    :return: Sandbox instance from DB
    :raise Http404: if sandbox does not exist
    """
    return get_object_or_404(Sandbox, pk=sb_pk)


def lock_sandbox(sandbox: Sandbox):
    """Locks given sandbox. Raise ValidationError if already locked."""
    with transaction.atomic():
        sandbox = Sandbox.objects.select_for_update().get(pk=sandbox.id)
        if hasattr(sandbox, 'lock'):
            raise exceptions.ValidationError("Sandbox already locked.")
        return Lock.objects.create(sandbox=sandbox)


def get_sandbox_topology(sandbox: Sandbox) -> Topology:
    """Get sandbox topology."""
    topology = Topology(sandbox)
    topology.create()
    return topology


def get_user_sshconfig(sandbox: Sandbox) -> Config:
    """Get user SSH config."""
    return SandboxSSHConfigCreator(sandbox).create_user_config()


def get_management_sshconfig(sandbox: Sandbox) -> Config:
    """Get management SSH config."""
    return SandboxSSHConfigCreator(sandbox).create_management_config()
