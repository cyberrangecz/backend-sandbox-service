import pytest

from kypo.sandbox_ansible_app.lib.inventory import Inventory

pytestmark = pytest.mark.django_db


class MockNetwork:
    def __init__(self, name):
        self.name = name


class TestCreateInventory:
    def test_create_inventory_success(self, mocker, top_ins, inventory):
        result = Inventory(top_ins, '/root/user_key', '/root/user_key.pub')
        assert result.data == inventory

    def test_create_inventory_extra_vars(self, mocker, top_ins, inventory):
        extra_vars = {'a': 1, 'b': 'b'}
        inventory['all']['vars'].update(extra_vars)

        result = Inventory(top_ins, '/root/user_key', '/root/user_key.pub', extra_vars)
        assert result.data == inventory

    def test_get_net_to_router(self, top_ins):
        expected = {'home-switch': 'home-router', 'server-switch': 'server-router'}
        result = Inventory._get_net_to_router(top_ins)
        assert expected == result
