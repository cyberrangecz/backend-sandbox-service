import pytest

from kypo.sandbox_ansible_app.lib.inventory import Inventory

pytestmark = pytest.mark.django_db


class TestCreateInventory:
    def test_create_inventory_success(self, top_ins, inventory):
        result = Inventory(top_ins, '/root/.ssh/user_key', '/root/.ssh/user_key.pub')

        del result.data['all']['vars']
        del inventory['all']['vars']

        assert result.data == inventory

    def test_create_inventory_extra_vars(self, top_ins, inventory):
        all_vars = dict(kypo_global_sandbox_name=top_ins.name, kypo_global_sandbox_ip=top_ins.ip)
        inventory['all']['vars'] = all_vars

        extra_vars = {'a': 1, 'b': 'b'}
        inventory['all']['vars'].update(extra_vars)

        result = Inventory(top_ins, '/root/.ssh/user_key', '/root/.ssh/user_key.pub', extra_vars)
        assert result.data == inventory

    def test_get_net_to_router(self, top_ins):
        expected = {'home-switch': 'home-router', 'server-switch': 'server-router'}
        result = Inventory._get_net_to_router(top_ins)
        assert expected == result
