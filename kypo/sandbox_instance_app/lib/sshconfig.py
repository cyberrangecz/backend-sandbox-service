from typing import List, Union, Optional
import structlog
from ssh_config import Host, SSHConfig

from kypo.openstack_driver.sandbox_topology import SandboxHost, SandboxRouter, \
    SandboxLink, SandboxExtraNode, UAN_NET_NAME, SandboxTopology

from kypo.sandbox_common_lib.config import KypoConfiguration

LOG = structlog.getLogger()

SSH_PROXY_USERNAME = 'user-access'
SSH_PROXY_KEY = '<path to proxy jump private key>'

Hostname = Union[str, List[str]]

# Add missing SSH Options to ssh_config.Host.attrs
Host.attrs += (
    ('UserKnownHostsFile', str),
    ('StrictHostKeyChecking', str),
)


class KypoSSHConfig(SSHConfig):
    """Subclass of ssh_config.SSHConfig with __str__ method."""

    def __init__(self):
        super().__init__('')

    def __str__(self) -> str:
        res = []
        for host in self.hosts():
            res.append(f'Host {host.name}\n')
            for attr in host.attributes():
                res.append(f'    {attr} {host.get(attr)}\n')
            res.append('\n')
        return "".join(res)

    def add_man(self, name: Union[str, List[str]], user: str, host_name: str,
                identity_file: str) -> None:
        self.append(Host(name, {'User': user,
                                'HostName': host_name,
                                'IdentityFile': identity_file,
                                'AddKeysToAgent': 'yes'}))

    def add_host(self, name: Union[str, List[str]], user: str, host_name: str,
                 proxy_jump: str, **kwargs) -> None:
        options = {'User': user,
                   'HostName': host_name,
                   'ProxyJump': proxy_jump}
        options.update(kwargs)
        self.append(Host(name, options))

    def add_git_server(self, name: Union[str, List[str]], user: str, identity_file: str) -> None:
        self.append(Host(name, {'User': user,
                                'IdentityFile': identity_file,
                                'UserKnownHostsFile': '/dev/null',
                                'StrictHostKeyChecking': 'no'}))

    def add_proxy_jump(self, stack, name: Union[str, List[str]], user: str, key_path: str) -> None:
        jump_host = Host(name, dict(
            User=user,
            IdentityFile=key_path,
            UserKnownHostsFile='/dev/null',
            StrictHostKeyChecking='no'
        ))
        self.append(jump_host)

        # Need to use the full-name
        self.get(" ".join([stack.man.name, stack.ip])).update(
            {'ProxyJump': user + '@' + name})

    @classmethod
    def create_user_config(cls, stack: SandboxTopology, config: KypoConfiguration)\
            -> 'KypoSSHConfig':
        """Generates user ssh config string for sandbox.
        If router has multiple networks, then config contains one router entry
        for each of the networks.
        """
        sshconf = cls()
        sshconf.add_man([stack.man.name, stack.ip],
                        SSH_PROXY_USERNAME,
                        stack.ip,
                        '<path_to_sandbox_private_key>')

        uan_ip = cls._get_uan_ip(stack)
        sshconf.add_host([stack.uan.name, uan_ip],
                         SSH_PROXY_USERNAME,
                         uan_ip,
                         SSH_PROXY_USERNAME + '@' + stack.man.name)

        for link in sshconf._get_uan_accessible_node_links(stack):
            sshconf.add_host([link.node.name, link.ip],
                             SSH_PROXY_USERNAME,
                             link.ip,
                             SSH_PROXY_USERNAME + '@' + stack.uan.name)

        if config.proxy_jump_to_man:
            sshconf.add_proxy_jump(stack,
                                   config.proxy_jump_to_man.Host,
                                   config.proxy_jump_to_man.User,
                                   SSH_PROXY_KEY)
        return sshconf

    @classmethod
    def create_management_config(cls, stack: SandboxTopology, config: KypoConfiguration,
                                 add_jump=True)\
            -> 'KypoSSHConfig':
        """Generates management ssh config string for sandbox.
        It uses MNG network for access.
        """
        sshconf = cls()
        sshconf.add_man([stack.man.name, stack.ip],
                        stack.man.user,
                        stack.ip,
                        '<path_to_pool_private_key>')

        for link in sshconf._get_man_accessible_node_links(stack):
            sshconf.add_host([link.node.name, link.ip],
                             link.node.user,
                             link.ip,
                             stack.man.user + '@' + stack.man.name)

        if add_jump and config.proxy_jump_to_man:
            sshconf.add_proxy_jump(stack,
                                   config.proxy_jump_to_man.Host,
                                   config.proxy_jump_to_man.User,
                                   SSH_PROXY_KEY)
        return sshconf

    @classmethod
    def create_ansible_config(cls, stack: SandboxTopology, config: KypoConfiguration,
                              mng_key: str, git_key: str,
                              proxy_key: Optional[str] = None) -> 'KypoSSHConfig':
        """Generates Ansible ssh config string for sandbox."""
        sshconf = cls.create_management_config(stack, config, add_jump=False)

        for host in sshconf.hosts():
            host.update(dict(UserKnownHostsFile='/dev/null',
                             StrictHostKeyChecking='no',
                             IdentityFile=mng_key))

        sshconf.add_git_server(config.git_server,
                               config.git_user,
                               git_key)

        if config.proxy_jump_to_man:
            sshconf.add_proxy_jump(stack,
                                   config.proxy_jump_to_man.Host,
                                   config.proxy_jump_to_man.User,
                                   proxy_key)
        return sshconf

    ###################################
    # Private methods
    ###################################

    @staticmethod
    def _get_uan_ip(stack: SandboxTopology) -> str:
        """Get IP of UAN in UAN_NETWORK."""
        for link in stack.links:
            if link.node == stack.uan and link.network.name == UAN_NET_NAME:
                return link.ip

    @classmethod
    def _get_uan_accessible_node_links(cls, stack: SandboxTopology) -> List[SandboxLink]:
        # Only 'inner' networks UAN is connected to
        networks = [link.network for link in stack.get_node_links(stack.uan)
                    if link.network.name not in [UAN_NET_NAME, stack.mng_net.name]]

        links = [link for link in stack.links
                 if link.network in networks
                 and link.node != stack.uan
                 and (isinstance(link.node, SandboxHost) or isinstance(link.node, SandboxRouter))]

        return cls._sorted_links(links)

    @classmethod
    def _get_man_accessible_node_links(cls, stack: SandboxTopology) -> List[SandboxLink]:
        links = [link for link in stack.links
                 if link.network == stack.mng_net and link.node != stack.man]

        return cls._sorted_links(links)

    @staticmethod
    def _sorted_links(links: List[SandboxLink]) -> List[SandboxLink]:
        """Return new list of links sorted by the hosts type and then by name."""
        mng_host_links = [link for link in links if isinstance(link.node, SandboxExtraNode)]
        router_links = [link for link in links if isinstance(link.node, SandboxRouter)]
        host_links = [link for link in links if isinstance(link.node, SandboxHost)]
        router_links.sort(key=lambda l: l.node.name)
        host_links.sort(key=lambda l: l.node.name)
        return mng_host_links + router_links + host_links
