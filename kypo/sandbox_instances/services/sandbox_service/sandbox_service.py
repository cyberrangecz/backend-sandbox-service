"""
Sandbox Service module for Sandbox management.

All functions should be able to work with batches.
If that makes at least a little bit sense, they should take an Iterable
of Sandboxes as an argument, not just one instance of Sandbox.
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


#######################################
# Batched Calls #
#######################################

def delete_sandboxes(sandboxes: Iterable[Sandbox], hard=False) -> None:
    """Deletes given sandbox. Hard specifies whether to use hard delete.
    On soft delete raises ValidationError if any sandbox is locked."""
    if hard:
        for sandbox in sandboxes:
            _delete_sandbox_hard(sandbox)
        return

    if any((sb.lock for sb in sandboxes)):
        raise exceptions.ValidationError("Some of the sandboxes are locked.")

    client = utils.get_ostack_client()
    for sandbox in sandboxes:
        client.delete_sandbox(sandbox.get_stack_name())
        # TODO: add task for deletion to OPENSTACK_QUEUE
        # TODO: add task for hard_deletion to OPENSTACK_QUEUE


def _delete_sandbox_hard(sandbox: Sandbox):
    """Subroutine for asynchronous hard delete of a sandbox."""
    client = utils.get_ostack_client()
    client.delete_sandbox_hard(sandbox.get_stack_name())
    sandbox.delete()


#######################################
# Single Instance Calls #
#######################################

def lock_sandbox(sandbox: Sandbox):
    """Locks given sandbox. Raise ValidationError if already locked."""
    with transaction.atomic():
        sandbox = Sandbox.objects.select_for_update().get(pk=sandbox.id)
        if sandbox.locked:
            raise exceptions.ValidationError("Sandbox already locked.")
        else:
            sandbox.locked = True
            sandbox.save()
        return sandbox


def unlock_sandbox(sandbox: Sandbox):
    """Unlocks given sandbox. Raise ValidationError if already unlocked."""
    with transaction.atomic():
        sandbox = Sandbox.objects.select_for_update().get(pk=sandbox.id)
        if not sandbox.locked:
            raise exceptions.ValidationError("Sandbox already unlocked.")
        else:
            sandbox.locked = False
            sandbox.save()
        return sandbox


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
