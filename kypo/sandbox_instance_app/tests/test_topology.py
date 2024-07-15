import pytest

from kypo.sandbox_instance_app import serializers
from kypo.sandbox_instance_app.lib.topology import Topology
from kypo.sandbox_instance_app.tests.conftest import mock_topology_cache

pytestmark = pytest.mark.django_db


class TestTopology:
    def test_topology_success(self, mocker, top_ins, topology, image):
        mock_images = mocker.patch(
            'kypo.terraform_driver.KypoTerraformClient.list_images')
        mock_images.return_value = [image]
        topo = mock_topology_cache(top_ins)

        result = serializers.TopologySerializer(topo).data

        for item in ['hosts', 'routers', 'switches', 'ports']:
            assert sorted(topology[item], key=lambda x: x['name']) == \
                   sorted(result[item], key=lambda x: x['name'])
        for item in ['links']:
            assert sorted(topology[item], key=lambda x: x['port_a']) == \
                   sorted(result[item], key=lambda x: x['port_a'])

    def test_topology_hidden_success(self, mocker, top_ins_hidden, topology_hidden, image):
        mock_images = mocker.patch(
            'kypo.terraform_driver.KypoTerraformClient.list_images')
        mock_images.return_value = [image]
        topo = mock_topology_cache(top_ins_hidden)

        result = serializers.TopologySerializer(topo).data

        for item in ['hosts', 'routers', 'switches', 'ports']:
            assert sorted(topology_hidden[item], key=lambda x: x['name']) == \
                   sorted(result[item], key=lambda x: x['name'])
        for item in ['links']:
            assert sorted(topology_hidden[item], key=lambda x: x['port_a']) == \
                   sorted(result[item], key=lambda x: x['port_a'])


class TestDockerContainers:
    def test_docker_containers_in_topology_object(self, mocker, top_ins_with_containers, image, topology_containers):
        """Test if containers are present in the Topology Visualization object."""
        mock_images = mocker.patch('kypo.terraform_driver.KypoTerraformClient.list_images')
        mock_images.return_value = [image]

        topology = Topology(top_ins_with_containers)
        result = serializers.TopologySerializer(topology).data

        assert sorted(topology_containers['hosts'], key=lambda x: x['name']) == \
               sorted(result['hosts'], key=lambda x: x['name'])

        for host in top_ins_with_containers.topology_definition.hosts:
            if host.name == "server":
                assert host.hidden
            elif host.name == "home":
                assert not host.hidden

    def test_server_host_is_hidden(self, mocker, top_ins_with_containers_with_server, image, topology_containers):
        mock_images = mocker.patch('kypo.terraform_driver.KypoTerraformClient.list_images')
        mock_images.return_value = [image]

        topology = Topology(top_ins_with_containers_with_server)
        result = serializers.TopologySerializer(topology).data

        assert result['hosts'][0]['containers'] == ['home-docker2']

        for host in top_ins_with_containers_with_server.topology_definition.hosts:
            if host.name == "server":
                assert host.hidden
            elif host.name == "home":
                assert not host.hidden
