import os
import string
import tempfile
from zipfile import ZipFile

import pytest
import structlog
from django.urls import reverse
from redis import Redis
from rest_framework import status
from rq import SimpleWorker
from django.conf import settings

from kypo.sandbox_ansible_app.lib.ansible_service import AnsibleDockerRunner
from kypo.sandbox_ansible_app.models import AnsibleOutput, DockerContainer
from kypo.sandbox_common_lib import utils
from kypo.sandbox_instance_app.lib.sandbox_creator import OPENSTACK_QUEUE, ANSIBLE_QUEUE
from kypo.sandbox_instance_app.models import Sandbox

LOG = structlog.get_logger()


def get_asset_repo_path(name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        f'assets/{name}')


NETWORKING_REPO_NAME = 'kypo2-ansible-stage-one.git.zip'
ansible_networking_rev = 'integration-test'

DEFINITION_REPO_NAME = 'small-sandbox.git.zip'
DEFINITION_REV = 'integration-test'

# Heat stack and template values
JUMP_STACK_NAME = 'integration_test_jump'
TEMPLATE_DICT = dict(
    PUBLIC_NETWORK='public-muni-147-251-124-GROUP',
    JUMP_IMAGE=settings.KYPO_CONFIG.trc.extra_nodes_image,
    JUMP_FLAVOR=settings.KYPO_CONFIG.trc.extra_nodes_flavor,
)

# URL names
DEFINITION_LIST = 'definition-list'
DEFINITION_DETAIL = 'definition-detail'
POOL_LIST = 'pool-list'
POOL_DETAIL = 'pool-detail'
ALLOCATION_UNIT_LIST = 'sandbox-allocation-unit-list'
ALLOCATION_UNIT_DETAIL = 'sandbox-allocation-unit-detail'
SANDBOX_LIST = 'pool-sandbox-list'
SANDBOX_GET_AND_LOCK = 'pool-sandbox-get-and-lock'
SANDBOX_LOCK_DETAIL = 'sandbox-lock-detail'
CLEANUP_REQUEST_LIST = 'sandbox-cleanup-request-list'


