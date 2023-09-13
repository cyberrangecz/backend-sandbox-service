import pytest

from kypo.sandbox_ansible_app.lib.inventory import Inventory, Routing

pytestmark = pytest.mark.django_db


class TestCreateInventory:
    def test_create_inventory_success(self, top_ins, inventory):
        ssh_public_mgmt_key = '/root/.ssh/pool_mng_key.pub'
        ssh_public_user_key = '/root/.ssh/user_key.pub'
        all_vars = dict(kypo_global_sandbox_name=top_ins.name,
                        kypo_global_sandbox_ip=top_ins.ip,
                        kypo_global_ssh_public_mgmt_key=ssh_public_mgmt_key,
                        kypo_global_ssh_public_user_key=ssh_public_user_key)
        extra_vars = {'a': 1, 'b': 'b'}
        all_vars.update(extra_vars)
        inventory['all']['vars'] = all_vars

        result = Inventory('pool-prefix', 'stack-name',
                           top_ins, '/root/.ssh/pool_mng_key', '/root/.ssh/pool_mng_cert',
                           ssh_public_mgmt_key, ssh_public_user_key, extra_vars)
        assert result.to_dict() == inventory

    def test_create_inventory_success_with_monitoring(self, top_ins_monitoring, inventory_monitoring):
        ssh_public_mgmt_key = '/root/.ssh/pool_mng_key.pub'
        ssh_public_user_key = '/root/.ssh/user_key.pub'
        all_vars = dict(kypo_global_sandbox_name=top_ins_monitoring.name,
                        kypo_global_sandbox_ip=top_ins_monitoring.ip,
                        kypo_global_ssh_public_mgmt_key=ssh_public_mgmt_key,
                        kypo_global_ssh_public_user_key=ssh_public_user_key)
        extra_vars = {'a': 1, 'b': 'b'}
        all_vars.update(extra_vars)
        inventory_monitoring['all']['vars'] = all_vars

        result = Inventory('pool-prefix', 'stack-name',
                           top_ins_monitoring, '/root/.ssh/pool_mng_key', '/root/.ssh/pool_mng_cert',
                           ssh_public_mgmt_key, ssh_public_user_key, extra_vars)

        assert result.to_dict() == inventory_monitoring

    def test_get_network_to_router_mapping(self, top_ins):
        expected = {'home-switch': 'home-router', 'server-switch': 'server-router'}
        result = Routing._get_network_to_router_mapping(top_ins)
        assert expected == result
