import pytest
from django_rq import get_worker, get_queue
from unittest.mock import MagicMock

from kypo.sandbox_common_lib import exceptions as api_exceptions
from kypo.sandbox_ansible_app.models import NetworkingAnsibleAllocationStage,\
    UserAnsibleAllocationStage, NetworkingAnsibleCleanupStage, UserAnsibleCleanupStage
from kypo.sandbox_instance_app.models import StackAllocationStage, StackCleanupStage

from kypo.sandbox_instance_app.lib import request_handlers

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


class PicklableMock(MagicMock):
    def __reduce__(self):
        return MagicMock, ()


def empty_queues():
    for queue_name in ['default', 'openstack', 'ansible']:
        queue = get_queue(queue_name)
        queue.empty()
        for register in [
            queue.started_job_registry,
            queue.deferred_job_registry,
            queue.finished_job_registry,
            queue.failed_job_registry,
            queue.scheduled_job_registry,
        ]:
            for job_id in register.get_job_ids():
                register.remove(job_id)


def assert_jobs_dependencies(jobs, default_queue):
    def _get_dependency(_job):
        _dependencies = [d.decode('utf-8') for d in _job.connection.smembers(_job.dependencies_key)]
        _dependents = [d.decode('utf-8') for d in _job.connection.smembers(_job.dependents_key)]
        return _dependencies, _dependents

    assert len(jobs) > 0
    expected_id = jobs[0].id
    expected_dependencies = []
    for job in jobs:
        dependencies, dependents = _get_dependency(job)
        assert len(dependents) == 1

        assert job.id == expected_id
        assert dependencies == expected_dependencies
        expected_id = dependents[0]
        expected_dependencies = [job.id]

    finalize_job = default_queue.fetch_job(expected_id)
    dependencies, dependents = _get_dependency(finalize_job)
    assert finalize_job.is_deferred
    assert finalize_job.id == expected_id
    assert dependencies == expected_dependencies
    assert dependents == []


class TestAllocationRequestHandler:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker):
        empty_queues()

        stack_execute_patch_target = 'kypo.sandbox_instance_app.lib.request_handlers.' \
                                     'AllocationStackStageHandler.execute'
        mocker.patch(stack_execute_patch_target, new_callable=PicklableMock)
        stack_cancel_patch_target = 'kypo.sandbox_instance_app.lib.request_handlers.' \
                                    'AllocationStackStageHandler.cancel'
        self.stack_cancel = mocker.patch(stack_cancel_patch_target, new_callable=PicklableMock)

        ansible_execute_patch_target = 'kypo.sandbox_instance_app.lib.request_handlers.' \
                                       'AllocationAnsibleStageHandler.execute'
        mocker.patch(ansible_execute_patch_target, new_callable=PicklableMock)
        ansible_cancel_patch_target = 'kypo.sandbox_instance_app.lib.request_handlers.' \
                                      'AllocationAnsibleStageHandler.cancel'
        self.ansible_cancel = mocker.patch(ansible_cancel_patch_target, new_callable=PicklableMock)

    @pytest.mark.django_db(transaction=True)
    def test_enqueue_request(self, allocation_request, sandbox):
        handler = request_handlers.AllocationRequestHandler(allocation_request)

        assert allocation_request.stages.all().count() == 0

        handler.enqueue_request(sandbox)

        assert allocation_request.stages.all().count() == 3

        assert isinstance(allocation_request.stackallocationstage, StackAllocationStage)
        assert isinstance(allocation_request.networkingansibleallocationstage,
                          NetworkingAnsibleAllocationStage)
        assert isinstance(allocation_request.useransibleallocationstage, UserAnsibleAllocationStage)

        job_stack = handler.queue_stack\
            .fetch_job(allocation_request.stackallocationstage.rq_job.job_id)
        job_networking = handler.queue_ansible\
            .fetch_job(allocation_request.networkingansibleallocationstage.rq_job.job_id)
        job_user = handler.queue_ansible\
            .fetch_job(allocation_request.useransibleallocationstage.rq_job.job_id)

        assert job_stack.is_queued
        assert job_networking.is_deferred
        assert job_user.is_deferred

        assert_jobs_dependencies([job_stack, job_networking, job_user], handler.queue_default)

        worker = get_worker('openstack', 'ansible', 'default')
        worker.work(burst=True)

        assert job_stack.is_finished
        assert job_networking.is_finished
        assert job_user.is_finished

    def test_cancel_request(self, allocation_request_started):
        handler = request_handlers.AllocationRequestHandler(allocation_request_started)

        handler.cancel_request()

        assert self.stack_cancel.call_count == 1
        assert self.ansible_cancel.call_count == 2

    def test_cancel_request_failed_on_completed_sandbox(self, sandbox_finished):
        handler = request_handlers\
            .AllocationRequestHandler(sandbox_finished.allocation_unit.allocation_request)

        with pytest.raises(api_exceptions.ValidationError):
            handler.cancel_request()

        self.stack_cancel.assert_not_called()
        self.ansible_cancel.assert_not_called()


