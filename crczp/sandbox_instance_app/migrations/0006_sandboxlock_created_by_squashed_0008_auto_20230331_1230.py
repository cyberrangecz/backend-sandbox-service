# Generated by Django 2.2.28 on 2023-04-12 10:16

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    replaces = [('sandbox_instance_app', '0006_sandboxlock_created_by'), ('sandbox_instance_app', '0007_auto_20230201_1540'), ('sandbox_instance_app', '0008_auto_20230331_1230')]

    dependencies = [
        ('sandbox_instance_app', '0005_auto_20220812_1634'),
    ]

    operations = [
        migrations.AddField(
            model_name='sandboxlock',
            name='created_by',
            field=models.ForeignKey(help_text='The user that created this lock.', null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL),
        ),
    ]
