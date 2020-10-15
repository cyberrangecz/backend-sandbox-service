import pytest
import django_rq
import redis

from django_rq import get_worker
from django.conf import settings

from kypo.sandbox_ansible_app.models import NetworkingAnsibleAllocationStage,\
    UserAnsibleAllocationStage

from kypo.sandbox_instance_app.models import StackAllocationStage, AllocationRequest, AllocationRQJob, Sandbox, \
    SandboxAllocationUnit

from kypo.sandbox_instance_app.lib.stage_handlers import StackStageHandler, AnsibleStageHandler

from kypo.sandbox_instance_app.lib.sandbox_creator import save_sandbox_to_database

from kypo.sandbox_common_lib import exceptions

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


class TestCreateSandbox:
    openstack_queue = 'openstack'
    ansible_queue = 'ansible'
    redis_connection = redis.StrictRedis(host='localhost', port=6379, db=0)

    @pytest.fixture(autouse=True)
    def set_up(self, mocker):
        mock_client = mocker.patch("kypo.openstack_driver.ostack_client.KypoOstackClient.create_stack")
        mock_client.return_value = {'stack': {'id': 1}}

        mocker.patch("kypo.sandbox_instance_app.lib.stage_handlers.StackStageHandler.wait_for_stack_creation")
        mocker.patch("kypo.sandbox_instance_app.lib.stage_handlers.AnsibleStageHandler.run_docker_container")

        mocker.patch("kypo.sandbox_instance_app.lib.stage_handlers.StageHandler.lock_job")
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.get_definition")
        mock_repo = mocker.patch("kypo.sandbox_definition_app.lib.definitions.get_def_provider")
        mock_repo.return_value.get_rev_sha = mocker.MagicMock(return_value='sha')

        yield

    @pytest.fixture
    def allocation_unit(self):
        return SandboxAllocationUnit.objects.create(pool_id=1)

    @pytest.fixture
    def sandbox(self, allocation_unit):
        return Sandbox(id=allocation_unit.id, allocation_unit=allocation_unit, private_user_key='priv_key',
                       public_user_key='public_key')

    @pytest.fixture
    def allocation_request(self, allocation_unit):
        return AllocationRequest.objects.create(allocation_unit=allocation_unit)

    @pytest.fixture
    def stage_stack(self, allocation_request):
        stage_stack = StackAllocationStage.objects.create(
            allocation_request=allocation_request,
            allocation_request_fk_many=allocation_request
        )

        return stage_stack

    @pytest.fixture
    def stage_networking(self, allocation_request):
        stage_networking = NetworkingAnsibleAllocationStage.objects.create(
            allocation_request=allocation_request,
            allocation_request_fk_many=allocation_request,
            repo_url=settings.KYPO_CONFIG.ansible_networking_url,
            rev=settings.KYPO_CONFIG.ansible_networking_rev
        )

        return stage_networking

    @pytest.fixture
    def stage_user_ansible(self, allocation_request, allocation_unit):
        stage_user_ansible = UserAnsibleAllocationStage.objects.create(
            allocation_request=allocation_request,
            allocation_request_fk_many=allocation_request,
            repo_url=allocation_unit.pool.definition.url,
            rev=allocation_unit.pool.rev_sha
        )

        return stage_user_ansible

    @staticmethod
    def assert_stage_created_successfully(stage):
        assert stage.start is not None
        assert stage.finished
        assert stage.end is not None
        assert stage.error_message is None
        assert not stage.failed

    @staticmethod
    def run_stage(sandbox, stage, worker, stage_handler_instance):
        rq_queue = django_rq.get_queue(worker, is_async=False,
                                       default_timeout=settings.KYPO_CONFIG.sandbox_build_timeout)

        rq_job = rq_queue.enqueue(
            stage_handler_instance.allocate, stage_name=stage.__class__.__name__,
            stage=stage, sandbox=sandbox
        )

        AllocationRQJob.objects.create(allocation_stage=stage, job_id=rq_job.id)

        get_worker(worker).work(burst=True)

    def test_stack_creation(self, sandbox, stage_stack):
        self.run_stage(sandbox, stage_stack, self.openstack_queue, StackStageHandler())

        self.assert_stage_created_successfully(stage_stack)

    def test_stack_creation_failed(self, sandbox, stage_stack):
        StackStageHandler.wait_for_stack_creation.side_effect = exceptions.StackError('testException')

        with pytest.raises(exceptions.StackError):
            self.run_stage(sandbox, stage_stack, self.openstack_queue, StackStageHandler())

    def test_networking_ansible(self, sandbox, stage_networking):
        self.run_stage(sandbox, stage_networking, self.ansible_queue, AnsibleStageHandler())

        self.assert_stage_created_successfully(stage_networking)

    def test_networking_ansible_failed(self, sandbox, stage_networking):
        AnsibleStageHandler.run_docker_container.side_effect = exceptions.AnsibleError('testException')

        with pytest.raises(exceptions.AnsibleError):
            self.run_stage(sandbox, stage_networking, self.ansible_queue, AnsibleStageHandler())

    def test_networking_ansible_docker_fail(self, sandbox, stage_networking):
        AnsibleStageHandler.run_docker_container.side_effect = exceptions.DockerError('testException')

        with pytest.raises(exceptions.DockerError):
            self.run_stage(sandbox, stage_networking, self.ansible_queue, AnsibleStageHandler())

    def test_user_ansible(self, sandbox, stage_user_ansible):
        self.run_stage(sandbox, stage_user_ansible, self.ansible_queue, AnsibleStageHandler())

        self.assert_stage_created_successfully(stage_user_ansible)

    def test_user_ansible_failed(self, sandbox, stage_user_ansible):
        AnsibleStageHandler.run_docker_container.side_effect = exceptions.AnsibleError('textException')

        with pytest.raises(exceptions.AnsibleError):
            self.run_stage(sandbox, stage_user_ansible, self.ansible_queue, AnsibleStageHandler())

    def test_user_ansible_docker_fail(self, sandbox, stage_user_ansible):
        AnsibleStageHandler.run_docker_container.side_effect = exceptions.DockerError('textException')

        with pytest.raises(exceptions.DockerError):
            self.run_stage(sandbox, stage_user_ansible, self.ansible_queue, AnsibleStageHandler())

    def test_saving_sandbox(self, mocker, sandbox):
        sandbox_spy = mocker.spy(Sandbox, "save")

        queue_default = django_rq.get_queue(is_async=False, connection=self.redis_connection)
        queue_default.enqueue(save_sandbox_to_database, sandbox=sandbox)

        get_worker().work(burst=True)

        sandbox_spy.assert_called_once()
