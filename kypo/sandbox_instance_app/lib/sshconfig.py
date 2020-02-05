from typing import List

import structlog
from kypo2_openstack_lib.sandbox import Host, Router, Link, MAN

from ..models import Sandbox
from ...sandbox_common_lib import sshconfig
from ...sandbox_common_lib import utils
from ...sandbox_common_lib.config import config

LOG = structlog.getLogger()


class SandboxSSHConfigCreator:
    """Class for creation of SSH config."""

    def __init__(self, sandbox: Sandbox):
        stack_name = sandbox.get_stack_name()
        client = utils.get_ostack_client()
        self.stack = client.get_sandbox(stack_name)

    def create_user_config(self) -> sshconfig.Config:
        """Generates user ssh config string for sandbox. If router has multiple networks,
        then config contains one router entry for each of the networks."""

        user_ssh_config = sshconfig.Config()
        user_ssh_config.add_entry(Host='{0} {1}'.format(self.stack.man.name, self.stack.ip),
                                  User=config.SSH_PROXY_USERNAME, HostName=self.stack.ip,
                                  IdentityFile='<path_to_sandbox_private_key>',
                                  AddKeysToAgent='yes')
        uan_ip = self._get_uan_ip()
        user_ssh_config.add_entry(Host='{0} {1}'.format(self.stack.uan.name, uan_ip),
                                  User=config.SSH_PROXY_USERNAME, HostName=uan_ip,
                                  ProxyJump=config.SSH_PROXY_USERNAME + '@' + self.stack.man.name)

        for link in self._get_uan_accessible_node_links():
            user_ssh_config.add_entry(Host='{0} {1}'.format(link.node.name, link.ip),
                                      User=config.SSH_PROXY_USERNAME, HostName=link.ip,
                                      ProxyJump=config.SSH_PROXY_USERNAME + '@' + self.stack.uan.name)
        return user_ssh_config

    def create_management_config(self) -> sshconfig.Config:
        """Generates management ssh config string for sandbox. It uses MNG network for access."""
        management_ssh_config = sshconfig.Config()
        management_ssh_config.add_entry(Host='{0} {1}'.format(self.stack.man.name, self.stack.ip),
                                        User=self.stack.man.user, HostName=self.stack.ip,
                                        IdentityFile='<path_to_pool_private_key>',
                                        AddKeysToAgent='yes')

        for link in self._get_man_accessible_node_links():
            management_ssh_config.add_entry(Host='{0} {1}'.format(link.node.name, link.ip),
                                            User=link.node.user, HostName=link.ip,
                                            ProxyJump=self.stack.man.user + '@' + self.stack.man.name)
        return management_ssh_config

    def _get_uan_ip(self) -> str:
        """Get link of UAN in UAN_NETWORK."""
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
