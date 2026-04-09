# Generated for single-sandbox-per-user: creator metadata

from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ('sandbox_instance_app', '0013_sandbox_ready'),
    ]

    operations = [
        migrations.AddField(
            model_name='sandboxallocationunit',
            name='created_by_sub',
            field=models.CharField(
                blank=True,
                help_text='OIDC sub of the creator when created via service-to-service (e.g. training backend).',
                max_length=255,
                null=True
            ),
        ),
        migrations.AddField(
            model_name='sandboxallocationunit',
            name='created_at',
            field=models.DateTimeField(
                default=timezone.now,
                help_text='When this allocation unit was created.'
            ),
        ),
    ]
