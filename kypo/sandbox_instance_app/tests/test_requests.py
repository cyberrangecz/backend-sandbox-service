import pytest
from unittest.mock import call
from django.db.models import ObjectDoesNotExist
from django.utils import timezone
from functools import partial

from kypo.sandbox_instance_app.models import Sandbox, CleanupRequest, SandboxAllocationUnit
from kypo.sandbox_instance_app.lib import requests

from kypo.sandbox_common_lib import exceptions as api_exceptions

pytestmark = pytest.mark.django_db


class TestAllocationRequest:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker):
        self.handler = mocker.patch('kypo.sandbox_instance_app.lib.requests.request_handlers.'
                                    'AllocationRequestHandler')

    def test_create_allocation_requests_success(self, pool, created_by, mocker):
        fake_on_commit = mocker.patch('django.db.transaction.on_commit')
        requests.create_allocations_requests(pool, 2, created_by)
        created_units = list(SandboxAllocationUnit.objects.filter(pool=pool))

        expected_partial = partial(self.handler.return_value.enqueue_request, created_units, created_by)
        actual_partial = fake_on_commit.call_args.args[0]

        # Assert the correct transaction.on_commit args are passed
        assert expected_partial.func == actual_partial.func
        assert expected_partial.args == actual_partial.args
        assert expected_partial.keywords == actual_partial.keywords

    def test_cancel_allocation_request_success(self, allocation_request_started):
        requests.cancel_allocation_request(allocation_request_started)

        self.handler.return_value.cancel_request.assert_called_once_with(allocation_request_started)

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

    def assert_cleanup_request_success(self, allocation_unit, force=False):
        requests.create_cleanup_requests([allocation_unit], force)

        with pytest.raises(ObjectDoesNotExist):
            assert Sandbox.objects.get(pk=allocation_unit.sandbox.id)

        self.handler.return_value.enqueue_request.assert_called_once_with(allocation_unit)

    def assert_cleanup_request_failed(self, allocation_unit):
        with pytest.raises(api_exceptions.ValidationError):
            requests.create_cleanup_request(allocation_unit)

        with pytest.raises(ObjectDoesNotExist):
            assert CleanupRequest.objects.get(pk=allocation_unit.id)
        self.handler.assert_not_called()

    def assert_cleanup_ongoing_force_skipped(self, allocation_unit):
        requests.create_cleanup_request_force(allocation_unit, False)

        self.handler.assert_not_called()

    def assert_multiple_cleanup_requests_success(self, allocation_units):
        for allocation_unit in allocation_units:
            with pytest.raises(ObjectDoesNotExist):
                assert Sandbox.objects.get(pk=allocation_unit.sandbox.id)

        self.handler.return_value.enqueue_request.assert_has_calls(
            [call(allocation_unit) for allocation_unit in allocation_units])

    def test_create_cleanup_request_success(self, sandbox_finished):
        allocation_unit = sandbox_finished.allocation_unit
        self.assert_cleanup_request_success(allocation_unit)

    def test_create_cleanup_request_failed_locked_sandbox(self, sandbox_lock):
        allocation_unit = sandbox_lock.sandbox.allocation_unit
        self.assert_cleanup_request_failed(allocation_unit)
        assert Sandbox.objects.get(pk=sandbox_lock.sandbox.id)

    def test_create_cleanup_request_force_locked_sandbox(self, sandbox_lock):
        allocation_unit = sandbox_lock.sandbox.allocation_unit
        self.assert_cleanup_request_success(allocation_unit, True)

    def test_create_cleanup_request_failed_active_allocation_request(self,
                                                                     allocation_stage_user_started):
        allocation_unit = allocation_stage_user_started.allocation_request.allocation_unit
        self.assert_cleanup_request_failed(allocation_unit)

    def test_create_cleanup_request_force_active_allocation_request(self, mocker,
                                                                    allocation_stage_user_started):
        allocation_unit = allocation_stage_user_started.allocation_request.allocation_unit
        mocker.patch('kypo.sandbox_instance_app.lib.requests.request_handlers.'
                     'AllocationRequestHandler')
        self.assert_cleanup_request_success(allocation_unit, True)

    def test_create_cleanup_request_failed_already_cleaning(self, sandbox_finished,
                                                            cleanup_request_started):
        allocation_unit = sandbox_finished.allocation_unit
        self.assert_cleanup_request_failed(allocation_unit)

    def test_create_cleanup_request_force_already_cleaning(self, mocker, sandbox_finished,
                                                           cleanup_request_started):
        allocation_unit = sandbox_finished.allocation_unit

        def mock_is_finished(_):
            CleanupRequest.is_finished = mocker.PropertyMock()
            CleanupRequest.is_finished.return_value = True

        mocker.patch('kypo.sandbox_instance_app.lib.requests.cancel_cleanup_request',
                     side_effect=mock_is_finished)
        self.assert_cleanup_ongoing_force_skipped(allocation_unit)

    def test_create_cleanup_requests(self, sandbox_finished):
        allocation_unit = sandbox_finished.allocation_unit

        requests.create_cleanup_requests([allocation_unit])
        self.assert_multiple_cleanup_requests_success([allocation_unit])

    @staticmethod
    def assert_cleanup_request_all_failed(allocation_units):
        with pytest.raises(api_exceptions.ValidationError):
            requests.create_cleanup_requests(
                [allocation_unit for allocation_unit in allocation_units])

        for allocation_unit in allocation_units:
            with pytest.raises(ObjectDoesNotExist):
                assert CleanupRequest.objects.get(pk=allocation_unit.id)

    def test_create_cleanup_requests_many_alloc_unfinished_first_fail(self, sandbox_finished):
        unit_alloc_unfinished = SandboxAllocationUnit.objects.get(pk=1)
        allocation_units = [sandbox_finished.allocation_unit, unit_alloc_unfinished]
        self.assert_cleanup_request_all_failed(allocation_units)

    def test_create_cleanup_requests_many_alloc_unfinished_last_fail(self, sandbox_finished):
        unit_alloc_unfinished = SandboxAllocationUnit.objects.get(pk=1)
        allocation_units = [unit_alloc_unfinished, sandbox_finished.allocation_unit]
        self.assert_cleanup_request_all_failed(allocation_units)

    def test_create_cleanup_requests_many_alloc_unfinished_locked_force(self, mocker, sandbox_lock):
        mocker.patch('kypo.sandbox_instance_app.lib.requests.request_handlers.'
                     'AllocationRequestHandler')
        unit_alloc_unfinished = SandboxAllocationUnit.objects.get(pk=1)
        allocation_units = [unit_alloc_unfinished, sandbox_lock.sandbox.allocation_unit]

        requests.create_cleanup_requests([allocation_unit for allocation_unit in allocation_units], True)
        self.assert_multiple_cleanup_requests_success(allocation_units)

    def test_cancel_cleanup_request_success(self, cleanup_request_started):
        requests.cancel_cleanup_request(cleanup_request_started)
        self.handler.return_value.cancel_request.assert_called_once_with(cleanup_request_started)

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
