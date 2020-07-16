import pytest
from django.conf import settings
from django.http import Http404
from rest_framework.exceptions import ValidationError
from rest_framework.reverse import reverse
from rest_framework.test import APIRequestFactory

from kypo.sandbox_common_lib.exceptions import ApiException
from kypo.sandbox_instance_app.lib import pools
from kypo.sandbox_instance_app.models import SandboxAllocationUnit, Sandbox
from kypo.sandbox_instance_app.views import PoolList

pytestmark = pytest.mark.django_db

DEFINITION_ID = 1
POOL_ID = 1
FULL_POOL_ID = 2


class TestCreatePool:
    MAX_SIZE = 10
    REV = "a1b2c3"

    @pytest.fixture(autouse=True)
    def set_up(self, mocker):
        self.client = mocker.patch("kypo.sandbox_common_lib.utils.get_ostack_client")
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.get_definition")
        mock_repo = mocker.patch("kypo.sandbox_definition_app.lib.definitions.get_def_provider")
        mock_repo.return_value.get_rev_sha = mocker.MagicMock(return_value='sha')
        self.arf = APIRequestFactory()
        yield

    def test_create_pool_success(self):
        pool = pools.create_pool(dict(definition_id=DEFINITION_ID,
                                      max_size=self.MAX_SIZE,
                                      rev=self.REV))
        assert pool.max_size == self.MAX_SIZE
        assert pool.rev == self.REV
        assert pool.definition.id == DEFINITION_ID

    def test_create_pool_invalid_definition(self):
        with pytest.raises(Http404):
            pools.create_pool(dict(definition_id=-1,
                                   max_size=self.MAX_SIZE,
                                   rev=self.REV))

    def test_create_pool_invalid_size(self):
        with pytest.raises(ValidationError):
            pools.create_pool(dict(definition_id=1,
                                   max_size=-10,
                                   rev=self.REV))

    def test_pool_views(self):
        request = self.arf.get(reverse('pool-list'))
        response = PoolList.as_view()(request)
        assert len(response.data['results']) == 2


class TestSandboxAllocationUnit:

    def test_get_stack_name(self):
        au: SandboxAllocationUnit = SandboxAllocationUnit.objects.get(id=1)
        prefix = settings.KYPO_SERVICE_CONFIG.stack_name_prefix

        expected_stack_name = f'{prefix}-pool-id-{au.pool.id}-sau-id-{au.id}'
        assert au.get_stack_name() == expected_stack_name

        sb: Sandbox = Sandbox.objects.get(id=1)
        assert sb.allocation_unit.get_stack_name() == expected_stack_name


class TestCreateSandboxesInPool:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker):
        self.create_mock = mocker.patch(
            "kypo.sandbox_instance_app.lib.sandbox_creator.enqueue_allocation_request")
        yield

    def test_create_sandboxes_in_pool_success_one(self):
        pool = pools.get_pool(POOL_ID)
        requests = pools.create_sandboxes_in_pool(pool, 1)

        assert len(requests) == 1
        assert all([req.pool.id == pool.id
                    for req in requests])

    def test_create_sandboxes_in_pool_success_all(self):
        pool = pools.get_pool(POOL_ID)
        size_before = pools.get_pool_size(pool)

        requests = pools.create_sandboxes_in_pool(pool)

        assert len(requests) == pool.max_size - size_before
        assert all([req.pool.id == pool.id
                    for req in requests])

    def test_create_sandboxes_in_pool_full(self):
        pool = pools.get_pool(FULL_POOL_ID)
        with pytest.raises(ApiException):
            pools.create_sandboxes_in_pool(pool, 1)


class TestGetUnlockedSandbox:
    def test_get_unlocked_sandbox_success(self):
        pool = pools.get_pool(POOL_ID)
        sb = pools.get_unlocked_sandbox(pool)
        assert sb.id == 1
        assert sb.lock

    def test_get_unlocked_sandbox_empty(self):
        pool = pools.get_pool(FULL_POOL_ID)
        sb = pools.get_unlocked_sandbox(pool)
        assert sb is None
