from ipaddress import ip_network
from typing import Dict, List, Optional
from itertools import chain
from enum import Enum
import structlog
import yaml
import abc

from django.conf import settings
from kypo.cloud_commons import TopologyInstance, Link
from kypo.topology_definition.models import Protocol, Router, Network

KYPO_PROXY_JUMP_NAME = 'kypo-proxy-jump'

LOG = structlog.get_logger()


class DefaultAnsibleHostsGroups(Enum):
    """
    Enumerator for default ansible hosts groups.
    """
    HOSTS = 'hosts'
    MANAGEMENT = 'management'
    ROUTERS = 'routers'
    SSH_NODES = 'ssh_nodes'
    WINRM_NODES = 'winrm_nodes'
    USER_ACCESSIBLE_NODES = 'user_accessible_nodes'
    HIDDEN_HOSTS = 'hidden_hosts'
    DOCKER_HOSTS = 'docker_hosts'


class Base(abc.ABC):
    def __init__(self):
        self.variables = {}

    @abc.abstractmethod
    def to_dict(self) -> dict:
        return self.variables

    def add_variables(self, **kwargs):
        self.variables.update(kwargs)


class Host(Base):
    """
    Represents Ansible inventory host entry.
    """
    def __init__(self, name: str, host: str, user: str):
        super().__init__()
        self.name = name
        self.add_variables(ansible_host=host)
        self.add_variables(ansible_user=user)

    def to_dict(self) -> dict:
        """
        Return Ansible inventory host entry represented as a dict.
        """
        return super().to_dict()


class Group(Base):
    """
    Represents Ansible inventory group entry.
    """
    def __init__(self, name: str, hosts: List[Host] = None):
        super().__init__()
        self.name = name
        self.hosts = {host.name: host for host in hosts} if hosts else {}
        self.groups = {}

    def to_dict(self) -> dict:
        """
        Return Ansible inventory group entry represented as a dict.
        """
        dictionary = {}
        if self.hosts:
            dictionary['hosts'] = {host.name: None for host in self.hosts.values()}
        children = {group.name: group.to_dict() for group in self.groups.values()}
        if children:
            dictionary['children'] = children
        if self.variables:
            dictionary['vars'] = self.variables
        return dictionary

    def add_host(self, host: Host) -> None:
        """
        Add Ansible host to this group.
        """
        self.hosts[host.name] = host

    def get_host(self, name: str) -> Optional[Host]:
        """
        Return Ansible host if exist.
        """
        return self.hosts.get(name)

    def add_group(self, group: 'Group') -> None:
        """
        Add Ansible child group to this one.
        """
        self.groups[group.name] = group

    def get_group(self, name: str) -> Optional['Group']:
        """
        Return Ansible child group if exist.
        """
        return self.groups.get(name)


class Route:
    """
    Represents route information to be set on an interface.
    """
    def __init__(self, network_cidr: str, gateway_ip: str):
        self.network_ip = network_cidr.split('/')[0]
        self.network_mask = str(ip_network(network_cidr).netmask)
        self.gateway_ip = gateway_ip

    def to_dict(self) -> dict:
        """
        Return route information represented as a dict.
        """
        return {
            'net': self.network_ip,
            'mask': self.network_mask,
            'gw': self.gateway_ip,
        }


class Interface:
    """
    Represents a network interface.
    """
    def __init__(self, mac: str, ip: str, default_gateway_ip: str = None):
        self.mac = mac
        self.ip = ip
        self.default_gateway_ip = default_gateway_ip
        self.routes = []

    def add_route(self, route: Route) -> None:
        """
        Add route information to this interface.
        """
        self.routes.append(route)

    def to_dict(self) -> dict:
        """
        Return a network interface represented as a dict.
        """
        return {
            'mac': self.mac,
            'def_gw_ip': self.default_gateway_ip,
            'routes': [route.to_dict() for route in self.routes],
        }


