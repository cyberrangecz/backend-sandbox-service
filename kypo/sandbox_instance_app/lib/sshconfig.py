import os
from typing import List
import structlog
import ssh_config

from kypo2_openstack_lib.sandbox import Host, Router, Link, MAN

from ...sandbox_common_lib.config import config

LOG = structlog.getLogger()

# Add missing SSH Options to ssh_config.Host.attrs
ssh_config.Host.attrs += (
    ('UserKnownHostsFile', str),
    ('StrictHostKeyChecking', str),
)


class KypoSSHConfig(ssh_config.SSHConfig):
    """Subclass of ssh_config.SSHConfig with __str__ method."""

    def __init__(self, stack):
        super().__init__(None)
        self.stack = stack

    def __str__(self) -> str:
        res = []
        for host in self.hosts():
            res.append(f'Host {host.name}\n')
            for attr in host.attributes():
                res.append(f'    {attr} {host.get(attr)}\n')
            res.append('\n')
        return "".join(res)

    @classmethod
    def create_user_config(cls, stack) -> 'KypoSSHConfig':
        """Generates user ssh config string for sandbox.
        If router has multiple networks, then config contains one router entry
        for each of the networks.
        """
        sshconf = cls(stack)
        man = ssh_config.Host([sshconf.stack.man.name, sshconf.stack.ip], dict(
            User=config.SSH_PROXY_USERNAME, HostName=sshconf.stack.ip,
            IdentityFile='<path_to_sandbox_private_key>',
            AddKeysToAgent='yes'))
        sshconf.append(man)

        uan_ip = sshconf._get_uan_ip()
        uan = ssh_config.Host([stack.uan.name, uan_ip], dict(
            User=config.SSH_PROXY_USERNAME, HostName=uan_ip,
            ProxyJump=config.SSH_PROXY_USERNAME + '@' + stack.man.name))
        sshconf.append(uan)

        for link in sshconf._get_uan_accessible_node_links():
            sshconf.append(ssh_config.Host([link.node.name, link.ip], dict(
                User=config.SSH_PROXY_USERNAME, HostName=link.ip,
                ProxyJump=config.SSH_PROXY_USERNAME + '@' +
                          stack.uan.name)))
        return sshconf

    @classmethod
    def create_management_config(cls, stack) -> 'KypoSSHConfig':
        """Generates management ssh config string for sandbox.
        It uses MNG network for access.
        """
        sshconf = cls(stack)
        man = ssh_config.Host([stack.man.name, stack.ip], dict(
            User=stack.man.user, HostName=stack.ip,
            IdentityFile='<path_to_pool_private_key>',
            AddKeysToAgent='yes'))
        sshconf.append(man)

        for link in sshconf._get_man_accessible_node_links():
            sshconf.append(ssh_config.Host([link.node.name, link.ip], dict(
                User=link.node.user, HostName=link.ip,
                ProxyJump=stack.man.user + '@' + stack.man.name)))

        return sshconf

    @classmethod
    def create_ansible_config(cls, stack) -> 'KypoSSHConfig':
        """Generates Ansible ssh config string for sandbox."""
        sshconf = cls.create_management_config(stack)

        mng_private_key = os.path.join(config.ANSIBLE_DOCKER_VOLUMES_MAPPING['SSH_DIR']['bind'],
                                       config.MNG_PRIVATE_KEY_FILENAME)
        git_private_key = os.path.join(config.ANSIBLE_DOCKER_VOLUMES_MAPPING['SSH_DIR']['bind'],
                                       os.path.basename(config.GIT_PRIVATE_KEY))

        for host in sshconf.hosts():
            host.update(dict(UserKnownHostsFile='/dev/null',
                             StrictHostKeyChecking='no',
                             IdentityFile=mng_private_key))

        sshconf.append(ssh_config.Host(config.GIT_SERVER, dict(
            User=config.GIT_USER, IdentityFile=git_private_key,
            UserKnownHostsFile='/dev/null', StrictHostKeyChecking='no')))

        if config.PROXY_JUMP_TO_MAN_SSH_OPTIONS:
            proxy_jump_to_man_private_key = os.path.join(
                config.ANSIBLE_DOCKER_VOLUMES_MAPPING['SSH_DIR']['bind'],
                os.path.basename(config.PROXY_JUMP_TO_MAN_PRIVATE_KEY))

            jump_host_name = config.PROXY_JUMP_TO_MAN_SSH_OPTIONS.get('Host')
            jump_host_user = config.PROXY_JUMP_TO_MAN_SSH_OPTIONS.get('User')
            jump_host = ssh_config.Host(jump_host_name, dict(
                USER=jump_host_user,
                IdentityFile=proxy_jump_to_man_private_key,
                UserKnownHostsFile='/dev/null', StrictHostKeyChecking='no'))
            sshconf.append(jump_host)

            # Need to use the full-name
            sshconf.get(" ".join([stack.man.name, stack.ip])).update(
                {'ProxyJump': jump_host_user + '@' + jump_host_name})

        return sshconf

    def _get_uan_ip(self) -> str:
        """Get IP of UAN in UAN_NETWORK."""
        for link in self.stack.links:
            if link.node == self.stack.uan and link.network.name == config.UAN_NETWORK_NAME:
                return link.ip

    def _get_uan_accessible_node_links(self) -> List[Link]:
        # Only 'inner' networks UAN is connected to
        networks = [link.network for link in self.stack.get_node_links(self.stack.uan)
                    if link.network.name not in [config.UAN_NETWORK_NAME, self.stack.mng_net.name]]

        links = [link for link in self.stack.links
                 if link.network in networks
                 and link.node != self.stack.uan
                 and (isinstance(link.node, Host) or isinstance(link.node, Router))]

        return self._sorted_links(links)

    def _get_man_accessible_node_links(self) -> List[Link]:
        links = [link for link in self.stack.links
                 if link.network == self.stack.mng_net and link.node != self.stack.man]

        return self._sorted_links(links)

    @staticmethod
    def _sorted_links(links: List[Link]) -> List[Link]:
        """Return new list of links sorted by the hosts type and then by name."""
        mng_host_links = [link for link in links if isinstance(link.node, MAN)]
        router_links = [link for link in links if isinstance(link.node, Router)]
        host_links = [link for link in links if isinstance(link.node, Host)]
        router_links.sort(key=lambda l: l.node.name)
        host_links.sort(key=lambda l: l.node.name)
        return mng_host_links + router_links + host_links
