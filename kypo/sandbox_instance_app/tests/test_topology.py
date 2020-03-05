import pytest

from kypo.sandbox_instance_app import serializers
from kypo.sandbox_instance_app.lib import sandboxes

pytestmark = pytest.mark.django_db


class TestTopology:
    def test_create_success(self, mocker, stack, topology, topology_definition):
        mocker.patch('kypo.sandbox_definition_app.lib.definitions.get_definition',
                     mocker.Mock(return_value=topology_definition))
        mock_client = mocker.patch('kypo.sandbox_common_lib.utils.get_ostack_client')
        client = mock_client.return_value
        client.get_sandbox.return_value = stack
        client.get_spice_console.return_value = 'console_url'
        client.pool.definition.content = ''

        sandbox = mocker.MagicMock()
        sandbox.pool.definition.content = 'name: name'

        topo = sandboxes.Topology(sandbox)
        topo.create()
        result = serializers.TopologySerializer(topo).data

        for item in ['hosts', 'routers', 'switches', 'ports']:
            assert sorted(topology[item], key=lambda x: x['name']) == \
                   sorted(result[item], key=lambda x: x['name'])
        for item in ['links']:
            assert sorted(topology[item], key=lambda x: x['port_a']) == \
                   sorted(result[item], key=lambda x: x['port_a'])

    def test_create_hidden(self, mocker, stack, topology_hidden, topology_definition):
        for host in topology_definition.hosts:
            if host.name == 'server':
                host.hidden = True
        mocker.patch('kypo.sandbox_definition_app.lib.definitions.get_definition',
                     mocker.Mock(return_value=topology_definition))
        mock_client = mocker.patch('kypo.sandbox_common_lib.utils.get_ostack_client')
        client = mock_client.return_value
        client.get_sandbox.return_value = stack
        client.get_spice_console.return_value = 'console_url'
        client.pool.definition.content = ''

        sandbox = mocker.MagicMock()
        sandbox.pool.definition.content = 'name: name'

        topo = sandboxes.Topology(sandbox)
        topo.create()
        result = serializers.TopologySerializer(topo).data

        for item in ['hosts', 'routers', 'switches', 'ports']:
            assert sorted(topology_hidden[item], key=lambda x: x['name']) == \
                   sorted(result[item], key=lambda x: x['name'])
        for item in ['links']:
            assert sorted(topology_hidden[item], key=lambda x: x['port_a']) == \
                   sorted(result[item], key=lambda x: x['port_a'])
