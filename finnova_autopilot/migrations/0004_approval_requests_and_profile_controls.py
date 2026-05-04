# Generated manually (no makemigrations in this environment)

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('finnovaapp', '0003_organization_segment'),
        ('payments_core', '0004_cardtoken_organization'),
        ('finnova_autopilot', '0003_alert_organization_smartbill_organization'),
    ]

    operations = [
        migrations.AddField(
            model_name='autopilotprofile',
            name='approval_required',
            field=models.BooleanField(
                default=True,
                help_text='If enabled, Autopilot will recommend payments and require human approval before executing.',
            ),
        ),
        migrations.AddField(
            model_name='autopilotprofile',
            name='max_autopay_amount',
            field=models.DecimalField(
                default=Decimal('25000.00'),
                max_digits=12,
                decimal_places=2,
                help_text='Autopilot will not recommend/execute bill payments above this amount.',
            ),
        ),
        migrations.AddField(
            model_name='autopilotprofile',
            name='max_retry_attempts',
            field=models.PositiveSmallIntegerField(default=2),
        ),
        migrations.CreateModel(
            name='ApprovalRequest',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('request_type', models.CharField(
                    max_length=30,
                    choices=[('BILL_PAYMENT', 'Bill Payment'), ('SAVINGS_TRANSFER', 'Savings Transfer'), ('OTHER', 'Other')],
                    default='OTHER',
                )),
                ('status', models.CharField(
                    max_length=20,
                    choices=[('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected'), ('EXPIRED', 'Expired')],
                    default='PENDING',
                    db_index=True,
                )),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('amount', models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))),
                ('why', models.TextField(blank=True, help_text='Explainability: why Autopilot is recommending this action')),
                ('rule_fired', models.CharField(max_length=120, blank=True)),
                ('metadata', models.JSONField(default=dict, blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('decided_at', models.DateTimeField(null=True, blank=True)),
                (
                    'bill',
                    models.ForeignKey(
                        to='finnova_autopilot.smartbill',
                        on_delete=django.db.models.deletion.SET_NULL,
                        null=True,
                        blank=True,
                        related_name='approval_requests',
                    ),
                ),
                (
                    'payment_intent',
                    models.ForeignKey(
                        to='payments_core.paymentintent',
                        on_delete=django.db.models.deletion.SET_NULL,
                        null=True,
                        blank=True,
                        related_name='approval_requests',
                    ),
                ),
                (
                    'organization',
                    models.ForeignKey(
                        to='finnovaapp.organization',
                        on_delete=django.db.models.deletion.SET_NULL,
                        null=True,
                        blank=True,
                        related_name='approval_requests',
                    ),
                ),
                (
                    'user',
                    models.ForeignKey(
                        to=settings.AUTH_USER_MODEL,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='approval_requests',
                    ),
                ),
                (
                    'decided_by',
                    models.ForeignKey(
                        to=settings.AUTH_USER_MODEL,
                        on_delete=django.db.models.deletion.SET_NULL,
                        null=True,
                        blank=True,
                        related_name='decided_approvals',
                    ),
                ),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='approvalrequest',
            index=models.Index(fields=['user', 'status', 'created_at'], name='appr_user_status_created'),
        ),
        migrations.AddConstraint(
            model_name='approvalrequest',
            constraint=models.UniqueConstraint(
                fields=('bill',),
                condition=Q(status='PENDING') & Q(bill__isnull=False),
                name='uniq_pending_approval_per_bill',
            ),
        ),
    ]
