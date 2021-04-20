import yaml
import pytest
import os
from django.core.management import call_command

from kypo.topology_definition.models import TopologyDefinition
from kypo.openstack_driver import TopologyInstance, TransformationConfiguration

from kypo.sandbox_instance_app.models import StackAllocationStage, SandboxAllocationUnit, \
    AllocationRequest, HeatStack, AllocationRQJob, Sandbox, CleanupRequest, StackCleanupStage,\
    Pool, SandboxLock
from kypo.sandbox_instance_app.lib.sshconfig import KypoSSHConfig
from kypo.sandbox_ansible_app.models import NetworkingAnsibleAllocationStage, \
    UserAnsibleAllocationStage, NetworkingAnsibleCleanupStage, UserAnsibleCleanupStage, \
    DockerContainer
from django.utils import timezone

TESTING_DATA_DIR = 'assets'

TESTING_DATABASE = 'database.yaml'
TESTING_TOPOLOGY_INSTANCE = 'topology_instance.json'
TESTING_SSH_CONFIG_USER = 'ssh_config_user'
TESTING_SSH_CONFIG_MANAGEMENT = 'ssh_config_management'
TESTING_SSH_CONFIG_ANSIBLE = 'ssh_config_ansible'
TESTING_DEFINITION = 'definition.yml'
TESTING_TOPOLOGY = 'topology.yml'
TESTING_SSH_ACCESS_SOURCE = 'ssh-access-source.sh'
TESTING_TRC_CONFIG = 'trc-config.yml'
TESTING_LINKS = 'links.yml'


def data_path_join(file: str, data_dir: str = TESTING_DATA_DIR) -> str:
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), data_dir, file)


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command('loaddata', data_path_join(TESTING_DATABASE))


@pytest.fixture
def trc_config():
    return TransformationConfiguration.from_file(data_path_join(TESTING_TRC_CONFIG))


@pytest.fixture
def top_def():
    """Creates example topology definition for a sandbox."""
    with open(data_path_join(TESTING_DEFINITION)) as f:
        return TopologyDefinition.load(f)


@pytest.fixture
def links():
    """Creates example links definition"""
    with open(data_path_join(TESTING_LINKS)) as f:
        return yaml.full_load(f)


@pytest.fixture
def top_ins(top_def, trc_config, links):
    """Creates example topology instance."""
    topology_instance = TopologyInstance(top_def, trc_config)
    topology_instance.name = 'stack-name'
    topology_instance.ip = '10.10.10.10'

    for link in topology_instance.get_links():
        link.ip = links[link.name]['ip']
        link.mac = links[link.name]['mac']

    return topology_instance


@pytest.fixture
def user_ssh_config():
    """Creates example User ssh config for a sandbox."""
    return KypoSSHConfig.load(data_path_join(TESTING_SSH_CONFIG_USER))


@pytest.fixture
def management_ssh_config():
    """Creates example Management ssh config for a sandbox."""
    return KypoSSHConfig.load(data_path_join(TESTING_SSH_CONFIG_MANAGEMENT))


@pytest.fixture
def ansible_ssh_config():
    """Creates example Management ssh config for a sandbox."""
    return KypoSSHConfig.load(data_path_join(TESTING_SSH_CONFIG_ANSIBLE))


@pytest.fixture
def topology():
    """Creates example topology for a sandbox."""
    with open(data_path_join(TESTING_TOPOLOGY)) as f:
        return yaml.full_load(f)


@pytest.fixture
def pool(mocker):
    mocked_pool = mocker.MagicMock()
    mocked_pool.public_management_key = 'public-management-key'
    mocked_pool.private_management_key = 'private-management-key'
    return mocked_pool


@pytest.fixture
def sandbox(mocker):
    mocked_sandbox = mocker.MagicMock()
    mocked_sandbox.public_user_key = 'public-user-key'
    mocked_sandbox.private_user_key = 'private-user-key'
    mocked_sandbox.allocation_unit.pool.id = 'pool-id'
    return mocked_sandbox


@pytest.fixture
def ssh_access_source():
    with open(data_path_join(TESTING_SSH_ACCESS_SOURCE)) as file:
        return file.read()


def set_stage_started(stage):
    stage.start = timezone.now()
    stage.save()


def set_stage_finished(stage):
    set_stage_started(stage)
    stage.failed = False
    stage.error_message = None
    stage.finished = True
    stage.end = timezone.now()
    stage.status = 'CREATE_COMPLETE'
    stage.status_reason = 'Stack CREATE completed successfully'
    stage.save()


@pytest.fixture
def stack():
    return {
        'stack': {
            'id': 'stack-id'
        }
    }


@pytest.fixture
def pool():
    return Pool.objects.get(pk=1)


@pytest.fixture
def allocation_unit(pool):
    return SandboxAllocationUnit.objects.create(pool=pool)


@pytest.fixture
def allocation_request(allocation_unit):
    return AllocationRequest.objects.create(allocation_unit=allocation_unit)


