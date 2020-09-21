from django.conf import settings
from django.db import models
from django.db.models import PositiveIntegerField
from django.utils import timezone

from kypo.sandbox_common_lib import utils
from kypo.sandbox_definition_app.models import Definition


class Pool(models.Model):
    definition = models.ForeignKey(
        Definition,
        on_delete=models.PROTECT
    )
    max_size = models.IntegerField(
        help_text='Maximum amount of Allocation Units associated with this pool.')
    private_management_key = models.TextField(
        help_text='Private key for management access.'
    )
    public_management_key = models.TextField(
        help_text='Public key for management access.'
    )
    uuid = models.TextField(default=utils.get_simple_uuid)
    rev = models.TextField(
        help_text='Definition revision used for sandboxes.'
    )
    rev_sha = models.TextField(
        help_text='SHA of the Definition revision.'
    )

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'ID: {self.id}, DEFINITION: {self.definition.id}, MAX_SIZE: {self.max_size}, ' \
               f'REV: {self.rev}'

    def get_keypair_name(self) -> str:
        """Returns a name of the management key-pair for this pool."""
        return self.definition.name + '-' + str(self.id) + '-' + str(self.uuid)


class SandboxAllocationUnit(models.Model):
    pool = models.ForeignKey(
        Pool,
        on_delete=models.CASCADE,
        related_name='allocation_units',
    )

    def get_stack_name(self) -> str:
        """Returns a name of the stack for this sandbox"""
        prefix = settings.KYPO_SERVICE_CONFIG.stack_name_prefix
        pool_id = self.pool.id
        return f'{prefix}-pool-id-{pool_id}-sau-id-{self.id}'


class Sandbox(models.Model):
    id = PositiveIntegerField(primary_key=True, auto_created=False, default=-1024)
    allocation_unit = models.OneToOneField(
        SandboxAllocationUnit,
        on_delete=models.PROTECT,
        related_name='sandbox',
    )
    private_user_key = models.TextField(
        help_text='Private key for user access.'
    )
    public_user_key = models.TextField(
        help_text='Public key for management access.'
    )

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'ID: {self.id}, ALLOCATION_UNIT: {self.allocation_unit.id}, ' \
               f'LOCK: {self.lock.id if hasattr(self, "lock") else None}'


class SandboxLock(models.Model):
    sandbox = models.OneToOneField(
        Sandbox,
        on_delete=models.PROTECT,
        related_name='lock',
    )

    def __str__(self):
        return f'ID: {self.id}, Sandbox: {self.sandbox.id}'


class PoolLock(models.Model):
    pool = models.OneToOneField(
        Pool,
        on_delete=models.PROTECT,
        related_name='lock',
    )

    def __str__(self):
        return f'ID: {self.id}, Pool: {self.pool.id}'


class SandboxRequest(models.Model):
    """Abstract base class for Sandbox Requests."""
    created = models.DateTimeField(default=timezone.now)

    class Meta:
        abstract = True
        ordering = ['created']

    def __str__(self):
        return f'ID: {self.id}, CREATED: {self.created}'


class AllocationRequest(SandboxRequest):
    allocation_unit = models.OneToOneField(
        SandboxAllocationUnit,
        on_delete=models.CASCADE,
        related_name='allocation_request',
    )

    @property
    def is_finished(self):
        """Whether all stages are finished."""
        return self.stages.filter(finished=False).count() == 0

    def __str__(self):
        return super().__str__() + f', ALLOCATION_UNIT: {self.allocation_unit.id}'


class CleanupRequest(SandboxRequest):
    allocation_unit = models.OneToOneField(
        SandboxAllocationUnit,
        on_delete=models.CASCADE,
        related_name='cleanup_request',
    )

    @property
    def is_finished(self):
        """Whether all stages are finished."""
        return self.stages.filter(finished=False).count() == 0

    def __str__(self):
        return super().__str__() + f', ALLOCATION_UNIT: {self.allocation_unit.id}'


class Stage(models.Model):
    """Abstract base class for stages."""
    start = models.DateTimeField(null=True, default=None,
                                 help_text='Timestamp indicating when the stage execution started.')
    end = models.DateTimeField(null=True, default=None,
                               help_text='Timestamp indicating when the stage execution ended.')
    failed = models.BooleanField(default=False,
                                 help_text='Indicates whether the stage execution failed.')
    error_message = models.TextField(null=True, default=None,
                                     help_text='Error message describing the potential error.')
    finished = models.BooleanField(default=False,
                                   help_text='Indicates whether the stage execution has finished.')

    class Meta:
        abstract = True
        ordering = ['id']

    def __str__(self):
        return f'ID: {self.id}, START: {self.start}, END: {self.end}, FAILED: {self.failed}, ' \
               f'ERROR: {self.error_message}'


class AllocationStage(Stage):
    allocation_request_fk_many = models.ForeignKey(
        AllocationRequest,
        on_delete=models.CASCADE,
        related_name='stages'
    )


class CleanupStage(Stage):
    cleanup_request_fk_many = models.ForeignKey(
        CleanupRequest,
        on_delete=models.CASCADE,
        related_name='stages'
    )


class StackAllocationStage(AllocationStage):
    allocation_request = models.OneToOneField(
        AllocationRequest,
        on_delete=models.CASCADE,
    )
    status = models.CharField(null=True, max_length=30, help_text='Stack status')
    status_reason = models.TextField(null=True, help_text='Stack status reason')

    def __str__(self):
        return super().__str__() + f', REQUEST: {self.allocation_request}, STATUS: {self.status},' \
                                   f' STATUS_REASON: {self.status_reason}'


class StackCleanupStage(CleanupStage):
    cleanup_request = models.OneToOneField(
        CleanupRequest,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return super().__str__() + f', REQUEST: {self.cleanup_request}'


class RQJob(models.Model):
    job_id = models.TextField()

    class Meta:
        abstract = True


class AllocationRQJob(RQJob):
    allocation_stage = models.OneToOneField(
        AllocationStage,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='rq_job',
    )

    def __str__(self):
        return f'STAGE: {self.allocation_stage.id}, JOB_ID: {self.job_id}'


class CleanupRQJob(RQJob):
    cleanup_stage = models.OneToOneField(
        CleanupStage,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='rq_job',
    )

    def __str__(self):
        return f'STAGE: {self.cleanup_stage.id}, JOB_ID: {self.job_id}'


class ExternalDependency(models.Model):
    allocation_stage = models.OneToOneField(
        AllocationStage,
        on_delete=models.CASCADE
    )

    class Meta:
        abstract = True


class HeatStack(ExternalDependency):
    stack_id = models.TextField()

    def __str__(self):
        return f'STAGE: {self.allocation_stage.id}, STACK: {self.stack_id}'


class SystemProcess(ExternalDependency):
    process_id = models.TextField()

    def __str__(self):
        return f'STAGE: {self.allocation_stage.id}, PROCESS: {self.process_id}'
