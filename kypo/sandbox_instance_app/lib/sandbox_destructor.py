import django_rq
import structlog
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings

from kypo.sandbox_instance_app.lib.stage_handlers import StackStageHandler, AnsibleStageHandler
from kypo.sandbox_instance_app.models import CleanupRequest, SandboxAllocationUnit, StackCleanupStage
from kypo.sandbox_instance_app.lib.sandbox_creator import OPENSTACK_QUEUE, ANSIBLE_QUEUE, \
    NETWORKING_ANSIBLE_NAME, USER_ANSIBLE_NAME
from kypo.sandbox_common_lib import exceptions
from kypo.sandbox_ansible_app.models import AnsibleCleanupStage

LOG = structlog.get_logger()


def cleanup_sandbox_request(allocation_unit: SandboxAllocationUnit) -> CleanupRequest:
    """Create cleanup request and enqueue it. Immediately delete sandbox from database."""
    try:
        sandbox = allocation_unit.sandbox
    except ObjectDoesNotExist:
        sandbox = None
    else:
        if hasattr(sandbox, 'lock'):
            raise exceptions.ValidationError('Sandbox ID={} is locked.'.format(sandbox.id))

    if any([stage.is_running for stage in
            allocation_unit.allocation_request.stages.all()]):
        raise exceptions.ValidationError(
            f'Create sandbox allocation request ID={allocation_unit.allocation_request.id}'
            f' has not finished yet. You need to stop it first.'
        )

    request = CleanupRequest.objects.create(allocation_unit=allocation_unit)
    LOG.info('CleanupRequest created', request=request,
             allocation_unit=allocation_unit, sandbox=sandbox)
    enqueue_request(request, allocation_unit)

    sandbox.delete()

    return request


def enqueue_request(request: CleanupRequest,
                    allocation_unit: SandboxAllocationUnit) -> None:
    """Enqueue given request."""
    alloc_stages = allocation_unit.allocation_request.stages.all().select_subclasses()

    stage_user_ans = AnsibleCleanupStage.objects.create(request=request,
                                                        allocation_stage=alloc_stages[2])
    queue_ansible = django_rq.get_queue(ANSIBLE_QUEUE)
    job_user_ans = queue_ansible.enqueue(
        StackStageHandler(USER_ANSIBLE_NAME).cleanup,
        stage=stage_user_ans)

    stage_networking = AnsibleCleanupStage.objects.create(request=request,
                                                          allocation_stage=alloc_stages[1])
    job_networking = queue_ansible.enqueue(
        StackStageHandler(NETWORKING_ANSIBLE_NAME).cleanup,
        stage=stage_user_ans, depeneds_on=job_user_ans)

    stage_openstack = StackCleanupStage.objects.create(request=request,
                                                       allocation_stage=alloc_stages[0])
    queue_openstack = django_rq.get_queue(OPENSTACK_QUEUE,
                                          default_timeout=settings.KYPO_CONFIG.sandbox_delete_timeout)
    job_openstack = queue_openstack.enqueue(
        StackStageHandler(stage_openstack.__class__.__name__).cleanup,
        stage=stage_openstack,
        denepnds_on=job_networking)

    queue_default = django_rq.get_queue()
    queue_default.enqueue(delete_allocation_unit, allocation_unit=allocation_unit,
                          depends_on=job_openstack)


def delete_allocation_unit(allocation_unit: SandboxAllocationUnit) -> None:
    allocation_unit.delete()
    LOG.info('Allocation Unit deleted from DB', allocation_unit=allocation_unit)
