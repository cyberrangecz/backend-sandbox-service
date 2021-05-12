from django.db import models

from kypo.sandbox_instance_app.models import ExternalDependency, AllocationStage, \
    CleanupStage, AllocationRequest, CleanupRequest, SandboxAllocationUnit,\
    ExternalDependencyCleanup


class AnsibleAllocationStage(AllocationStage):
    repo_url = models.TextField(help_text='URL of the Ansible repository.')
    rev = models.TextField(help_text='Revision of the Ansible repository.')

    class Meta:
        abstract = True

    def __str__(self):
        return super().__str__() + \
               f', REPO_URL: {self.repo_url}, REV: {self.rev}'


class NetworkingAnsibleAllocationStage(AnsibleAllocationStage):
    allocation_request = models.OneToOneField(
        AllocationRequest,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return super().__str__() + f', REQUEST: {self.allocation_request}'


class UserAnsibleAllocationStage(AnsibleAllocationStage):
    allocation_request = models.OneToOneField(
        AllocationRequest,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return super().__str__() + f', REQUEST: {self.allocation_request}'


class AnsibleCleanupStage(CleanupStage):

    class Meta:
        abstract = True


class NetworkingAnsibleCleanupStage(AnsibleCleanupStage):
    cleanup_request = models.OneToOneField(
        CleanupRequest,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return super().__str__() + f', REQUEST: {self.cleanup_request}'


class UserAnsibleCleanupStage(AnsibleCleanupStage):
    cleanup_request = models.OneToOneField(
        CleanupRequest,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return super().__str__() + f', REQUEST: {self.cleanup_request}'


class AnsibleOutput(models.Model):
    content = models.TextField()

    class Meta:
        abstract = True
        ordering = ['id']

    def __str__(self):
        return f'ID: {self.id}, CONTENT: {self.content}'


# TODO not the best relationship
class AllocationAnsibleOutput(AnsibleOutput):
    allocation_stage = models.ForeignKey(
        AllocationStage,
        on_delete=models.CASCADE,
        related_name='outputs'
    )

    def __str__(self):
        return f'{super().__str__()} STAGE: {self.allocation_stage.id}'


class CleanupAnsibleOutput(AnsibleOutput):
    cleanup_stage = models.ForeignKey(
        CleanupStage,
        on_delete=models.CASCADE,
        related_name='outputs'
    )

    def __str__(self):
        return f'{super().__str__()} STAGE: {self.cleanup_stage.id}'


class DockerContainer(ExternalDependency):
    container_id = models.TextField()

    def __str__(self):
        return f'STAGE: {self.allocation_stage.id}, CONTAINER: {self.container_id}'


class DockerContainerCleanup(ExternalDependencyCleanup):
    container_id = models.TextField()

    def __str__(self):
        return f'STAGE: {self.cleanup_stage.id}, CONTAINER: {self.container_id}'