class TestCleanupRequestHandler:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker):
        empty_queues()

        target = 'kypo.sandbox_instance_app.lib.request_handlers.CleanupStackStageHandler.execute'
        mocker.patch(target, new_callable=PicklableMock)
        target = 'kypo.sandbox_instance_app.lib.request_handlers.CleanupStackStageHandler.cancel'
        self.stack_cancel = mocker.patch(target, new_callable=PicklableMock)

        target = 'kypo.sandbox_instance_app.lib.request_handlers.CleanupAnsibleStageHandler.execute'
        mocker.patch(target, new_callable=PicklableMock)
        target = 'kypo.sandbox_instance_app.lib.request_handlers.CleanupAnsibleStageHandler.cancel'
        self.ansible_cancel = mocker.patch(target, new_callable=PicklableMock)

    @pytest.mark.django_db(transaction=True)
    def test_enqueue_request(self, cleanup_request):
        handler = request_handlers.CleanupRequestHandler(cleanup_request)

        assert cleanup_request.stages.all().count() == 0

        handler.enqueue_request()

        assert cleanup_request.stages.all().count() == 3

        cleanup_request: request_handlers.CleanupRequest
        assert isinstance(cleanup_request.useransiblecleanupstage, UserAnsibleCleanupStage)
        assert isinstance(cleanup_request.networkingansiblecleanupstage,
                          NetworkingAnsibleCleanupStage)
        assert isinstance(cleanup_request.stackcleanupstage, StackCleanupStage)

        job_user = handler.queue_ansible \
            .fetch_job(cleanup_request.useransiblecleanupstage.rq_job.job_id)
        job_networking = handler.queue_ansible \
            .fetch_job(cleanup_request.networkingansiblecleanupstage.rq_job.job_id)
        job_stack = handler.queue_stack \
            .fetch_job(cleanup_request.stackcleanupstage.rq_job.job_id)

        assert job_user.is_queued
        assert job_networking.is_deferred
        assert job_stack.is_deferred

        assert_jobs_dependencies([job_user, job_networking, job_stack], handler.queue_default)

        worker = get_worker('openstack', 'ansible', 'default')
        worker.work(burst=True)

        assert job_user.is_finished
        assert job_networking.is_finished
        assert job_stack.is_finished

    def test_cancel_request(self, cleanup_request_started):
        handler = request_handlers.CleanupRequestHandler(cleanup_request_started)

        handler.cancel_request()

        assert self.stack_cancel.call_count == 1
        assert self.ansible_cancel.call_count == 2

    def test_cancel_request_failed_on_completed_sandbox(self, cleanup_request_finished):
        handler = request_handlers.AllocationRequestHandler(cleanup_request_finished)

        with pytest.raises(api_exceptions.ValidationError):
            handler.cancel_request()

        self.stack_cancel.assert_not_called()
        self.ansible_cancel.assert_not_called()
