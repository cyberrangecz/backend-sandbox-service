import pytest
from unittest.mock import call
from django.db.models import ObjectDoesNotExist
from django.utils import timezone
from functools import partial

from crczp.sandbox_instance_app.models import Sandbox, CleanupRequest, SandboxAllocationUnit, \
    AllocationRequest, StackAllocationStage
from crczp.sandbox_instance_app.lib import requests

from crczp.sandbox_common_lib import exceptions as api_exceptions

pytestmark = pytest.mark.django_db


class TestAllocationRequest:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker):
        self.handler = mocker.patch('crczp.sandbox_instance_app.lib.requests.request_handlers.'
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

    def test_create_allocation_requests_with_created_by_sub_persists_metadata(self, pool, mocker):
        """Single-sandbox-per-user: created_by_sub and created_at are set when provided."""
        mocker.patch('django.db.transaction.on_commit')
        requests.create_allocations_requests(pool, 1, created_by=None, created_by_sub='user-123')
        unit = SandboxAllocationUnit.objects.get(pool=pool)
        assert unit.created_by_sub == 'user-123'
        assert unit.created_at is not None

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
        mocker.patch('crczp.sandbox_instance_app.lib.requests.LOG')
        self.handler = mocker.patch('crczp.sandbox_instance_app.lib.requests.request_handlers.'
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
        mocker.patch('crczp.sandbox_instance_app.lib.requests.request_handlers.'
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

        mocker.patch('crczp.sandbox_instance_app.lib.requests.cancel_cleanup_request',
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
        mocker.patch('crczp.sandbox_instance_app.lib.requests.request_handlers.'
                     'AllocationRequestHandler')
        unit_alloc_unfinished = SandboxAllocationUnit.objects.get(pk=1)
        allocation_units = [unit_alloc_unfinished, sandbox_lock.sandbox.allocation_unit]

        requests.create_cleanup_requests([allocation_unit for allocation_unit in allocation_units], True)
        self.assert_multiple_cleanup_requests_success(allocation_units)

    def test_create_cleanup_requests_force_skips_first_stage_running(self, mocker, sandbox_finished,
                                                                     pool, created_by):
        """Delete All / Delete Unlocked: when force=True, skip units with first stage running and clean the rest."""
        mocker.patch('crczp.sandbox_instance_app.lib.requests.request_handlers.'
                     'AllocationRequestHandler')
        cleanup_handler = mocker.patch('crczp.sandbox_instance_app.lib.requests.request_handlers.'
                                       'CleanupRequestHandler')
        # Unit that can be cleaned (all stages finished)
        unit_finished = sandbox_finished.allocation_unit
        # Second unit with first stage running (start set, not finished/failed)
        unit_running = SandboxAllocationUnit.objects.create(pool=pool, created_by=created_by)
        alloc_req = AllocationRequest.objects.create(allocation_unit=unit_running)
        StackAllocationStage.objects.create(
            allocation_request=alloc_req,
            allocation_request_fk_many=alloc_req,
            start=timezone.now(),
            finished=False,
            failed=False,
        )
        Sandbox.objects.create(
            id=unit_running.id,
            allocation_unit=unit_running,
            private_user_key='key',
            public_user_key='pub',
            ready=False,
        )
        allocation_units = [unit_finished, unit_running]
        requests.create_cleanup_requests(allocation_units, force=True)
        # Finished unit cleaned, running unit skipped
        with pytest.raises(ObjectDoesNotExist):
            Sandbox.objects.get(pk=unit_finished.sandbox.id)
        assert Sandbox.objects.get(pk=unit_running.sandbox.id) is not None
        cleanup_handler.return_value.enqueue_request.assert_called_once_with(unit_finished)

    def test_force_cancel_allocation_units_in_pool_removes_stuck_units(self, mocker, pool,
                                                                       created_by):
        """Force Cancel Allocation removes units with first stage running from the DB."""
        mocker.patch('crczp.sandbox_instance_app.lib.requests.request_handlers.'
                     'AllocationRequestHandler')
        unit = SandboxAllocationUnit.objects.create(pool=pool, created_by=created_by)
        alloc_req = AllocationRequest.objects.create(allocation_unit=unit)
        StackAllocationStage.objects.create(
            allocation_request=alloc_req,
            allocation_request_fk_many=alloc_req,
            start=timezone.now(),
            finished=False,
            failed=False,
        )
        Sandbox.objects.create(
            id=unit.id,
            allocation_unit=unit,
            private_user_key='key',
            public_user_key='pub',
            ready=False,
        )
        pool.size = 1
        pool.save()
        assert SandboxAllocationUnit.objects.filter(pool=pool).count() == 1
        cancelled = requests.force_cancel_allocation_units_in_pool(pool.id)
        assert cancelled == 1
        assert SandboxAllocationUnit.objects.filter(pool=pool).count() == 0
        pool.refresh_from_db()
        assert pool.size == 0

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
