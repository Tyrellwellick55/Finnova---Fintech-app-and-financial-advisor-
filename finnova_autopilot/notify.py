"""
AutoPilot notification handlers
"""
from notifications.services import NotificationService

def notify_autopilot_event(user, event_type, description, confidence=0.0):
    """
    Notify about AutoPilot events
    """
    severity = 'CRITICAL' if confidence > 0.9 else 'HIGH' if confidence > 0.7 else 'MEDIUM'
    
    NotificationService.create_notification(
        user=user,
        source='finnovaautopilot.system',
        event_type='AUTOPILOT',
        severity=severity,
        title=f'AutoPilot: {event_type}',
        message=description,
        related_app='finnovaautopilot',
        related_model='AutoPilotEvent',
        action_hint='Review AutoPilot recommendations',
        action_url='/autopilot/',
        metadata={
            'confidence': confidence,
            'event_type': event_type
        }
    )

def notify_trade_executed(user, trade_details):
    """
    Notify when AutoPilot executes a trade
    """
    NotificationService.create_notification(
        user=user,
        source='finnovaautopilot.trading',
        event_type='AUTOPILOT',
        severity='HIGH',
        title=f'Trade Executed: {trade_details.get("symbol")}',
        message=f'AutoPilot executed a trade for {trade_details.get("quantity")} '
                f'shares of {trade_details.get("symbol")} at ${trade_details.get("price")}',
        related_app='finnovaautopilot',
        related_model='Trade',
        related_id=trade_details.get('trade_id'),
        requires_acknowledgment=True,
        metadata=trade_details
    )