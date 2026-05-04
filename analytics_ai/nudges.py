from decimal import Decimal

from finnova_autopilot.services import create_event_notification
from payments_core.models import PaymentAccount


def _get_primary_wallet(user):
    """
    Helper to fetch the user's primary wallet‑style payment account.
    Falls back gracefully if none exists.
    """
    return (
        PaymentAccount.objects.filter(user=user, is_active=True)
        .order_by('-is_primary', '-created_at')
        .first()
    )


# smart nudge engine
def generate_financial_nudges(user):
    """
    Generate intelligent nudges based on the
    user's real‑time wallet behaviour.
    """

    wallet = _get_primary_wallet(user)
    if not wallet:
        return

    # Low balance warning
    if wallet.balance < Decimal("1000"):
        create_event_notification(
            user=user,
            source="AI",
            event_type="NUDGE",
            severity="MEDIUM",
            title="Low Balance Alert",
            message="Your wallet balance is running low.",
            action_hint="Consider reducing expenses or adding funds.",
        )

    # High‑risk / frozen warning
    if wallet.wallet_status == "FROZEN":
        create_event_notification(
            user=user,
            source="AI",
            event_type="RISK",
            severity="CRITICAL",
            title="Wallet Frozen",
            message="Your wallet is frozen due to financial risk.",
            action_hint="Contact support or review your recent activity.",
        )
