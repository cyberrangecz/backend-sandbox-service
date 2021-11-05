from typing import List
import structlog
from ssh_config.client import Host, SSHConfig, EmptySSHConfig, WrongSSHConfig

from kypo.openstack_driver import TopologyInstance, Link

LOG = structlog.getLogger()

SSH_PROXY_USERNAME = 'user-access'
SSH_PROXY_KEY = '<path_to_proxy_jump_private_key>'

# Add missing SSH Options to ssh_config.Host.attrs
Host.attrs += (
    ('UserKnownHostsFile', str),
    ('StrictHostKeyChecking', str),
    ('IdentitiesOnly', str),
)


class KypoSSHConfig(SSHConfig):
    """
    Represents SSH config file for KYPO purposes.
    """
    def __str__(self):
        return '\n'.join([str(host) for host in self.hosts()]) + '\n'

    def serialize(self) -> str:
        """
        Return the string representation of KypoSSHConfig.
        """
        return str(self)

    def add_host(self, host_name: str, user: str, identity_file: str,
                 proxy_jump: str = None, alias: str = None, **kwargs) -> None:
        """
        Create and add ssh_config.Host instance to this SSH config file.
        """
        opts = dict(HostName=host_name, User=user, IdentityFile=identity_file,
                    UserKnownHostsFile='/dev/null', StrictHostKeyChecking='no',
                    IdentitiesOnly='yes')
        if proxy_jump:
            opts.update(dict(ProxyJump=proxy_jump))
        opts.update(kwargs)
        host = Host([alias, host_name] if alias else host_name, opts)
        self.append(host)

    @classmethod
    def from_str(cls, ssh_config):
        """
        Load SSH config file from string.
        """
        self = cls('')

        self.raw = ssh_config
        if len(self.raw) <= 0:
            raise EmptySSHConfig(ssh_config)
        parsed = self.parse()
        if parsed is None:
            raise WrongSSHConfig(ssh_config)
        for name, config in sorted(parsed.asDict().items()):
            attrs = dict()
            for attr in config:
                attrs.update(attr)
            self.append(Host(name, attrs))
        return self


class KypoUserSSHConfig(KypoSSHConfig):
    """
    Represents SSH config file used by KYPO trainees.
    """
    def __init__(self, top_ins: TopologyInstance, proxy_host: str, proxy_user: str,
                 sandbox_private_key_path: str = '<path_to_sandbox_private_key>'):
        super().__init__('')

        # Create an entry for KYPO PROXY JUMP host.
        self.add_host(proxy_host, proxy_user, sandbox_private_key_path)
        proxy_jump = f'{proxy_user}@{proxy_host}'

        # Create an entry for MAN as a proxy jump host.
        self.add_host(top_ins.ip, SSH_PROXY_USERNAME, sandbox_private_key_path,
                      proxy_jump=proxy_jump, alias=top_ins.man.name)
        man_proxy_jump = f'{SSH_PROXY_USERNAME}@{top_ins.man.name}'

        # Create an entry for user-accessible nodes of a sandbox.
        for link in top_ins.get_links_to_user_accessible_nodes():
            self.add_host(link.ip, SSH_PROXY_USERNAME, sandbox_private_key_path,
                          proxy_jump=man_proxy_jump, alias=link.node.name)


class KypoMgmtSSHConfig(KypoSSHConfig):
    """
    Represents SSH config file used by KYPO designers/organizers.
    """
    def __init__(self, top_ins: TopologyInstance, proxy_host: str, proxy_user: str,
                 pool_private_key_path: str = '<path_to_pool_private_key>',
                 proxy_private_key_path: str = '<path_to_pool_private_key>'):
        super().__init__('')

        # Create an entry for KYPO PROXY JUMP host.
        self.add_host(proxy_host, proxy_user, proxy_private_key_path)
        proxy_jump = f'{proxy_user}@{proxy_host}'

        # Create an entry for MAN as a proxy jump host.
        self.add_host(top_ins.ip, top_ins.man.base_box.mgmt_user, pool_private_key_path,
                      proxy_jump=proxy_jump, alias=top_ins.man.name)
        man_proxy_jump = f'{top_ins.man.base_box.mgmt_user}@{top_ins.man.name}'

        # Create an entry for every other node of a sandbox.
        for link in self._get_man_accessible_node_links(top_ins):
            self.add_host(link.ip, link.node.base_box.mgmt_user, pool_private_key_path,
                          proxy_jump=man_proxy_jump, alias=link.node.name)

    @classmethod
    def _get_man_accessible_node_links(cls, top_ins: TopologyInstance) -> List[Link]:
        """
        Get links for MAN-accessible nodes using Management network.
        """
        return [link_pair.second for link_pair in
                top_ins.get_link_pairs_man_to_nodes_over_management_network()]


class KypoAnsibleSSHConfig(KypoMgmtSSHConfig):
    """
    Represents SSH config file used by KYPO automated provisioning using Ansible.
    """
    def __init__(self, top_ins: TopologyInstance, pool_private_key_path: str,
                 proxy_host: str, proxy_user: str, proxy_private_key_path: str,
                 git_host: str, git_user: str, git_private_key_path: str):
        super().__init__(top_ins, proxy_host, proxy_user,
                         pool_private_key_path=pool_private_key_path,
                         proxy_private_key_path=proxy_private_key_path)
        # Create an entry for Git repository.
        self.add_host(git_host, git_user, git_private_key_path)


class KypoAnsibleCleanupSSHConfig(KypoSSHConfig):
    """
    Represents SSH config file used by KYPO AnsibleCleanupStage.
    """

    def __init__(self, proxy_jump_host: str, proxy_jump_user: str, pool_private_key_path: str,
                 git_host: str, git_user: str, git_private_key_path: str):
        super().__init__('')
        self.add_host(proxy_jump_host, proxy_jump_user, pool_private_key_path)
        self.add_host(git_host, git_user, git_private_key_path)
