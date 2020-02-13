import structlog
from kypo.openstack_driver.sandbox_topology import SandboxTopology as Stack, BR_NET_NAME, UAN_NET_NAME

from ..models import Sandbox
from ...sandbox_common_lib import utils
from ...sandbox_definition_app.lib.definition_service import get_definition

LOG = structlog.getLogger()


class Topology:
    """Represents a topology of a sandbox."""

    class Port:
        def __init__(self, ip, mac, parent, name):
            self.ip = ip
            self.mac = mac
            self.parent = parent
            self.name = name

    class Link:
        def __init__(self, real_port, dummy_port):
            self.real_port = real_port
            self.dummy_port = dummy_port

    def __init__(self, sandbox: Sandbox):
        self.sandbox = sandbox
        self.hosts = []
        self.routers = []
        self.switches = []
        self.links = []
        self.ports = []

    def create(self) -> None:
        """Retrieves data from cloud and parses topology data for given sandbox"""
        stack_name = self.sandbox.get_stack_name()
        client = utils.get_ostack_client()
        stack = client.get_sandbox(stack_name)

        self._remove_hidden_data_from_stack(self.sandbox, stack)

        self.hosts = stack.hosts.values()
        self.routers = stack.routers.values()
        self.switches = stack.networks.values()

        self._add_ports_and_links(stack)

    def _add_ports_and_links(self, stack) -> None:
        for ln in stack.links:
            real_port = self.Port(ln.ip, ln.mac, ln.node.name, ln.name + "_" + ln.node.name)
            dummy_port = self.Port(None, None, ln.network.name, ln.name + "_" + ln.network.name)

            self.links.append(self.Link(real_port, dummy_port))
            self.ports.append(real_port)
            self.ports.append(dummy_port)

    @staticmethod
    def _remove_hidden_data_from_stack(sandbox: Sandbox, stack: Stack) -> None:
        """Removes data about management and hidden nodes from stack"""

        # Delete hidden host
        definition = sandbox.allocation_unit.pool.definition
        top_def = get_definition(url=definition.url, rev=definition.rev)

        for name, host in top_def.hosts.items():
            if host.hidden:
                del stack.hosts[name]

        # Delete MNG infrastructure
        mng_nodes = (stack.man.name, stack.br.name, stack.uan.name)
        mng_networks = (UAN_NET_NAME, BR_NET_NAME, stack.mng_net.name)

        for net in mng_networks:
            del stack.networks[net]

        # Delete links
        stack.links = [link for link in stack.links
                       if link.node.name not in mng_nodes
                       and not link.node.hidden
                       and link.network.name not in mng_networks]
