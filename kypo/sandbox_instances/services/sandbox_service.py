"""
Sandbox Service module for Sandbox management.

All functions should be able to work with batches.
If that makes at least a little bit sense, they should take an Iterable
of Sandboxes as an argument, not just one instance of Sandbox.
"""
from typing import Iterable, List
import structlog
import yaml
from django.db import transaction
from django.http import Http404
from rest_framework.generics import get_object_or_404
import django.core.exceptions

from kypo2_openstack_lib.sandbox import Sandbox as Stack, Host, Router, Link, MAN
from . import utils
from .definition_service import get_sandbox_definition
from . import ssh_config

from .. import exceptions, tasks
from ..config import config
from ..models import Sandbox, SandboxDeleteRequest
from .. import models

UAN_NETWORK_NAME = "uan-network"
BR_NETWORK_NAME = "br-network"

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
            tasks.hard_delete_sandbox(sandbox)
        return

    if any((sb.locked for sb in sandboxes)):
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


def list_snapshots(sandboxes: List[Sandbox]) -> List[list]:
    """
    Retrieves list of snapshot lists for given sandboxes.

    :return: List of snapshot lists
    """
    client = utils.get_ostack_client()
    snapshots = []
    for sandbox in sandboxes:
        snapshots.append(client.list_sandbox_snapshots(sandbox.get_stack_name()))
    return snapshots


def create_snapshot(sandboxes: Iterable[Sandbox]) -> List:
    """
    Creates snapshot of given sandboxes.

    :return: List of snapshots
    """
    client = utils.get_ostack_client()
    snapshots = []
    for sandbox in sandboxes:
        snapshots.append(client.create_sandbox_snapshot(sandbox.get_stack_name()))
    return snapshots


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


def get_snapshot(sandbox: Sandbox, snap_id: int) -> dict:
    """Retrieves given snapshot."""
    snapshots = list_snapshots([sandbox])[0]
    for snap in snapshots:
        if snap['id'] == snap_id:
            return snap
    raise Http404


def restore_snapshot(sandbox: Sandbox, snap_id: int) -> None:
    """Restores given snapshot."""
    client = utils.get_ostack_client()
    client.restore_sandbox_snapshot(sandbox.get_stack_name(), snap_id)


def delete_snapshot(sandbox: Sandbox, snap_id: int) -> None:
    """Deletes given snapshot."""
    client = utils.get_ostack_client()
    client.delete_sandbox_snapshot(sandbox.get_stack_name(), snap_id)


class Topology:
    """Represents a topology of a sandbox."""
    class Port:
        def __init__(self, ip, mac, parent, name):
            self.ip = ip
            self.mac = mac
            self.parent = parent
            self.name = name

    class Link:
        def __init__(self, real_port, dummy_port):
            self.real_port = real_port
            self.dummy_port = dummy_port

    def __init__(self, sandbox: Sandbox):
        self.sandbox = sandbox
        self.hosts = []
        self.routers = []
        self.switches = []
        self.links = []
        self.ports = []

    def create(self) -> None:
        """Retrieves data from cloud and parses topology data for given sandbox"""
        stack_name = self.sandbox.get_stack_name()
        client = utils.get_ostack_client()
        stack = client.get_sandbox(stack_name)

        self._remove_hidden_data_from_stack(self.sandbox, stack)

        self.hosts = stack.hosts.values()
        self.routers = stack.routers.values()
        self.switches = stack.networks.values()

        self._add_ports_and_links(stack)

    def _add_ports_and_links(self, stack) -> None:
        for ln in stack.links:
            real_port = self.Port(ln.ip, ln.mac, ln.node.name, ln.name + "_" + ln.node.name)
            dummy_port = self.Port(None, None, ln.network.name, ln.name + "_" + ln.network.name)

            self.links.append(self.Link(real_port, dummy_port))
            self.ports.append(real_port)
            self.ports.append(dummy_port)

    @staticmethod
    def _remove_hidden_data_from_stack(sandbox: Sandbox, stack: Stack) -> None:
        """Removes data about management and hidden nodes from stack"""

        # Delete hidden host
        definition = yaml.full_load(get_sandbox_definition(url=sandbox.request.pool.definition.url,
                                                           rev=sandbox.request.pool.definition.rev))

        hidden_hosts = []
        if 'hidden_hosts' in definition:
            hidden_hosts = definition['hidden_hosts']
        for hostname in hidden_hosts:
            del stack.hosts[hostname]

        # Delete MNG infrastructure
        mng_nodes = (stack.man.name, stack.br.name, stack.uan.name)
        mng_networks = (UAN_NETWORK_NAME, BR_NETWORK_NAME, stack.mng_net.name)

        for net in mng_networks:
            del stack.networks[net]

        # Delete links
        stack.links = [link for link in stack.links
                       if link.node.name not in mng_nodes
                       and link.node.name not in hidden_hosts
                       and link.network.name not in mng_networks]


