"""
Group builder functions for constructing Ansible inventory groups from a TopologyInstance.

Each function receives the Inventory and TopologyInstance, builds one or more
Ansible groups (or variables), and adds them to the inventory as a side-effect.

GROUP_BUILDERS is the ordered list of all builders applied by Inventory._create_groups.
"""
from typing import TYPE_CHECKING, Callable, List

import structlog

from crczp.cloud_commons import TopologyInstance
from crczp.topology_definition.models import Protocol
from crczp.sandbox_common_lib.common_cloud import list_images
from crczp.sandbox_ansible_app.lib.inventory import (
    Group, DefaultAnsibleHostsGroups, _normalize_address,
)

if TYPE_CHECKING:
    from crczp.sandbox_ansible_app.lib.inventory import Inventory

LOG = structlog.get_logger()

_Builder = Callable[['Inventory', TopologyInstance], None]


# ---------------------------------------------------------------------------
# Individual builder functions
# ---------------------------------------------------------------------------

def _add_hosts_group(inventory: 'Inventory', topology: TopologyInstance) -> None:
    hosts = [inventory.hosts[node.name] for node in topology.get_hosts()]
    inventory.add_group(Group(DefaultAnsibleHostsGroups.HOSTS.value, hosts))


def _add_management_group(inventory: 'Inventory', topology: TopologyInstance) -> None:
    inventory.add_group(Group(DefaultAnsibleHostsGroups.MANAGEMENT.value, [topology.man]))


def _add_routers_group(inventory: 'Inventory', topology: TopologyInstance) -> None:
    routers = [inventory.hosts[node.name] for node in topology.get_routers()]
    inventory.add_group(Group(DefaultAnsibleHostsGroups.ROUTERS.value, routers))


def _add_winrm_nodes_group(inventory: 'Inventory', topology: TopologyInstance) -> None:
    man = topology.man
    winrm_nodes = [
        inventory.hosts[node.name] for node in topology.get_nodes()
        if node.base_box.mgmt_protocol == Protocol.WINRM and node != man
    ]
    inventory.add_group(Group(DefaultAnsibleHostsGroups.WINRM_NODES.value, winrm_nodes))


def _add_ssh_nodes_group(inventory: 'Inventory', topology: TopologyInstance) -> None:
    man = topology.man
    ssh_nodes = [
        inventory.hosts[node.name] for node in topology.get_nodes()
        if node.base_box.mgmt_protocol == Protocol.SSH and node != man
    ]
    inventory.add_group(Group(DefaultAnsibleHostsGroups.SSH_NODES.value, ssh_nodes))


def _add_user_accessible_nodes_group(inventory: 'Inventory',
                                     topology: TopologyInstance) -> None:
    inventory.add_group(Group(DefaultAnsibleHostsGroups.USER_ACCESSIBLE_NODES.value,
                              inventory.get_user_accessible_nodes()))


def _add_hidden_hosts_group(inventory: 'Inventory', topology: TopologyInstance) -> None:
    hidden_hosts = [inventory.hosts[node.name] for node in topology.get_hosts()
                    if node.hidden]
    inventory.add_group(Group(DefaultAnsibleHostsGroups.HIDDEN_HOSTS.value, hidden_hosts))


def _add_docker_hosts_group(inventory: 'Inventory', topology: TopologyInstance) -> None:
    inventory.docker_hosts = None
    if topology.containers:
        docker_hosts = [
            inventory.hosts[container_mapping.host]
            for container_mapping in topology.containers.container_mappings
        ]
        inventory.docker_hosts = list(set(docker_hosts))
        inventory.add_group(Group(DefaultAnsibleHostsGroups.DOCKER_HOSTS.value,
                                  inventory.docker_hosts))


def _add_monitored_hosts_tcp_group(inventory: 'Inventory',
                                   topology: TopologyInstance) -> None:
    _mt = topology.topology_definition.monitoring_targets
    if not (_mt and _mt.tcp):
        return
    hosts_variables = {}
    hosts = []
    for monitored_node in topology.get_monitored_hosts_tcp():
        # inventory.hosts includes routers and switches
        host = inventory.hosts[monitored_node.node]
        hosts.append(host)
        hosts_variables[host.name] = {
            'tcp_targets': [
                {k: v for k, v in {
                    'port': target.port,
                    'interface': target.interface,
                    'address': _normalize_address(target.address),
                }.items() if v is not None}
                for target in monitored_node.targets
            ]
        }
    inventory.add_group(Group(DefaultAnsibleHostsGroups.MONITORED_HOSTS_TCP.value,
                              hosts, hosts_variables))


def _add_monitored_hosts_icmp_group(inventory: 'Inventory',
                                    topology: TopologyInstance) -> None:
    _mt = topology.topology_definition.monitoring_targets
    if not (_mt and _mt.icmp):
        return
    hosts_variables = {}
    hosts = []
    for monitored_node in topology.get_monitored_hosts_icmp():
        host = inventory.hosts[monitored_node.node]
        hosts.append(host)
        hosts_variables[host.name] = {
            'icmp_targets': [
                {k: v for k, v in {
                    'interface': target.interface,
                    'address': _normalize_address(target.address),
                }.items() if v is not None}
                for target in monitored_node.targets
            ]
        }
    inventory.add_group(Group(DefaultAnsibleHostsGroups.MONITORED_HOSTS_ICMP.value,
                              hosts, hosts_variables))


def _add_monitored_hosts_http_vars(inventory: 'Inventory',
                                   topology: TopologyInstance) -> None:
    _mt = topology.topology_definition.monitoring_targets
    if not (_mt and _mt.http):
        return
    inventory.add_variables(monitoring_http_targets=[
        {k: v for k, v in {
            'url': target.url,
            'check_string': target.check_string,
        }.items() if v is not None}
        for target in topology.get_monitored_hosts_http().targets
    ])


def _add_windows_hosts_group(inventory: 'Inventory', topology: TopologyInstance) -> None:
    windows_hosts = _get_windows_hosts(inventory, topology)
    if windows_hosts:
        windows_group = Group(DefaultAnsibleHostsGroups.WINDOWS_HOSTS.value, windows_hosts)
        windows_group.add_variables(ansible_shell_type='powershell')
        inventory.add_group(windows_group)


def _get_windows_hosts(inventory: 'Inventory', topology: TopologyInstance) -> List:
    """
    Return hosts that use Windows images based on the os_type parameter.
    """
    try:
        images = list_images()
        image_os_type_map = {image.name: image.os_type for image in images}

        windows_hosts = []
        for node in topology.get_nodes():
            os_type = image_os_type_map.get(node.base_box.image)
            if os_type and os_type.lower() == 'windows':
                host = inventory.hosts.get(node.name)
                if host:
                    windows_hosts.append(host)

        return windows_hosts
    except Exception as e:
        LOG.warning(f'Failed to create windows_hosts group: {e}')
        return []


# ---------------------------------------------------------------------------
# Ordered registry — the sequence matters (e.g. docker_hosts must exist before
# _update_docker_hosts is called later in Inventory.__init__).
# ---------------------------------------------------------------------------

GROUP_BUILDERS: List[_Builder] = [
    _add_hosts_group,
    _add_management_group,
    _add_routers_group,
    _add_winrm_nodes_group,
    _add_ssh_nodes_group,
    _add_user_accessible_nodes_group,
    _add_hidden_hosts_group,
    _add_docker_hosts_group,
    _add_monitored_hosts_tcp_group,
    _add_monitored_hosts_icmp_group,
    _add_monitored_hosts_http_vars,
    _add_windows_hosts_group,
]