class Routing:
    """
    Represents sandbox routing information.
    """
    def __init__(self, topology_instance: TopologyInstance):
        self.topology_instance = topology_instance
        self.network_to_router_mappings = self._get_network_to_router_mapping(topology_instance)
        self.interfaces: Dict[str, Dict[str, Interface]] =\
            {node.name: {} for node in topology_instance.get_nodes()}
        self._set_sandbox_routing()

    def get_node_interfaces(self, node_name: str) -> List[Interface]:
        """
        Return a list of Interface settings for a particular node.
        """
        return list(self.interfaces.get(node_name, {}).values())

    def _set_sandbox_routing(self) -> None:
        """
        The main method that initializes a Routing instance from TopologyInstance.
        """
        man_to_routers_link = self.topology_instance.get_link_between_node_and_network(
            self.topology_instance.man, self.topology_instance.wan
        )
        man_to_routers_interface = self._create_interface_for_link(man_to_routers_link)
        for router_link in self.topology_instance.get_links_from_wan_to_routers():
            router_to_man_interface = self._create_interface_for_link(router_link,
                                                                      man_to_routers_link.ip)
            for network in self._get_host_networks_for_routing(router_link.node):
                man_to_routers_interface.add_route(Route(network.cidr, router_to_man_interface.ip))

    def _get_host_networks_for_routing(self, router: Router) -> List[Network]:
        """
        Return a list of user-defined Networks connected to The Router needed to be routed to.
        """
        return [
            router_to_network_link.network for router_to_network_link
            in self.topology_instance.get_node_links(router,
                                                     self.topology_instance.get_hosts_networks())
            if router_to_network_link.node.name ==
            self.network_to_router_mappings[router_to_network_link.network.name]
        ]

    def _create_interface_for_link(self, link: Link, default_gateway_ip: str = "") -> Interface:
        interface = Interface(link.mac, link.ip, default_gateway_ip)
        self.interfaces[link.node.name][link.mac] = interface
        return interface

    @staticmethod
    def _get_network_to_router_mapping(topology_instance: TopologyInstance) -> Dict[str, str]:
        """
        Return Dict[network_name, router_name].

        Prefers router which is first in alphabetical order.
        """
        net_to_router = {}
        router_mappings = sorted(topology_instance.topology_definition.router_mappings,
                                 key=lambda x: x.router, reverse=True)
        for router_mapping in router_mappings:
            net_to_router[router_mapping.network] = router_mapping.router
        return net_to_router


class BaseInventory(Group):
    """
    Represents Ansible inventory just for KYPO Proxy.
    """
    def __init__(self, proxy_jump_user_access_mgmt_name: str,
                 proxy_jump_user_access_user_name: str):
        super().__init__('all')
        self.add_proxy_jump(proxy_jump_user_access_mgmt_name, proxy_jump_user_access_user_name)

    def add_proxy_jump(self, user_access_mgmt_name: str, user_access_user_name: str) -> None:
        """
        Add Ansible host for KYPO Proxy to this group.
        """
        proxy_jump_config = settings.KYPO_CONFIG.proxy_jump_to_man
        host = Host(KYPO_PROXY_JUMP_NAME, proxy_jump_config.Host, proxy_jump_config.User)
        host.add_variables(user_access_mgmt_name=user_access_mgmt_name,
                           user_access_user_name=user_access_user_name,
                           user_access_present=False)
        self.add_host(host)

    def to_dict(self) -> dict:
        """
        Return Ansible inventory represented as a dict.
        """
        inventory = {'all': super().to_dict()}
        inventory['all']['hosts'] = {host.name: host.to_dict() for host in self.hosts.values()}
        return inventory

    def serialize(self) -> str:
        """
        Return YAML representation of Inventory as a string.
        """
        return yaml.dump(self.to_dict(), default_flow_style=False, indent=2)


