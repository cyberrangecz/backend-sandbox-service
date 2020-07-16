from django.db import models

from kypo.sandbox_instance_app.models import ExternalDependency, AllocationStage, \
    CleanupStage, AllocationRequest, CleanupRequest, SandboxAllocationUnit


class AnsibleAllocationStage(AllocationStage):
    repo_url = models.TextField(help_text='URL of the Ansible repository.')
    rev = models.TextField(help_text='Revision of the Ansible repository.')

    class Meta:
        abstract = True

    def __str__(self):
        return super().__str__() + \
               ', REPO_URL: {0.repo_url}, REV: {0.rev}'.format(self)


class NetworkingAnsibleAllocationStage(AnsibleAllocationStage):
    allocation_request = models.OneToOneField(
        AllocationRequest,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return super().__str__() + ', REQUEST: {0.allocation_request}'.format(self)


class UserAnsibleAllocationStage(AnsibleAllocationStage):
    allocation_request = models.OneToOneField(
        AllocationRequest,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return super().__str__() + ', REQUEST: {0.allocation_request}'.format(self)


class AnsibleCleanupStage(CleanupStage):

    class Meta:
        abstract = True


class NetworkingAnsibleCleanupStage(AnsibleCleanupStage):
    cleanup_request = models.OneToOneField(
        CleanupRequest,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return super().__str__() + ', REQUEST: {0.cleanup_request}'.format(self)


class UserAnsibleCleanupStage(AnsibleCleanupStage):
    cleanup_request = models.OneToOneField(
        CleanupRequest,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return super().__str__() + ', REQUEST: {0.cleanup_request}'.format(self)


# TODO not the best relationship
class AnsibleOutput(models.Model):
    allocation_stage = models.ForeignKey(
        AllocationStage,
        on_delete=models.CASCADE,
        related_name='outputs'
    )
    content = models.TextField()

    class Meta:
        ordering = ['id']

    def __str__(self):
        return 'ID: {0.id}, STAGE: {0.stage.id}, CONTENT: {0.content}'.format(self)


class DockerContainer(ExternalDependency):
    container_id = models.TextField()

    def __str__(self):
        return 'STAGE: {0.stage.id}, CONTAINER: {0.container_id}'.format(self)
