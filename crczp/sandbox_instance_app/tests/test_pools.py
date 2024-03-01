import pytest
import zipfile
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from rest_framework.exceptions import ValidationError
from rest_framework.reverse import reverse
from rest_framework.test import APIRequestFactory

from crczp.sandbox_common_lib.exceptions import ApiException, StackError
from crczp.sandbox_instance_app.lib import pools, sshconfig
from crczp.sandbox_instance_app.models import SandboxAllocationUnit, Sandbox
from crczp.sandbox_instance_app.views import PoolListCreateView, SandboxGetAndLockView

from crczp.cloud_commons import exceptions, HardwareUsage


pytestmark = pytest.mark.django_db

DEFINITION_ID = 1
POOL_ID = 1
FULL_POOL_ID = 2
SANDBOX_UUID = '1'


class TestCreatePool:
    MAX_SIZE = 10

    @pytest.fixture(autouse=True)
    def set_up(self, mocker, image):
        self.client = mocker.patch("crczp.sandbox_common_lib.utils.get_terraform_client")
        mocker.patch("crczp.sandbox_cloud_app.lib.projects.list_images", return_value=[image])
        mocker.patch("crczp.sandbox_definition_app.lib.definitions.get_definition")
        mocker.patch("crczp.sandbox_definition_app.lib.definitions.get_containers")
        mock_repo = mocker.patch("crczp.sandbox_definition_app.lib.definitions.get_def_provider")
        mock_repo.return_value.get_rev_sha = mocker.MagicMock(return_value='sha')
        self.arf = APIRequestFactory()
        yield

    def test_create_pool_success(self, definition, created_by, get_terraform_client):
        pool = pools.create_pool(dict(definition_id=DEFINITION_ID,
                                      max_size=self.MAX_SIZE), created_by=created_by)

        assert pool.max_size == self.MAX_SIZE
        assert pool.rev == definition.rev
        assert pool.definition.id == DEFINITION_ID

    def test_create_pool_invalid_definition(self, created_by):
        with pytest.raises(Http404):
            pools.create_pool(dict(definition_id=-1,
                                   max_size=self.MAX_SIZE), created_by=created_by)

    def test_create_pool_invalid_size(self, created_by):
        with pytest.raises(ValidationError):
            pools.create_pool(dict(definition_id=1,
                                   max_size=-10), created_by=created_by)

    def test_pool_views(self, mocker):
        mocker.patch("crczp.sandbox_instance_app.lib.pools.get_hardware_usage_of_sandbox",
                     return_value=HardwareUsage(**{'vcpu': 0.0, 'ram': 0.0, 'instances': 0.0,
                                                   'network': 0.0, 'subnet': 0.0, 'port': 0.0}))
        request = self.arf.get(reverse('pool-list'))
        response = PoolListCreateView.as_view()(request)
        assert len(response.data['results']) == 2


class TestSandboxAllocationUnit:

    def test_get_stack_name(self):
        au: SandboxAllocationUnit = SandboxAllocationUnit.objects.get(id=1)
        prefix = settings.CRCZP_SERVICE_CONFIG.stack_name_prefix

        expected_stack_name = f'{prefix}-p{au.pool.id:010d}-s{au.id:010d}'
        assert au.get_stack_name() == expected_stack_name

        sb: Sandbox = Sandbox.objects.get(id=1)
        assert sb.allocation_unit.get_stack_name() == expected_stack_name


class TestCreateSandboxesInPool:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker, definition):
        self.client = mocker.MagicMock()
        mock_get_client = mocker.patch("crczp.sandbox_common_lib.utils.get_terraform_client")
        mock_get_client.return_value = self.client
        mocker.patch("crczp.sandbox_definition_app.lib.definitions.get_definition")
        self.fake_create_allocation_requests = mocker.patch(
            "crczp.sandbox_instance_app.lib.requests.create_allocations_requests")

    def test_create_sandboxes_in_pool_success_one(self, created_by):
        pool = pools.get_pool(POOL_ID)
        pools.create_sandboxes_in_pool(pool, created_by, 1)
        self.fake_create_allocation_requests.assert_called_once_with(pool, 1, created_by)

    def test_create_sandboxes_in_pool_success_all(self, created_by):
        pool = pools.get_pool(POOL_ID)
        size_before = pool.size

        pools.create_sandboxes_in_pool(pool, created_by)
        self.fake_create_allocation_requests.assert_called_once_with(pool, pool.max_size - size_before, created_by)

    def test_create_sandboxes_in_pool_full(self, created_by):
        pool = pools.get_pool(FULL_POOL_ID)
        with pytest.raises(ApiException):
            pools.create_sandboxes_in_pool(pool, created_by, 1)

    def test_create_sandboxes_in_pool_limits_exceeded(self, created_by):
        self.client.validate_hardware_usage_of_stacks.side_effect =\
            exceptions.StackCreationFailed('testException')
        pool = pools.get_pool(POOL_ID)

        with pytest.raises(StackError):
            pools.create_sandboxes_in_pool(pool, created_by)


