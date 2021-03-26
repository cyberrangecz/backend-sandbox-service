import pytest

from kypo.sandbox_ansible_app.lib.inventory import Inventory, Routing

pytestmark = pytest.mark.django_db


class TestCreateInventory:
    def test_create_inventory_success(self, top_ins, inventory):
        all_vars = dict(kypo_global_sandbox_name=top_ins.name,
                        kypo_global_sandbox_ip=top_ins.ip)
        extra_vars = {'a': 1, 'b': 'b'}
        all_vars.update(extra_vars)
        inventory['all']['vars'] = all_vars

        result = Inventory(top_ins, '/root/.ssh/pool_mng_key', '/root/.ssh/pool_mng_cert',
                           '/root/.ssh/user_key', '/root/.ssh/user_key.pub', extra_vars).to_dict()

        assert result == inventory

    def test_get_network_to_router_mapping(self, top_ins):
        expected = {'home-switch': 'home-router', 'server-switch': 'server-router'}
        result = Routing._get_network_to_router_mapping(top_ins)
        assert expected == result
