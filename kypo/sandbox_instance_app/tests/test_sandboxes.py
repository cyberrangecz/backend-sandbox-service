import zipfile
import pytest
from django.db import IntegrityError
from django.http import Http404

from kypo.sandbox_instance_app import serializers
from kypo.sandbox_common_lib import exceptions
from kypo.sandbox_instance_app.lib import sandboxes
from kypo.sandbox_instance_app.models import Sandbox, SandboxAllocationUnit

pytestmark = pytest.mark.django_db

SANDBOX_ID = 1


class TestGetSandbox:
    def test_get_sandbox_success(self):
        assert sandboxes.get_sandbox(SANDBOX_ID).id == SANDBOX_ID

    def test_get_sandbox_404(self):
        with pytest.raises(Http404):
            sandboxes.get_sandbox(-1)

    def test_id_generation_raises(self):
        au: SandboxAllocationUnit = SandboxAllocationUnit.objects.create(pool_id=1)
        with pytest.raises(IntegrityError):
            Sandbox.objects.create(allocation_unit=au)

    def test_id_generation_success(self):
        au: SandboxAllocationUnit = SandboxAllocationUnit.objects.create(pool_id=1)
        sandbox: Sandbox = Sandbox.objects.create(id=64, allocation_unit=au)
        assert sandboxes.get_sandbox(sandbox.id) is not None


class TestSandboxesManipulation:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker, top_ins):
        self.mock_get_top_ins = mocker.patch(
            'kypo.sandbox_instance_app.lib.sandboxes.get_topology_instance')
        self.mock_get_top_ins.return_value = top_ins
        yield

    def test_lock_sandbox_success(self):
        sandbox = sandboxes.get_sandbox(SANDBOX_ID)
        assert sandboxes.lock_sandbox(sandbox).sandbox.id == sandbox.id

    def test_lock_sandbox_already_locked(self, mocker):
        mocker.patch('kypo.sandbox_instance_app.lib.sandboxes.Sandbox')
        with pytest.raises(exceptions.ValidationError):
            sandboxes.lock_sandbox(mocker.Mock())

    def test_get_sandbox_topology(self, mocker, topology):
        topo = sandboxes.get_sandbox_topology(mocker.Mock())

        result = serializers.TopologySerializer(topo).data

        for item in ['hosts', 'routers', 'switches', 'ports']:
            assert sorted(topology[item], key=lambda x: x['name']) == \
                   sorted(result[item], key=lambda x: x['name'])
        for item in ['links']:
            assert sorted(topology[item], key=lambda x: x['port_a']) == \
                   sorted(result[item], key=lambda x: x['port_a'])

    def test_get_user_sshconfig(self, mocker, user_ssh_config):
        ssh_conf = sandboxes.get_user_sshconfig(mocker.Mock())
        assert ssh_conf.serialize() == user_ssh_config

    def test_get_ssh_access_source_file(self, ssh_access_source):
        ssh_access_source_file = sandboxes.get_ssh_access_source_file('<ssh_config_path>')

        assert ssh_access_source_file == ssh_access_source

    def test_get_user_ssh_access(self, sandbox, user_ssh_config):
        ssh_access_name = f'pool-id-{sandbox.allocation_unit.pool.id}-sandbox-id-{sandbox.id}-user'
        ssh_config_name = f'{ssh_access_name}-config'
        private_key = f'{ssh_access_name}-key'
        user_ssh_config = user_ssh_config.replace('<path_to_sandbox_private_key>',
                                                  f'~/.ssh/{private_key}')

        in_memory_zip_file = sandboxes.get_user_ssh_access(sandbox)

        with zipfile.ZipFile(in_memory_zip_file, 'r', zipfile.ZIP_DEFLATED) as zip_file:
            with zip_file.open(ssh_config_name) as file:
                assert file.read().decode('utf-8') == user_ssh_config
            with zip_file.open(private_key) as file:
                assert file.read().decode('utf-8') == sandbox.private_user_key
            with zip_file.open(f'{private_key}.pub') as file:
                assert file.read().decode('utf-8') == sandbox.public_user_key

    def test_get_management_sshconfig(self, mocker, management_ssh_config):
        ssh_conf = sandboxes.get_management_sshconfig(mocker.Mock())
        assert ssh_conf.serialize() == management_ssh_config

    def test_get_ansible_sshconfig(self, mocker, ansible_ssh_config):
        ssh_conf = sandboxes.get_ansible_sshconfig(mocker.Mock(),
                                                   mng_key='/root/.ssh/pool_mng_key',
                                                   git_key='/root/.ssh/git_rsa_key',
                                                   proxy_key='/root/.ssh/id_rsa')
        assert ssh_conf.serialize() == ansible_ssh_config
