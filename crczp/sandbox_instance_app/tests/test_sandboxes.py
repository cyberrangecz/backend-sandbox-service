"""Tests for sandbox management functions."""

import io
import zipfile
from unittest import mock

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError
from django.http import Http404
from rest_framework.test import APIRequestFactory

from crczp.sandbox_common_lib import exceptions
from crczp.sandbox_instance_app import serializers
from crczp.sandbox_instance_app.lib import sandboxes, sshconfig
from crczp.sandbox_instance_app.models import Sandbox, SandboxAllocationUnit
from crczp.sandbox_instance_app.views import SandboxUserSSHAccessView

pytestmark = pytest.mark.django_db

SANDBOX_ID = 1
SANDBOX_UUID = '1'


class TestGetSandbox:
    """Tests for the get_sandbox retrieval function."""

    def test_get_sandbox_success(self):
        """Test successful sandbox retrieval by ID."""
        assert sandboxes.get_sandbox(SANDBOX_ID).id == SANDBOX_UUID

    def test_get_sandbox_404(self):
        """Test that a non-existent sandbox raises Http404."""
        with pytest.raises(Http404):
            sandboxes.get_sandbox(-1)

    def test_id_generation_raises(self, created_by):
        """Test that creating a Sandbox without an ID raises IntegrityError."""
        au: SandboxAllocationUnit = SandboxAllocationUnit.objects.create(
            pool_id=1, created_by=created_by
        )
        with pytest.raises(IntegrityError):
            Sandbox.objects.create(allocation_unit=au)

    def test_id_generation_success(self, created_by):
        """Test that creating a Sandbox with an explicit ID succeeds."""
        au: SandboxAllocationUnit = SandboxAllocationUnit.objects.create(
            pool_id=1, created_by=created_by
        )
        sandbox: Sandbox = Sandbox.objects.create(id=64, allocation_unit=au, ready=True)
        assert sandboxes.get_sandbox(sandbox.id) is not None