class SandboxSSHConfigCreator:
    """Class for creation of SSH config."""
    def __init__(self, sandbox: Sandbox):
        stack_name = sandbox.get_stack_name()
        client = utils.get_ostack_client()
        self.stack = client.get_sandbox(stack_name)

    def create_user_config(self) -> ssh_config.Config:
        """Generates user ssh config string for sandbox. If router has multiple networks,
        then config contains one router entry for each of the networks."""

        user_ssh_config = ssh_config.Config()
        user_ssh_config.add_entry(Host='{0} {1}'.format(self.stack.man.name, self.stack.ip),
                                  User=config.SSH_PROXY_USERNAME, HostName=self.stack.ip,
                                  IdentityFile='<path_to_sandbox_private_key>', AddKeysToAgent='yes')
        uan_ip = self._get_uan_ip()
        user_ssh_config.add_entry(Host='{0} {1}'.format(self.stack.uan.name, uan_ip),
                                  User=config.SSH_PROXY_USERNAME, HostName=uan_ip, ProxyJump=self.stack.man.name)

        for link in self._get_uan_accessible_node_links():
            user_ssh_config.add_entry(Host='{0} {1}'.format(link.node.name, link.ip),
                                      User=config.SSH_PROXY_USERNAME, HostName=link.ip, ProxyJump=self.stack.uan.name)
        return user_ssh_config

    def create_management_config(self) -> ssh_config.Config:
        """Generates management ssh config string for sandbox. It uses MNG network for access."""
        management_ssh_config = ssh_config.Config()
        management_ssh_config.add_entry(Host='{0} {1}'.format(self.stack.man.name, self.stack.ip),
                                        User=self.stack.man.user, HostName=self.stack.ip,
                                        IdentityFile='<path_to_pool_private_key>', AddKeysToAgent='yes')

        for link in self._get_man_accessible_node_links():
            management_ssh_config.add_entry(Host='{0} {1}'.format(link.node.name, link.ip),
                                            User=link.node.user, HostName=link.ip, ProxyJump=self.stack.man.name)
        return management_ssh_config

    def _get_uan_ip(self) -> str:
        """Get link of UAN in UAN_NETWORK."""
        for link in self.stack.links:
            if link.node == self.stack.uan and link.network.name == UAN_NETWORK_NAME:
                return link.ip

    def _get_uan_accessible_node_links(self) -> List[Link]:
        # Only 'inner' networks UAN is connected to
        networks = [link.network for link in self.stack.get_node_links(self.stack.uan)
                    if link.network.name not in [UAN_NETWORK_NAME, self.stack.mng_net.name]]

        links = [link for link in self.stack.links
                 if link.network in networks
                 and link.node != self.stack.uan
                 and (isinstance(link.node, Host) or isinstance(link.node, Router))]

        return self._sorted_links(links)

    def _get_man_accessible_node_links(self) -> List[Link]:
        links = [link for link in self.stack.links
                 if link.network == self.stack.mng_net and link.node != self.stack.man]

        return self._sorted_links(links)

    @staticmethod
    def _sorted_links(links: List[Link]) -> List[Link]:
        """Return new list of links sorted by the hosts type and then by name."""
        mng_host_links = [link for link in links if isinstance(link.node, MAN)]
        router_links = [link for link in links if isinstance(link.node, Router)]
        host_links = [link for link in links if isinstance(link.node, Host)]
        router_links.sort(key=lambda l: l.node.name)
        host_links.sort(key=lambda l: l.node.name)
        return mng_host_links + router_links + host_links


def get_sandbox_info(request: models.SandboxCreateRequest) -> models.SandboxInfo:
    try:
        sandbox_locked = request.sandbox.locked
        sandbox_private_user_key = request.sandbox.private_user_key
        sandbox_public_user_key = request.sandbox.public_user_key
    except django.core.exceptions.ObjectDoesNotExist:
        sandbox_locked = False
        sandbox_private_user_key = ''
        sandbox_public_user_key = ''

    def _get_sandbox_info(_stage, _action):
        sandbox_info = models.SandboxInfo(id=request.id, pool=request.pool.id, locked=sandbox_locked,
                                          status_reason=_stage.error_message,
                                          private_user_key=sandbox_private_user_key,
                                          public_user_key=sandbox_public_user_key)
        if _stage.failed:
            sandbox_info.status = '{0}_FAILED'.format(_action)
        elif not _stage.end:
            sandbox_info.status = '{0}_IN_PROGRESS'.format(_action)
        else:
            sandbox_info.status = '{0}_COMPLETE'.format(_action)
        return sandbox_info

    try:
        _del_req = SandboxDeleteRequest.objects.get(sandbox_create_request=request)
        return models.SandboxInfo(id=request.id, pool=request.pool.id, locked=sandbox_locked,
                                  status='DELETE_IN_PROGRESS',
                                  status_reason='Deleting sandbox',
                                  private_user_key=sandbox_private_user_key,
                                  public_user_key=sandbox_public_user_key)
    except django.core.exceptions.ObjectDoesNotExist:
        pass

    stages = request.stages.all().select_subclasses()

    current_stage = None
    for stage in stages:
        if stage.start:
            current_stage = stage

    if not current_stage:
        return models.SandboxInfo(id=request.id, pool=request.pool.id, locked=sandbox_locked, status='INIT',
                                  status_reason='Sandbox is waiting to be created',
                                  private_user_key=sandbox_private_user_key,
                                  public_user_key=sandbox_public_user_key)
    elif current_stage == stages.latest('id') and current_stage.end and not current_stage.failed:
        return _get_sandbox_info(current_stage, 'FULL_BUILD')

    if isinstance(current_stage, models.StackCreateStage):
        return _get_sandbox_info(current_stage, 'CREATE')
    elif isinstance(current_stage, models.BootstrapStage):
        return _get_sandbox_info(current_stage, 'BOOTSTRAP')
    elif isinstance(current_stage, models.AnsibleStage):
        return _get_sandbox_info(current_stage, 'ANSIBLE')

    raise exceptions.ApiException('Unknown stage: {0}'.format(current_stage))
