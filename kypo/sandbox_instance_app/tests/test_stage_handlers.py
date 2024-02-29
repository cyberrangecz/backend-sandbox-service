import pytest
import docker
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from docker.errors import DockerException, NotFound as DockerContainerNotFound

from kypo.cloud_commons import exceptions as driver_exceptions

from kypo.sandbox_instance_app.models import Stage
from kypo.sandbox_ansible_app.models import NetworkingAnsibleAllocationStage
from kypo.sandbox_ansible_app.lib.container import DockerContainer
from kypo.sandbox_common_lib import exceptions as api_exceptions

from kypo.sandbox_instance_app.lib import stage_handlers

pytestmark = pytest.mark.django_db


def assert_db_stage(stage: Stage, start_time: timezone.datetime, failed: bool = False):
    assert start_time < stage.start
    assert stage.start < stage.end
    assert stage.end < timezone.now()
    assert stage.failed == failed
    assert isinstance(stage.error_message, str)\
        if failed else stage.error_message is None


class TestAllocationStackStageHandler:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker, process):
        mocker.patch('kypo.sandbox_instance_app.lib.stage_handlers.LOG')
        mocker.patch('kypo.sandbox_instance_app.lib.stage_handlers.definitions.get_definition')
        mocker.patch('kypo.sandbox_instance_app.lib.stage_handlers.utils.get_terraform_client')
        stage_handlers.AllocationStackStageHandler._client = mocker.Mock()
        stage_handlers.AllocationStackStageHandler._client\
            .get_process_output.return_value = ['output']
        stage_handlers.AllocationStackStageHandler._client\
            .create_stack.return_value = process
        stage_handlers.AllocationStackStageHandler._wait_for_process = mocker.Mock()

    def test_execute_success(self, now, allocation_stage_stack, process):
        handler = stage_handlers.AllocationStackStageHandler(allocation_stage_stack)

        handler.execute()

        assert allocation_stage_stack.terraformstack.stack_id == process.pid
        assert_db_stage(allocation_stage_stack, now, failed=False)

    def test_execute_failed_creation_request(self, now, allocation_stage_stack):
        handler = stage_handlers.AllocationStackStageHandler(allocation_stage_stack)
        stage_handlers.AllocationStackStageHandler._client \
            .create_stack.side_effect = driver_exceptions.StackCreationFailed('error-message')

        with pytest.raises(driver_exceptions.StackCreationFailed):
            handler.execute()

        with pytest.raises(ObjectDoesNotExist):
            assert allocation_stage_stack.terraformstack
        assert_db_stage(allocation_stage_stack, now, failed=True)

    @pytest.mark.xfail(reason='cancellation should set error_message to \'canceled\'')
    def test_cancel_success(self, now, allocation_stage_stack_started):
        handler = stage_handlers.AllocationStackStageHandler(allocation_stage_stack_started)

        handler.cancel()

        assert_db_stage(allocation_stage_stack_started, now, failed=True)

    @pytest.mark.xfail(reason='cancellation should set error_message to \'canceled\'')
    def test_cancel_failed_deletion(self, now, allocation_stage_stack_started):
        handler = stage_handlers.AllocationStackStageHandler(allocation_stage_stack_started)
        stage_handlers.AllocationStackStageHandler._client \
            .delete_stack.side_effect = driver_exceptions.StackException('error-message')

        handler.cancel()

        assert_db_stage(allocation_stage_stack_started, now, failed=True)


class TestCleanupStackStageHandler:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker, process):
        mocker.patch('kypo.sandbox_instance_app.lib.stage_handlers.LOG')
        mocker.patch('kypo.sandbox_instance_app.lib.stage_handlers.utils.get_terraform_client')
        stage_handlers.CleanupStackStageHandler._client = mocker.Mock()
        stage_handlers.CleanupStackStageHandler._client\
            .get_process_output.return_value = ['output']
        stage_handlers.CleanupStackStageHandler._wait_for_process = mocker.Mock()

    def test_execute_success(self, now, cleanup_stage_stack):
        handler = stage_handlers.CleanupStackStageHandler(cleanup_stage_stack)

        handler.execute()

        assert_db_stage(cleanup_stage_stack, now, failed=False)

    @pytest.mark.xfail(reason='cancellation should set error_message to \'canceled\'')
    def test_cancel_success(self, now, cleanup_stage_stack_started):
        handler = stage_handlers.CleanupStackStageHandler(cleanup_stage_stack_started)

        handler.cancel()

        assert_db_stage(cleanup_stage_stack_started, now, failed=True)


