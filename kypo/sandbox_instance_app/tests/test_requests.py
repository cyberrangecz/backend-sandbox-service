import pytest
from django.db.models import ObjectDoesNotExist
from django.utils import timezone

from kypo.sandbox_instance_app.models import Sandbox, CleanupRequest
from kypo.sandbox_common_lib import exceptions as api_exceptions

from kypo.sandbox_instance_app.lib import requests

pytestmark = pytest.mark.django_db


class TestAllocationRequest:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker):
        self.gen_ssh = mocker\
            .patch('kypo.sandbox_instance_app.lib.requests.utils.generate_ssh_keypair')
        self.gen_ssh.return_value = 'private-key', 'public-key'
        self.sandbox = mocker.patch('kypo.sandbox_instance_app.lib.requests.Sandbox')
        self.handler = mocker.patch('kypo.sandbox_instance_app.lib.requests.request_handlers.'
                                    'AllocationRequestHandler')

    def test_create_allocation_request_success(self, pool):
        sandbox_allocation_unit = requests.create_allocation_request(pool)

        assert sandbox_allocation_unit.pool_id == pool.id
        assert sandbox_allocation_unit.allocation_request
        self.gen_ssh.assert_called_once()
        self.sandbox.assert_called_once_with(id=sandbox_allocation_unit.id,
                                             allocation_unit=sandbox_allocation_unit,
                                             private_user_key=self.gen_ssh.return_value[0],
                                             public_user_key=self.gen_ssh.return_value[1])
        self.handler.assert_called_once_with(sandbox_allocation_unit.allocation_request)
        self.handler.return_value.enqueue_request.assert_called_once_with(self.sandbox.return_value)

    def test_create_allocation_requests_success(self, pool):
        sandbox_allocation_units = requests.create_allocations_requests(pool, 2)

        assert len(sandbox_allocation_units) == 2
        for sandbox_allocation_unit in sandbox_allocation_units:
            assert sandbox_allocation_unit.pool_id == pool.id
            assert sandbox_allocation_unit.allocation_request

    def test_cancel_allocation_request_success(self, allocation_request_started):
        requests.cancel_allocation_request(allocation_request_started)

        self.handler.assert_called_once_with(allocation_request_started)
        self.handler.return_value.cancel_request.assert_called_once()

    def test_get_allocation_request_stages_state(self, allocation_request,
                                                 allocation_stage_networking_started,
                                                 allocation_stage_user):
        stages_state = requests.get_allocation_request_stages_state(allocation_request)

        assert stages_state == [requests.StageState.FINISHED.value,
                                requests.StageState.RUNNING.value,
                                requests.StageState.IN_QUEUE.value]

    def test_get_allocation_request_stages_state_fail(self, allocation_request,
                                                      allocation_stage_networking_started,
                                                      allocation_stage_user):
        allocation_stage_networking_started.failed = True
        allocation_stage_networking_started.end = timezone.now()
        allocation_stage_user.failed = True
        allocation_stage_user.end = timezone.now()

        stages_state = requests.get_allocation_request_stages_state(allocation_request)

        assert stages_state == [requests.StageState.FINISHED.value,
                                requests.StageState.FAILED.value,
                                requests.StageState.FAILED.value]


class TestCleanupRequest:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker):
        mocker.patch('kypo.sandbox_instance_app.lib.requests.LOG')
        self.handler = mocker.patch('kypo.sandbox_instance_app.lib.requests.request_handlers.'
                                    'CleanupRequestHandler')

    def test_create_cleanup_request_success(self, sandbox_finished):
        allocation_unit = sandbox_finished.allocation_unit

        sandbox_cleanup_request = requests.create_cleanup_request(allocation_unit)

        assert sandbox_cleanup_request.allocation_unit_id == allocation_unit.id
        with pytest.raises(ObjectDoesNotExist):
            assert Sandbox.objects.get(pk=sandbox_cleanup_request.allocation_unit.sandbox.id)
        self.handler.assert_called_once_with(sandbox_cleanup_request)
        self.handler.return_value.enqueue_request.assert_called_once()

    def test_create_cleanup_request_failed_locked_sandbox(self, sandbox_lock):
        allocation_unit = sandbox_lock.sandbox.allocation_unit

        with pytest.raises(api_exceptions.ValidationError):
            requests.create_cleanup_request(allocation_unit)

        assert Sandbox.objects.get(pk=sandbox_lock.sandbox.id)
        with pytest.raises(ObjectDoesNotExist):
            assert CleanupRequest.objects.get(pk=allocation_unit.id)
        self.handler.assert_not_called()

    def test_create_cleanup_request_failed_active_allocation_request(self,
                                                                     allocation_stage_user_started):
        allocation_unit = allocation_stage_user_started.allocation_request.allocation_unit

        with pytest.raises(api_exceptions.ValidationError):
            requests.create_cleanup_request(allocation_unit)

        with pytest.raises(ObjectDoesNotExist):
            assert CleanupRequest.objects.get(pk=allocation_unit.id)
        self.handler.assert_not_called()

    def test_create_cleanup_request_failed_already_cleaning(self, cleanup_request_started):
        allocation_unit = cleanup_request_started.allocation_unit

        with pytest.raises(api_exceptions.ValidationError):
            requests.create_cleanup_request(allocation_unit)

        with pytest.raises(ObjectDoesNotExist):
            assert CleanupRequest.objects.get(pk=allocation_unit.id)
        self.handler.assert_not_called()

    def test_create_cleanup_requests_success(self, sandbox_finished):
        allocation_unit = sandbox_finished.allocation_unit

        cleanup_requests = requests.create_cleanup_requests([allocation_unit])

        assert len(cleanup_requests) == 1
        for cleanup_request in cleanup_requests:
            assert cleanup_request.allocation_unit_id == allocation_unit.id
            with pytest.raises(ObjectDoesNotExist):
                assert Sandbox.objects.get(pk=cleanup_request.allocation_unit.sandbox.id)

    def test_cancel_cleanup_request_success(self, cleanup_request_started):
        requests.cancel_cleanup_request(cleanup_request_started)

        self.handler.assert_called_once_with(cleanup_request_started)
        self.handler.return_value.cancel_request.assert_called_once()

    def test_delete_cleanup_request_success(self, cleanup_request_finished):
        requests.delete_cleanup_request(cleanup_request_finished)

        with pytest.raises(ObjectDoesNotExist):
            CleanupRequest.objects.get(pk=cleanup_request_finished.id)

    def test_get_cleanup_request_stages_state(self, cleanup_request, cleanup_stage_stack,
                                              cleanup_stage_networking_started):
        stages_state = requests.get_cleanup_request_stages_state(cleanup_request)

        assert stages_state == [requests.StageState.IN_QUEUE.value,
                                requests.StageState.RUNNING.value,
                                requests.StageState.FINISHED.value]

    def test_get_cleanup_request_stages_state_fail(self, cleanup_request, cleanup_stage_stack,
                                                   cleanup_stage_networking_started,
                                                   cleanup_stage_user):
        cleanup_stage_networking_started.end = timezone.now()
        cleanup_stage_networking_started.failed = True
        cleanup_stage_stack.end = timezone.now()
        cleanup_stage_stack.failed = True

        stages_state = requests.get_cleanup_request_stages_state(cleanup_request)

        assert stages_state == [requests.StageState.FAILED.value,
                                requests.StageState.FAILED.value,
                                requests.StageState.FINISHED.value]