@pytest.fixture
def allocation_stage_stack(allocation_request):
    return StackAllocationStage.objects.create(
        allocation_request=allocation_request,
        allocation_request_fk_many=allocation_request
    )


@pytest.fixture
def allocation_stage_stack_started(allocation_stage_stack, stack):
    set_stage_started(allocation_stage_stack)
    HeatStack.objects.create(
        allocation_stage=allocation_stage_stack,
        stack_id=stack['stack']['id']
    )
    AllocationRQJob.objects.create(
        job_id='stack-allocation-rq-job-id',
        allocation_stage=allocation_stage_stack,
    )
    return allocation_stage_stack


@pytest.fixture
def allocation_stage_networking(allocation_request):
    return NetworkingAnsibleAllocationStage.objects.create(
        allocation_request=allocation_request,
        allocation_request_fk_many=allocation_request,
        repo_url='stage-one-repo-url',
        rev='stage-one-repo-rev'
    )


@pytest.fixture
def allocation_stage_networking_started(allocation_stage_networking,
                                        allocation_stage_stack_started):
    set_stage_finished(allocation_stage_stack_started)
    set_stage_started(allocation_stage_networking)
    DockerContainer.objects.create(
        allocation_stage=allocation_stage_networking,
        container_id='docker-container-id'
    )
    AllocationRQJob.objects.create(
        job_id='networking-allocation-rq-job-id',
        allocation_stage=allocation_stage_networking,
    )
    return allocation_stage_networking


@pytest.fixture
def allocation_stage_user(allocation_request):
    return UserAnsibleAllocationStage.objects.create(
        allocation_request=allocation_request,
        allocation_request_fk_many=allocation_request,
        repo_url=allocation_request.allocation_unit.pool.definition.url,
        rev=allocation_request.allocation_unit.pool.rev_sha
    )


@pytest.fixture
def allocation_stage_user_started(allocation_stage_user, allocation_stage_networking_started):
    set_stage_finished(allocation_stage_networking_started)
    set_stage_started(allocation_stage_user)
    DockerContainer.objects.create(
        allocation_stage=allocation_stage_user,
        container_id='docker-container-id'
    )
    AllocationRQJob.objects.create(
        job_id='user-allocation-rq-job-id',
        allocation_stage=allocation_stage_user,
    )
    return allocation_stage_user


@pytest.fixture
def allocation_request_started(allocation_stage_user_started):
    return allocation_stage_user_started.allocation_request


@pytest.fixture
def now():
    return timezone.now()


@pytest.fixture
def sandbox(allocation_unit):
    return Sandbox.objects.create(
        id=allocation_unit.id,
        allocation_unit=allocation_unit,
        private_user_key='private-key',
        public_user_key='public-key'
    )


@pytest.fixture
def sandbox_finished(allocation_stage_user_started, sandbox):
    set_stage_finished(allocation_stage_user_started)
    return sandbox


@pytest.fixture
def sandbox_lock(sandbox_finished):
    return SandboxLock.objects.create(sandbox=sandbox_finished)


@pytest.fixture
def cleanup_request(allocation_unit):
    return CleanupRequest.objects.create(allocation_unit=allocation_unit)


@pytest.fixture
def cleanup_stage_user(cleanup_request):
    return UserAnsibleCleanupStage.objects.create(
        cleanup_request=cleanup_request,
        cleanup_request_fk_many=cleanup_request,
    )


@pytest.fixture
def cleanup_stage_user_started(cleanup_stage_user, allocation_request_started):
    set_stage_started(cleanup_stage_user)
    return cleanup_stage_user


@pytest.fixture
def cleanup_stage_networking(cleanup_request):
    return NetworkingAnsibleCleanupStage.objects.create(
        cleanup_request=cleanup_request,
        cleanup_request_fk_many=cleanup_request,
    )


@pytest.fixture
def cleanup_stage_networking_started(cleanup_stage_networking, cleanup_stage_user_started):
    set_stage_finished(cleanup_stage_user_started)
    set_stage_started(cleanup_stage_networking)
    return cleanup_stage_networking


@pytest.fixture
def cleanup_stage_stack(cleanup_request):
    return StackCleanupStage.objects.create(
        cleanup_request=cleanup_request,
        cleanup_request_fk_many=cleanup_request,
    )


@pytest.fixture
def cleanup_stage_stack_started(cleanup_stage_stack, cleanup_stage_networking_started):
    set_stage_finished(cleanup_stage_networking_started)
    set_stage_started(cleanup_stage_stack)
    return cleanup_stage_stack


@pytest.fixture
def cleanup_request_started(cleanup_stage_stack_started):
    return cleanup_stage_stack_started.cleanup_request


@pytest.fixture
def cleanup_request_finished(cleanup_stage_stack_started):
    set_stage_finished(cleanup_stage_stack_started)
    return cleanup_stage_stack_started.cleanup_request
