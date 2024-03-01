import pytest

from crczp.sandbox_ansible_app.lib.inventory import Inventory, Routing

pytestmark = pytest.mark.django_db


class TestCreateInventory:
    def test_create_inventory_success(self, top_ins, inventory):
        ssh_public_mgmt_key = '/root/.ssh/pool_mng_key.pub'
        ssh_public_user_key = '/root/.ssh/user_key.pub'
        all_vars = dict(global_sandbox_name=top_ins.name,
                        global_sandbox_ip=top_ins.ip,
                        global_ssh_public_mgmt_key=ssh_public_mgmt_key,
                        global_ssh_public_user_key=ssh_public_user_key)
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
        all_vars = dict(global_sandbox_name=top_ins_monitoring.name,
                        global_sandbox_ip=top_ins_monitoring.ip,
                        global_ssh_public_mgmt_key=ssh_public_mgmt_key,
                        global_ssh_public_user_key=ssh_public_user_key)
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


class TestContainersInInventory:
    def test_containers_added_to_inventory(self, top_ins_with_containers, inventory, inventory_containers):
        ssh_public_mgmt_key = '/root/.ssh/pool_mng_key.pub'
        ssh_public_user_key = '/root/.ssh/user_key.pub'
        all_vars = dict(global_sandbox_name=top_ins_with_containers.name,
                        global_sandbox_ip=top_ins_with_containers.ip,
                        global_ssh_public_mgmt_key=ssh_public_mgmt_key,
                        global_ssh_public_user_key=ssh_public_user_key)
        extra_vars = {'a': 1, 'b': 'b'}
        all_vars.update(extra_vars)
        inventory['all']['vars'] = all_vars

        result = Inventory('pool-prefix', 'stack-name',
                           top_ins_with_containers, '/root/.ssh/pool_mng_key', '/root/.ssh/pool_mng_cert',
                           ssh_public_mgmt_key, ssh_public_user_key, extra_vars)

        assert sorted(result.to_dict()) == sorted(inventory_containers)
