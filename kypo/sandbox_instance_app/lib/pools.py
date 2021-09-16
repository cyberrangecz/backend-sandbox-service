"""
Pool Service module for Pool management.
"""
import io
import zipfile
from typing import List, Dict, Optional
import structlog
from django.db import transaction
from django.db.models import QuerySet, ProtectedError
from django.shortcuts import get_object_or_404
from django.conf import settings

from kypo.sandbox_common_lib import utils, exceptions
from kypo.sandbox_definition_app.lib import definitions
from kypo.sandbox_definition_app.models import Definition

from kypo.sandbox_instance_app.lib import requests, sandboxes
from kypo.sandbox_instance_app import serializers
from kypo.sandbox_instance_app.models import Pool, Sandbox, SandboxAllocationUnit, CleanupRequest, \
    SandboxLock, PoolLock

from kypo.openstack_driver.exceptions import KypoException, InvalidTopologyDefinition,\
    StackCreationFailed
from kypo.openstack_driver.open_stack_proxy_elements import HardwareUsage

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
    Also creates management key-pairs in OpenStack

    :param data: dict of attributes to create model. Currently must contain:
        - definition: primary key (ID) of the Definition that new Pool instance is related to
        - max_size: max size of new Pool instance
    :return: new Pool instance
    """
    definition = get_object_or_404(Definition, pk=data.get('definition_id'))
    provider = definitions.get_def_provider(definition.url, settings.KYPO_CONFIG)

    data['rev'] = definition.rev
    data['rev_sha'] = provider.get_rev_sha(definition.rev)

    serializer = serializers.PoolSerializerCreate(data=data)
    serializer.is_valid(raise_exception=True)
    pool = serializer.save()
    try:
        client = utils.get_ostack_client()

        # Validate definition
        top_def = definitions.get_definition(definition.url, pool.rev_sha, settings.KYPO_CONFIG)
        client.validate_topology_definition(top_def)
    except (exceptions.GitError, exceptions.ValidationError, InvalidTopologyDefinition):
        pool.delete()
        raise

    private_key, public_key = utils.generate_ssh_keypair()
    certificate = utils.create_self_signed_certificate(private_key)

    pool.private_management_key = private_key
    pool.public_management_key = public_key
    pool.management_certificate = certificate
    pool.save()

    try:
        client.create_keypair(pool.ssh_keypair_name, public_key, 'ssh')
        client.create_keypair(pool.certificate_keypair_name, certificate, 'x509')
    except KypoException:
        try:
            delete_pool(pool)
        except KypoException:
            pass

        raise

    return pool


def delete_pool(pool: Pool) -> None:
    """Deletes given Pool. Also deletes management key-pair in OpenStack."""
    ssh_keypair_name = pool.ssh_keypair_name
    certificate_keypair_name = pool.certificate_keypair_name

    try:
        pool.delete()
    except ProtectedError:
        raise exceptions.ValidationError('Cannot delete locked pool.')

    client = utils.get_ostack_client()
    try:
        client.delete_keypair(ssh_keypair_name)
    except KypoException as exc:
        LOG.warning(exc)

    try:
        client.delete_keypair(certificate_keypair_name)
    except KypoException as exc:
        LOG.warning(exc)


def get_pool_size(pool: Pool) -> int:
    """Updates sandboxes in given pool and returns current size of pool."""
    return pool.allocation_units.count()


def get_sandboxes_in_pool(pool: Pool) -> QuerySet:
    """Returns DB QuerySet of sandboxes from given pool."""
    alloc_unit_ids = [unit.id for unit in pool.allocation_units.all()]
    return Sandbox.objects.all().filter(allocation_unit_id__in=alloc_unit_ids)


def validate_hardware_usage_of_sandboxes(pool, count) -> None:
    """
    Validates Heat Stacks hardware usage of sandboxes against OpenStack limits.

    :param pool: Pool in which sandboxes are built.
    :param count: Number of sandboxes.
    :return: None
    :raise: StackError if limits are exceeded.
    """
    try:
        top_def = definitions.get_definition(pool.definition.url, pool.rev_sha,
                                             settings.KYPO_CONFIG)
        client = utils.get_ostack_client()
        client.validate_hardware_usage_of_stacks(top_def, count)
    except StackCreationFailed as exc:
        raise exceptions.StackError(f'Cannot build {count} sandboxes: {exc}')


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

        validate_hardware_usage_of_sandboxes(pool, count)

        return requests.create_allocations_requests(pool, count)


def delete_allocation_units(pool: Pool) -> List[CleanupRequest]:
    """Delete all sandboxes in given pool."""
    units = pool.allocation_units.all()
    return requests.create_cleanup_requests(units)


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


def get_management_ssh_access(pool: Pool) -> io.BytesIO:
    """Get management SSH access files."""
    ssh_access_name = f'pool-id-{pool.id}'
    private_key_name = f'{ssh_access_name}-management-key'
    public_key_name = f'{private_key_name}.pub'

    in_memory_zip_file = io.BytesIO()
    with zipfile.ZipFile(in_memory_zip_file, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for sandbox in get_sandboxes_in_pool(pool):
            tmp = f'{ssh_access_name}-sandbox-id-{sandbox.id}-management'
            ssh_config_name = f'{tmp}-config'

            ssh_config = sandboxes.get_management_sshconfig(sandbox, f'~/.ssh/{private_key_name}')

            zip_file.writestr(ssh_config_name, ssh_config.serialize())

        zip_file.writestr(private_key_name, pool.private_management_key)
        zip_file.writestr(public_key_name, pool.public_management_key)

    in_memory_zip_file.seek(0)
    return in_memory_zip_file


def get_hardware_usage_of_sandbox(pool: Pool) -> HardwareUsage:
    """
    Get Heat Stack hardware usage of a single sandbox in a pool, whether it is allocated or not.

    :param pool: Pool to get HardwareUsage from.
    :return: Hardware usage of pool.
    """
    top_def = definitions.get_definition(pool.definition.url, pool.rev_sha,
                                         settings.KYPO_CONFIG)
    client = utils.get_ostack_client()
    return client.get_hardware_usage(top_def)

