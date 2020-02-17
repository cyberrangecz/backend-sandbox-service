from typing import Dict, Tuple, List, Optional, Any

from kypo.topology_definition.models import TopologyDefinition

from kypo.openstack_driver.sandbox_topology import SandboxTopology as Stack


class Inventory:
    """CLass for Ansible inventory creation."""

    @staticmethod
    def route_dict(cidr: str, mask: str, gw: str) -> Dict[str, str]:
        return {'net': cidr.split('/')[0],
                'mask': mask,
                'gw': gw}

    @staticmethod
    def interface_dict(mac: str, def_gw: Optional[str], routes: List[Dict[str, str]])\
            -> Dict[str, str]:
        return {'mac': mac,
                'def_gw_ip': def_gw,
                'routes': routes}

    @classmethod
    def create_inventory(cls, stack: Stack, top_def: TopologyDefinition,
                         user_private_key_path: str, user_public_key_path: str) -> Dict[str, Any]:
        """
        Creates ansible inventory.

        :return: Dict representation of Ansible inventory file
        """
        net_to_router = cls.get_net_to_router(top_def)
        routers_routing, man_routes, br_interfaces = cls.create_routers_group(stack, net_to_router)
        mng_routing = cls.create_management_group(stack, br_interfaces, man_routes,
                                                  user_private_key_path, user_public_key_path)
        host_routing = cls.create_host_group(stack)

        routing = {
            'management': {'hosts': mng_routing},
            'routers': {'hosts': routers_routing},
            'hosts': {'hosts': host_routing},
        }
        cls.add_management_ips(stack, routing)

        # set MAN ip to outer IP, not in MNG network
        routing['management']['hosts'][stack.man.name]['ansible_host'] = stack.ip

        routing.update(cls.create_user_groups(top_def))

        inventory = {'all': {'children': routing}}
        return inventory

    @staticmethod
    def get_management_ips(stack: Stack) -> Dict[str, str]:
        """Creates dict of `Node name: management IP`."""
        return {link.node.name: link.ip
                for link in stack.get_network_links(stack.mng_net)}

    @classmethod
    def add_management_ips(cls, stack: Stack, routing: Dict[str, Any]) -> None:
        """Add management IPs to routing"""
        mng_ips = cls.get_management_ips(stack)
        for group in routing.values():
            for name, node in group['hosts'].items():
                node['ansible_host'] = mng_ips[name]

    @classmethod
    def create_management_group(cls, stack: Stack, br_interfaces: List, man_routes: List,
                                user_private_key_path: str, user_public_key_path: str) -> Dict:
        """Get routing information for management nodes."""
        routing = {}
        man_uan_link, uan_man_link = \
            [link_tuple for link_tuple in
             stack.get_links_to_network_between_nodes(stack.man, stack.uan)
             if link_tuple[0].network.name == stack.get_uan_network().name][0]
        man_br_link, _ = \
            [link_tuple for link_tuple in
             stack.get_links_to_network_between_nodes(stack.man, stack.br)
             if link_tuple[0].network.name == stack.get_br_network().name][0]

        routing[stack.uan.name] = {
            "ip_forward": False,
            "interfaces": [cls.interface_dict(uan_man_link.mac, man_uan_link.ip, [])],
            "ansible_user": stack.uan.user,
        }
        routing[stack.br.name] = {
            'ip_forward': True,
            'interfaces': br_interfaces,
            "ansible_user": stack.br.user,
        }
        routing[stack.man.name] = {
            'ip_forward': True,
            'interfaces': [
                cls.interface_dict(man_br_link.mac, None, man_routes)],
            "ansible_user": stack.man.user,
            'user_private_key_path': user_private_key_path,
            'user_public_key_path': user_public_key_path
        }
        return routing

    @classmethod
    def create_routers_group(cls, stack: Stack, net_to_router: Dict[str, str]) -> Tuple[Dict, List, List]:
        """Get routing information for routers
        and MAN routes and BR interfaces."""
        routing = dict()
        man_br_link, br_man_link = \
            [link_tuple for link_tuple in
             stack.get_links_to_network_between_nodes(stack.man, stack.br)
             if link_tuple[0].network.name == stack.get_br_network().name][0]
        man_routes = []
        br_interfaces = [cls.interface_dict(br_man_link.mac, man_br_link.ip, [])]

        br_links_to_routers = [link for link in stack.get_node_links(stack.br)
                               if link.network is not stack.mng_net
                               and link is not br_man_link]
        for br_link in br_links_to_routers:
            for r_link in stack.get_network_links(br_link.network):
                if r_link.node.name not in stack.routers:  # link back to MAN
                    continue
                routing[r_link.node.name] = {
                    'ip_forward': True,
                    'interfaces': [cls.interface_dict(r_link.mac, br_link.ip, [])],
                    "ansible_user": r_link.node.user,
                }
                # Update MAN routes and BR interfaces
                br_routes = []
                man_routes.append(
                    cls.route_dict(r_link.network.cidr, r_link.network.mask, br_man_link.ip))
                for net_link in stack.get_node_links(r_link.node):
                    if net_link.network is not stack.mng_net and net_link.network is not r_link.network\
                            and net_to_router[net_link.network.name] == r_link.node.name:
                        br_routes.append(
                            cls.route_dict(net_link.network.cidr, net_link.network.mask, r_link.ip)
                        )
                        man_routes.append(
                            cls.route_dict(net_link.network.cidr, net_link.network.mask,
                                           br_man_link.ip)
                        )
                br_interfaces.append(cls.interface_dict(br_link.mac, None, br_routes))

        return routing, man_routes, br_interfaces

    @staticmethod
    def get_net_to_router(top_def: TopologyDefinition) -> Dict[str, str]:
        """
        Return Dict[net_name, router_name].
        Prefers router which is first in alphabetical order.
        """
        net_to_router = {}
        # if 'router_mappings' in definition:
        mapping = sorted(top_def.router_mappings, key=lambda x: x.router, reverse=True)
        for mapp in mapping:
            net_to_router[mapp.network] = mapp.router
        return net_to_router

    @staticmethod
    def create_host_group(stack: Stack) -> Dict[str, dict]:
        """Get routing information for hosts."""
        routing = {}
        for name, host in stack.hosts.items():
            routing[name] = {}
            routing[name]['ansible_user'] = host.user
        return routing

    @staticmethod
    def create_user_groups(top_def: TopologyDefinition) -> Dict[str, Dict[str, Dict[str, None]]]:
        """Parses user groups from _validated_ definition.
        Return Dict of user groups."""
        return {g.name: {'hosts': {node: None for node in g.nodes}}
                for g in top_def.groups}
