# Generated manually (no makemigrations in this environment)

import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('finnovaapp', '0003_organization_segment'),
    ]

    operations = [
        migrations.CreateModel(
            name='DomainEvent',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('event_type', models.CharField(max_length=80, db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('correlation_id', models.UUIDField(default=uuid.uuid4, db_index=True)),
                ('idempotency_key', models.CharField(max_length=120, null=True, blank=True, db_index=True)),
                ('metadata', models.JSONField(default=dict, blank=True)),
                ('processed', models.BooleanField(default=False, db_index=True)),
                ('processed_at', models.DateTimeField(null=True, blank=True)),
                ('processing_error', models.TextField(null=True, blank=True)),
                (
                    'organization',
                    models.ForeignKey(
                        to='finnovaapp.organization',
                        on_delete=django.db.models.deletion.SET_NULL,
                        null=True,
                        blank=True,
                        related_name='domain_events',
                    ),
                ),
                (
                    'actor',
                    models.ForeignKey(
                        to=settings.AUTH_USER_MODEL,
                        on_delete=django.db.models.deletion.SET_NULL,
                        null=True,
                        blank=True,
                        related_name='domain_events',
                    ),
                ),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='domainevent',
            constraint=models.UniqueConstraint(
                fields=('event_type', 'idempotency_key'),
                condition=Q(idempotency_key__isnull=False),
                name='uniq_eventhub_type_idempotency_key',
            ),
        ),
    ]