class TestGetUnlockedSandbox:
    def test_get_unlocked_sandbox_success_anonymous(self):
        pool = pools.get_pool(POOL_ID)
        sb = pools.get_unlocked_sandbox(pool, None)
        assert sb.id == SANDBOX_UUID
        assert sb.lock

    def test_get_unlocked_sandbox_empty_anonymous(self):
        pool = pools.get_pool(FULL_POOL_ID)
        sb = pools.get_unlocked_sandbox(pool, None)
        assert sb is None

    def test_get_unlocked_sandbox_success(self, created_by):
        pool = pools.get_pool(POOL_ID)
        sb = pools.get_unlocked_sandbox(pool, created_by)
        assert sb.id == SANDBOX_UUID
        assert sb.lock

    def test_get_unlocked_sandbox_empty(self, created_by):
        pool = pools.get_pool(FULL_POOL_ID)
        sb = pools.get_unlocked_sandbox(pool, created_by)
        assert sb is None


class TestGetManagementSSHAccess:
    mock_get_top_ins = None
    mock_get_sandboxes_in_pool = None

    @pytest.fixture(autouse=True)
    def set_up(self, mocker, top_ins, sandbox):
        self.mock_get_top_ins = mocker.patch(
            'crczp.sandbox_instance_app.lib.sandboxes.get_topology_instance')
        self.mock_get_top_ins.return_value = top_ins

        self.mock_get_sandboxes_in_pool = mocker.patch(
            'crczp.sandbox_instance_app.lib.pools.get_sandboxes_in_pool')
        self.mock_get_sandboxes_in_pool.return_value = [sandbox]
        yield

    def test_get_management_ssh_access_success(self, pool, sandbox, management_ssh_config, mocker):
        pool.get_pool_prefix = mocker.MagicMock()
        pool.get_pool_prefix.return_value = 'pool-prefix'
        ssh_access_name = f'pool-id-{pool.id}'
        ssh_config_name = f'{ssh_access_name}-sandbox-id-{sandbox.id}-management-config'
        private_key = f'{ssh_access_name}-management-key'

        for host in management_ssh_config:
            identity_file = host.get('IdentityFile')
            host.set('IdentityFile', identity_file.replace('<path_to_pool_private_key>',
                                                           f'~/.ssh/{private_key}'))

        in_memory_zip_file = pools.get_management_ssh_access(pool)

        with zipfile.ZipFile(in_memory_zip_file, 'r', zipfile.ZIP_DEFLATED) as zip_file:
            with zip_file.open(ssh_config_name) as file:
                assert sshconfig.CrczpSSHConfig.from_str(file.read().decode('utf-8')).asdict()\
                       == management_ssh_config.asdict()
            with zip_file.open(private_key) as file:
                assert file.read().decode('utf-8') == pool.private_management_key
            with zip_file.open(f'{private_key}.pub') as file:
                assert file.read().decode('utf-8') == pool.public_management_key


class TestPoolLock:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker, pool):
        self.factory = APIRequestFactory()
        self.wrong_training_access_token = "token-5768"
        mocker.patch('crczp.sandbox_common_lib.utils.get_object_or_404', return_value=pool)
        yield

    def test_sandbox_get_and_lock_view_correct_token_successful(self, pool, pool_lock, sandbox, training_access_token):
        request = self.factory.get(f"/pools/{pool.id}/sandboxes/get-and-lock/{training_access_token}")
        request.user = AnonymousUser()

        view = SandboxGetAndLockView()
        view.kwargs = {'training_access_token': training_access_token, 'pool_id': pool.id}
        response = view.get(request)

        assert response.status_code == 200
        assert response.data['lock_id'] == sandbox.lock.id
        assert response.data['allocation_unit_id'] == sandbox.allocation_unit_id

    def test_sandbox_get_and_lock_view_incorrect_token_unsuccessful(self, pool, pool_lock, training_access_token):
        request = self.factory.get(f"/pools/{pool.id}/sandboxes/get-and-lock/{training_access_token}")
        request.user = AnonymousUser()

        view = SandboxGetAndLockView()
        view.kwargs = {'training_access_token': self.wrong_training_access_token, 'pool_id': pool.id}
        response = view.get(request)

        assert response.status_code == 403

    def test_sandbox_get_and_lock_view_correct_token_full_pool(self, mocker, pool, pool_lock, sandbox, training_access_token):
        response = None

        responses_list = [sandbox] * (pool.max_size - 1)
        responses_list.append(None)
        mocker.patch('crczp.sandbox_instance_app.lib.pools.get_unlocked_sandbox', side_effect=responses_list)

        request = self.factory.get(f"/pools/{pool.id}/sandboxes/get-and-lock/{training_access_token}")
        request.user = AnonymousUser()
        view = SandboxGetAndLockView()
        view.kwargs = {'training_access_token': training_access_token, 'pool_id': pool.id}

        for _ in range(pool.max_size):
            response = view.get(request)

        assert response.status_code == 409
