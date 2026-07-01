import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('sandbox_instance_app', '0013_sandbox_ready'),
    ]

    operations = [
        migrations.CreateModel(
            name='SandboxNetbirdAccess',
            fields=[
                (
                    'id',
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name='ID'
                    ),
                ),
                (
                    'access_group_id',
                    models.CharField(
                        default=None,
                        help_text='Netbird group ID shared by all client peers of the sandbox.',
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    'access_setup_key_id',
                    models.CharField(
                        default=None,
                        help_text='Netbird setup key ID for the shared access group.',
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    'access_setup_key_value',
                    models.TextField(
                        default=None,
                        help_text='Plaintext setup key for the shared access group.',
                        null=True,
                    ),
                ),
                (
                    'dns_nameserver_group_id',
                    models.CharField(
                        default=None,
                        help_text=(
                            'Netbird DNS nameserver group ID distributed to the access group.'
                        ),
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    'sandbox',
                    models.OneToOneField(
                        help_text='Sandbox these access resources belong to.',
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='netbird_access',
                        to='sandbox_instance_app.sandbox',
                    ),
                ),
            ],
            options={
                'verbose_name_plural': 'sandbox netbird access',
                'ordering': ['id'],
            },
        ),
        migrations.CreateModel(
            name='SandboxNetbirdResources',
            fields=[
                (
                    'id',
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name='ID'
                    ),
                ),
                (
                    'entrypoint_host_name',
                    models.CharField(
                        help_text='Name of the topology host configured as VPN entrypoint.',
                        max_length=255,
                    ),
                ),
                (
                    'host_group_id',
                    models.CharField(
                        default=None,
                        help_text='Netbird group ID for the entrypoint peer.',
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    'host_setup_key_id',
                    models.CharField(
                        default=None,
                        help_text='Netbird setup key ID used by the agent on the entrypoint VM.',
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    'host_setup_key_value',
                    models.TextField(
                        default=None,
                        help_text='Plaintext setup key for the entrypoint host agent.',
                        null=True,
                    ),
                ),
                (
                    'route_ids',
                    models.TextField(
                        default=None,
                        help_text='Comma-separated Netbird route IDs for this entrypoint.',
                        null=True,
                    ),
                ),
                (
                    'route_cidrs',
                    models.TextField(
                        default=None,
                        help_text='Comma-separated CIDR strings for the routes of this entrypoint.',
                        null=True,
                    ),
                ),
                (
                    'policy_id',
                    models.CharField(
                        default=None,
                        help_text='Netbird access policy ID permitting client-to-host traffic.',
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    'sandbox',
                    models.ForeignKey(
                        help_text='Sandbox these resources belong to.',
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='netbird_resources',
                        to='sandbox_instance_app.sandbox',
                    ),
                ),
            ],
            options={
                'verbose_name_plural': 'sandbox netbird resources',
                'ordering': ['id'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='sandboxnetbirdresources',
            unique_together={('sandbox', 'entrypoint_host_name')},
        ),
    ]
