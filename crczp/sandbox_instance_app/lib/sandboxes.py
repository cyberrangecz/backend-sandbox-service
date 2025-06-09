"""
Sandbox Service module for Sandbox management.
"""
import uuid
from typing import Optional

import os
import io
import zipfile
import structlog
import requests
import json
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.contrib.auth.models import User
from crczp.cloud_commons import TopologyInstance
from crczp.topology_definition.models import TopologyDefinition, DockerContainers
from rest_framework.generics import get_object_or_404

from crczp.sandbox_common_lib import exceptions, utils
from crczp.sandbox_definition_app.lib import definitions
from crczp.sandbox_instance_app.lib.sshconfig import SSH_PROXY_KEY,\
    CrczpMgmtSSHConfig, CrczpUserSSHConfig, CrczpAnsibleSSHConfig
from crczp.sandbox_instance_app.lib.topology import Topology
from crczp.sandbox_instance_app.models import Sandbox, SandboxLock

SANDBOX_CACHE_TIMEOUT = None  # Cache indefinitely
SANDBOX_CACHE_PREFIX = 'terraformstack-{}'
TEMPLATE_DIR_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'assets')
HEADERS = {
    'accept': 'application/json',
    'Content-Type': 'application/json'
}

LOG = structlog.getLogger()


def get_post_data_json(user_id, access_token, generated_variables):
    post_data = {
        'user_id': user_id,
        'access_token': access_token,
        'sandbox_answers': []
    }

    for variable in generated_variables:
        post_data['sandbox_answers'].append({
            'answer_content': variable.generated_value,
            'answer_variable_name': variable.name
        })

    return json.dumps(post_data, indent=4)


def post_answers(user_id, access_token, generated_variables):
    try:
        post_data_json = get_post_data_json(user_id, access_token, generated_variables)
        answers_storage_endpoint = settings.CRCZP_CONFIG.answers_storage_api + \
                'sandboxes' if settings.CRCZP_CONFIG.answers_storage_api[-1] == '/' else '/sandboxes'
        post_response = requests.post(answers_storage_endpoint, data=post_data_json,
                                      headers=HEADERS)
        post_response.raise_for_status()
    except requests.HTTPError as exc:
        raise exceptions.ApiException(f'Sending generated variables failed. Error: {exc}')


def get_sandbox(sb_pk: int, include_unfinished=False) -> Sandbox:
    """
    Retrieve sandbox instance from DB (or raises 404)
    and possibly update its state.

    :param sb_pk: Sandbox primary key (ID)
    :param include_unfinished: Allow returning an unfinished sandbox
    :return: Sandbox instance from DB
    :raise Http404: if sandbox does not exist
    """
    if include_unfinished:
        return get_object_or_404(Sandbox, pk=sb_pk)
    return get_object_or_404(Sandbox, pk=sb_pk, ready=True)


def get_topology_definition_and_containers(sandbox: Sandbox) -> (TopologyDefinition, DockerContainers):
    """Create topology definition for given sandbox."""
    pool = sandbox.allocation_unit.pool
    definition = pool.definition
    return definitions.get_definition(definition.url, pool.rev_sha, settings.CRCZP_CONFIG), definitions.get_containers(
        definition.url, pool.rev_sha, settings.CRCZP_CONFIG)


def lock_sandbox(sandbox: Sandbox, created_by: Optional[User]) -> SandboxLock:
    """Lock given sandbox. Raise ValidationError if already locked."""
    with transaction.atomic():
        sandbox = Sandbox.objects.select_for_update().get(pk=sandbox.id)
        if hasattr(sandbox, 'lock'):
            raise exceptions.ValidationError("Sandbox already locked.")
        return SandboxLock.objects.create(sandbox=sandbox, created_by=created_by)


def get_sandbox_topology(sandbox: Sandbox) -> Topology:
    """Get sandbox topology."""
    ti = get_topology_instance(sandbox)
    topology = Topology(ti)
    return topology


def get_user_sshconfig(sandbox: Sandbox,
                       sandbox_private_key_path: str = '<path_to_sandbox_private_key>')\
        -> CrczpUserSSHConfig:
    """Get user SSH config."""
    ti = get_topology_instance(sandbox)
    # Sandbox jump host name is stack name
    stack_name = sandbox.allocation_unit.get_stack_name()
    proxy_jump = settings.CRCZP_CONFIG.proxy_jump_to_man
    return CrczpUserSSHConfig(ti, proxy_jump.Host, stack_name, sandbox_private_key_path, proxy_port=proxy_jump.Port)


def get_user_ssh_access(sandbox: Sandbox) -> io.BytesIO:
    """Get user SSH access files."""
    ssh_access_name = f'pool-id-{sandbox.allocation_unit.pool.id}-sandbox-id-{sandbox.id}-user'
    ssh_config_name = f'{ssh_access_name}-config'
    private_key_name = f'{ssh_access_name}-key'
    public_key_name = f'{private_key_name}.pub'

    ssh_config = get_user_sshconfig(sandbox, f'~/.ssh/{private_key_name}')

    in_memory_zip_file = io.BytesIO()
    with zipfile.ZipFile(in_memory_zip_file, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr(ssh_config_name, ssh_config.serialize())
        zip_file.writestr(private_key_name, sandbox.private_user_key)
        zip_file.writestr(public_key_name, sandbox.public_user_key)

    in_memory_zip_file.seek(0)
    return in_memory_zip_file


def get_management_sshconfig(sandbox: Sandbox,
                             pool_private_key_path: str = '<path_to_pool_private_key>')\
        -> CrczpMgmtSSHConfig:
    """Get management SSH config."""
    ti = get_topology_instance(sandbox)
    proxy_jump_host = settings.CRCZP_CONFIG.proxy_jump_to_man.Host
    proxy_jump_user = sandbox.allocation_unit.pool.get_pool_prefix()
    proxy_jump_port = settings.CRCZP_CONFIG.proxy_jump_to_man.Port
    return CrczpMgmtSSHConfig(ti, proxy_jump_host, proxy_jump_user, proxy_port=proxy_jump_port,
                             pool_private_key_path=pool_private_key_path,
                             proxy_private_key_path=pool_private_key_path)


def get_ansible_sshconfig(sandbox: Sandbox, mng_key: str,
                          proxy_key: Optional[str] = None) -> CrczpAnsibleSSHConfig:
    """Get Ansible SSH config."""
    ti = get_topology_instance(sandbox)
    proxy_jump = settings.CRCZP_CONFIG.proxy_jump_to_man
    return CrczpAnsibleSSHConfig(ti, mng_key, proxy_jump.Host, proxy_jump.User, proxy_key, proxy_port=int(proxy_jump.Port))


def get_topology_instance(sandbox: Sandbox) -> TopologyInstance:
    """Get topology instance object. This function is cached."""
    client = utils.get_terraform_client()
    topology_definition, containers = get_topology_definition_and_containers(sandbox)
    ti = cache.get_or_set(
        get_cache_key(sandbox),
        lambda: client.get_enriched_topology_instance(
            sandbox.allocation_unit.get_stack_name(),
            topology_definition, containers),
        SANDBOX_CACHE_TIMEOUT
    )
    return ti


def clear_cache(sandbox: Sandbox) -> None:
    """Delete cached entries for this sandbox."""
    cache.delete(get_cache_key(sandbox))


def get_cache_key(sandbox: Sandbox) -> str:
    return SANDBOX_CACHE_PREFIX.format(sandbox.id)


def generate_new_sandbox_uuid():
    while True:
        new_uuid = str(uuid.uuid4())
        if not Sandbox.objects.filter(pk=new_uuid).count():
            return new_uuid

