from ipaddress import ip_network
from typing import Dict, Tuple, List, Optional, Any
import yaml

from kypo.openstack_driver.topology_instance import TopologyInstance


class Inventory:
    """This class represents Ansible inventory.

    Use `data` attribute to access the inventory as a dictionary.
    The inventory `vars` section contains by default following attributes:
    - `kypo_global_sandbox_name`
    - `kypo_global_sandbox_ip`
    If you need any extra data in the vars section, pass them as the
    `extra_vars` dictionary to constructor.
    """

    def __init__(self, top_ins: TopologyInstance, user_priv_key_path: str, user_pub_key_path: str,
                 extra_vars: Optional[Dict[str, Any]] = None):
        router_group, man_routes, br_interfaces = self.create_routers_group(top_ins)
        mng_group = self.create_management_group(top_ins, br_interfaces, man_routes,
                                                 user_priv_key_path, user_pub_key_path)
        host_group = self.create_host_group(top_ins)

        groups = {
            'management': {'hosts': mng_group},
            'routers': {'hosts': router_group},
            'hosts': {'hosts': host_group},
        }
        self.add_management_ips(top_ins, groups)

        # set MAN ip to outer IP, not in MNG network
        groups['management']['hosts'][top_ins.man.name]['ansible_host'] = top_ins.ip

        groups.update(self.create_user_groups(top_ins))

        ans_vars = self._get_vars(top_ins, extra_vars)
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
    def create_management_group(cls, top_ins: TopologyInstance, br_interfaces: List,
                                man_routes: List, user_priv_key_path: str,
                                user_pub_key_path: str) -> Dict:
        """Get routing information for management nodes."""
        group = {}

        man_uan_link_pair = top_ins.get_link_pair_man_to_uan_over_uan_network()
        man_uan_link, uan_man_link = man_uan_link_pair.first, man_uan_link_pair.second

        man_br_link = top_ins.get_link_pair_man_to_br_over_br_network().first

        group[top_ins.uan.name] = cls.router(
            False,
            [cls.interface(uan_man_link.mac, man_uan_link.ip, [])],
            top_ins.uan.base_box.man_user
        )
        group[top_ins.br.name] = cls.router(
            True,
            br_interfaces,
            top_ins.br.base_box.man_user
        )
        group[top_ins.man.name] = {
            'ip_forward': True,
            'interfaces': [
                cls.interface(man_br_link.mac, None, man_routes)],
            "ansible_user": top_ins.uan.base_box.man_user,
            'user_private_key_path': user_priv_key_path,
            'user_public_key_path': user_pub_key_path
        }
        return group

    @classmethod
    def create_routers_group(cls, top_ins: TopologyInstance) -> Tuple[Dict, List, List]:
        """Get routing information for routers and MAN routes and BR interfaces."""
        net_to_router = cls._get_net_to_router(top_ins)
        group = dict()
        man_br_link_pair = top_ins.get_link_pair_man_to_br_over_br_network()
        man_br_link, br_man_link = man_br_link_pair.first, man_br_link_pair.second
        man_routes = []
        br_interfaces = [cls.interface(br_man_link.mac, man_br_link.ip, [])]

        br_links_to_routers = [link for link in top_ins.get_node_links(top_ins.br)
                               if link.network is not top_ins.man_network
                               and link is not br_man_link]
        for br_link in br_links_to_routers:
            for r_link in top_ins.get_network_links(br_link.network):
                if r_link.node not in top_ins.get_routers():  # link back to MAN
                    continue
                group[r_link.node.name] = cls.router(True,
                                                     [cls.interface(r_link.mac, br_link.ip, [])],
                                                     r_link.node.base_box.man_user)
                cls._update_man_routes_and_br_interfaces(
                    man_routes, br_interfaces, top_ins, r_link, br_man_link, br_link, net_to_router)

        return group, man_routes, br_interfaces

    @staticmethod
    def create_host_group(top_ins: TopologyInstance) -> Dict[str, dict]:
        """Get routing information for hosts."""
        group = {}
        for host in top_ins.get_hosts():
            group[host.name] = {'ansible_user': host.base_box.man_user}
        return group

    @staticmethod
    def create_user_groups(top_ins: TopologyInstance) -> Dict[str, Dict[str, Dict[str, None]]]:
        """Parses user groups from _validated_ definition.
        Return Dict of user groups.
        """
        return {g.name: {'hosts': {node: None for node in g.nodes}}
                for g in top_ins.get_groups()}

    @classmethod
    def add_management_ips(cls, top_ins: TopologyInstance, groups: Dict[str, Any]) -> None:
        """Add management IPs to groups routing."""
        mng_ips = cls._get_management_ips(top_ins)
        for group in groups.values():
            for name, node in group['hosts'].items():
                node['ansible_host'] = mng_ips[name]

    ###################################
    # Private methods
    ###################################

    @staticmethod
    def _get_net_to_router(top_ins: TopologyInstance) -> Dict[str, str]:
        """Return Dict[net_name, router_name].
        Prefers router which is first in alphabetical order.
        """
        net_to_router = {}
        mapping = sorted(top_ins.topology_definition.router_mappings,
                         key=lambda x: x.router, reverse=True)
        for mapp in mapping:
            net_to_router[mapp.network] = mapp.router
        return net_to_router

    @classmethod
    def _update_man_routes_and_br_interfaces(cls, man_routes, br_interfaces, top_ins, r_link,
                                             br_man_link, br_link, net_to_router) -> None:
        br_routes = []
        man_routes.append(
            cls.route(r_link.network.cidr, cls.get_mask_to_cidr(r_link.network.cidr),
                      br_man_link.ip))
        for net_link in top_ins.get_node_links(r_link.node):
            if net_link.network is not top_ins.man_network and \
                    net_link.network is not r_link.network \
                    and net_to_router[net_link.network.name] == r_link.node.name:
                br_routes.append(
                    cls.route(net_link.network.cidr,
                              cls.get_mask_to_cidr(net_link.network.cidr), r_link.ip)
                )
                man_routes.append(
                    cls.route(net_link.network.cidr, cls.get_mask_to_cidr(net_link.network.cidr),
                              br_man_link.ip)
                )
        br_interfaces.append(cls.interface(br_link.mac, None, br_routes))

    @staticmethod
    def _get_management_ips(top_ins: TopologyInstance) -> Dict[str, str]:
        """Creates dict of `Node name: management IP`."""
        return {link.node.name: link.ip
                for link in top_ins.get_network_links(top_ins.man_network)}

    @staticmethod
    def _get_vars(top_ins: TopologyInstance, extra_vars: Optional[Dict[str, Any]] = None)\
            -> Dict[str, str]:
        if extra_vars is None:
            extra_vars = {}
        return dict(
            kypo_global_sandbox_name=top_ins.name,
            kypo_global_sandbox_ip=top_ins.ip,
            **extra_vars
        )

    @staticmethod
    def get_mask_to_cidr(cidr: str) -> str:
        return str(ip_network(cidr).netmask)