class TestSandboxesManipulation:
    """Tests for sandbox locking, topology, and SSH config operations."""

    @pytest.fixture(autouse=True)
    def set_up(self, mocker, top_ins):
        """Patch get_topology_instance to return a test topology instance."""
        self.mock_get_top_ins = mocker.patch(
            'crczp.sandbox_instance_app.lib.sandboxes.get_topology_instance'
        )
        self.mock_get_top_ins.return_value = top_ins
        yield

    def test_lock_sandbox_success_anonymous_user(self):
        """Test locking a sandbox with an anonymous user succeeds."""
        sandbox = sandboxes.get_sandbox(SANDBOX_ID)
        assert sandboxes.lock_sandbox(sandbox, None).sandbox.id == sandbox.id

    def test_lock_sandbox_already_locked_anonymous_user(self, mocker):
        """Test that locking an already-locked sandbox raises ValidationError."""
        mocker.patch('crczp.sandbox_instance_app.lib.sandboxes.Sandbox')
        with pytest.raises(exceptions.ValidationError):
            sandboxes.lock_sandbox(mocker.Mock(), None)

    def test_lock_sandbox_success(self, created_by):
        """Test locking a sandbox with an authenticated user succeeds."""
        sandbox = sandboxes.get_sandbox(SANDBOX_ID)
        assert sandboxes.lock_sandbox(sandbox, created_by).sandbox.id == sandbox.id

    def test_lock_sandbox_already_locked(self, mocker, created_by):
        """Test that locking an already-locked sandbox with a user raises ValidationError."""
        mocker.patch('crczp.sandbox_instance_app.lib.sandboxes.Sandbox')
        with pytest.raises(exceptions.ValidationError):
            sandboxes.lock_sandbox(mocker.Mock(), created_by)

    def test_get_sandbox_topology(self, mocker, topology, image):
        """Test that get_sandbox_topology returns correctly serialized topology data."""
        mock_images = mocker.patch('crczp.terraform_driver.CrczpTerraformClient.list_images')
        mock_images.return_value = [image]

        with (
            mock.patch('django.core.cache.cache.get') as mock_cache_get,
            mock.patch('django.core.cache.cache.set'),
        ):
            mock_cache_get.return_value = None
            topo = sandboxes.get_sandbox_topology(mocker.Mock())

        result = serializers.TopologySerializer(topo).data

        assert sorted(topology['routers'], key=lambda x: x['name']) == sorted(
            result['routers'], key=lambda x: x['name']
        )

    def test_get_user_ssh_config(self, mocker, user_ssh_config):
        """Test that get_user_sshconfig returns the expected SSH config."""
        sandbox = mocker.MagicMock()
        sandbox.allocation_unit.get_stack_name.return_value = 'stack-name'

        ssh_conf = sandboxes.get_user_sshconfig(sandbox)
        assert ssh_conf.asdict() == user_ssh_config.asdict()

    def test_get_user_ssh_access(self, mocker, sandbox, user_ssh_config):
        """Test that get_user_ssh_access returns a zip containing the SSH config and keys."""
        sandbox.allocation_unit.get_stack_name = mocker.MagicMock()
        sandbox.allocation_unit.get_stack_name.return_value = 'stack-name'
        ssh_access_name = f'pool-id-{sandbox.allocation_unit.pool.id}-sandbox-id-{sandbox.id}-user'
        ssh_config_name = f'{ssh_access_name}-config'
        private_key = f'{ssh_access_name}-key'

        for host in user_ssh_config.hosts:
            identity_file = host.get('IdentityFile')
            host.set(
                'IdentityFile',
                identity_file.replace('<path_to_sandbox_private_key>', f'~/.ssh/{private_key}'),
            )

        in_memory_zip_file = sandboxes.get_user_ssh_access(sandbox)

        with zipfile.ZipFile(in_memory_zip_file, 'r', zipfile.ZIP_DEFLATED) as zip_file:
            with zip_file.open(ssh_config_name) as file:
                assert (
                    sshconfig.CrczpSSHConfig.from_str(file.read().decode('utf-8')).asdict()
                    == user_ssh_config.asdict()
                )
            with zip_file.open(private_key) as file:
                assert file.read().decode('utf-8') == sandbox.private_user_key
            with zip_file.open(f'{private_key}.pub') as file:
                assert file.read().decode('utf-8') == sandbox.public_user_key

    def test_get_management_ssh_config(self, mocker, management_ssh_config):
        """Test that get_management_sshconfig returns the expected SSH config."""
        sandbox = mocker.Mock()
        sandbox.allocation_unit.pool.get_pool_prefix.return_value = 'pool-prefix'

        ssh_conf = sandboxes.get_management_sshconfig(sandbox)

        assert ssh_conf.asdict() == management_ssh_config.asdict()

    def test_get_ansible_ssh_config(self, mocker, ansible_ssh_config):
        """Test that get_ansible_sshconfig returns the expected SSH config."""
        ssh_conf = sandboxes.get_ansible_sshconfig(
            mocker.Mock(), mng_key='/root/.ssh/pool_mng_key', proxy_key='/root/.ssh/id_rsa'
        )
        assert ssh_conf.asdict() == ansible_ssh_config.asdict()


class TestSandboxUserSSHAccessView:
    """Tests for the sandbox user SSH access API view."""

    @pytest.fixture(autouse=True)
    def set_up(self):
        """Create the request factory used by the view tests."""
        self.factory = APIRequestFactory()

    def test_sets_content_disposition_filename_to_sandbox_id(self, mocker, sandbox):
        """Test that the downloaded filename uses the sandbox identifier."""
        sandbox.id = 'sandbox-uuid'
        mocker.patch('crczp.sandbox_instance_app.views.sandboxes.get_sandbox', return_value=sandbox)
        mocker.patch(
            'crczp.sandbox_instance_app.views.sandboxes.get_user_ssh_access',
            return_value=io.BytesIO(b'zip-content'),
        )

        request = self.factory.get(f'/sandboxes/{sandbox.id}/user-ssh-access')
        request.user = AnonymousUser()

        response = SandboxUserSSHAccessView.as_view()(request, sandbox_uuid=sandbox.id)

        assert response.status_code == 200
        assert response['Content-Disposition'] == (
            f'attachment; filename=user-ssh-access-pool-{sandbox.allocation_unit.pool.id}'
            f'-sandbox-{sandbox.id}.zip'
        )
