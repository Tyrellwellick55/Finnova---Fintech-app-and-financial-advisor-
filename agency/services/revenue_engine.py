# agency/services/revenue_engine.py
"""
Revenue analytics engine for Agency mode.

Provides monthly revenue series, client revenue rankings, collection-rate
metrics, and growth analytics — all grounded in Invoice data.

Used by:
  - Agency Control Tower (revenue chart, KPI strip)
  - Analytics module (org-scoped insights)
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


class RevenueEngine:
    """Revenue analytics for an organization."""

    @classmethod
    def monthly_revenue_series(cls, org, months=12):
        """Month-by-month revenue data for the Control Tower chart."""
        from agency.models import Invoice

        series = {
            'labels': [],
            'collected': [],
            'invoiced': [],
            'growth': [],
        }
        now = timezone.now().date()
        prev_collected = None

        for i in range(months - 1, -1, -1):
            ref = now - timedelta(days=30 * i)
            month_start = ref.replace(day=1)
            if month_start.month == 12:
                next_month = month_start.replace(year=month_start.year + 1, month=1)
            else:
                next_month = month_start.replace(month=month_start.month + 1)
            month_end = next_month - timedelta(days=1)

            invoiced = Invoice.objects.filter(
                organization=org,
                issued_date__gte=month_start,
                issued_date__lte=month_end,
            ).exclude(
                status='CANCELLED'
            ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

            collected = Invoice.objects.filter(
                organization=org,
                status='PAID',
                paid_date__gte=month_start,
                paid_date__lte=month_end,
            ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

            growth = Decimal('0')
            if prev_collected and prev_collected > 0:
                growth = ((collected - prev_collected) / prev_collected) * 100

            series['labels'].append(month_start.strftime('%b'))
            series['collected'].append(float(collected))
            series['invoiced'].append(float(invoiced))
            series['growth'].append(float(growth))
            prev_collected = collected

        return series

    @classmethod
    def client_revenue_ranking(cls, org, limit=10):
        """Top clients by revenue collected."""
        from agency.models import Client

        return Client.objects.filter(
            organization=org,
            is_active=True,
        ).annotate(
            revenue=Sum(
                'invoices__amount',
                filter=Q(invoices__status='PAID'),
            ),
            invoice_count=Count('invoices'),
        ).exclude(
            revenue=None,
        ).order_by('-revenue')[:limit]

    @classmethod
    def collection_rate(cls, org, days=90):
        """Collection efficiency over a period — paid vs total invoiced."""
        from agency.models import Invoice

        cutoff = timezone.now().date() - timedelta(days=days)

        qs = Invoice.objects.filter(
            organization=org,
            issued_date__gte=cutoff,
        ).exclude(status='CANCELLED')

        total_invoiced = qs.aggregate(t=Sum('amount'))['t'] or Decimal('0')
        total_collected = qs.filter(
            status='PAID'
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

        rate = Decimal('0')
        if total_invoiced > 0:
            rate = (total_collected / total_invoiced) * 100

        return {
            'total_invoiced': float(total_invoiced),
            'total_collected': float(total_collected),
            'outstanding': float(total_invoiced - total_collected),
            'collection_rate': float(rate),
            'period_days': days,
        }

    @classmethod
    def get_kpi_summary(cls, org):
        """One-shot KPI summary for the Control Tower hero strip."""
        from agency.models import Client, Invoice, Project

        now = timezone.now().date()
        fy_start = now.replace(month=4, day=1) if now.month >= 4 else now.replace(
            year=now.year - 1, month=4, day=1
        )

        total_clients = Client.objects.filter(
            organization=org, is_active=True
        ).count()

        active_projects = Project.objects.filter(
            organization=org, status='ACTIVE'
        ).count()

        total_revenue_fy = Invoice.objects.filter(
            organization=org, status='PAID',
            paid_date__gte=fy_start,
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

        # Monthly recurring revenue (sum of active project retainers)
        mrr = Project.objects.filter(
            organization=org, status='ACTIVE',
        ).aggregate(t=Sum('monthly_retainer'))['t'] or Decimal('0')

        outstanding = Invoice.objects.filter(
            organization=org, status__in=['SENT', 'OVERDUE'],
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

        overdue = Invoice.objects.filter(
            organization=org, status='OVERDUE',
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

        overdue_count = Invoice.objects.filter(
            organization=org, status='OVERDUE',
        ).count()

        # Average project value
        avg_project_value = Decimal('0')
        if total_clients > 0:
            avg_project_value = total_revenue_fy / total_clients

        collection_data = cls.collection_rate(org, days=90)

        return {
            'total_clients': total_clients,
            'active_projects': active_projects,
            'total_revenue_fy': float(total_revenue_fy),
            'mrr': float(mrr),
            'outstanding': float(outstanding),
            'overdue': float(overdue),
            'overdue_count': overdue_count,
            'avg_project_value': float(avg_project_value),
            'collection_rate': collection_data['collection_rate'],
        }
