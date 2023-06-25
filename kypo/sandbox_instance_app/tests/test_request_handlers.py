import pytest
from django_rq import get_worker, get_queue
from unittest.mock import MagicMock, call

from kypo.sandbox_common_lib import exceptions as api_exceptions
from kypo.sandbox_ansible_app.models import NetworkingAnsibleAllocationStage,\
    UserAnsibleAllocationStage, NetworkingAnsibleCleanupStage, UserAnsibleCleanupStage
from kypo.sandbox_instance_app.models import StackAllocationStage, StackCleanupStage

from kypo.sandbox_instance_app.lib import request_handlers

pytestmark = [pytest.mark.django_db]


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


class TestAllocationRequestHandlerUnit:

    @pytest.fixture(autouse=True)
    def set_up(self, mocker):
        mocker.patch(
            'kypo.sandbox_instance_app.lib.request_handlers.LOG'
        )
        mocker.patch(
            'kypo.sandbox_instance_app.lib.request_handlers.sandboxes.generate_new_sandbox_uuid', return_value='123'
        )
        fake_kypo_config = MagicMock(ansible_networking_url='fake_repo_url', ansible_networking_rev='fake_rev')
        mocker.patch('kypo.sandbox_instance_app.lib.request_handlers.settings.KYPO_CONFIG', new=fake_kypo_config)
        self.handler = request_handlers.AllocationRequestHandler()
        self.fake_gen_ssh = mocker.patch(
            'kypo.sandbox_instance_app.lib.request_handlers.utils.generate_ssh_keypair'
        )
        self.fake_gen_ssh.return_value = ('fake_private_key', 'fake_public_key')

    @staticmethod
    def assert_handlers(handlers, stages):
        stack_handler = handlers[0]
        assert stack_handler.stage == stages[0]
        network_handler = handlers[1]
        assert network_handler.stage == stages[1]
        user_handler = handlers[2]
        assert user_handler.stage == stages[2]

    def test_enqueue_stages(self, sandbox, mocker):
        fake_get_fin_stage_fn = mocker.patch(
            'kypo.sandbox_instance_app.lib.request_handlers.RequestHandler._get_finalizing_stage_function'
        )
        fake_get_fin_stage_fn.return_value = 'fake_finalization_fn'
        fake_transaction = mocker.patch(
            'kypo.sandbox_instance_app.lib.request_handlers.transaction'
        )
        fake_partial = mocker.patch(
            'kypo.sandbox_instance_app.lib.request_handlers.partial'
        )
        fake_partial.return_value = 'fake_partial'

        self.handler._enqueue_stages(sandbox, 'stage_handlers')
        fake_partial.assert_called_once_with(self.handler._enqueue_request, 'stage_handlers', 'fake_finalization_fn')
        fake_transaction.on_commit.assert_called_once_with('fake_partial')  # partial messes with assert_called_once_with

    def test_create_allocation_jobs(self, pool, mocker):
        self.handler._enqueue_stages = MagicMock()
        self.handler._create_stage_handlers = MagicMock()
        fake_sandbox = MagicMock()
        fake_sandbox_class = mocker.patch(
            'kypo.sandbox_instance_app.lib.request_handlers.Sandbox', return_value=fake_sandbox
        )

        self.handler._create_allocation_jobs(pool, 2, None)

        created_units = pool.allocation_units.all()
        assert len(created_units) == 2
        for unit in created_units:
            assert hasattr(unit, 'allocation_request')
            assert not hasattr(unit, 'sandbox')
            fake_sandbox_class.assert_has_calls([call(id='123', allocation_unit=unit, private_user_key='fake_private_key', public_user_key='fake_public_key')])
            self.handler._enqueue_stages.assert_has_calls([call(fake_sandbox, self.handler._create_stage_handlers.return_value)])

    def test_enqueue_request(self, pool, created_by):
        self.handler.queue_default.enqueue = MagicMock()
        self.handler.enqueue_request(pool, 1, created_by)
        self.handler.queue_default.enqueue.assert_called_once_with(
            self.handler._create_allocation_jobs, pool, 1, created_by
        )

    def test_create_restart_jobs(self, allocation_unit, allocation_request, mocker):
        fake_sandbox = MagicMock()
        fake_sandbox_class = mocker.patch(
            'kypo.sandbox_instance_app.lib.request_handlers.Sandbox', return_value=fake_sandbox
        )
        self.handler._restart_stage_handlers = MagicMock()
        self.handler._enqueue_stages = MagicMock()

        self.handler._create_restart_jobs(allocation_unit)

        assert self.handler.request == allocation_request
        fake_sandbox_class.assert_called_once_with(
            id='123', allocation_unit=allocation_unit, private_user_key='fake_private_key', public_user_key='fake_public_key'
        )
        self.handler._restart_stage_handlers.assert_called_once_with(fake_sandbox)
        self.handler._enqueue_stages.assert_called_once_with(fake_sandbox, self.handler._restart_stage_handlers.return_value)

    def test_restart_request(self, allocation_request):
        self.handler.queue_default.enqueue = MagicMock()
        self.handler.restart_request(allocation_request.allocation_unit)
        self.handler.queue_default.enqueue.assert_called_once_with(
            self.handler._create_restart_jobs, allocation_request.allocation_unit
        )

    def test_create_db_stage(self, allocation_request):
        self.handler.request = allocation_request
        self.handler._create_db_stage(NetworkingAnsibleAllocationStage, repo_url='fake_repo_url', rev='fake_rev')

        assert allocation_request.stages.count() == 1
        stage = NetworkingAnsibleAllocationStage.objects.get(allocation_request=allocation_request)
        assert stage.repo_url == 'fake_repo_url'
        assert stage.rev == 'fake_rev'

    def test_create_stage_handlers(self, sandbox, allocation_request, mocker):
        self.handler.request = allocation_request

        fake_stack_stage = MagicMock()
        fake_network_stage = MagicMock()
        fake_user_stage = MagicMock()
        self.handler._create_db_stage = MagicMock()
        self.handler._create_db_stage.side_effect = [fake_stack_stage, fake_network_stage, fake_user_stage]

        handlers = self.handler._create_stage_handlers(sandbox)

        self.handler._create_db_stage.assert_has_calls([
            call(StackAllocationStage),
            call(NetworkingAnsibleAllocationStage, repo_url='fake_repo_url', rev='fake_rev'),
            call(UserAnsibleAllocationStage, repo_url=allocation_request.allocation_unit.pool.definition.url,
                 rev=allocation_request.allocation_unit.pool.rev_sha)
        ])
        self.assert_handlers(handlers, [fake_stack_stage, fake_network_stage, fake_user_stage])

    def test_restart_stage_handlers_not_finished(self, allocation_request_started, sandbox):
        self.handler.request = allocation_request_started
        with pytest.raises(api_exceptions.ValidationError) as cm:
            self.handler._restart_stage_handlers(sandbox)

        assert str(cm.value) == 'Allocation of the sandbox is still in progress.'

    def test_restart_stage_handlers_finished_successfully(self, sandbox_finished):
        self.handler.request = sandbox_finished.allocation_unit.allocation_request
        with pytest.raises(api_exceptions.ValidationError) as cm:
            self.handler._restart_stage_handlers(sandbox_finished)

        assert str(cm.value) == 'All stages finished without failing. Only failed stages can be restarted.'

    def test_restart_stage_handlers(self, sandbox_failed_stack_stage):
        self.handler.request = sandbox_failed_stack_stage.allocation_unit.allocation_request

        fake_stack_stage = MagicMock()
        fake_network_stage = MagicMock()
        fake_user_stage = MagicMock()
        self.handler._create_db_stage = MagicMock()
        self.handler._create_db_stage.side_effect = [fake_stack_stage, fake_network_stage, fake_user_stage]

        handlers = self.handler._restart_stage_handlers(sandbox_failed_stack_stage)

        self.handler._create_db_stage.assert_has_calls([
            call(StackAllocationStage),
            call(NetworkingAnsibleAllocationStage, repo_url='fake_repo_url', rev='fake_rev'),
            call(UserAnsibleAllocationStage, repo_url=sandbox_failed_stack_stage.allocation_unit.pool.definition.url,
                 rev=sandbox_failed_stack_stage.allocation_unit.pool.rev_sha)
        ])
        self.assert_handlers(handlers, [fake_stack_stage, fake_network_stage, fake_user_stage])

    def test_restart_stage_handler_user_stage_failed(self, sandbox_failed_user_stage):
        self.handler.request = sandbox_failed_user_stage.allocation_unit.allocation_request

        fake_user_stage = MagicMock()
        self.handler._create_db_stage = MagicMock(return_value=fake_user_stage)

        handlers = self.handler._restart_stage_handlers(sandbox_failed_user_stage)

        self.handler._create_db_stage.assert_called_once_with(
            UserAnsibleAllocationStage, repo_url=sandbox_failed_user_stage.allocation_unit.pool.definition.url,
            rev=sandbox_failed_user_stage.allocation_unit.pool.rev_sha
        )
        user_stage = handlers[0]
        assert user_stage.stage == fake_user_stage

    def test_get_stage_handlers(self, allocation_request_started):
        self.handler.request = allocation_request_started

        handlers = self.handler._get_stage_handlers()

        self.assert_handlers(handlers, [
            allocation_request_started.useransibleallocationstage,
            allocation_request_started.networkingansibleallocationstage,
            allocation_request_started.stackallocationstage
        ])


