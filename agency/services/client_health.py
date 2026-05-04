# agency/services/client_health.py
"""
Client health scoring for Agency mode.

Scores each client 0–100 based on payment behavior, revenue contribution,
project activity, and overdue status. Used for the client list health badge
and the Control Tower client pipeline.
"""

import logging
from decimal import Decimal

from django.db.models import F, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


class ClientHealthScorer:
    """Score clients 0–100 based on payment behavior and activity."""

    @classmethod
    def score(cls, client):
        """Return an integer health score (0–100) for a single client."""
        score = 50  # baseline

        try:
            # 1. Payment timeliness (+/- 20 pts)
            total_invoices = client.invoices.exclude(status='CANCELLED').count()
            if total_invoices > 0:
                on_time = client.invoices.filter(
                    status='PAID',
                    paid_date__lte=F('due_date'),
                ).count()
                payment_ratio = on_time / total_invoices
                score += int((payment_ratio - 0.5) * 40)  # -20 to +20

            # 2. Revenue contribution (+/- 15 pts)
            from agency.models import Invoice
            org_total = Invoice.objects.filter(
                organization_id=client.organization_id,
                status='PAID',
            ).aggregate(t=Sum('amount'))['t'] or Decimal('1')

            client_paid = client.total_paid
            if org_total > 0:
                client_share = client_paid / org_total
                if client_share > Decimal('0.20'):
                    score += 15  # Top client
                elif client_share > Decimal('0.10'):
                    score += 10
                elif client_share > Decimal('0.05'):
                    score += 5

            # 3. Active projects (+15 pts)
            active_count = client.active_projects_count
            if active_count > 0:
                score += min(active_count * 5, 15)

            # 4. Overdue invoices (-10 pts) or clean record (+10 pts)
            if client.outstanding_amount > 0:
                overdue_count = client.invoices.filter(status='OVERDUE').count()
                score -= min(overdue_count * 5, 15)
            else:
                score += 10

            # 5. Recency bonus — paid something in last 30 days (+5)
            thirty_days_ago = timezone.now().date() - timezone.timedelta(days=30)
            recent_payment = client.invoices.filter(
                status='PAID',
                paid_date__gte=thirty_days_ago,
            ).exists()
            if recent_payment:
                score += 5

        except Exception:
            logger.exception("ClientHealthScorer: error scoring client %s", client.id)

        return max(0, min(100, score))

    @classmethod
    def score_label(cls, score_value):
        """Return a human-readable label and CSS class for a score."""
        if score_value >= 80:
            return 'Excellent', 'green'
        elif score_value >= 60:
            return 'Good', 'brand'
        elif score_value >= 40:
            return 'Fair', 'yellow'
        else:
            return 'At Risk', 'red'

    @classmethod
    def score_all(cls, org):
        """Score all active clients for an organization. Returns list of dicts."""
        from agency.models import Client

        clients = Client.objects.filter(
            organization=org,
            is_active=True,
        ).prefetch_related('invoices', 'projects')

        results = []
        for client in clients:
            s = cls.score(client)
            label, css = cls.score_label(s)
            results.append({
                'client': client,
                'score': s,
                'label': label,
                'css_class': css,
            })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results
