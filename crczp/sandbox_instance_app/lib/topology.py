from typing import List

import structlog
from crczp.cloud_commons import TopologyInstance

from crczp.sandbox_common_lib.common_cloud import list_images
from crczp.sandbox_instance_app.lib.nodes import find_image_for_node, get_node_image_has_gui_access

LOG = structlog.getLogger()


class Topology(object):
    """Represents a topology of a sandbox."""

    class HostNode(object):
        def __init__(self, name, os_type, gui_access, is_accessible, ip):
            """
            Initialize a HostNode instance.

            :param str name: The name of the host
            :param str os_type: The operating system type
            :param bool gui_access: Whether GUI access is available
            :param str ip: The IP address of the host
            """
            self.name = name
            self.os_type = os_type
            self.gui_access = gui_access
            self.is_accessible = is_accessible
            self.ip = ip

    class RouterNode(HostNode):
        def __init__(self, name, os_type, gui_access, subnets, is_accessible, ip):
            """
            Initialize a RouterNode instance.

            :param str name: The name of the router
            :param str os_type: The operating system type
            :param bool gui_access: Whether GUI access is available
            :param subnets: List of subnets connected to this router
            :type subnets: List[Topology.Subnet]
            :param str ip: The IP address of the router
            """
            super().__init__(name, os_type, gui_access,is_accessible, ip)
            self.subnets = subnets

    class Subnet(object):
        def __init__(self, name, cidr, hosts):
            """
            Initialize a Subnet instance.

            :param str name: The name of the subnet
            :param str cidr: The subnet CIDR mask
            :param hosts: List of hosts in this subnet
            :type hosts: List[Topology.HostNode]
            """
            self.name = name
            self.cidr = cidr
            self.hosts = hosts

    def __init__(self, top_inst):
        """
        Initialize a Topology instance.

        :param TopologyInstance top_inst: The topology instance to build from
        """
        self.routers = []
        self._build_topology(top_inst)

    def _build_topology(self, top_inst):
        """
        Build the complete topology structure from TopologyInstance.

        :param TopologyInstance top_inst: The topology instance to build from
        """
        images = list_images()
        subnets_dict = self._create_subnets_with_hosts(top_inst, images)
        self._create_routers_with_subnets(top_inst, images, subnets_dict)

    def _create_subnets_with_hosts(self, top_inst, images):
        """
        Create all subnets and populate them with hosts.

        :param TopologyInstance top_inst: The topology instance
        :param images: List of available images
        :type images: list
        :return: Dictionary mapping subnet names to subnet objects
        :rtype: dict[str, Topology.Subnet]
        """
        subnets_dict = {}

        for network in top_inst.get_visible_networks():
            if self._is_wan_network(network):
                continue

            hosts_in_network = self._get_hosts_for_network(network, top_inst, images)
            subnet = self.Subnet(
                name=network.name,
                cidr=network.cidr,
                hosts=hosts_in_network
            )
            subnets_dict[network.name] = subnet

        return subnets_dict

    def _create_routers_with_subnets(self, top_inst, images, subnets_dict):
        """
        Create routers and assign their connected subnets.

        :param TopologyInstance top_inst: The topology instance
        :param images: List of available images
        :type images: list
        :param subnets_dict: Dictionary mapping subnet names to subnet objects
        :type subnets_dict: dict[str, Topology.Subnet]
        """
        for router_node in top_inst.get_visible_routers():
            router_image = find_image_for_node(router_node, images)
            if router_image is None:
                continue

            router_subnets = self._get_subnets_for_router(router_node, top_inst, subnets_dict)

            wan_link = top_inst.get_link_between_node_and_network(router_node, top_inst.wan)
            wan_ip = wan_link.ip if wan_link else None

            router = self.RouterNode(
                name=router_node.name,
                os_type=router_image.os_type,
                gui_access=get_node_image_has_gui_access(router_image),
                subnets=router_subnets,
                is_accessible=True,
                ip=wan_ip
            )
            self.routers.append(router)

    def _is_wan_network(self, network):
        """
        Check if network is a WAN network that should be ignored.

        :param network: The network object to check
        :return: True if network is WAN, False otherwise
        :rtype: bool
        """
        return network.name.lower() == 'wan'

    def _get_hosts_for_network(self, network, top_inst, images):
        """
        Get all hosts connected to a specific network.

        :param network: The network object
        :param TopologyInstance top_inst: The topology instance
        :param images: List of available images
        :type images: list
        :return: List of host nodes in the network
        :rtype: list[Topology.HostNode]
        """
        hosts_in_network = []

        for link in top_inst.get_network_links(network, top_inst.get_visible_hosts()):
            host_node = link.node
            host_image = find_image_for_node(host_node, images)

            if host_image is None:
                continue

            host = self.HostNode(
                name=host_node.name,
                os_type=host_image.os_type,
                gui_access=get_node_image_has_gui_access(host_image),
                is_accessible=network.accessible_by_user,
                ip=link.ip
            )
            hosts_in_network.append(host)

        return hosts_in_network

    def _get_subnets_for_router(self, router_node, top_inst, subnets_dict):
        """
        Get all subnets connected to a specific router.

        :param router_node: The router node object
        :param TopologyInstance top_inst: The topology instance
        :param subnets_dict: Dictionary mapping subnet names to subnet objects
        :type subnets_dict: dict[str, Topology.Subnet]
        :return: List of subnets connected to the router
        :rtype: list[Topology.Subnet]
        """
        router_subnets = []

        for link in top_inst.get_node_links(router_node, top_inst.get_hosts_networks()):
            if self._is_wan_network(link.network):
                continue

            if link.network.name in subnets_dict:
                router_subnets.append(subnets_dict[link.network.name])

        return router_subnets

    def get_hosts(self):
        """
        Get all hosts from all routers' subnets.

        :return: List of all host nodes in the topology
        :rtype: list[Topology.HostNode]
        """
        all_hosts = []
        for router in self.routers:
            for subnet in router.subnets:
                all_hosts.extend(subnet.hosts)
        return all_hosts