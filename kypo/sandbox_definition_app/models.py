from django.db import models
from django.contrib.auth.models import User


class Definition(models.Model):
    name = models.CharField(max_length=100, help_text='Name of the definition.')
    url = models.TextField(help_text='URL of the definition.')
    rev = models.TextField(default='master', help_text='Default revision.')
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                   help_text='The user that created this definition.')

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'ID: {self.id}, NAME: {self.name}, URL: {self.url}, REV: {self.rev}'
