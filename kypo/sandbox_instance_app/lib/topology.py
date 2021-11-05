import structlog

from kypo.openstack_driver import TopologyInstance

LOG = structlog.getLogger()
INTERNET_NODE_NAME = 'internet'


class Topology:
    """Represents a topology of a sandbox."""

    class SpecialNode:
        def __init__(self, name):
            self.name = name

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

    def __init__(self, top_inst: TopologyInstance):
        self.special_nodes = []
        self.hosts = []
        self.routers = []
        self.switches = []
        self.links = []
        self.ports = []

        self.add_host_routes_and_switches(top_inst)
        self.add_ports_and_links(top_inst)

    def add_host_routes_and_switches(self, top_inst: TopologyInstance) -> None:
        self.special_nodes = [self.SpecialNode(INTERNET_NODE_NAME)]
        self.hosts = [h for h in top_inst.get_hosts() if not h.hidden]
        self.routers = top_inst.get_routers()
        self.switches = [n for n in top_inst.get_networks()
                         if n != top_inst.man_network]

    def add_ports_and_links(self, top_inst: TopologyInstance) -> None:
        hidden_hosts = top_inst.get_hidden_hosts()

        for ln in top_inst.get_links():
            if ln.node in hidden_hosts or ln.network == top_inst.man_network:
                continue

            if ln.node == top_inst.man:
                real_port = self.Port(None, None, INTERNET_NODE_NAME,
                                      ln.name + "_" + INTERNET_NODE_NAME)
            else:
                real_port = self.Port(ln.ip, ln.mac, ln.node.name, ln.name + "_" + ln.node.name)

            dummy_port = self.Port(None, None, ln.network.name, ln.name + "_" + ln.network.name)

            self.links.append(self.Link(real_port, dummy_port))
            self.ports.append(real_port)
            self.ports.append(dummy_port)
