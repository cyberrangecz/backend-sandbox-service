import structlog

from kypo.cloud_commons import TopologyInstance
from kypo.topology_definition.models import Host

from kypo.sandbox_common_lib.common_cloud import list_images

LOG = structlog.getLogger()
INTERNET_NODE_NAME = 'internet'


class Topology:
    """Represents a topology of a sandbox."""

    class Node:
        def __init__(self, name, os_type, gui_access):
            self.name = name
            self.os_type = os_type
            self.gui_access = gui_access

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

        self.add_nodes(top_inst)
        self.add_special_nodes_and_switches(top_inst)
        self.add_ports_and_links(top_inst)
        self.add_containers(top_inst)

    def add_nodes(self, top_inst: TopologyInstance) -> None:
        images = list_images()
        for node in top_inst.get_visible_routers() + top_inst.get_visible_hosts():
            image = next(image for image in images if image.name == node.base_box.image)
            gui_access = image.owner_specified.get('owner_specified.openstack.gui_access') == 'true'
            new_node = self.Node(node.name, image.os_type, gui_access)

            if type(node) == Host:
                self.hosts.append(new_node)
                new_node.containers = []
            else:
                self.routers.append(new_node)

    def add_special_nodes_and_switches(self, top_inst: TopologyInstance) -> None:
        self.special_nodes = [self.SpecialNode(INTERNET_NODE_NAME)]
        self.switches = top_inst.get_visible_networks()

    def add_ports_and_links(self, top_inst: TopologyInstance) -> None:
        for ln in top_inst.get_links():
            if ((ln.node != top_inst.man and ln.node.hidden) or ln.network == top_inst.man_network
                    # assumes this function it called after add_special_nodes_and_switches()
                    or ln.network not in self.switches):
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

    def add_containers(self, top_inst: TopologyInstance):
        if top_inst.containers is None or top_inst.containers.hide_all:
            return

        containers_by_host = {}
        for mapping in top_inst.containers.container_mappings:
            if mapping.hidden:
                continue

            if mapping.host in containers_by_host.keys():
                containers_by_host[mapping.host].append(mapping.host + "-" + mapping.container)
            else:
                containers_by_host[mapping.host] = [mapping.host + "-" + mapping.container]

        for host in self.hosts:
            if host.name in containers_by_host.keys():
                host.containers = containers_by_host[host.name]
