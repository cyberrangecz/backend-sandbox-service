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
from django.contrib.auth.models import User
from django.core.cache import cache

from crczp.sandbox_common_lib import utils, exceptions
from crczp.sandbox_definition_app.lib import definitions
from crczp.sandbox_definition_app.models import Definition

from crczp.sandbox_instance_app.lib import requests, sandboxes
from crczp.sandbox_instance_app import serializers
from crczp.sandbox_instance_app.models import Pool, Sandbox, SandboxAllocationUnit, CleanupRequest, \
    SandboxLock, PoolLock

from crczp.cloud_commons import CrczpException, InvalidTopologyDefinition,\
    StackCreationFailed, HardwareUsage

LOG = structlog.get_logger()
POOL_CACHE_TIMEOUT = None
PROJECT_LIMITS_CACHE_IDENTIFIER = 'project-limits'
POOL_CACHE_PREFIX = "hardware-usage-pool-{}"


def get_pool(pool_pk: int) -> Pool:
    """
    Retrieves Pool instance from DB (or raises 404).
    Alternative to self.get_object method of APIView classes.

    :param pool_pk: Pool primary key (ID)
    :return: Pool instance from DB
    :raise Http404: if Pool does not exist
    """
    return get_object_or_404(Pool, pk=pool_pk)


def create_pool(data: Dict, created_by: Optional[User]) -> Pool:
    """
    Creates new Pool instance.
    Also creates management key-pairs in OpenStack

    :param data: dict of attributes to create model. Currently must contain:
        - definition: primary key (ID) of the Definition that new Pool instance is related to
        - max_size: max size of new Pool instance
    :param created_by: User creating pool
    :return: new Pool instance
    """
    definition = get_object_or_404(Definition, pk=data.get('definition_id'))
    provider = definitions.get_def_provider(definition.url, settings.CRCZP_CONFIG)

    data['rev'] = definition.rev
    data['rev_sha'] = provider.get_rev_sha(definition.rev)

    serializer = serializers.PoolSerializerCreate(data=data)
    serializer.is_valid(raise_exception=True)
    pool = serializer.save(created_by=created_by)
    try:
        client = utils.get_terraform_client()

        # Validate definition
        top_def = definitions.get_definition(definition.url, pool.rev_sha, settings.CRCZP_CONFIG)
        definitions.validate_topology_definition(top_def)

        # Validate containers
        containers = definitions.get_containers(definition.url, pool.rev_sha, settings.CRCZP_CONFIG)
        if containers:
            definitions.validate_docker_containers(definition.url, pool.rev_sha,
                                                   settings.CRCZP_CONFIG)
        client.validate_topology_definition(top_def)
    except (exceptions.GitError, exceptions.ValidationError, InvalidTopologyDefinition):
        pool.delete()
        raise

    private_key, public_key = utils.generate_ssh_keypair()
    if settings.AWS_PROVIDER_CONFIGURED:
        certificate = ''
    else:
        certificate = utils.create_self_signed_certificate(private_key)

    pool.private_management_key = private_key
    pool.public_management_key = public_key
    pool.management_certificate = certificate
    pool.save()

    try:
        client.create_keypair(pool.ssh_keypair_name, public_key, 'ssh')
        if certificate:
            client.create_keypair(pool.certificate_keypair_name, certificate, 'x509')
    except CrczpException:
        try:
            delete_pool(pool)
        except CrczpException:
            pass

        raise

    return pool


def delete_pool(pool: Pool) -> None:
    """Deletes given Pool, deletes management key-pair in OpenStack and cache record for pool"""
    ssh_keypair_name = pool.ssh_keypair_name
    certificate_keypair_name = pool.certificate_keypair_name
    pool_cache_key = get_cache_key(pool)

    try:
        pool.delete()
        utils.clear_cache(pool_cache_key)
    except ProtectedError as e:
        error_message = str(e)
        if 'PoolLock' in error_message:
            raise exceptions.ValidationError(f'Cannot delete locked pool (ID="{pool.id}").')
        if 'AllocationUnit' in error_message:
            raise exceptions.ValidationError(f'Cannot delete non-empty pool (ID="{pool.id}"). '
                                             'Delete all allocation units before deleting the pool.')
        raise exceptions.ValidationError('Unknown error: ' + error_message)

    client = utils.get_terraform_client()
    try:
        client.delete_keypair(ssh_keypair_name)
    except CrczpException as exc:
        LOG.warning(exc)

    try:
        client.delete_keypair(certificate_keypair_name)
    except CrczpException as exc:
        LOG.warning(exc)


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
                                             settings.CRCZP_CONFIG)
        client = utils.get_terraform_client()
        topology_instance = client.get_topology_instance(top_def)
        client.validate_hardware_usage_of_stacks(topology_instance, count)
    except StackCreationFailed as exc:
        raise exceptions.StackError(f'Cannot build {count} sandboxes: {exc}')


