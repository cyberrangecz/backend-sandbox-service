from typing import List, Optional, Dict, Any
import structlog
from ssh_config.client import Host, parse_config  # Don't import SSHConfig unless reading from file
from ssh_config.keywords import Keywords

from crczp.cloud_commons import TopologyInstance, Link

LOG = structlog.getLogger()

SSH_PROXY_USERNAME = 'user'
SSH_PROXY_KEY = '<path_to_proxy_jump_private_key>'

class CrczpSSHConfig:
    """
    Represents SSH config file for CRCZP purposes.
    This class works in-memory and does not require a backing file.
    """
    def __init__(self):
        self.hosts: List[Host] = []
        self.raw: Optional[str] = None

    def __str__(self):
        return '\n'.join([str(host) for host in self.hosts]) + '\n'

    def serialize(self) -> str:
        """
        Return the string representation of CrczpSSHConfig.
        """
        return str(self)

    def add_host(self, host_name: str, user: str, identity_file: str,
                 proxy_jump: Optional[str] = None, alias: Optional[str] = None, port: Optional[int] = None, **kwargs) -> None:
        """
        Create and add Host instance to this SSH config file.
        """
        opts = dict(HostName=host_name, User=user, IdentityFile=identity_file,
                    UserKnownHostsFile='/dev/null', StrictHostKeyChecking='no',
                    IdentitiesOnly='yes')
        if port is not None:
            opts['Port'] = port
        if proxy_jump:
            opts['ProxyJump'] = proxy_jump
        opts.update(kwargs)
        # Use alias as first name if given, otherwise host_name
        names = [alias, host_name] if alias else host_name
        host = Host(names, opts)
        self.hosts.append(host)

    def add_docker_host(self, host_name: str, user: str, identity_file: str, port: int,
                        proxy_jump: Optional[str] = None, alias: Optional[str] = None, **kwargs) -> None:
        opts = dict(HostName=host_name, User=user, IdentityFile=identity_file, Port=port,
                    UserKnownHostsFile='/dev/null', StrictHostKeyChecking='no',
                    IdentitiesOnly='yes')
        if proxy_jump:
            opts['ProxyJump'] = proxy_jump
        opts.update(kwargs)
        # For containers, alias is always present
        host = Host([alias, host_name] if alias else host_name, opts)
        self.hosts.append(host)

    @classmethod
    def from_str(cls, ssh_config: str):
        """
        Load SSH config file from string.
        """
        instance = cls()
        instance.raw = ssh_config
        if not ssh_config or not ssh_config.strip():
            raise Exception("Empty SSHConfig string")
        hosts, global_options = parse_config(ssh_config)
        for host_dict in hosts:
            name = host_dict["host"]
            attrs = host_dict["attrs"]
            instance.hosts.append(Host(name, attrs))
        return instance

    def asdict(self) -> List[Dict[str, Any]]:
        """
        Return a list of dicts for all hosts.
        """
        hosts_data = []
        for host in self.hosts:
            host_dict = {"Host": host.name}
            host_dict.update(host.attributes())
            hosts_data.append(host_dict)
        return hosts_data


class CrczpUserSSHConfig(CrczpSSHConfig):
    """
    Represents SSH config file used by CRCZP trainees.
    """
    def __init__(self, top_ins: TopologyInstance, proxy_host: str, proxy_user: str,
                 sandbox_private_key_path: str = '<path_to_sandbox_private_key>', proxy_port: int = 22):
        super().__init__()
        # Create an entry for PROXY JUMP host.
        self.add_host(proxy_host, proxy_user, sandbox_private_key_path, port=proxy_port)
        proxy_jump = f'{proxy_user}@{proxy_host}:{proxy_port}' if proxy_port != 22 else f'{proxy_user}@{proxy_host}'
        # Create an entry for MAN as a proxy jump host.
        self.add_host(top_ins.ip, SSH_PROXY_USERNAME, sandbox_private_key_path,
                      proxy_jump=proxy_jump, alias=top_ins.man.name)
        man_proxy_jump = f'{SSH_PROXY_USERNAME}@{top_ins.man.name}'

        # Create an entry for user-accessible nodes of a sandbox.
        for link in top_ins.get_links_to_user_accessible_nodes():
            self.add_host(link.ip, SSH_PROXY_USERNAME, sandbox_private_key_path,
                          proxy_jump=man_proxy_jump, alias=link.node.name)

        # Create entries for docker containers
        if hasattr(top_ins, "containers") and top_ins.containers:
            for container_mapping in top_ins.containers.container_mappings:
                self.add_docker_host('127.0.0.1', 'root', sandbox_private_key_path,
                                     port=container_mapping.port, proxy_jump=container_mapping.host,
                                     alias=f'{container_mapping.host}-{container_mapping.container}')


class CrczpMgmtSSHConfig(CrczpSSHConfig):
    """
    Represents SSH config file used by CRCZP designers/organizers.
    """
    def __init__(self, top_ins: TopologyInstance, proxy_host: str, proxy_user: str, proxy_port: int = 22,
                 pool_private_key_path: str = '<path_to_pool_private_key>',
                 proxy_private_key_path: str = '<path_to_pool_private_key>'):
        super().__init__()
        # Create an entry for PROXY JUMP host.
        self.add_host(proxy_host, proxy_user, proxy_private_key_path, port=proxy_port)
        proxy_jump = f'{proxy_user}@{proxy_host}:{proxy_port}' if proxy_port != 22 else f'{proxy_user}@{proxy_host}'
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


class CrczpAnsibleSSHConfig(CrczpMgmtSSHConfig):
    """
    Represents SSH config file used by CRCZP automated provisioning using Ansible.
    """
    def __init__(self, top_ins: TopologyInstance, pool_private_key_path: str,
                 proxy_host: str, proxy_user: str, proxy_private_key_path: str, proxy_port: int = 22):
        super().__init__(
            top_ins=top_ins,
            proxy_host=proxy_host,
            proxy_user=proxy_user,
            proxy_port=proxy_port,
            pool_private_key_path=pool_private_key_path,
            proxy_private_key_path=proxy_private_key_path
        )


class CrczpAnsibleCleanupSSHConfig(CrczpSSHConfig):
    """
    Represents SSH config file used by CRCZP AnsibleCleanupStage.
    """
    def __init__(self, proxy_jump_host: str, proxy_jump_user: str, pool_private_key_path: str, proxy_port: int = 22):
        super().__init__()
        self.add_host(proxy_jump_host, proxy_jump_user, pool_private_key_path, port=proxy_port)
