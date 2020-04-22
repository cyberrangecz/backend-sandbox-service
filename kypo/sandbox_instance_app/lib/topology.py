import structlog

from kypo.openstack_driver.topology_instance import TopologyInstance, UAN_NET_NAME, BR_NET_NAME

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
        self.hosts = top_inst.get_hosts()
        self.routers = top_inst.get_routers()
        self.switches = top_inst.get_networks()
        self.links = []
        self.ports = []

        self.add_ports_and_links(top_inst)
        self.remove_hidden_data(top_inst)

    def add_ports_and_links(self, top_inst: TopologyInstance) -> None:
        for ln in top_inst.links:
            real_port = self.Port(ln.ip, ln.mac, ln.node.name, ln.name + "_" + ln.node.name)
            dummy_port = self.Port(None, None, ln.network.name, ln.name + "_" + ln.network.name)

            self.links.append(self.Link(real_port, dummy_port))
            self.ports.append(real_port)
            self.ports.append(dummy_port)

    def remove_hidden_data(self, top_inst: TopologyInstance) -> None:
        """Removes data about management and hidden nodes from stack"""
        # Delete hidden host
        self.hosts = [h for h in self.hosts if not h.hidden]

        # Delete MNG infrastructure
        mng_nodes = [n.name for n in top_inst.get_extra_nodes()]
        mng_networks = (UAN_NET_NAME, BR_NET_NAME, top_inst.man.name)

        self.networks = [n for n in self.networks if n.name not in mng_networks]

        # Delete links
        self.links = [link for link in self.links
                      if link.node.name not in mng_nodes
                      and not link.node.hidden
                      and link.network.name not in mng_networks]
