from typing import List, Union, Optional
import structlog
from ssh_config import Host, SSHConfig

from kypo.topology_definition.models import Host as SandboxHost, Router
from kypo.openstack_driver import TopologyInstance, Link, ExtraNode

from kypo.sandbox_common_lib.kypo_config import KypoConfiguration

LOG = structlog.getLogger()

SSH_PROXY_USERNAME = 'user-access'
SSH_PROXY_KEY = '<path_to_proxy_jump_private_key>'

# Add missing SSH Options to ssh_config.Host.attrs
Host.attrs += (
    ('UserKnownHostsFile', str),
    ('StrictHostKeyChecking', str),
)


class KypoSSHConfig(SSHConfig):
    """Subclass of ssh_config.SSHConfig with __str__ method."""

    def __init__(self):
        super().__init__('')

    def __str__(self):
        return self.serialize()

    def serialize(self) -> str:
        """Return the string representation of KypoSSHConfig."""
        res = []
        for host in self.hosts():
            res.append(f'Host {host.name}\n')
            for attr in host.attributes():
                res.append(f'    {attr} {host.get(attr)}\n')
            res.append('\n')
        return "".join(res)

    def add_man(self, name: Union[str, List[str]], user: str, host_name: str,
                identity_file: str) -> None:
        opts = dict(User=user, HostName=host_name, IdentityFile=identity_file)
        self.append(Host(name, opts))

    def add_host(self, name: Union[str, List[str]], user: str, host_name: str,
                 proxy_jump: str, identity_file: str, **kwargs) -> None:
        opts = dict(User=user, HostName=host_name, IdentityFile=identity_file, ProxyJump=proxy_jump)
        opts.update(kwargs)
        self.append(Host(name, opts))

    def add_git_server(self, name: Union[str, List[str]], user: str, identity_file: str) -> None:
        opts = dict(User=user, IdentityFile=identity_file,
                    UserKnownHostsFile='/dev/null', StrictHostKeyChecking='no')
        self.append(Host(name, opts))

    def add_proxy_jump(self, stack, name: Union[str, List[str]], user: str, key_path: str) -> None:
        opts = dict(User=user, IdentityFile=key_path, UserKnownHostsFile='/dev/null',
                    StrictHostKeyChecking='no')
        jump_host = Host(name, opts)
        self.append(jump_host)

        # Need to use the full-name
        self.get(" ".join([stack.man.name, stack.ip])).update(dict(ProxyJump=user + '@' + name))

    @classmethod
    def create_user_config(cls, top_ins: TopologyInstance, config: KypoConfiguration,
                           sandbox_private_key_path: str = '<path_to_sandbox_private_key>')\
            -> 'KypoSSHConfig':
        """Generates user ssh config string for sandbox.
        If router has multiple networks, then config contains one router entry
        for each of the networks.
        """
        sshconf = cls()
        sshconf.add_man([top_ins.man.name, top_ins.ip],
                        SSH_PROXY_USERNAME,
                        top_ins.ip,
                        sandbox_private_key_path)

        uan_ip = cls._get_uan_ip(top_ins)
        sshconf.add_host([top_ins.uan.name, uan_ip],
                         SSH_PROXY_USERNAME,
                         uan_ip,
                         SSH_PROXY_USERNAME + '@' + top_ins.man.name,
                         sandbox_private_key_path)

        for link in sshconf._get_uan_accessible_node_links(top_ins):
            sshconf.add_host([link.node.name, link.ip],
                             SSH_PROXY_USERNAME,
                             link.ip,
                             SSH_PROXY_USERNAME + '@' + top_ins.uan.name,
                             sandbox_private_key_path)

        if config.proxy_jump_to_man:
            sshconf.add_proxy_jump(top_ins,
                                   config.proxy_jump_to_man.Host,
                                   config.proxy_jump_to_man.User,
                                   SSH_PROXY_KEY)
        return sshconf

    @classmethod
    def create_management_config(cls, top_ins: TopologyInstance, config: KypoConfiguration,
                                 add_jump=True,
                                 pool_private_key_path: str = '<path_to_pool_private_key>')\
            -> 'KypoSSHConfig':
        """Generates management ssh config string for sandbox.
        It uses MNG network for access.
        """
        sshconf = cls()
        sshconf.add_man([top_ins.man.name, top_ins.ip],
                        top_ins.man.base_box.mgmt_user ,
                        top_ins.ip,
                        pool_private_key_path)

        for link in sshconf._get_man_accessible_node_links(top_ins):
            sshconf.add_host([link.node.name, link.ip],
                             link.node.base_box.mgmt_user,
                             link.ip,
                             top_ins.man.base_box.mgmt_user + '@' + top_ins.man.name,
                             pool_private_key_path)

        if add_jump and config.proxy_jump_to_man:
            sshconf.add_proxy_jump(top_ins,
                                   config.proxy_jump_to_man.Host,
                                   config.proxy_jump_to_man.User,
                                   SSH_PROXY_KEY)
        return sshconf

    @classmethod
    def create_ansible_config(cls, top_ins: TopologyInstance, config: KypoConfiguration,
                              mng_key: str, git_key: str,
                              proxy_key: Optional[str] = None) -> 'KypoSSHConfig':
        """Generates Ansible ssh config string for sandbox."""
        sshconf = cls.create_management_config(top_ins, config, add_jump=False)

        for host in sshconf.hosts():
            opts = dict(UserKnownHostsFile='/dev/null',
                        StrictHostKeyChecking='no',
                        IdentityFile=mng_key)
            host.update(opts)

        sshconf.add_git_server(config.git_server,
                               config.git_user,
                               git_key)

        if config.proxy_jump_to_man:
            sshconf.add_proxy_jump(top_ins,
                                   config.proxy_jump_to_man.Host,
                                   config.proxy_jump_to_man.User,
                                   proxy_key)
        return sshconf

    ###################################
    # Private methods
    ###################################

    @staticmethod
    def _get_uan_ip(top_ins: TopologyInstance) -> str:
        """Get IP of UAN in UAN_NETWORK."""
        return top_ins.get_link_between_node_and_network(top_ins.uan, top_ins.uan_network).ip

    @classmethod
    def _get_uan_accessible_node_links(cls, top_ins: TopologyInstance) -> List[Link]:
        """Get links for UAN-accessible nodes."""
        links = [link_pair.second for link_pair in
                 top_ins.get_link_pairs_uan_to_nodes_over_user_accessible_hosts_networks()]
        return cls._sorted_links(links)

    @classmethod
    def _get_man_accessible_node_links(cls, top_ins: TopologyInstance) -> List[Link]:
        """Get links for MAN-accessible nodes using Management network."""
        links = [link_pair.second for link_pair in
                 top_ins.get_link_pairs_man_to_nodes_over_management_network()]
        return cls._sorted_links(links)

    @staticmethod
    def _sorted_links(links: List[Link]) -> List[Link]:
        """Return new list of links sorted by the hosts type and then by name."""
        mng_host_links = [link for link in links if isinstance(link.node, ExtraNode)]
        router_links = [link for link in links if isinstance(link.node, Router)]
        host_links = [link for link in links if isinstance(link.node, SandboxHost)]
        router_links.sort(key=lambda l: l.node.name)
        host_links.sort(key=lambda l: l.node.name)
        return mng_host_links + router_links + host_links
