import pytest

from kypo.sandbox_ansible_app.lib.ansible import AnsibleDockerRunner
from kypo.sandbox_instance_app.models import Sandbox

pytestmark = pytest.mark.django_db


class TestPrepareInventoryFile:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker, top_ins):
        self.client = mocker.patch('kypo.sandbox_common_lib.utils.get_ostack_client')
        self.client.get_sandbox.return_value = top_ins
        self.save_file = mocker.patch(
            'kypo.sandbox_ansible_app.lib.ansible.AnsibleDockerRunner.save_file')
        yield

    def test_prepare_inventory_file_success(self, mocker, top_ins):
        mock_inventory = mocker.patch('kypo.sandbox_ansible_app.lib.ansible.Inventory')
        dir_path = '/tmp'
        sandbox = Sandbox.objects.get(pk=1)
        AnsibleDockerRunner().prepare_inventory_file(dir_path, sandbox, top_ins)

        mock_inventory.assert_called_once()

    def test_prepare_inventory_object(self, top_ins, inventory):
        sandbox = Sandbox.objects.get(pk=1)
        result = AnsibleDockerRunner().prepare_inventory(sandbox, top_ins)

        assert result.data == inventory
