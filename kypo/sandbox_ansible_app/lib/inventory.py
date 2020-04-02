from typing import Dict, Tuple, List, Optional, Any

import yaml

from kypo.topology_definition.models import TopologyDefinition

from kypo.openstack_driver.sandbox_topology import SandboxTopology as Stack


class Inventory:
    """This class represents Ansible inventory.

    Use `data` attribute to access the inventory as a dictionary.
    The inventory `vars` section contains by default following attributes:
    - `sandbox_name`
    - `sandbox_ip`
    If you need any extra data in the vars section, pass them as the
    `extra_vars` dictionary to constructor.
    """

    def __init__(self, stack: Stack, top_def: TopologyDefinition, user_priv_key_path: str,
                 user_pub_key_path: str, extra_vars: Optional[Dict[str, Any]] = None):
        router_group, man_routes, br_interfaces = self.create_routers_group(stack, top_def)
        mng_group = self.create_management_group(stack, br_interfaces, man_routes,
                                                 user_priv_key_path, user_pub_key_path)
        host_group = self.create_host_group(stack)

        groups = {
            'management': {'hosts': mng_group},
            'routers': {'hosts': router_group},
            'hosts': {'hosts': host_group},
        }
        self.add_management_ips(stack, groups)

        # set MAN ip to outer IP, not in MNG network
        groups['management']['hosts'][stack.man.name]['ansible_host'] = stack.ip

        groups.update(self.create_user_groups(top_def))

        ans_vars = self._get_vars(stack, extra_vars)
        self.data = {'all': {'children': groups,
                             'vars': ans_vars}}

    def __str__(self):
        return self.serialize()

    @staticmethod
    def route(cidr: str, mask: str, gw: str) -> Dict[str, str]:
        return {'net': cidr.split('/')[0],
                'mask': mask,
                'gw': gw}

    @staticmethod
    def interface(mac: str, def_gw: Optional[str], routes: List[Dict[str, str]]) -> Dict[str, str]:
        return {'mac': mac,
                'def_gw_ip': def_gw,
                'routes': routes}

    @staticmethod
    def router(ip_forward: bool, interfaces: List[Dict], ansible_user: str) -> Dict[str, Any]:
        return {'ip_forward': ip_forward,
                'interfaces': interfaces,
                "ansible_user": ansible_user}

    def serialize(self) -> str:
        """Return YAML representation of Inventory as a string."""
        return yaml.dump(self.data, default_flow_style=False, indent=2)

    @classmethod
    def create_management_group(cls, stack: Stack, br_interfaces: List, man_routes: List,
                                user_priv_key_path: str, user_pub_key_path: str) -> Dict:
        """Get routing information for management nodes."""
        group = {}
        man_uan_link, uan_man_link = \
            [link_tuple for link_tuple in
             stack.get_links_to_network_between_nodes(stack.man, stack.uan)
             if link_tuple[0].network.name == stack.get_uan_network().name][0]
        man_br_link, _ = \
            [link_tuple for link_tuple in
             stack.get_links_to_network_between_nodes(stack.man, stack.br)
             if link_tuple[0].network.name == stack.get_br_network().name][0]

        group[stack.uan.name] = cls.router(
            False,
            [cls.interface(uan_man_link.mac, man_uan_link.ip, [])],
            stack.uan.user
        )
        group[stack.br.name] = cls.router(
            True,
            br_interfaces,
            stack.br.user
        )
        group[stack.man.name] = {
            'ip_forward': True,
            'interfaces': [
                cls.interface(man_br_link.mac, None, man_routes)],
            "ansible_user": stack.man.user,
            'user_private_key_path': user_priv_key_path,
            'user_public_key_path': user_pub_key_path
        }
        return group

    @classmethod
    def create_routers_group(cls, stack: Stack, top_def: TopologyDefinition)\
            -> Tuple[Dict, List, List]:
        """Get routing information for routers and MAN routes and BR interfaces."""
        net_to_router = cls._get_net_to_router(top_def)
        group = dict()
        man_br_link, br_man_link = cls._get_man_br_links(stack)
        man_routes = []
        br_interfaces = [cls.interface(br_man_link.mac, man_br_link.ip, [])]

        br_links_to_routers = [link for link in stack.get_node_links(stack.br)
                               if link.network is not stack.mng_net
                               and link is not br_man_link]
        for br_link in br_links_to_routers:
            for r_link in stack.get_network_links(br_link.network):
                if r_link.node.name not in stack.routers:  # link back to MAN
                    continue
                group[r_link.node.name] = cls.router(True,
                                                     [cls.interface(r_link.mac, br_link.ip, [])],
                                                     r_link.node.user)
                cls._update_man_routes_and_br_interfaces(
                    man_routes, br_interfaces, stack, r_link, br_man_link, br_link, net_to_router)

        return group, man_routes, br_interfaces

    @staticmethod
    def create_host_group(stack: Stack) -> Dict[str, dict]:
        """Get routing information for hosts."""
        group = {}
        for name, host in stack.hosts.items():
            group[name] = {'ansible_user': host.user}
        return group

    @staticmethod
    def create_user_groups(top_def: TopologyDefinition) -> Dict[str, Dict[str, Dict[str, None]]]:
        """Parses user groups from _validated_ definition.
        Return Dict of user groups.
        """
        return {g.name: {'hosts': {node: None for node in g.nodes}}
                for g in top_def.groups}

    @classmethod
    def add_management_ips(cls, stack: Stack, groups: Dict[str, Any]) -> None:
        """Add management IPs to groups routing."""
        mng_ips = cls._get_management_ips(stack)
        for group in groups.values():
            for name, node in group['hosts'].items():
                node['ansible_host'] = mng_ips[name]

    ###################################
    # Private methods
    ###################################

    @staticmethod
    def _get_man_br_links(stack: Stack) -> List:
        return [link_tuple for link_tuple in
                stack.get_links_to_network_between_nodes(stack.man, stack.br)
                if link_tuple[0].network.name == stack.get_br_network().name][0]

    @staticmethod
    def _get_net_to_router(top_def: TopologyDefinition) -> Dict[str, str]:
        """Return Dict[net_name, router_name].
        Prefers router which is first in alphabetical order.
        """
        net_to_router = {}
        mapping = sorted(top_def.router_mappings, key=lambda x: x.router, reverse=True)
        for mapp in mapping:
            net_to_router[mapp.network] = mapp.router
        return net_to_router

    @classmethod
    def _update_man_routes_and_br_interfaces(cls, man_routes, br_interfaces, stack, r_link,
                                             br_man_link, br_link, net_to_router) -> None:
        br_routes = []
        man_routes.append(
            cls.route(r_link.network.cidr, r_link.network.mask, br_man_link.ip))
        for net_link in stack.get_node_links(r_link.node):
            if net_link.network is not stack.mng_net and net_link.network is not r_link.network \
                    and net_to_router[net_link.network.name] == r_link.node.name:
                br_routes.append(
                    cls.route(net_link.network.cidr, net_link.network.mask, r_link.ip)
                )
                man_routes.append(
                    cls.route(net_link.network.cidr, net_link.network.mask,
                              br_man_link.ip)
                )
        br_interfaces.append(cls.interface(br_link.mac, None, br_routes))

    @staticmethod
    def _get_management_ips(stack: Stack) -> Dict[str, str]:
        """Creates dict of `Node name: management IP`."""
        return {link.node.name: link.ip
                for link in stack.get_network_links(stack.mng_net)}

    @staticmethod
    def _get_vars(stack: Stack, extra_vars: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        if extra_vars is None:
            extra_vars = {}
        return dict(
            sandbox_name=stack.name,
            sandbox_ip=stack.ip,
            **extra_vars
        )
