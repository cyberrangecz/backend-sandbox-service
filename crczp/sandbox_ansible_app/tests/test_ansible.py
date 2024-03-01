import pytest

from crczp.sandbox_ansible_app.lib.ansible import AllocationAnsibleRunner
from crczp.sandbox_instance_app.models import Sandbox
from crczp.sandbox_instance_app.lib import sandboxes

pytestmark = pytest.mark.django_db


class TestPrepareInventoryFile:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker, top_ins):
        self.client = mocker.patch('crczp.sandbox_common_lib.utils.get_terraform_client')
        self.client.get_sandbox.return_value = top_ins
        self.save_file = mocker.patch(
            'crczp.sandbox_ansible_app.lib.ansible.AnsibleRunner.save_file')
        yield

    def test_prepare_inventory_file_success(self, mocker, top_ins):
        mock_inventory = mocker.patch('crczp.sandbox_ansible_app.lib.ansible.Inventory')
        mocker.patch('crczp.sandbox_ansible_app.lib.ansible.docker.from_env')
        sandboxes.get_topology_instance = mocker.MagicMock()
        sandboxes.get_topology_instance.return_value = top_ins

        dir_path = '/tmp'
        sandbox = Sandbox.objects.get(pk=1)
        AllocationAnsibleRunner(dir_path).prepare_inventory_file(sandbox)

        mock_inventory.assert_called_once()

    def test_prepare_inventory_object(self, mocker, top_ins, inventory):
        mocker.patch('crczp.sandbox_ansible_app.lib.ansible.docker.from_env')
        dir_path = mocker.MagicMock()
        sandbox = Sandbox.objects.get(pk=1)
        sandbox.allocation_unit.pool.get_pool_prefix = mocker.MagicMock()
        sandbox.allocation_unit.pool.get_pool_prefix.return_value = 'pool-prefix'
        sandbox.allocation_unit.get_stack_name = mocker.MagicMock()
        sandbox.allocation_unit.get_stack_name.return_value = 'stack-name'
        result = AllocationAnsibleRunner(dir_path).create_inventory(sandbox)

        assert result.to_dict() == inventory
