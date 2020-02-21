from enum import Enum

from django.db import models
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
    max_size = models.IntegerField()
    private_management_key = models.TextField()
    public_management_key = models.TextField()
    uuid = models.TextField(default=utils.get_simple_uuid)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return "ID: {0.id}, DEFINITION: {0.definition.id}, MAX_SIZE: {0.max_size}".format(self)

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
    allocation_unit = models.OneToOneField(
        SandboxAllocationUnit,
        on_delete=models.PROTECT,
        related_name='sandbox',
    )
    private_user_key = models.TextField()
    public_user_key = models.TextField()

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"ID: {self.id}, ALLOCATION_UNIT: {self.allocation_unit.id}, " \
               f"LOCK: {self.lock.id if hasattr(self, 'lock') else None}"

    def get_stack_name(self) -> str:
        """Returns a name of the stack for this sandbox"""
        return self.allocation_unit.get_stack_name()


class Lock(models.Model):
    sandbox = models.OneToOneField(
        Sandbox,
        on_delete=models.PROTECT,
        related_name='lock',
    )

    def __str__(self):
        return f"ID: {self.id}, Sandbox: {self.sandbox.id}"


class SandboxRequest(models.Model):
    """Abstract base class for Sandbox Requests."""
    created = models.DateTimeField(default=timezone.now)

    class Meta:
        abstract = True
        ordering = ['created']

    def __str__(self):
        return "ID: {0.id}, ALLOCATION_UNIT: {0.allocation_unit.id}, CREATED: {0.created}"\
            .format(self)

    def get_stack_name(self) -> str:
        """Returns a name of the stack for this sandbox"""
        return self.allocation_unit.get_stack_name()


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
    start = models.DateTimeField(null=True, default=None)
    end = models.DateTimeField(null=True, default=None)

    failed = models.BooleanField(default=False)
    error_message = models.TextField(null=True)

    @property
    def is_finished(self):
        return self.end is not None

    @property
    def is_running(self):
        return self.start is not None and self.end is None

    class Meta:
        abstract = True
        ordering = ['id']

    def __str__(self):
        return "START: {0.start}, END: {0.end} FAILED: {0.failed}".format(self)

    def mark_failed(self, exception=None):
        self.failed = True
        if exception:
            self.error_message = str(exception)
        self.save()


class AllocationStage(Stage):
    type = 'unknown'

    request = models.ForeignKey(
        AllocationRequest,
        on_delete=models.CASCADE,
        related_name='stages',
    )

    objects = InheritanceManager()

    def __str__(self):
        return "{0.id}, ".format(self) + super().__str__()


class StackAllocationStage(AllocationStage):
    type = StageType.OPENSTACK

    status = models.CharField(null=True, max_length=30)
    status_reason = models.TextField(null=True)

    def __str__(self):
        return super().__str__() + \
               ", STATUS: {0.status}, STATUS_REASON: {0.status_reason}".format(self)


class CleanupStage(Stage):
    type = 'unknown'

    request = models.ForeignKey(
        CleanupRequest,
        on_delete=models.CASCADE,
        related_name='stages',
    )

    objects = InheritanceManager()

    class Meta:
        ordering = ['id']

    def __str__(self):
        return "{0.id}, ".format(self) + super().__str__()


class StackCleanupStage(CleanupStage):
    type = StageType.OPENSTACK

    allocation_stage = models.OneToOneField(
        StackAllocationStage,
        on_delete=models.CASCADE,
        related_name='cleanup_stage',
    )

    def __str__(self):
        return super().__str__() + \
               ", ALLOCATION_STAGE: {0.allocation_stage}".format(self)


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


class SystemProcesses(ExternalDependency):
    pass