class TestAllocationAnsibleStageHandler:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker, allocation_stage_networking):
        mocker.patch('kypo.sandbox_instance_app.lib.stage_handlers.LOG')
        mocker.patch('kypo.sandbox_instance_app.lib.stage_handlers.os.path.join')
        mocker.patch('kypo.sandbox_instance_app.lib.sandboxes.get_topology_instance')
        mocker.patch('kypo.sandbox_ansible_app.lib.container.DockerContainer._run_container')
        mocker.patch('kypo.sandbox_ansible_app.lib.container.DockerContainer.delete')

        allocation_runner_class = mocker \
            .patch('kypo.sandbox_instance_app.lib.stage_handlers.AllocationAnsibleRunner')

        runner_class = mocker \
            .patch('kypo.sandbox_instance_app.lib.stage_handlers.AnsibleRunner')

        container = mocker.Mock()
        type(container).id = 'docker-container-id'
        container.logs.return_value = [b'output\n']
        container.wait.return_value = {
            'StatusCode': 0
        }
        container_class = DockerContainer('url', 'rev', allocation_stage_networking, 'ssh_dir',
                                          'inventory_path', 'containers_path', 'credentials_path')
        container_class.container = container
        container_class.CLIENT = mocker.MagicMock()

        runner = mocker.Mock()
        runner.run_ansible_playbook.return_value = container_class
        allocation_runner_class.return_value = runner

        self.runner = runner
        self.container_class = container_class

    def test_execute_success(self, now, allocation_stage_networking, sandbox):
        handler = stage_handlers.AllocationAnsibleStageHandler(allocation_stage_networking, sandbox)

        handler.execute()

        assert allocation_stage_networking.container.container_name ==\
               self.runner.run_ansible_playbook.return_value.container.id
        assert allocation_stage_networking.outputs.count() == 1
        assert allocation_stage_networking.outputs.first().content == 'output'
        assert_db_stage(allocation_stage_networking, now, failed=False)

    def test_execute_failed_to_create_docker(self, now, allocation_stage_networking, sandbox):
        handler = stage_handlers.AllocationAnsibleStageHandler(allocation_stage_networking, sandbox)
        self.runner.run_ansible_playbook.side_effect = DockerException('error-message')

        with pytest.raises(DockerException):
            handler.execute()

        with pytest.raises(ObjectDoesNotExist):
            assert allocation_stage_networking.container
        assert allocation_stage_networking.outputs.count() == 0
        assert_db_stage(allocation_stage_networking, now, failed=True)

    def test_execute_failed_to_obtain_docker_logs(self, now, allocation_stage_networking, sandbox,
                                                  mocker):
        handler = stage_handlers.AllocationAnsibleStageHandler(allocation_stage_networking, sandbox)
        self.runner.run_ansible_playbook.return_value.get_container_outputs = mocker.MagicMock()
        self.runner.run_ansible_playbook.return_value.get_container_outputs.side_effect =\
            DockerException('error-message')

        with pytest.raises(DockerException):
            handler.execute()

        assert allocation_stage_networking.container.container_name ==\
               self.runner.run_ansible_playbook.return_value.container.id
        assert allocation_stage_networking.outputs.count() == 0
        assert_db_stage(allocation_stage_networking, now, failed=True)

    def test_execute_failed_ansible(self, now, allocation_stage_networking, sandbox):
        handler = stage_handlers.AllocationAnsibleStageHandler(allocation_stage_networking, sandbox)
        self.runner.run_ansible_playbook.return_value.container.wait.return_value = {
            'StatusCode': -1
        }

        with pytest.raises(api_exceptions.AnsibleError):
            handler.execute()

        assert allocation_stage_networking.container.container_name ==\
               self.runner.run_ansible_playbook.return_value.container.id
        assert allocation_stage_networking.outputs.count() == 1
        assert allocation_stage_networking.outputs.first().content == 'output'
        assert_db_stage(allocation_stage_networking, now, failed=True)

    @pytest.mark.xfail(reason='cancellation should set error_message to \'canceled\'')
    def test_cancel_success(self, now, allocation_stage_networking_started, sandbox):
        handler = stage_handlers\
            .AllocationAnsibleStageHandler(allocation_stage_networking_started, sandbox)

        with transaction.atomic():
            handler.cancel()

        allocation_stage_networking_started = NetworkingAnsibleAllocationStage.objects\
            .get(pk=allocation_stage_networking_started.id)
        with pytest.raises(ObjectDoesNotExist):
            assert allocation_stage_networking_started.container
        assert_db_stage(allocation_stage_networking_started, now, failed=True)

    @pytest.mark.xfail(reason='cancellation should set error_message to \'canceled\'')
    def test_cancel_nonexistent_docker_container(self, now, allocation_stage_networking_started,
                                                 sandbox):
        handler = stage_handlers \
            .AllocationAnsibleStageHandler(allocation_stage_networking_started, sandbox)
        self.runner.delete_container.side_effect = DockerContainerNotFound('error-message')

        handler.cancel()

        assert_db_stage(allocation_stage_networking_started, now, failed=True)


class TestCleanupAnsibleStageHandler:
    @pytest.fixture(autouse=True)
    def set_up(self, mocker, allocation_stage_networking):
        mocker.patch('kypo.sandbox_instance_app.lib.stage_handlers.LOG')
        mocker.patch('kypo.sandbox_ansible_app.lib.container.DockerContainer._run_container')
        mocker.patch('kypo.sandbox_ansible_app.lib.container.DockerContainer.delete')

        runner_class = mocker \
            .patch('kypo.sandbox_instance_app.lib.stage_handlers.CleanupAnsibleRunner')

        container = mocker.Mock()
        type(container).id = 'docker-container-id'
        container.logs.return_value = [b'output\n']
        container.wait.return_value = {
            'StatusCode': 0
        }
        container_class = DockerContainer('url', 'rev', allocation_stage_networking, 'ssh_dir',
                                          'inventory_path', 'containers_path', 'credentials_path')
        container_class.container = container
        container_class.CLIENT = mocker.MagicMock()

        runner = mocker.Mock()
        runner.run_ansible_playbook.return_value = container_class
        runner_class.return_value = runner

        self.runner = runner
        self.container_class = container_class

    def test_execute_success(self, now, cleanup_stage_networking, allocation_stage_networking):
        cleanup_stage_networking.cleanup_request.allocation_unit.allocation_request\
            .networkingansibleallocationstage = allocation_stage_networking

        handler = stage_handlers.CleanupAnsibleStageHandler(cleanup_stage_networking)

        handler.execute()

        assert_db_stage(cleanup_stage_networking, now, failed=False)

    @pytest.mark.xfail(reason='cancellation should set error_message to \'canceled\'')
    def test_cancel_success(self, now, cleanup_stage_networking_started):
        handler = stage_handlers.CleanupAnsibleStageHandler(cleanup_stage_networking_started)

        handler.cancel()

        assert_db_stage(cleanup_stage_networking_started, now, failed=True)
