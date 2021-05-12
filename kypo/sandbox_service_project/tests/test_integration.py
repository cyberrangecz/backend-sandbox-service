import os
import string

import pytest
import structlog
from django.conf import settings
from django.urls import reverse
from redis import Redis
from rest_framework import status
from rq import SimpleWorker

from kypo.sandbox_ansible_app.models import AllocationAnsibleOutput
from kypo.sandbox_common_lib import utils
from kypo.sandbox_instance_app.models import Sandbox

LOG = structlog.get_logger()

DEFINITION_URL = 'git@192.168.55.101:/repos/prototypes-and-examples/sandbox-definitions/small-sandbox.git'
DEFINITION_REV = 'master'

# Heat stack and template values
JUMP_STACK_NAME = 'integration_test_jump'
DEFAULT_PUBLIC_NETWORK = 'public-cesnet-78-128-251-GROUP'
KEY_PAIR = 'test_key'
JUMP_NETWORK = settings.KYPO_CONFIG.trc.base_network
JUMP_SERVER = 'jump_server'
TEMPLATE_DICT = dict(
    PUBLIC_NETWORK=os.environ.get('PUBLIC_NETWORK', DEFAULT_PUBLIC_NETWORK),
    JUMP_IMAGE=settings.KYPO_CONFIG.trc.extra_nodes_image,
    JUMP_FLAVOR=settings.KYPO_CONFIG.trc.extra_nodes_flavor,
    KEY_PAIR=KEY_PAIR,
    JUMP_NETWORK=JUMP_NETWORK,
    JUMP_SERVER=JUMP_SERVER,
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
SANDBOX_CLEANUP_REQUEST = 'sandbox-cleanup-request'
SANDBOX_CLEANUP_REQUEST_CANCEL = 'sandbox-cleanup-request-cancel'
SANDBOX_ALLOCATION_REQUEST_CANCEL = 'sandbox-allocation-request-cancel'
ALLOCATION_STAGE_OPENSTACK = 'openstack-allocation-stage'
ALLOCATION_STAGE_NETWORKING_ANSIBLE = 'networking-ansible-allocation-stage'
ALLOCATION_STAGE_USER_ANSIBLE = 'user-ansible-allocation-stage'
CLEANUP_STAGE_OPENSTACK = 'openstack-cleanup-stage'
CLEANUP_STAGE_NETWORKING_ANSIBLE = 'networking-ansible-cleanup-stage'
CLEANUP_STAGE_USER_ANSIBLE = 'user-ansible-cleanup-stage'


@pytest.mark.integration
class TestIntegration:
    pytestmark = pytest.mark.django_db(transaction=True)
    RQ_QUEUES = ('default', 'openstack', 'ansible')

    def test_build_sandbox_full(self, client, jump_template):
        try:
            private_key = self.create_key_pair()
            self.create_jump_host(jump_template)
            jump_ip = self.get_jump_ip_address()
            self.set_jump_host_config(jump_ip, private_key)

            def_id = self.create_definition(client, DEFINITION_URL, DEFINITION_REV)
            try:
                pool_id = self.create_pool(client, def_id)
                try:
                    unit_id, alloc_req_id = self.create_alloc_unit(client, pool_id)
                    try:
                        try:
                            assert len(Sandbox.objects.all()) == 1
                        except AssertionError:
                            ansible_outputs = [x.content for x in AllocationAnsibleOutput.objects.all()]
                            LOG.info('Ansible outputs', ansible_outputs='\n'.join(ansible_outputs))
                            self.cancel_allocation_request(client, alloc_req_id)
                            raise
                        sb_id, lock_id = self.get_and_lock(client, pool_id)
                        self.unlock_sandbox(client, sb_id, lock_id)
                        self.create_cancel_delete_cleanup_request(client, unit_id)
                    finally:
                        self.create_cleanup_req(client, unit_id)
                finally:
                    self.delete_pool(client, pool_id)
            finally:
                self.delete_definition(client, def_id)
        finally:
            self.delete_key_pair()
            self.delete_jump_host()

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
        data = {'definition_id': def_id, 'max_size': max_size}
        response = client.post(reverse(POOL_LIST), data, 'application/json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['definition_id'] == def_id
        assert response.data['size'] == 0
        assert response.data['max_size'] == max_size
        return response.data['id']

    @classmethod
    def create_alloc_unit(cls, client, pool_id):
        LOG.info("Creating Allocation Unit")
        base_url = reverse(ALLOCATION_UNIT_LIST, kwargs={'pool_id': pool_id})
        response = client.post(base_url + '?count=1')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data[0]['pool_id'] == pool_id

        unit_id = response.data[0]['id']
        alloc_req_id = response.data[0]['allocation_request']['id']

        cls.get_allocation_stages(client, alloc_req_id)
        cls.run_worker()

        return unit_id, alloc_req_id

    @staticmethod
    def get_allocation_stages(client, request_id):
        LOG.info("Retrieving Allocation stages.")

        for stage_url in (ALLOCATION_STAGE_OPENSTACK,
                          ALLOCATION_STAGE_NETWORKING_ANSIBLE,
                          ALLOCATION_STAGE_USER_ANSIBLE):
            base_url = reverse(stage_url, kwargs={'request_id': request_id})
            response = client.get(base_url)
            assert response.status_code == status.HTTP_200_OK
            assert response.data['request_id'] == request_id

    @staticmethod
    def get_cleanup_stages(client, request_id):
        LOG.info("Retrieving Cleanup stages.")

        for stage_url in (CLEANUP_STAGE_OPENSTACK,
                          CLEANUP_STAGE_NETWORKING_ANSIBLE,
                          CLEANUP_STAGE_USER_ANSIBLE):
            base_url = reverse(stage_url, kwargs={'request_id': request_id})
            response = client.get(base_url)
            assert response.status_code == status.HTTP_200_OK
            assert response.data['request_id'] == request_id

    @staticmethod
    def cancel_allocation_request(client, allocation_req_id):
        LOG.info("Canceling Allocation Request")

        response = client.patch(reverse(SANDBOX_ALLOCATION_REQUEST_CANCEL,
                                        kwargs={'request_id': allocation_req_id}))
        assert response.status_code == status.HTTP_200_OK

    @staticmethod
    def create_cancel_delete_cleanup_request(client, unit_id):
        LOG.info("Test Create, Cancel and Delete of Cleanup request")

        # Create success
        response = client.post(reverse(SANDBOX_CLEANUP_REQUEST, kwargs={'unit_id': unit_id}))
        assert response.status_code == status.HTTP_201_CREATED
        cleanup_req_id = response.data['id']

        # Create duplicate fail
        response = client.post(reverse(SANDBOX_CLEANUP_REQUEST, kwargs={'unit_id': unit_id}))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # Delete fail
        response = client.delete(reverse(SANDBOX_CLEANUP_REQUEST, kwargs={'unit_id': unit_id}))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # Cancel
        response = client.patch(reverse(SANDBOX_CLEANUP_REQUEST_CANCEL,
                                        kwargs={'request_id': cleanup_req_id}))
        assert response.status_code == status.HTTP_200_OK

        # Delete success
        response = client.delete(reverse(SANDBOX_CLEANUP_REQUEST, kwargs={'unit_id': unit_id}))
        assert response.status_code == status.HTTP_204_NO_CONTENT

    @classmethod
    def create_cleanup_req(cls, client, unit_id):
        LOG.info("Creating Cleanup request")
        response = client.post(reverse(SANDBOX_CLEANUP_REQUEST,
                                       kwargs={'unit_id': unit_id}))

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['allocation_unit_id'] == unit_id

        cleanup_req_id = response.data['id']
        cls.get_cleanup_stages(client, cleanup_req_id)
        cls.run_worker()

    @staticmethod
    def get_and_lock(client, pool_id):
        LOG.info("Get and lock sandbox")
        response = client.get(reverse(SANDBOX_GET_AND_LOCK,
                                      kwargs={'pool_id': pool_id}))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['lock_id'] is not None
        sb_id = response.data['id']
        lock_id = response.data['lock_id']
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
        client.open_stack_proxy.create_stack_from_template(
            template.safe_substitute(**TEMPLATE_DICT), JUMP_STACK_NAME)

        result, msg = client.wait_for_stack_create_action(JUMP_STACK_NAME)
        assert result

    @staticmethod
    def delete_jump_host():
        LOG.info("Deleting Jump Host")
        client = utils.get_ostack_client()
        client.delete_stack(JUMP_STACK_NAME)

    @staticmethod
    def set_jump_host_config(host, private_key):
        key_path = f'/tmp/test-key-{utils.get_simple_uuid()}'
        LOG.info('Set jump host config', host=host, key_path=key_path,
                 private_key=private_key)
        settings.KYPO_CONFIG.proxy_jump_to_man.Host = host
        settings.KYPO_CONFIG.proxy_jump_to_man.IdentityFile = key_path
        with open(key_path, 'w') as f:
            f.write(private_key)

    @staticmethod
    def create_key_pair():
        client = utils.get_ostack_client()
        return client.create_keypair(KEY_PAIR).to_dict().get('private_key')

    @staticmethod
    def delete_key_pair():
        client = utils.get_ostack_client()
        client.delete_keypair(KEY_PAIR)

    @staticmethod
    def get_jump_ip_address():
        client = utils.get_ostack_client()
        links = client.get_node(JUMP_STACK_NAME, JUMP_SERVER).links.get(JUMP_NETWORK)
        links = [link for link in links if link['type'] == 'floating']
        return links[0]['addr'] if links else None
