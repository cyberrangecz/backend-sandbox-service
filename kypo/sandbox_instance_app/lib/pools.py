"""
Pool Service module for Pool management.
"""
from typing import List, Dict, Optional
import structlog
from django.db import transaction
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django.conf import settings

from kypo.sandbox_common_lib import utils, exceptions
from kypo.sandbox_definition_app.lib.definition_providers import GitlabProvider, GitProvider
from kypo.sandbox_definition_app.lib import definitions
from kypo.sandbox_definition_app.models import Definition

from kypo.sandbox_instance_app.lib import sandbox_creator, sandbox_destructor
from kypo.sandbox_instance_app import serializers
from kypo.sandbox_instance_app.models import Pool, Sandbox, SandboxAllocationUnit, CleanupRequest, \
    SandboxLock, PoolLock

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
        - rev: rev of the definition for pool
        - max_size: max size of new Pool instance
    :return: new Pool instance
    """
    definition = get_object_or_404(Definition, pk=data.get('definition_id'))
    if 'rev' not in data:
        data['rev'] = definition.rev
    if GitlabProvider.is_providable(definition.url):
        provider = GitlabProvider(definition.url, settings.KYPO_CONFIG.git_access_token)
    else:
        provider = GitProvider(definition.url, settings.KYPO_CONFIG.git_private_key)

    data['rev_sha'] = provider.get_rev_sha(data['rev'])

    serializer = serializers.PoolSerializerCreate(data=data)
    serializer.is_valid(raise_exception=True)
    pool = serializer.save()
    try:
        client = utils.get_ostack_client()

        # Validate definition
        top_def = definitions.get_definition(definition.url, pool.rev, settings.KYPO_CONFIG)
        client.validate_topology_definition(top_def)

        private_key, public_key = utils.generate_ssh_keypair()
        pool.private_management_key = private_key
        pool.public_management_key = public_key
        pool.save()

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


def get_pool_size(pool: Pool) -> int:
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

        current_size = get_pool_size(pool)
        if count is None:
            count = pool.max_size - current_size

        if current_size + count > pool.max_size:
            raise exceptions.ValidationError(
                "Current pool size is {curr}/{max}, cannot build {count} more sandboxes".format(
                    curr=current_size, max=pool.max_size, count=count)
                )

        return sandbox_creator.create_allocations_requests(pool, count)


def delete_allocation_units(pool: Pool) -> List[CleanupRequest]:
    """Delete all sandboxes in given pool."""
    units = pool.allocation_units.all()
    return sandbox_destructor.create_cleanup_requests(units)


def get_unlocked_sandbox(pool: Pool) -> Optional[Sandbox]:
    """Return unlocked sandbox."""
    # TODO: Create Locks immediately on Sandbox creation
    with transaction.atomic():
        sb_queryset = Sandbox.objects\
            .select_for_update()\
            .order_by('id')\
            .filter(allocation_unit__pool=pool)
        # Lock filtering needs to be done in Python.
        # FOR UPDATE cannot be applied to the nullable side of a relation.
        sandbox = next((sb for sb in sb_queryset if not hasattr(sb, 'lock')), None)
        if not sandbox:
            return None
        SandboxLock.objects.create(sandbox=sandbox)
        return sandbox


def lock_pool(pool: Pool) -> PoolLock:
    """Lock given Pool. Raise ValidationError if already locked."""
    with transaction.atomic():
        pool = Pool.objects.select_for_update().get(pk=pool.id)
        if hasattr(pool, 'lock'):
            raise exceptions.ValidationError("Pool already locked.")
        return PoolLock.objects.create(pool=pool)
