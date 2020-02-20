import os
from typing import List, Union
import structlog
from ssh_config import Host, SSHConfig

from kypo.openstack_driver.sandbox_topology import SandboxHost, SandboxRouter, \
    SandboxLink, SandboxExtraNode, UAN_NET_NAME, SandboxTopology

from ...sandbox_ansible_app.lib.ansible_service import ANSIBLE_DOCKER_SSH_DIR

from . import sandbox_creator
from ...sandbox_common_lib.config import KypoConfiguration

LOG = structlog.getLogger()

SSH_PROXY_USERNAME = "user-access"


# Add missing SSH Options to ssh_config.Host.attrs
Host.attrs += (
    ('UserKnownHostsFile', str),
    ('StrictHostKeyChecking', str),
)


class KypoSSHConfig(SSHConfig):
    """Subclass of ssh_config.SSHConfig with __str__ method."""

    def __init__(self, stack, config):
        super().__init__('')
        self.stack = stack
        self.config = config

    def __str__(self) -> str:
        res = []
        for host in self.hosts():
            res.append(f'Host {host.name}\n')
            for attr in host.attributes():
                res.append(f'    {attr} {host.get(attr)}\n')
            res.append('\n')
        return "".join(res)

    @staticmethod
    def man_entry(name: Union[str, List[str]], user: str, host_name: str,
                  identity_file: str) -> Host:
        return Host(name, {'User': user,
                           'HostName': host_name,
                           'IdentityFile': identity_file,
                           'AddKeysToAgent': 'yes'})

    @staticmethod
    def host_entry(name: Union[str, List[str]], user: str, host_name: str,
                   proxy_jump: str) -> Host:
        return Host(name, {'User': user,
                           'HostName': host_name,
                           'ProxyJump': proxy_jump})

    @classmethod
    def create_user_config(cls, stack: SandboxTopology, config: KypoConfiguration)\
            -> 'KypoSSHConfig':
        """Generates user ssh config string for sandbox.
        If router has multiple networks, then config contains one router entry
        for each of the networks.
        """
        sshconf = cls(stack, config)
        sshconf.append(cls.man_entry([sshconf.stack.man.name, sshconf.stack.ip],
                                     SSH_PROXY_USERNAME,
                                     stack.ip,
                                     '<path_to_sandbox_private_key>'))

        uan_ip = sshconf._get_uan_ip()
        uan = cls.host_entry([stack.uan.name, uan_ip],
                             SSH_PROXY_USERNAME,
                             uan_ip,
                             SSH_PROXY_USERNAME + '@' + stack.man.name)
        sshconf.append(uan)

        for link in sshconf._get_uan_accessible_node_links():
            sshconf.append(cls.host_entry([link.node.name, link.ip],
                                          SSH_PROXY_USERNAME,
                                          link.ip,
                                          SSH_PROXY_USERNAME + '@' + stack.uan.name))
        return sshconf

    @classmethod
    def create_management_config(cls, stack: SandboxTopology, config: KypoConfiguration)\
            -> 'KypoSSHConfig':
        """Generates management ssh config string for sandbox.
        It uses MNG network for access.
        """
        sshconf = cls(stack, config)
        sshconf.append(cls.man_entry([sshconf.stack.man.name, sshconf.stack.ip],
                                     stack.man.user,
                                     stack.ip,
                                     '<path_to_pool_private_key>'))

        for link in sshconf._get_man_accessible_node_links():
            sshconf.append(cls.host_entry([link.node.name, link.ip],
                                          link.node.user,
                                          link.ip,
                                          stack.man.user + '@' + stack.man.name))
        return sshconf

    @classmethod
    def create_ansible_config(cls, stack: SandboxTopology, config: KypoConfiguration)\
            -> 'KypoSSHConfig':
        """Generates Ansible ssh config string for sandbox."""
        sshconf = cls.create_management_config(stack, config)

        mng_private_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                                       sandbox_creator.MNG_PRIVATE_KEY_FILENAME)
        git_private_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                                       os.path.basename(
                                           config.git_private_key))

        for host in sshconf.hosts():
            host.update(dict(UserKnownHostsFile='/dev/null',
                             StrictHostKeyChecking='no',
                             IdentityFile=mng_private_key))

        sshconf.append(Host(config.git_server, dict(
            User=config.git_user,
            IdentityFile=git_private_key,
            UserKnownHostsFile='/dev/null',
            StrictHostKeyChecking='no')))

        if config.proxy_jump_to_man:
            sshconf.add_proxy_jump()

        return sshconf

    def add_proxy_jump(self):
        jump_host_name = self.config.proxy_jump_to_man.Host
        jump_host_user = self.config.proxy_jump_to_man.User
        jump_host_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                                     os.path.basename(
                                         self.config.proxy_jump_to_man.IdentityFile))

        jump_host = Host(jump_host_name, dict(
            User=jump_host_user,
            IdentityFile=jump_host_key,
            UserKnownHostsFile='/dev/null',
            StrictHostKeyChecking='no'
        ))
        self.append(jump_host)

        # Need to use the full-name
        self.get(" ".join([self.stack.man.name, self.stack.ip])).update(
            {'ProxyJump': jump_host_user + '@' + jump_host_name})

    def _get_uan_ip(self) -> str:
        """Get IP of UAN in UAN_NETWORK."""
        for link in self.stack.links:
            if link.node == self.stack.uan and link.network.name == UAN_NET_NAME:
                return link.ip

    def _get_uan_accessible_node_links(self) -> List[SandboxLink]:
        # Only 'inner' networks UAN is connected to
        networks = [link.network for link in self.stack.get_node_links(self.stack.uan)
                    if link.network.name not in [UAN_NET_NAME, self.stack.mng_net.name]]

        links = [link for link in self.stack.links
                 if link.network in networks
                 and link.node != self.stack.uan
                 and (isinstance(link.node, SandboxHost) or isinstance(link.node, SandboxRouter))]

        return self._sorted_links(links)

    def _get_man_accessible_node_links(self) -> List[SandboxLink]:
        links = [link for link in self.stack.links
                 if link.network == self.stack.mng_net and link.node != self.stack.man]

        return self._sorted_links(links)

    @staticmethod
    def _sorted_links(links: List[SandboxLink]) -> List[SandboxLink]:
        """Return new list of links sorted by the hosts type and then by name."""
        mng_host_links = [link for link in links if isinstance(link.node, SandboxExtraNode)]
        router_links = [link for link in links if isinstance(link.node, SandboxRouter)]
        host_links = [link for link in links if isinstance(link.node, SandboxHost)]
        router_links.sort(key=lambda l: l.node.name)
        host_links.sort(key=lambda l: l.node.name)
        return mng_host_links + router_links + host_links