@pytest.mark.integration
class TestIntegration:
    pytestmark = pytest.mark.django_db(transaction=True)
    RQ_QUEUES = ('default', OPENSTACK_QUEUE, ANSIBLE_QUEUE)
    DEFINITION_URL = None

    @pytest.fixture(autouse=True)
    def kypo_ostack_client(self):
        """Set config values. Config.yml overrides those values if set.
        Also extract the zip repositories to tmp directory.
        """
        config = settings.KYPO_CONFIG
        if not config.os_auth_url:
            config.os_auth_url = os.environ.get('OS_AUTH_URL')
        if not config.os_application_credential_id:
            config.os_application_credential_id = os.environ.get('OS_APPLICATION_CREDENTIAL_ID')
        if not config.os_application_credential_secret:
            config.os_application_credential_secret = os.environ.get('OS_APPLICATION_CREDENTIAL_SECRET')

        if not config.ansible_networking_url:
            with tempfile.TemporaryDirectory() as tmpdir:
                for archive in (DEFINITION_REPO_NAME, NETWORKING_REPO_NAME):
                    with ZipFile(get_asset_repo_path(archive)) as f:
                        f.extractall(tmpdir)

                name = NETWORKING_REPO_NAME.replace('.zip', "")
                config.ansible_networking_url = 'file://' + os.path.join(tmpdir,
                                                                         name)
                config.ansible_networking_rev = ansible_networking_rev
                name = DEFINITION_REPO_NAME.replace('.zip', "")
                self.DEFINITION_URL = 'file://' + os.path.join(tmpdir, name)
                yield

    def test_build_sandbox_full(self, client, jump_template):
        def_id = self.create_definition(client, self.DEFINITION_URL, DEFINITION_REV)
        pool_id = self.create_pool(client, def_id)
        try:
            try:
                outs = self.create_jump_host(jump_template)
                self.set_jump_host_config(outs['jump_ip'], outs['test_key'])

                unit_id, alloc_req_id = self.create_alloc_unit(client, pool_id)
                sb_id, lock_id = self.get_and_lock(client, pool_id)
                self.unlock_sandbox(client, sb_id, lock_id)

                self.create_cleanup_req(client, unit_id)
            finally:
                self.delete_jump_host()
        finally:
            self.delete_pool(client, pool_id)

        self.delete_definition(client, def_id)

    @classmethod
    def run_worker(cls):
        worker = SimpleWorker(queues=cls.RQ_QUEUES, connection=Redis())
        worker.work(burst=True)

    @staticmethod
    def create_definition(client, url, rev):
        LOG.info("Creating definition")
        data = {'url': url, 'rev': rev}
        response = client.post(reverse(DEFINITION_LIST), data, 'application/json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['url'] == url
        assert response.data['rev'] == rev
        return response.data['id']

    @staticmethod
    def create_pool(client, def_id):
        LOG.info("Creating Pool")
        max_size = 10
        data = {'definition': def_id, 'max_size': max_size}
        response = client.post(reverse(POOL_LIST), data, 'application/json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['definition'] == def_id
        assert response.data['size'] == 0
        assert response.data['max_size'] == max_size
        return response.data['id']

    @classmethod
    def create_alloc_unit(cls, client, pool_id):
        LOG.info("Creating Allocation Unit")
        base_url = reverse(ALLOCATION_UNIT_LIST, kwargs={'pool_id': pool_id})
        response = client.post(base_url + '?count=1')

        if response.status_code != status.HTTP_201_CREATED:
            LOG.info('Ansible output',
                     output=[str(x) for x in AnsibleOutput.objects.all()],
                     logs=[AnsibleDockerRunner().get_container(x.container_id).logs()
                           for x in DockerContainer.objects.all()]
                     )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data[0]['pool'] == pool_id

        cls.run_worker()
        assert len(Sandbox.objects.all()) == 1

        unit_id = response.data[0]['id']
        alloc_req_id = response.data[0]['allocation_request']
        return unit_id, alloc_req_id

    @classmethod
    def create_cleanup_req(cls, client, unit_id):
        LOG.info("Creating Cleanup Unit")
        response = client.post(reverse(CLEANUP_REQUEST_LIST,
                                       kwargs={'unit_id': unit_id}))

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['allocation_unit'] == unit_id

        cls.run_worker()

    @staticmethod
    def get_and_lock(client, pool_id):
        LOG.info("Get and lock sandbox")
        response = client.get(reverse(SANDBOX_GET_AND_LOCK,
                                      kwargs={'pool_id': pool_id}))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['lock'] is not None
        sb_id = response.data['id']
        lock_id = response.data['lock']
        return sb_id, lock_id

    @staticmethod
    def unlock_sandbox(client, sb_id, lock_id):
        LOG.info("Unlocking sandbox")
        response = client.delete(reverse(SANDBOX_LOCK_DETAIL,
                                         kwargs={'sandbox_id': sb_id,
                                                 'lock_id': lock_id}))
        assert response.status_code == status.HTTP_204_NO_CONTENT

    @staticmethod
    def delete_definition(client, def_id):
        LOG.info("Deleting definition")
        response = client.delete(reverse(DEFINITION_DETAIL,
                                         kwargs={'definition_id': def_id}))
        assert response.status_code == status.HTTP_204_NO_CONTENT

    @staticmethod
    def delete_pool(client, pool_id):
        LOG.info("Deleting Pool")
        response = client.delete(reverse(POOL_DETAIL,
                                         kwargs={'pool_id': pool_id}))
        assert response.status_code == status.HTTP_204_NO_CONTENT

    @staticmethod
    def create_jump_host(jump_template):
        LOG.info(f'Creating jump host {JUMP_STACK_NAME}')
        template = string.Template(jump_template)
        client = utils.get_ostack_client()
        client.stacks.create_stack_from_template(
            template.safe_substitute(**TEMPLATE_DICT), JUMP_STACK_NAME)

        succ, msg = client.wait_for_stack_create_action(JUMP_STACK_NAME)
        assert succ

        return client.stacks.get_outputs(JUMP_STACK_NAME)

    @staticmethod
    def delete_jump_host():
        LOG.info("Deleting Jump Host")
        client = utils.get_ostack_client()
        client.delete_sandbox(JUMP_STACK_NAME)

    @staticmethod
    def set_jump_host_config(host, private_key):
        key_path = f'/tmp/test-key-{utils.get_simple_uuid()}'
        LOG.info('Stack outputs', host=host, key_path=key_path,
                 private_key=private_key)
        settings.KYPO_CONFIG.proxy_jump_to_man.Host = host
        settings.KYPO_CONFIG.proxy_jump_to_man.IdentityFile = key_path
        with open(key_path, 'w') as f:
            f.write(private_key)
