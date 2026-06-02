"""Tests for the Ansible runner utilities."""

import pytest

from crczp.sandbox_ansible_app.lib.ansible import AllocationAnsibleRunner
from crczp.sandbox_instance_app.lib import sandboxes
from crczp.sandbox_instance_app.models import Sandbox, SandboxNetbirdResources

pytestmark = pytest.mark.django_db


class TestPrepareInventoryFile:
    """Tests for Ansible inventory file preparation."""

    @pytest.fixture(autouse=True)
    def set_up(self, mocker, top_ins):  # pylint: disable=attribute-defined-outside-init
        """Set up mocks for each test."""
        self.client = mocker.patch('crczp.sandbox_common_lib.utils.get_terraform_client')
        self.client.get_sandbox.return_value = top_ins
        self.save_file = mocker.patch(
            'crczp.sandbox_ansible_app.lib.ansible.AnsibleRunner.save_file'
        )
        yield

    def test_prepare_inventory_file_success(self, mocker, top_ins):  # pylint: disable=unused-argument
        """Test that the inventory file is saved when preparing a successful allocation."""
        mock_inventory = mocker.patch('crczp.sandbox_ansible_app.lib.ansible.Inventory')
        mocker.patch.object(sandboxes, 'get_topology_instance', return_value=top_ins)

        dir_path = '/tmp'  # nosec B108
        sandbox = Sandbox.objects.get(pk=1)
        AllocationAnsibleRunner(dir_path).prepare_inventory_file(sandbox)

        mock_inventory.assert_called_once()

    def test_prepare_inventory_object(self, mocker, top_ins, inventory):
        """Test that create_inventory returns a correctly structured inventory dict."""
        mocker.patch.object(sandboxes, 'get_topology_instance', return_value=top_ins)
        dir_path = mocker.MagicMock()
        sandbox = Sandbox.objects.get(pk=1)
        sandbox.allocation_unit.pool.get_pool_prefix = mocker.MagicMock()
        sandbox.allocation_unit.pool.get_pool_prefix.return_value = 'pool-prefix'
        sandbox.allocation_unit.get_stack_name = mocker.MagicMock()
        sandbox.allocation_unit.get_stack_name.return_value = 'stack-name'
        result = AllocationAnsibleRunner(dir_path).create_inventory(sandbox)

        assert result.to_dict() == inventory

    def test_create_inventory_attaches_netbird_setup_key(self, mocker, top_ins_vpn):
        sandboxes.get_topology_instance = mocker.MagicMock()
        sandboxes.get_topology_instance.return_value = top_ins_vpn

        dir_path = mocker.MagicMock()
        sandbox = Sandbox.objects.get(pk=1)
        sandbox.allocation_unit.pool.get_pool_prefix = mocker.MagicMock()
        sandbox.allocation_unit.pool.get_pool_prefix.return_value = 'pool-prefix'
        sandbox.allocation_unit.get_stack_name = mocker.MagicMock()
        sandbox.allocation_unit.get_stack_name.return_value = 'stack-name'

        SandboxNetbirdResources.objects.create(
            sandbox=sandbox,
            entrypoint_host_name='server',
            host_setup_key_value='SK-TEST-123',
        )

        result = AllocationAnsibleRunner(dir_path).create_inventory(sandbox)

        vpn_group = result.get_group('vpn_entrypoints')
        assert vpn_group is not None
        assert vpn_group.hosts_vars['server'] == {'netbird_setup_key': 'SK-TEST-123'}