def create_sandboxes_in_pool(pool: Pool, created_by: Optional[User], count: int = None) -> List[SandboxAllocationUnit]:
    """
    Creates count sandboxes in given pool.

    :param pool: Pool where to build sandbox
    :param created_by: User initiating the build.
    :param count: Count of sandboxes, None to build maximum
    :return: sandbox instance
    """
    with transaction.atomic():
        pool = Pool.objects.select_for_update().get(pk=pool.id)

        current_size = pool.size
        if count is None:
            count = pool.max_size - current_size

        if current_size + count > pool.max_size:
            raise exceptions.ValidationError(
                "Current pool size is {curr}/{max}, cannot build {count} more sandboxes".format(
                    curr=current_size, max=pool.max_size, count=count)
                )

        validate_hardware_usage_of_sandboxes(pool, count)
        units = requests.create_allocations_requests(pool, count, created_by)
        pool.size += count
        pool.save()
        return units


def get_unlocked_sandbox(pool: Pool, created_by: Optional[User]) -> Optional[Sandbox]:
    """Return unlocked sandbox."""
    # TODO: Create Locks immediately on Sandbox creation
    with transaction.atomic():
        sb_queryset = Sandbox.objects\
            .select_for_update()\
            .order_by('id')\
            .filter(allocation_unit__pool=pool, ready=True)
        # Lock filtering needs to be done in Python.
        # FOR UPDATE cannot be applied to the nullable side of a relation.
        if _has_locked_sandbox(sb_queryset, created_by):
            raise CrczpException("You already have a sandbox assigned. Use that one or ask your tutor for help.")
        sandbox = next((sb for sb in sb_queryset if not hasattr(sb, 'lock')), None)

        if not sandbox:
            return None
        SandboxLock.objects.create(sandbox=sandbox, created_by=created_by)
        return sandbox


def _has_locked_sandbox(sb_queryset, created_by: Optional[User]):
    """Check if User locked a sandbox in queryset"""
    if created_by is None:
        return False
    return len(sb_queryset.filter(lock__created_by=created_by)) != 0


def lock_pool(pool: Pool,  training_access_token: str = None) -> PoolLock:
    """Lock given Pool. Raise ValidationError if already locked."""
    with transaction.atomic():
        pool = Pool.objects.select_for_update().get(pk=pool.id)
        if hasattr(pool, 'lock'):
            raise exceptions.ValidationError("Pool already locked.")
        return PoolLock.objects.create(pool=pool, training_access_token=training_access_token)


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


def _get_hardware_usage(url: str, rev: str) -> Optional[HardwareUsage]:
    """
    Get Heat Stack hardware usage calculated from topology definition.

    :param url: URL of git repository from which topology definition is downloaded
    :param rev: Revision of git repository
    :return: Hardware usage or None if error occurs.
    """
    try:
        top_def = definitions.get_definition(url, rev, settings.CRCZP_CONFIG)
        client = utils.get_terraform_client()
        client.validate_topology_definition(top_def)
        top_instance = client.get_topology_instance(top_def)
    except (exceptions.GitError, exceptions.ImproperlyConfigured, exceptions.ValidationError,
            CrczpException):
        return None

    return client.get_hardware_usage(top_instance)


def get_hardware_usage_of_sandbox(pool: Pool) -> Optional[HardwareUsage]:
    """
    Get Heat Stack hardware usage of a single sandbox in a pool, whether it is allocated or not.

    :param pool: Pool to get HardwareUsage from.
    :return: Hardware usage or None if error occurs.
    """
    # sentinel object is used to differentiate between stored None and cache miss
    sentinel = object()
    definition = pool.definition

    hardware_usage = cache.get(get_cache_key(pool), sentinel)
    if hardware_usage is sentinel:
        hardware_usage = _get_hardware_usage(definition.url, definition.rev)

    limits = cache.get(PROJECT_LIMITS_CACHE_IDENTIFIER, sentinel)
    if limits is sentinel:
        client = utils.get_terraform_client()
        limits = client.get_project_limits()

    hardware_usage_pool = hardware_usage
    if hardware_usage_pool:
        hardware_usage_pool *= pool.size
        hardware_usage_pool /= limits

    cache.set(get_cache_key(pool), hardware_usage, POOL_CACHE_TIMEOUT)
    cache.set(PROJECT_LIMITS_CACHE_IDENTIFIER, limits, POOL_CACHE_TIMEOUT)

    return hardware_usage_pool


def get_cache_key(pool: Pool) -> str:
    """
    Get unique key which is used as cache record key

    :param pool: Pool for which the cache record is for
    :return: Cache key as string
    """
    return POOL_CACHE_PREFIX.format(pool.id)

