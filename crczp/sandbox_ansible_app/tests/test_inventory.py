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

class TestWindowsHostsGroup:
    def test_windows_hosts_group_created(self, top_ins):
        """Test that windows_hosts group is created with correct hosts."""
        ssh_public_mgmt_key = '/root/.ssh/pool_mng_key.pub'
        ssh_public_user_key = '/root/.ssh/user_key.pub'

        result = Inventory(
            'pool-prefix',
            'stack-name',
            top_ins,
            '/root/.ssh/pool_mng_key',
            '/root/.ssh/pool_mng_cert',
            ssh_public_mgmt_key,
            ssh_public_user_key,
        )

        # Check that windows_hosts group exists
        assert 'windows_hosts' in result.to_dict()['all']['children']

        # Check that 'home' is in windows_hosts (it uses windows-10 image)
        windows_hosts = result.to_dict()['all']['children']['windows_hosts']['hosts']
        assert 'home' in windows_hosts

        # Check that debian hosts are NOT in windows_hosts
        assert 'server' not in windows_hosts
        assert 'server-router' not in windows_hosts
        assert 'home-router' not in windows_hosts

    def test_windows_hosts_group_empty_when_no_windows(self, top_ins, mocker):
        """Test that windows_hosts group is not created when there are no Windows hosts."""
        # Mock list_images to return only Linux images
        mock_images = [
            mocker.MagicMock(name='debian-12-x86_64', os_type='linux'),
            mocker.MagicMock(name='windows-10', os_type='linux'),  # Pretend windows-10 is Linux
        ]
        mocker.patch('crczp.sandbox_ansible_app.lib.inventory.list_images', return_value=mock_images)

        ssh_public_mgmt_key = '/root/.ssh/pool_mng_key.pub'
        ssh_public_user_key = '/root/.ssh/user_key.pub'

        result = Inventory(
            'pool-prefix',
            'stack-name',
            top_ins,
            '/root/.ssh/pool_mng_key',
            '/root/.ssh/pool_mng_cert',
            ssh_public_mgmt_key,
            ssh_public_user_key,
        )

        # Check that windows_hosts group does not exist
        assert 'windows_hosts' not in result.to_dict()['all']['children']
