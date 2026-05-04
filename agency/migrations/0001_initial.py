# Generated manually (Django not available in this execution environment)
from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('finnovaapp', '0003_organization_segment'),
    ]

    operations = [
        migrations.CreateModel(
            name='Client',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('name', models.CharField(max_length=160)),
                ('company_name', models.CharField(max_length=220, blank=True, null=True)),
                ('email', models.EmailField(max_length=254, blank=True, null=True)),
                ('phone', models.CharField(max_length=40, blank=True, null=True)),
                ('billing_address', models.TextField(blank=True, null=True)),
                ('gstin', models.CharField(max_length=20, blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('notes', models.TextField(blank=True, null=True)),
                ('metadata', models.JSONField(default=dict, blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='agency_clients', to='finnovaapp.organization')),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Project',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('name', models.CharField(max_length=180)),
                ('description', models.TextField(blank=True, null=True)),
                ('monthly_retainer', models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))),
                ('monthly_budget', models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))),
                ('start_date', models.DateField(blank=True, null=True)),
                ('end_date', models.DateField(blank=True, null=True)),
                ('status', models.CharField(max_length=20, choices=[('ACTIVE','Active'),('PAUSED','Paused'),('CLOSED','Closed')], default='ACTIVE')),
                ('metadata', models.JSONField(default=dict, blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='projects', to='agency.client')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='agency_projects', to='finnovaapp.organization')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Invoice',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('invoice_number', models.CharField(max_length=50)),
                ('title', models.CharField(max_length=200, blank=True, null=True)),
                ('amount', models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))),
                ('issued_date', models.DateField(default=django.utils.timezone.now)),
                ('due_date', models.DateField()),
                ('status', models.CharField(max_length=20, choices=[('DRAFT','Draft'),('SENT','Sent'),('PAID','Paid'),('OVERDUE','Overdue'),('CANCELLED','Cancelled')], default='DRAFT')),
                ('paid_date', models.DateField(blank=True, null=True)),
                ('payment_reference', models.CharField(max_length=120, blank=True, null=True)),
                ('notes', models.TextField(blank=True, null=True)),
                ('metadata', models.JSONField(default=dict, blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='invoices', to='agency.client')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_invoices', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='agency_invoices', to='finnovaapp.organization')),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='invoices', to='agency.project')),
            ],
            options={
                'ordering': ['-due_date', '-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='invoice',
            constraint=models.UniqueConstraint(fields=('organization', 'invoice_number'), name='uniq_invoice_number_per_org'),
        ),
        migrations.AddIndex(
            model_name='client',
            index=models.Index(fields=['organization', 'is_active', 'name'], name='agency_clie_organiza_6fda7b_idx'),
        ),
        migrations.AddIndex(
            model_name='project',
            index=models.Index(fields=['organization', 'status'], name='agency_proj_organiza_098e0c_idx'),
        ),
        migrations.AddIndex(
            model_name='project',
            index=models.Index(fields=['client', 'status'], name='agency_proj_client__693e7a_idx'),
        ),
        migrations.AddIndex(
            model_name='invoice',
            index=models.Index(fields=['organization', 'status', 'due_date'], name='agency_invo_organiza_086d22_idx'),
        ),
        migrations.AddIndex(
            model_name='invoice',
            index=models.Index(fields=['client', 'status', 'due_date'], name='agency_invo_client__a4d4f9_idx'),
        ),
    ]
