import pytest
from rest_framework.exceptions import ValidationError

from kypo.sandbox_common_lib.exceptions import ApiException
from kypo.sandbox_instance_app.lib import pools

pytestmark = pytest.mark.django_db

DEFINITION_ID = 1
POOL_ID = 1
FULL_POOL_ID = 2


class TestCreatePool:
    MAX_SIZE = 10

    @pytest.fixture(autouse=True)
    def set_up(self, mocker):
        self.client = mocker.patch("kypo.sandbox_common_lib.utils.get_ostack_client")
        yield

    def test_create_pool_success(self):
        pool = pools.create_pool(dict(definition=DEFINITION_ID,
                                             max_size=self.MAX_SIZE))
        assert pool.max_size == self.MAX_SIZE
        assert pool.definition.id == DEFINITION_ID

    def test_create_pool_invalid_definition(self):
        with pytest.raises(ValidationError):
            pools.create_pool(dict(definition=-1,
                                          max_size=self.MAX_SIZE))


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
