from enum import Enum

from django.db import models
from django.db.models import PositiveIntegerField
from django.utils import timezone
from model_utils.managers import InheritanceManager

from kypo.sandbox_common_lib import utils
from kypo.sandbox_definition_app.models import Definition

class StageType(Enum):
    OPENSTACK = 'openstack'
    ANSIBLE = 'ansible'


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
        return 'ID: {0.id}, DEFINITION: {0.definition.id}, MAX_SIZE: {0.max_size}, ' \
               'REV: {0.rev}'.format(self)

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
        return self.pool.definition.name + '-' + str(self.id)


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
        return 'ID: {0.id}, ALLOCATION_UNIT: {0.allocation_unit.id}, CREATED: {0.created}'\
            .format(self)

    @property
    def is_running(self):
        return any([stage.is_running for stage in self.stages.all()])

    @property
    def is_finished(self):
        return all([stage.is_finished for stage in self.stages.all()])


class AllocationRequest(SandboxRequest):
    allocation_unit = models.OneToOneField(
        SandboxAllocationUnit,
        on_delete=models.CASCADE,
        related_name='allocation_request',
    )


class CleanupRequest(SandboxRequest):
    allocation_unit = models.ForeignKey(
        SandboxAllocationUnit,
        on_delete=models.CASCADE,
        related_name='cleanup_requests',
    )


class Stage(models.Model):
    """Abstract base class for stages."""
    STAGE_CHOICES = [(stg_type.value, stg_type.value) for stg_type in StageType]
    type = models.CharField(choices=STAGE_CHOICES, max_length=32,
                            help_text='Type of the stage')

    start = models.DateTimeField(null=True, default=None,
                                 help_text='Timestamp indicating when the stage execution started.')
    end = models.DateTimeField(null=True, default=None,
                               help_text='Timestamp indicating when the stage execution ended.')
    failed = models.BooleanField(default=False,
                                 help_text='Indicates whether the stage execution failed.')
    error_message = models.TextField(null=True, default=None,
                                     help_text='Error message describing the potential error.')

    @property
    def is_finished(self):
        return self.end is not None or self.failed

    @property
    def is_running(self):
        return self.start is not None and self.end is None

    class Meta:
        abstract = True
        ordering = ['id']

    def __str__(self):
        return 'START: {0.start}, END: {0.end}, FAILED: {0.failed}, TYPE: {0.type}'.format(self)

    def mark_failed(self, exception=None):
        self.failed = True
        if exception:
            self.error_message = str(exception)
        self.save()


class AllocationStage(Stage):
    request = models.ForeignKey(
        AllocationRequest,
        on_delete=models.CASCADE,
        related_name='stages',
    )

    objects = InheritanceManager()

    def __str__(self):
        return '{0.id}, '.format(self) + super().__str__()


class StackAllocationStage(AllocationStage):
    status = models.CharField(null=True, max_length=30, help_text='Stack status')
    status_reason = models.TextField(null=True, help_text='Stack status reason')

    def __init__(self, *args, **kwargs):
        """Custom constructor that sets the correct stage type."""
        super().__init__(*args, **kwargs)
        self.type = StageType.OPENSTACK.value

    def __str__(self):
        return super().__str__() + \
               ', STATUS: {0.status}, STATUS_REASON: {0.status_reason}'.format(self)


class CleanupStage(Stage):
    request = models.ForeignKey(
        CleanupRequest,
        on_delete=models.CASCADE,
        related_name='stages',
    )

    objects = InheritanceManager()

    class Meta:
        ordering = ['id']

    def __str__(self):
        return '{0.id}, '.format(self) + super().__str__()


class StackCleanupStage(CleanupStage):
    allocation_stage = models.ForeignKey(
        StackAllocationStage,
        on_delete=models.CASCADE,
        related_name='cleanup_stages',
    )

    def __init__(self, *args, **kwargs):
        """Custom constructor that sets the correct stage type."""
        super().__init__(*args, **kwargs)
        self.type = StageType.OPENSTACK.value

    def __str__(self):
        return super().__str__() + \
               ', ALLOCATION_STAGE: {0.allocation_stage}'.format(self)


class ExternalDependency(models.Model):
    class Meta:
        abstract = True


class HeatStack(ExternalDependency):
    stage = models.OneToOneField(
        StackAllocationStage,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='heatstack',
    )
    stack_id = models.TextField()

    def __str__(self):
        return 'STAGE: {0.stage.id}, STACK: {0.stack_id}'.format(self)


class RQJob(ExternalDependency):
    stage = models.OneToOneField(
        AllocationStage,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='rq_job',
    )
    job_id = models.TextField()

    def __str__(self):
        return 'STAGE: {0.stage.id}, JOB_ID: {0.job_id}'.format(self)


class SystemProcess(ExternalDependency):
    stage = models.OneToOneField(
        AllocationStage,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='process',
    )
    process_id = models.TextField()

    def __str__(self):
        return 'STAGE: {0.stage.id}, PROCESS: {0.process_id}'.format(self)
