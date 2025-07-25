import io

import yaml
import pytest
import os
from django.core.management import call_command
from django.contrib.auth.models import User

from crczp.topology_definition.models import TopologyDefinition
from crczp.cloud_commons import TopologyInstance, TransformationConfiguration, Image

from crczp.sandbox_definition_app.lib.definitions import load_docker_containers
from crczp.sandbox_definition_app.models import Definition
from crczp.sandbox_instance_app.lib import pools
from crczp.sandbox_instance_app.models import StackAllocationStage, SandboxAllocationUnit, \
    AllocationRequest, TerraformStack, AllocationRQJob, Sandbox, CleanupRequest, StackCleanupStage, \
    Pool, SandboxLock
from crczp.sandbox_instance_app.lib.sshconfig import CrczpSSHConfig
from crczp.sandbox_ansible_app.models import NetworkingAnsibleAllocationStage, \
    UserAnsibleAllocationStage, NetworkingAnsibleCleanupStage, UserAnsibleCleanupStage, \
    Container
from crczp.sandbox_ansible_app.lib.container import DockerContainer
from django.utils import timezone
from unittest import mock
from crczp.sandbox_instance_app.lib.topology import Topology

from ruamel.yaml import YAML

TESTING_DATA_DIR = 'assets'

TESTING_DATABASE = 'database.yaml'
TESTING_TOPOLOGY_INSTANCE = 'topology_instance.json'
TESTING_SSH_CONFIG_USER = 'ssh_config_user'
TESTING_SSH_CONFIG_MANAGEMENT = 'ssh_config_management'
TESTING_SSH_CONFIG_ANSIBLE = 'ssh_config_ansible'
TESTING_DEFINITION = 'definition.yml'
TESTING_DEFINITION_HIDDEN = 'definition_hidden.yml'
TESTING_TOPOLOGY = 'topology.yml'
TESTING_TOPOLOGY_HIDDEN = 'topology_hidden.yml'
TESTING_TRC_CONFIG = 'trc-config.yml'
TESTING_LINKS = 'links.yml'
TESTING_LINKS_HIDDEN = 'links_hidden.yml'
TESTING_CONTAINERS = 'containers.yml'
TESTING_TOPOLOGY_CONTAINERS = 'topology_containers.yml'

TESTING_TOPOLOGY_CUSTOM_FLAVORS = 'definition_flavor_mapping.yml'



def mock_topology_cache(top_ins):
    with mock.patch('django.core.cache.cache.get') as mock_cache_get, \
            mock.patch('django.core.cache.cache.set') as mock_cache_set:
        # Simulate cache miss
        mock_cache_get.return_value = None
        topo = Topology(top_ins)
    return topo


@pytest.fixture
def get_terraform_client(mocker, image, flavor_dict):
    mock_client = mocker.MagicMock()
    mock_client.get_flavors_dict.return_value = flavor_dict
    mock_client.list_images.return_value = [image]

    mocker.patch('crczp.sandbox_common_lib.utils.get_terraform_client', return_value=mock_client)
    return mock_client


def data_path_join(file: str, data_dir: str = TESTING_DATA_DIR) -> str:
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), data_dir, file)


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command('loaddata', data_path_join(TESTING_DATABASE))


@pytest.fixture(autouse=True)
def docker_sys_mock(mocker):
    mocker.patch.object(DockerContainer, 'CLIENT')


@pytest.fixture
def trc_config():
    return TransformationConfiguration.from_file(data_path_join(TESTING_TRC_CONFIG))


@pytest.fixture
def top_def():
    """Creates example topology definition for a sandbox."""
    with open(data_path_join(TESTING_DEFINITION)) as f:
        return TopologyDefinition.load(f)


@pytest.fixture
def top_def_hidden():
    """Creates example topology definition for a sandbox."""
    with open(data_path_join(TESTING_DEFINITION_HIDDEN)) as f:
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
def top_ins_hidden(top_def_hidden, trc_config):
    """Creates example topology instance."""
    topology_instance = TopologyInstance(top_def_hidden, trc_config)
    topology_instance.name = 'stack-name'
    topology_instance.ip = '10.10.10.10'

    return topology_instance


@pytest.fixture
def flavor_dict():
    return {"standard.small": "", "standard.tiny1x4": "", "standard.medium": "",
            "standard.large": "", "standard.medium4x8": "", "standard.medium4x16": "",
            "standard.large8x16": "", "standard.large8x32": "", "standard.jumbo16x32": "",
            "standard.jumbo16x64": ""
            }


@pytest.fixture
def top_ins_with_containers(top_def, trc_config, links, containers):
    """Creates example topology instance."""
    loaded_containers = load_docker_containers(io.StringIO(containers))
    loaded_containers.hide_all = False
    topology_instance = TopologyInstance(top_def, trc_config, containers=loaded_containers)
    topology_instance.name = 'stack-name'
    topology_instance.ip = '10.10.10.10'

    for link in topology_instance.get_links():
        link.ip = links[link.name]['ip']
        link.mac = links[link.name]['mac']

    return topology_instance


@pytest.fixture
def top_ins_with_containers_with_server(top_def, trc_config, links, containers):
    """Creates example topology instance."""
    containers = containers.replace("home", "server", 1)
    loaded_containers = load_docker_containers(io.StringIO(containers))
    loaded_containers.hide_all = False
    topology_instance = TopologyInstance(top_def, trc_config, containers=loaded_containers)
    topology_instance.name = 'stack-name'
    topology_instance.ip = '10.10.10.10'

    return topology_instance


