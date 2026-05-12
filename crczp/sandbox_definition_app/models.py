"""Django models for the sandbox definition app."""

from django.contrib.auth.models import User
from django.db import models


class Definition(models.Model):
    """Represents a sandbox definition consisting of a git URL and revision."""

    name = models.CharField(max_length=100, help_text='Name of the definition.')
    url = models.TextField(help_text='URL of the definition.')
    rev = models.TextField(default='master', help_text='Default revision.')
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        help_text='The user that created this definition.',
    )

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta options for Definition."""

        ordering = ['id']

    def __str__(self):
        return f'ID: {self.id}, NAME: {self.name}, URL: {self.url}, REV: {self.rev}'
