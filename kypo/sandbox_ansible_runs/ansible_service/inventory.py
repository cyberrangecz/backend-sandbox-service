from typing import Dict, Tuple, List, Optional, Any

from kypo2_openstack_lib.sandbox import Sandbox as Stack


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
    def create_inventory(cls, stack: Stack, definition: Dict, user_private_key_path: str,
                         user_public_key_path: str) -> Dict[str, Any]:
        """
        Creates ansible inventory.

        :return: Dict representation of Ansible inventory file
        """
        routers_routing, smn_routes, br_interfaces = cls.create_routers_group(stack)
        mng_routing = cls.create_management_group(stack, br_interfaces, smn_routes,
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

        routing.update(cls.create_user_groups(definition))

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
    def create_management_group(cls, stack: Stack, br_interfaces: List, smn_routes: List,
                                user_private_key_path: str, user_public_key_path: str) -> Dict:
        """Get routing information for management nodes."""
        routing = {}
        smn_uan_link, uan_smn_link = \
            [link_tuple for link_tuple in
             stack.get_links_to_network_between_nodes(stack.man, stack.uan)
             if link_tuple[0].network.name == stack.get_uan_network().name][0]
        smn_br_link, _ = \
            [link_tuple for link_tuple in
             stack.get_links_to_network_between_nodes(stack.man, stack.br)
             if link_tuple[0].network.name == stack.get_br_network().name][0]

        routing[stack.uan.name] = {
            "ip_forward": False,
            "interfaces": [cls.interface_dict(uan_smn_link.mac, smn_uan_link.ip, [])],
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
                cls.interface_dict(smn_br_link.mac, None, smn_routes)],
            "ansible_user": stack.man.user,
            'user_private_key_path': user_private_key_path,
            'user_public_key_path': user_public_key_path
        }
        return routing

    @classmethod
    def create_routers_group(cls, stack: Stack) -> Tuple[Dict, List, List]:
        """Get routing information for routers
        and SMN routes and BR interfaces."""
        routing = dict()
        smn_br_link, br_smn_link = \
            [link_tuple for link_tuple in
             stack.get_links_to_network_between_nodes(stack.man, stack.br)
             if link_tuple[0].network.name == stack.get_br_network().name][0]
        smn_routes = []
        br_interfaces = [cls.interface_dict(br_smn_link.mac, smn_br_link.ip, [])]

        br_links_to_routers = [link for link in stack.get_node_links(stack.br)
                               if link.network is not stack.mng_net
                               and link is not br_smn_link]

        for br_link in br_links_to_routers:
            for r_link in stack.get_network_links(br_link.network):
                if r_link.node.name not in stack.routers:  # link back to SMN
                    continue
                routing[r_link.node.name] = {
                    'ip_forward': True,
                    'interfaces': [cls.interface_dict(r_link.mac, br_link.ip, [])],
                    "ansible_user": r_link.node.user,
                }
                # Update SMN routes and BR interfaces
                br_routes = []
                smn_routes.append(
                    cls.route_dict(r_link.network.cidr, r_link.network.mask, br_smn_link.ip))
                for net_link in stack.get_node_links(r_link.node):
                    if net_link.network is not stack.mng_net and net_link.network is not r_link.network:
                        br_routes.append(
                            cls.route_dict(net_link.network.cidr, net_link.network.mask,
                                           r_link.ip))
                        smn_routes.append(
                            cls.route_dict(net_link.network.cidr, net_link.network.mask,
                                           br_smn_link.ip))
                br_interfaces.append(cls.interface_dict(br_link.mac, None, br_routes))

        return routing, smn_routes, br_interfaces

    @staticmethod
    def create_host_group(stack: Stack) -> Dict[str, dict]:
        """Get routing information for hosts."""
        routing = {}
        for name, host in stack.hosts.items():
            routing[name] = {}
            routing[name]['ansible_user'] = host.user
        return routing

    @staticmethod
    def create_user_groups(definition: Dict[str, Dict]) -> Dict[str, Dict[str, Dict[str, None]]]:
        """Parses user groups from _validated_ definition.
        Return Dict of user groups."""
        groups = {}
        for node in definition.get('hosts', []) + definition.get('routers', []):
            for group in node.get('groups', []):
                if group in groups:
                    groups[group]['hosts'].update({node['name']: None})
                else:
                    groups[group] = {'hosts': {node['name']: None}}
        return groups
