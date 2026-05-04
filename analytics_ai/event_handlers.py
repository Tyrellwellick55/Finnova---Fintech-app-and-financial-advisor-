"""Analytics handlers wired into the EventHub backbone."""

import logging

from eventhub.dispatcher import subscribe

logger = logging.getLogger(__name__)


def _refresh_health(ev):
    try:
        meta = ev.metadata or {}
        user = ev.actor
        if not user:
            return

        from analytics_ai.services import FinancialAnalyticsService
        service = FinancialAnalyticsService(user)
        service.calculate_financial_health()
    except Exception:
        logger.exception('Analytics refresh failed')


subscribe('PAYMENT_SUCCEEDED', _refresh_health)
subscribe('PAYMENT_FAILED', _refresh_health)
