from functools import partial
from typing import List

import django_rq
import structlog
from django.db import transaction
from django.conf import settings

from kypo.sandbox_common_lib import utils
from kypo.sandbox_ansible_app.models import AnsibleAllocationStage
from kypo.sandbox_instance_app.lib import jobs
from kypo.sandbox_instance_app.models import Sandbox, Pool, SandboxAllocationUnit, \
    AllocationRequest, StackAllocationStage, SystemProcess, StageType
from kypo.sandbox_instance_app.lib.stage_handlers import StackStageHandler, AnsibleStageHandler

STACK_STATUS_CREATE_COMPLETE = "CREATE_COMPLETE"

LOG = structlog.get_logger()

OPENSTACK_QUEUE = 'openstack'
ANSIBLE_QUEUE = 'ansible'


def create_allocation_request(pool: Pool) -> SandboxAllocationUnit:
    """Create Sandbox Allocation Request.
    Also create sandbox, but do not save it to the database until
    successfully created.
    """
    unit = SandboxAllocationUnit.objects.create(pool=pool)
    request = AllocationRequest.objects.create(allocation_unit=unit)
    pri_key, pub_key = utils.generate_ssh_keypair()
    sandbox = Sandbox(id=unit.id, allocation_unit=unit,
                      private_user_key=pri_key, public_user_key=pub_key)
    enqueue_allocation_request(request, sandbox)
    return unit


def create_allocations_requests(pool: Pool, count: int) -> List[SandboxAllocationUnit]:
    """Batch version of create_allocation_request. Create count Sandbox Requests."""
    return [create_allocation_request(pool) for _ in range(count)]


def enqueue_allocation_request(request: AllocationRequest, sandbox: Sandbox) -> None:
    with transaction.atomic():
        stage_stack = StackAllocationStage.objects.create(request=request,
                                                          type=StageType.OPENSTACK.value)
        queue_stack = django_rq.get_queue(
            OPENSTACK_QUEUE, default_timeout=settings.KYPO_CONFIG.sandbox_build_timeout)
        job_stack = queue_stack.enqueue(
            StackStageHandler().build, stage_name=stage_stack.__class__.__name__,
            stage=stage_stack, sandbox=sandbox, meta=dict(locked=True)
        )
        SystemProcess.objects.create(stage=stage_stack, process_id=job_stack.id)

        stage_networking = AnsibleAllocationStage.objects.create(
            request=request, repo_url=settings.KYPO_CONFIG.ansible_networking_url,
            rev=settings.KYPO_CONFIG.ansible_networking_rev, type=StageType.ANSIBLE.value
        )
        queue_ansible = django_rq.get_queue(
            ANSIBLE_QUEUE, default_timeout=settings.KYPO_CONFIG.sandbox_ansible_timeout)
        job_networking = queue_ansible.enqueue(
            AnsibleStageHandler().build, stage_name='Allocation Networking Ansible',
            stage=stage_networking, sandbox=sandbox, depends_on=job_stack
        )
        SystemProcess.objects.create(stage=stage_networking, process_id=job_networking.id)

        stage_user_ansible = AnsibleAllocationStage.objects.create(
            request=request, repo_url=request.allocation_unit.pool.definition.url,
            rev=request.allocation_unit.pool.rev_sha, type=StageType.ANSIBLE.value
        )
        job_user_ansible = queue_ansible.enqueue(
            AnsibleStageHandler().build, stage_name='Allocation User Ansible',
            stage=stage_user_ansible, sandbox=sandbox, depends_on=job_networking)
        SystemProcess.objects.create(stage=stage_user_ansible, process_id=job_user_ansible.id)

        queue_default = django_rq.get_queue()
        queue_default.enqueue(save_sandbox_to_database, sandbox=sandbox,
                              depends_on=job_user_ansible)
        transaction.on_commit(partial(jobs.unlock_job, job_stack))


def save_sandbox_to_database(sandbox):
    sandbox.save()
