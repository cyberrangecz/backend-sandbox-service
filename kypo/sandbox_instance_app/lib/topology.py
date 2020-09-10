import structlog

from kypo.openstack_driver import TopologyInstance

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

    def __init__(self, top_inst: TopologyInstance):
        self.hosts = []
        self.routers = []
        self.switches = []
        self.links = []
        self.ports = []

        self.add_host_routes_and_switches(top_inst)
        self.add_ports_and_links(top_inst)

    def add_host_routes_and_switches(self, top_inst: TopologyInstance) -> None:
        self.hosts = [h for h in top_inst.get_hosts() if not h.hidden]
        self.routers = top_inst.get_routers()
        self.switches = [n for n in top_inst.get_networks()
                         if n not in top_inst.get_extra_networks()]

    def add_ports_and_links(self, top_inst: TopologyInstance) -> None:
        extra_nodes = top_inst.get_extra_nodes()
        hidden_hosts = top_inst.get_hidden_hosts()
        extra_nets = top_inst.get_extra_networks()

        for ln in top_inst.get_links():
            if ln.node in extra_nodes or \
                    ln.node in hidden_hosts or \
                    ln.network in extra_nets:
                continue
            real_port = self.Port(ln.ip, ln.mac, ln.node.name, ln.name + "_" + ln.node.name)
            dummy_port = self.Port(None, None, ln.network.name, ln.name + "_" + ln.network.name)

            self.links.append(self.Link(real_port, dummy_port))
            self.ports.append(real_port)
            self.ports.append(dummy_port)
