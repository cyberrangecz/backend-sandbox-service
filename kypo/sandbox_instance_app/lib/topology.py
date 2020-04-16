import structlog
from kypo.openstack_driver.sandbox_topology import SandboxTopology as Stack,\
    BR_NET_NAME, UAN_NET_NAME

from django.conf import settings
from kypo.sandbox_instance_app.models import Sandbox
from kypo.sandbox_definition_app.lib import definitions

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

    def __init__(self, sandbox: Sandbox, stack: Stack):
        self.hosts = []
        self.routers = []
        self.switches = []
        self.links = []
        self.ports = []

        self._remove_hidden_data_from_stack(sandbox, stack)

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
        top_def = definitions.get_definition(definition.url, definition.rev, settings.KYPO_CONFIG)

        hidden = []
        for host in top_def.hosts:
            if host.hidden:
                hidden.append(host.name)
                del stack.hosts[host.name]

        # Delete MNG infrastructure
        mng_nodes = (stack.man.name, stack.br.name, stack.uan.name)
        mng_networks = (UAN_NET_NAME, BR_NET_NAME, stack.mng_net.name)

        for net in mng_networks:
            del stack.networks[net]

        # Delete links
        stack.links = [link for link in stack.links
                       if link.node.name not in mng_nodes
                       and link.node.name not in hidden
                       and link.network.name not in mng_networks]
