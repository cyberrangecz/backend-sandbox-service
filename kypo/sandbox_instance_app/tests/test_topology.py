import pytest

from kypo.sandbox_instance_app import serializers
from kypo.sandbox_instance_app.tests.conftest import mock_cache

pytestmark = pytest.mark.django_db


class TestTopology:
    def test_topology_success(self, mocker, top_ins, topology, image):
        mock_images = mocker.patch(
            'kypo.terraform_driver.KypoTerraformClient.list_images')
        mock_images.return_value = [image]
        topo = mock_cache(top_ins)

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
        topo = mock_cache(top_ins_hidden)

        result = serializers.TopologySerializer(topo).data

        for item in ['hosts', 'routers', 'switches', 'ports']:
            assert sorted(topology_hidden[item], key=lambda x: x['name']) == \
                   sorted(result[item], key=lambda x: x['name'])
        for item in ['links']:
            assert sorted(topology_hidden[item], key=lambda x: x['port_a']) == \
                   sorted(result[item], key=lambda x: x['port_a'])