@pytest.fixture
def topology_containers():
    """Creates container topology. Not to be mistaken with topology instance."""
    with open(data_path_join(TESTING_TOPOLOGY_CONTAINERS)) as f:
        return yaml.full_load(f)


@pytest.fixture
def containers() -> str:
    """Imitates containers.yml file from sandbox-definition git repository."""
    # the ruamel.yaml library keeps the order of the keys in the yaml file
    ruamel_yaml = YAML()
    stream = io.StringIO()

    with open(data_path_join(TESTING_CONTAINERS)) as f:
        ruamel_yaml.dump(ruamel_yaml.load(f), stream)
        return stream.getvalue()


@pytest.fixture
def user_ssh_config():
    """Creates example User ssh config for a sandbox."""
    return CrczpSSHConfig.load(data_path_join(TESTING_SSH_CONFIG_USER))


@pytest.fixture
def management_ssh_config():
    """Creates example Management ssh config for a sandbox."""
    return CrczpSSHConfig.load(data_path_join(TESTING_SSH_CONFIG_MANAGEMENT))


@pytest.fixture
def ansible_ssh_config():
    """Creates example Management ssh config for a sandbox."""
    return CrczpSSHConfig.load(data_path_join(TESTING_SSH_CONFIG_ANSIBLE))


@pytest.fixture
def topology():
    """Creates example topology for a sandbox."""
    with open(data_path_join(TESTING_TOPOLOGY)) as f:
        return yaml.full_load(f)


@pytest.fixture
def topology_hidden():
    """Creates example topology for a sandbox."""
    with open(data_path_join(TESTING_TOPOLOGY_HIDDEN)) as f:
        return yaml.full_load(f)


@pytest.fixture
def definition_custom_flavors():
    """Creates example definition with custom flavors for a sandbox."""
    # the ruamel.yaml library keeps the order of the keys in the yaml file
    ruamel_yaml = YAML()
    stream = io.StringIO()

    with open(data_path_join(TESTING_TOPOLOGY_CUSTOM_FLAVORS)) as f:
        ruamel_yaml.dump(yaml.unsafe_load(f), stream)
        return stream.getvalue()


@pytest.fixture
def image():
    return Image(os_distro=None, os_type="debian",
                 disk_format=None, container_format=None,
                 visibility=None, size=None, status=None,
                 min_ram=None, min_disk=None,
                 created_at=None, updated_at=None, tags=[],
                 default_user=None, name="debian-12-x86_64",
                 owner_specified={"": ""})


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


def set_stage_failed(stage):
    set_stage_started(stage)
    stage.failed = True
    stage.error_message = 'Stack CREATE failed'
    stage.finished = True
    stage.end = timezone.now()
    stage.status = 'CREATE_FAILED'
    stage.status_reason = 'Stack CREATE failed'
    stage.save()


@pytest.fixture
def stack():
    return {
        'stack': {
            'id': 'stack-id'
        }
    }


@pytest.fixture
def process(mocker):
    proc = mocker.MagicMock()
    proc.pid = 1
    return proc


@pytest.fixture
def created_by():
    return User.objects.create(username='test-user', first_name='test-first-name',
                               last_name='test-last-name', email='test@email.com')


@pytest.fixture
def definition(created_by):
    return Definition.objects.create(name='test-def-name', url='test-def-url', rev='test-def-rev',
                                     created_by=created_by)


@pytest.fixture
def pool(definition, created_by):
    return Pool.objects.create(definition=definition, max_size=3,
                               private_management_key='-----RSA PRIVATE KEY-----',
                               public_management_key='ssh-rsa', uuid='0fb3160d',
                               created_by=created_by)


@pytest.fixture
def allocation_unit(pool, created_by):
    return SandboxAllocationUnit.objects.create(pool=pool, created_by=created_by)


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
    TerraformStack.objects.create(
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
    Container.objects.create(
        allocation_stage=allocation_stage_networking,
        container_name='docker-container-id'
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
    Container.objects.create(
        allocation_stage=allocation_stage_user,
        container_name='docker-container-id'
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
        public_user_key='public-key',
        ready=True
    )


@pytest.fixture
def sandbox_finished(allocation_stage_user_started, sandbox):
    set_stage_finished(allocation_stage_user_started)
    return sandbox


@pytest.fixture
def sandbox_failed_stack_stage(allocation_stage_stack, allocation_stage_networking, allocation_stage_user, sandbox):
    set_stage_failed(allocation_stage_stack)
    set_stage_failed(allocation_stage_networking)
    set_stage_failed(allocation_stage_user)
    return sandbox


@pytest.fixture
def sandbox_failed_user_stage(allocation_stage_stack, allocation_stage_networking, allocation_stage_user, sandbox):
    set_stage_finished(allocation_stage_stack)
    set_stage_finished(allocation_stage_networking)
    set_stage_failed(allocation_stage_user)
    return sandbox


@pytest.fixture
def sandbox_lock(sandbox_finished):
    return SandboxLock.objects.create(sandbox=sandbox_finished)


@pytest.fixture
def pool_lock(pool, training_access_token):
    return pools.lock_pool(pool=pool, training_access_token=training_access_token)


@pytest.fixture
def training_access_token():
    return "token-1234"


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
