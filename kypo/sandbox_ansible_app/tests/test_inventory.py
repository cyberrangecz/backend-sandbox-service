import pytest

from kypo.sandbox_ansible_app.lib.inventory import Inventory

pytestmark = pytest.mark.django_db


class TestCreateInventory:
    def test_create_inventory_success(self, mocker, stack, inventory, top_def):
        class TestNetwork:
            def __init__(self, name):
                self.name = name
        mock_br_network = mocker.patch(
            'kypo.openstack_driver.sandbox_topology.SandboxTopology.get_br_network')
        mock_uan_network = mocker.patch(
            'kypo.openstack_driver.sandbox_topology.SandboxTopology.get_uan_network')
        mock_br_network.return_value = TestNetwork('br-network')
        mock_uan_network.return_value = TestNetwork('uan-network')
        result = Inventory(stack, top_def, '/root/user_key', '/root/user_key.pub')
        assert result.data == inventory

    def test_get_net_to_router(self, top_def):
        expected = {'home-switch': 'home-router', 'server-switch': 'server-router'}
        result = Inventory._get_net_to_router(top_def)
        assert expected == result
