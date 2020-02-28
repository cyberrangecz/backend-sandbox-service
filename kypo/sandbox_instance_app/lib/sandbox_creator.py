from functools import partial
from typing import List

import django_rq
import structlog
from django.db import transaction
from rq.job import Job
from django.conf import settings

from kypo.sandbox_instance_app.models import Sandbox, Pool, SandboxAllocationUnit, \
    AllocationRequest, StackAllocationStage, SystemProcess
from kypo.sandbox_ansible_app.models import AnsibleAllocationStage
from kypo.sandbox_common_lib import utils
from kypo.sandbox_instance_app.lib.stage_handlers import StackStageHandler, AnsibleStageHandler

STACK_STATUS_CREATE_COMPLETE = "CREATE_COMPLETE"

LOG = structlog.get_logger()

OPENSTACK_QUEUE = 'openstack'
ANSIBLE_QUEUE = 'ansible'

NETWORKING_ANSIBLE_NAME = 'Networking Ansible'
USER_ANSIBLE_NAME = 'User Ansible'


def create_sandbox_requests(pool: Pool, count: int) -> List[SandboxAllocationUnit]:
    """
    Creates Sandbox Requests.
    Also creates sandboxes, but does not save them to the database until
    successfully created.
    """
    units = []
    requests = []
    sandboxes = []
    for _ in range(count):
        unit = SandboxAllocationUnit.objects.create(pool=pool)
        request = AllocationRequest.objects.create(allocation_unit=unit)
        units.append(unit)
        requests.append(request)

        pri_key, pub_key = utils.generate_ssh_keypair()
        sandbox = Sandbox(id=request.id, allocation_unit=unit,
                          private_user_key=pri_key, public_user_key=pub_key)
        sandboxes.append(sandbox)
    enqueue_requests(requests, sandboxes)
    return units


def enqueue_requests(requests: List[AllocationRequest], sandboxes) -> None:
    for request, sandbox in zip(requests, sandboxes):
        with transaction.atomic():
            stage_openstack = StackAllocationStage.objects.create(request=request)
            queue_openstack = django_rq.get_queue(
                OPENSTACK_QUEUE, default_timeout=settings.KYPO_CONFIG.sandbox_build_timeout)
            job_openstack = queue_openstack.enqueue(
                StackStageHandler(stage_openstack.__class__.__name__).build,
                stage=stage_openstack, sandbox=sandbox, meta=dict(locked=True)
            )
            SystemProcess.objects.create(stage=stage_openstack, process_id=job_openstack.id)

            stage_networking = AnsibleAllocationStage.objects.create(
                request=request, repo_url=settings.KYPO_CONFIG.ansible_networking_url,
                rev=settings.KYPO_CONFIG.ansible_networking_rev
            )
            queue_ansible = django_rq.get_queue(
                ANSIBLE_QUEUE, default_timeout=settings.KYPO_CONFIG.sandbox_ansible_timeout)
            job_networking = queue_ansible.enqueue(
                AnsibleStageHandler(NETWORKING_ANSIBLE_NAME).build, stage=stage_networking,
                sandbox=sandbox, depends_on=job_openstack
            )
            SystemProcess.objects.create(stage=stage_networking, process_id=job_networking.id)

            stage_user_ansible = AnsibleAllocationStage.objects.create(
                request=request, repo_url=request.allocation_unit.pool.definition.url,
                rev=request.allocation_unit.pool.definition.rev
            )
            job_user_ansible = queue_ansible.enqueue(
                AnsibleStageHandler(USER_ANSIBLE_NAME).build, stage=stage_user_ansible,
                sandbox=sandbox, depends_on=job_networking)
            SystemProcess.objects.create(stage=stage_user_ansible, process_id=job_user_ansible.id)

            queue_default = django_rq.get_queue()
            queue_default.enqueue(save_sandbox_to_database, sandbox=sandbox,
                                  depends_on=job_user_ansible)
            transaction.on_commit(partial(unlock_job, job_openstack))


def unlock_job(job: Job):
    stage = job.kwargs.get('stage')
    if job.meta.get('locked', True):
        LOG.debug('Unlocking stage.', stage=stage)
    job.meta['locked'] = False
    job.save_meta()


def save_sandbox_to_database(sandbox):
    sandbox.save()
