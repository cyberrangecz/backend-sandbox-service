"""
Pool Service module for Pool management.
"""
import structlog
from django.db import transaction
from django.db.models import QuerySet
from typing import List, Dict, Optional
from django.shortcuts import get_object_or_404

from ...sandbox_common import utils, exceptions

from . import sandbox_service, sandbox_creator
from ..models import Pool, Sandbox, SandboxAllocationUnit
from .. import serializers

LOG = structlog.get_logger()


def get_pool(pool_pk: int) -> Pool:
    """
    Retrieves Pool instance from DB (or raises 404).
    Alternative to self.get_object method of APIView classes.

    :param pool_pk: Pool primary key (ID)
    :return: Pool instance from DB
    :raise Http404: if Pool does not exist
    """
    return get_object_or_404(Pool, pk=pool_pk)


def create_pool(data: Dict) -> Pool:
    """
    Creates new Pool instance.
    Also creates management key-pair in OpenStack

    :param data: dict of attributes to create model. Currently must contain:
        - definition: primary key (ID) of the Definition that new Pool instance is related to
        - max_size: max size of new Pool instance
    :return: new Pool instance
    """
    serializer = serializers.PoolSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    pool = serializer.save()
    try:
        private_key, public_key = utils.generate_ssh_keypair()
        pool.private_management_key = private_key
        pool.public_management_key = public_key
        pool.save()

        client = utils.get_ostack_client()
        client.create_keypair(pool.get_keypair_name(), public_key)

    except Exception:
        pool.delete()
        raise

    return pool


def delete_pool(pool: Pool) -> None:
    """Deletes given Pool. Also deletes management key-pair in OpenStack."""
    keypair_name = pool.get_keypair_name()
    pool.delete()
    client = utils.get_ostack_client()
    client.delete_keypair(keypair_name)


def get_current_size(pool: Pool) -> int:
    """Updates sandboxes in given pool and returns current size of pool."""
    return pool.allocation_units.count()


def get_sandboxes_in_pool(pool: Pool) -> QuerySet:
    """Returns DB QuerySet of sandboxes from given pool."""
    alloc_unit_ids = [unit.id for unit in pool.allocation_units.all()]
    return Sandbox.objects.all().filter(allocation_unit_id__in=alloc_unit_ids)


def create_sandboxes_in_pool(pool: Pool, count: int = None) -> List[SandboxAllocationUnit]:
    """
    Creates count sandboxes in given pool.

    :param pool: Pool where to build sandbox
    :param count: Count of sandboxes, None to build maximum
    :return: sandbox instance
    """
    with transaction.atomic():
        pool = Pool.objects.select_for_update().get(pk=pool.id)

        current_size = get_current_size(pool)
        if count is None:
            count = pool.max_size - current_size

        if current_size + count > pool.max_size:
            raise exceptions.ValidationError(
                "Current pool size is {curr}/{max}, cannot build {count} more sandboxes".format(
                    curr=current_size, max=pool.max_size, count=count)
                )

        return sandbox_creator.create_sandbox_requests(pool, count)


# TODO: fix
# def delete_sandboxes_in_pool(pool: Pool) -> None:
#     """Delete all sandboxes in given pool."""
#     sandboxes = get_sandboxes_in_pool(pool)
#     sandbox_service.delete_sandboxes(sandboxes)


#FIXME: use new model
def get_unlocked_sandbox(pool: Pool) -> Optional[Sandbox]:
    """Return unlocked sandbox."""
    with transaction.atomic():
        create_req_ids = [req.id for req in pool.sandboxcreaterequests.all()]
        delete_create_req_ids = [req.sandbox_create_request.id
                                 for req in pool.sandboxdeleterequests.all()]

        sandbox = Sandbox.objects\
            .select_for_update()\
            .order_by('id')\
            .filter(request_id__in=create_req_ids, locked=False)\
            .exclude(request_id__in=delete_create_req_ids)\
            .first()
        if not sandbox:
            return None
        sandbox.locked = True
        sandbox.save()
        return sandbox