class TestCleanupRequestHandlerUnit:

    @pytest.fixture(autouse=True)
    def set_up(self, mocker):
        mocker.patch(
            'kypo.sandbox_instance_app.lib.request_handlers.LOG'
        )
        self.handler = request_handlers.CleanupRequestHandler()

    @staticmethod
    def assert_handlers(handlers, stages):
        assert len(handlers) == len(stages)
        for handler, stage in zip(handlers, stages):
            assert handler.stage == stage

    def test_enqueue_stages(self, mocker, allocation_request):
        self.handler.request = allocation_request
        self.handler._create_stage_handlers = MagicMock(return_value='fake_handlers')
        self.handler._get_finalizing_stage_function = MagicMock(return_value='fake_finalizing_function')
        fake_partial = mocker.patch('kypo.sandbox_instance_app.lib.request_handlers.partial')
        fake_transaction = mocker.patch('kypo.sandbox_instance_app.lib.request_handlers.transaction')

        self.handler._enqueue_stages()

        self.handler._create_stage_handlers.assert_called_once()
        self.handler._get_finalizing_stage_function.assert_called_once_with(self.handler._delete_allocation_unit,
                                                                            allocation_request.allocation_unit, allocation_request)
        fake_partial.assert_called_once_with(self.handler._enqueue_request, 'fake_handlers', 'fake_finalizing_function')
        fake_transaction.on_commit.assert_called_once_with(fake_partial.return_value)

    def test_create_cleanup_jobs(self, cleanup_request):
        self.handler.request = cleanup_request
        self.handler._enqueue_stages = MagicMock()

        self.handler._create_cleanup_jobs(cleanup_request.allocation_unit)

        self.handler._enqueue_stages.assert_called_once()
        assert self.handler.request == cleanup_request

    def test_create_cleanup_jobs_no_request(self, allocation_unit):
        self.handler._enqueue_stages = MagicMock()

        self.handler._create_cleanup_jobs(allocation_unit)

        self.handler._enqueue_stages.assert_called_once()
        assert self.handler.request == allocation_unit.cleanup_request

    def test_create_db_stage(self, cleanup_request):
        self.handler.request = cleanup_request
        self.handler._create_db_stage(NetworkingAnsibleCleanupStage)

        assert self.handler.request.networkingansiblecleanupstage is not None

    def test_create_stage_handlers(self, cleanup_request_finished):
        self.handler.request = cleanup_request_finished
        fake_user_stage = MagicMock()
        fake_network_stage = MagicMock()
        fake_stack_stage = MagicMock()
        self.handler._create_db_stage = MagicMock(side_effect=[fake_user_stage, fake_network_stage, fake_stack_stage])

        handlers = self.handler._create_stage_handlers()

        self.handler._create_db_stage.assert_has_calls([
            call(UserAnsibleCleanupStage), call(NetworkingAnsibleCleanupStage), call(StackCleanupStage)
        ])
        self.assert_handlers(handlers, [fake_user_stage, fake_network_stage, fake_stack_stage])

    def test_create_stage_handlers_no_user_stage(self, cleanup_stage_networking_started):
        self.handler.request = cleanup_stage_networking_started.cleanup_request
        StackCleanupStage.delete = MagicMock()
        UserAnsibleCleanupStage.delete = MagicMock()
        self.handler._create_db_stage = MagicMock(side_effect=[MagicMock(), MagicMock(), MagicMock()])

        self.handler._create_stage_handlers()

        self.handler._create_db_stage.assert_has_calls([
            call(UserAnsibleCleanupStage), call(NetworkingAnsibleCleanupStage), call(StackCleanupStage)
        ])
        UserAnsibleCleanupStage.delete.assert_called_once()
        StackCleanupStage.delete.assert_not_called()

    def test_get_stage_handlers(self, cleanup_request_finished):
        self.handler.request = cleanup_request_finished

        handlers = self.handler._get_stage_handlers()

        self.assert_handlers(handlers, [
            cleanup_request_finished.stackcleanupstage,
            cleanup_request_finished.networkingansiblecleanupstage,
            cleanup_request_finished.useransiblecleanupstage
        ])


@pytest.mark.integration
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


@pytest.mark.integration
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