class Inventory(BaseInventory):
    """
    Represents Ansible inventory.

    The inventory `vars` section contains by default following attributes:
    - `kypo_global_sandbox_name`
    - `kypo_global_sandbox_ip`
    If you need any extra data in the vars section, pass them as the
    `extra_vars` dictionary to constructor.
    """
    def __init__(self, proxy_jump_user_access_mgmt_name: str, proxy_jump_user_access_user_name: str,
                 topology_instance: TopologyInstance, mgmt_private_key: str,
                 mgmt_public_certificate: str, mgmt_public_key: str, user_public_key: str,
                 extra_vars: dict = None):
        super().__init__(proxy_jump_user_access_mgmt_name, proxy_jump_user_access_user_name)
        self.topology_instance = topology_instance
        self.routing = Routing(topology_instance)

        self._create_hosts()
        self._set_ip_forward()
        self._create_groups()
        self._create_user_defined_groups()
        self._add_user_network_ip_to_user_defined_nodes()

        self.get_host(KYPO_PROXY_JUMP_NAME).add_variables(user_access_present=True)
        self.get_group('winrm_nodes')\
            .add_variables(**self._get_winrm_connection_variables(mgmt_private_key,
                                                                  mgmt_public_certificate))
        self.add_variables(kypo_global_sandbox_name=self.topology_instance.name,
                           kypo_global_sandbox_ip=self.topology_instance.ip,
                           kypo_global_ssh_public_user_key=user_public_key,
                           kypo_global_ssh_public_mgmt_key=mgmt_public_key)
        if extra_vars:
            self.add_variables(**extra_vars)
        if topology_instance.containers:
            self._update_docker_hosts()

    def _create_hosts(self) -> None:
        """
        Create Ansible host entry for every host in TopologyInstance.
        """
        mgmt_links = {link.node.name: link.ip for link in
                      self.topology_instance.get_network_links(self.topology_instance.man_network)}
        mgmt_links[self.topology_instance.man.name] = self.topology_instance.ip
        for node in self.topology_instance.get_nodes():
            self._add_host(Host(node.name, mgmt_links[node.name], node.base_box.mgmt_user))

    def _add_host(self, host: Host) -> None:
        """
        Add Ansible host entry with routing information if exist to special Ansible group 'all'.
        """
        interfaces = self.routing.get_node_interfaces(host.name)
        if interfaces:
            host.add_variables(interfaces=[interface.to_dict() for interface in interfaces])
        self.add_host(host)

    def _set_ip_forward(self) -> None:
        """
        Set IP forward variable to Routers, Border-Router and MAN.
        """
        ip_forward_nodes = list(self.topology_instance.get_routers()) +\
            [self.topology_instance.man]
        for node in ip_forward_nodes:
            host = self.hosts.get(node.name)
            if host:
                host.add_variables(ip_forward=True)

    def _create_groups(self) -> None:
        """
        Create KYPO default Ansible group entries.

        Default groups: 'hosts', 'management', 'routers', 'winrm_nodes', 'ssh_nodes',
         'user_accessible_nodes', 'hidden_hosts' and 'docker_hosts'.
        """
        man = self.topology_instance.man

        hosts = [self.hosts[node.name] for node in self.topology_instance.get_hosts()]
        self.add_group(Group(DefaultAnsibleHostsGroups.HOSTS.value, hosts))

        self.add_group(Group(DefaultAnsibleHostsGroups.MANAGEMENT.value, [man]))

        routers = [self.hosts[node.name] for node in self.topology_instance.get_routers()]
        self.add_group(Group(DefaultAnsibleHostsGroups.ROUTERS.value, routers))

        winrm_nodes = [self.hosts[node.name] for node in self.topology_instance.get_nodes()
                       if node.base_box.mgmt_protocol == Protocol.WINRM and node != man]
        self.add_group(Group(DefaultAnsibleHostsGroups.WINRM_NODES.value, winrm_nodes))

        ssh_nodes = [self.hosts[node.name] for node in self.topology_instance.get_nodes()
                     if node.base_box.mgmt_protocol == Protocol.SSH and node != man]
        self.add_group(Group(DefaultAnsibleHostsGroups.SSH_NODES.value, ssh_nodes))

        self.add_group(Group(DefaultAnsibleHostsGroups.USER_ACCESSIBLE_NODES.value,
                             self.get_user_accessible_nodes()))

        hidden_hosts = [self.hosts[node.name] for node in self.topology_instance.get_hosts()
                        if node.hidden]
        self.add_group(Group(DefaultAnsibleHostsGroups.HIDDEN_HOSTS.value, hidden_hosts))

        self.docker_hosts = None
        if self.topology_instance.containers:
            self.docker_hosts = [self.hosts[container_mapping.host] for container_mapping
                            in self.topology_instance.containers.container_mappings]
            self.docker_hosts = list(set(self.docker_hosts))
            self.add_group(Group(DefaultAnsibleHostsGroups.DOCKER_HOSTS.value, self.docker_hosts))

    def get_user_accessible_nodes(self) -> List[Host]:
        """
        Create and return user accessible nodes from user accessible networks.
        """
        return [self.hosts[link.node.name] for link in
                self.topology_instance.get_links_to_user_accessible_nodes()]

    def _create_user_defined_groups(self) -> None:
        """
        Create user-defined Ansible group entries.
        """
        for group in self.topology_instance.get_groups():
            self.add_group(Group(group.name, [self.hosts[node_name] for node_name in group.nodes]))

    def _add_user_network_ip_to_user_defined_nodes(self) -> None:
        """
        Add IP of user network as variable for every user defined nodes.
        """
        user_defined_networks = self.topology_instance.get_hosts_networks()
        networks_links = [self.topology_instance.get_network_links(network)
                          for network in user_defined_networks]
        networks_links = chain(*networks_links)

        for link in networks_links:
            if link.node.name == 'uan':
                continue
            self.hosts[link.node.name].add_variables(user_network_ip=link.ip)

    def _update_docker_hosts(self) -> None:
        print("Updating docker hosts")
        docker_host_names = [host.name for host in self.docker_hosts]
        for hostname in self.hosts:
            if hostname in docker_host_names:
                print(f"Found docker host: {hostname}")
                print(f"Docker containers host path: /root/containers/{hostname}/")
                self.get_host(hostname).add_variables(containers_path=f"/root/containers/{hostname}/")

    @staticmethod
    def _get_winrm_connection_variables(mgmt_private_key: str,
                                        mgmt_public_certificate: str) -> dict:
        """
        Return Ansible variables needed for connection with nodes over WinRM protocol.
        """
        return {
            'ansible_connection': 'psrp',
            'ansible_psrp_auth': 'certificate',
            'ansible_psrp_cert_validation': 'ignore',
            'ansible_psrp_certificate_key_pem': mgmt_private_key,
            'ansible_psrp_certificate_pem': mgmt_public_certificate,
            'ansible_psrp_proxy': 'socks5://localhost:12345',
        }
