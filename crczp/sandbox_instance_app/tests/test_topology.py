"""Tests for topology serialization and Docker container topology."""

import pytest

from crczp.sandbox_instance_app import serializers
from crczp.sandbox_instance_app.lib.topology import Topology
from crczp.sandbox_instance_app.tests.conftest import mock_topology_cache

pytestmark = pytest.mark.django_db


class TestTopology:
    """Tests for topology serialization from a topology instance."""

    def test_topology_success(self, mocker, top_ins, topology, image):
        """Test that a topology instance serializes correctly."""
        mock_images = mocker.patch('crczp.terraform_driver.CrczpTerraformClient.list_images')
        mock_images.return_value = [image]
        topo = mock_topology_cache(top_ins)

        result = serializers.TopologySerializer(topo).data

        assert sorted(topology['routers'], key=lambda x: x['name']) == sorted(
            result['routers'], key=lambda x: x['name']
        )

    def test_topology_hidden_success(self, mocker, top_ins_hidden, topology_hidden, image):
        """Test that hidden topology items are serialized correctly."""
        mock_images = mocker.patch('crczp.terraform_driver.CrczpTerraformClient.list_images')
        mock_images.return_value = [image]
        topo = mock_topology_cache(top_ins_hidden)

        result = serializers.TopologySerializer(topo).data

        assert sorted(topology_hidden['routers'], key=lambda x: x['name']) == sorted(
            result['routers'], key=lambda x: x['name']
        )


class TestDockerContainers:
    """Tests for Docker container entries in the topology object."""

    def test_docker_containers_in_topology_object(
        self, mocker, top_ins_with_containers, image, topology_containers
    ):
        """Test if containers are present in the Topology Visualization object."""
        mock_images = mocker.patch('crczp.terraform_driver.CrczpTerraformClient.list_images')
        mock_images.return_value = [image]

        topology = Topology(top_ins_with_containers)
        result = serializers.TopologySerializer(topology).data

        assert sorted(topology_containers['routers'], key=lambda x: x['name']) == sorted(
            result['routers'], key=lambda x: x['name']
        )

        for host in top_ins_with_containers.topology_definition.hosts:
            if host.name == 'server':
                assert host.hidden
            elif host.name == 'home':
                assert not host.hidden

    def test_server_host_is_hidden(
        self, mocker, top_ins_with_containers_with_server, image, topology_containers_server
    ):
        """Test that a server container host is marked hidden in the topology."""
        mock_images = mocker.patch('crczp.terraform_driver.CrczpTerraformClient.list_images')
        mock_images.return_value = [image]

        topology = Topology(top_ins_with_containers_with_server)
        result = serializers.TopologySerializer(topology).data

        assert sorted(topology_containers_server['routers'], key=lambda x: x['name']) == sorted(
            result['routers'], key=lambda x: x['name']
        )

        for host in top_ins_with_containers_with_server.topology_definition.hosts:
            if host.name == 'server':
                assert host.hidden
            elif host.name == 'home':
                assert not host.hidden
