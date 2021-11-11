import pytest

from kypo.sandbox_instance_app import serializers
from kypo.sandbox_instance_app.lib import sandboxes

pytestmark = pytest.mark.django_db


class TestTopology:
    def test_topology_success(self, mocker, top_ins, topology, image):
        mock_images = mocker.patch(
            'kypo.openstack_driver.open_stack_client.KypoOpenStackClient.list_images')
        mock_images.return_value = [image]
        topo = sandboxes.Topology(top_ins)

        result = serializers.TopologySerializer(topo).data

        for item in ['hosts', 'routers', 'switches', 'ports']:
            assert sorted(topology[item], key=lambda x: x['name']) == \
                   sorted(result[item], key=lambda x: x['name'])
        for item in ['links']:
            assert sorted(topology[item], key=lambda x: x['port_a']) == \
                   sorted(result[item], key=lambda x: x['port_a'])
