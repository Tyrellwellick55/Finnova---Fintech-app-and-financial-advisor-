from django.core.management.base import BaseCommand
from notifications.models import NotificationTemplate

DEFAULT_TEMPLATES = [
    {
        'template_id': 'PAYMENT_FAILED',
        'name': 'Payment Failed',
        'description': 'Sent when a payment transaction fails',
        'title_template': 'Payment Failed: Transaction {payment_id}',
        'message_template': 'Your payment of {amount} failed. Reason: {reason}',
        'action_hint_template': 'Review payment details and try again',
        'default_severity': 'HIGH',
        'default_category': 'PAYMENT',
        'requires_acknowledgment': True,
        'variables': ['payment_id', 'amount', 'reason']
    },
    {
        'template_id': 'PAYMENT_COMPLETED',
        'name': 'Payment Completed',
        'description': 'Sent when a payment transaction completes successfully',
        'title_template': 'Payment Completed: {amount} sent to {recipient}',
        'message_template': 'Your payment of {amount} to {recipient} has been completed successfully.',
        'action_hint_template': 'View transaction receipt',
        'default_severity': 'INFO',
        'default_category': 'PAYMENT',
        'requires_acknowledgment': False,
        'variables': ['payment_id', 'amount', 'recipient']
    },
    {
        'template_id': 'RISK_ALERT_HIGH',
        'name': 'High Risk Alert',
        'description': 'Sent for high-risk activities detected',
        'title_template': 'High Risk Activity Detected',
        'message_template': 'A high-risk activity has been detected in your account. Details: {details}',
        'action_hint_template': 'Review account activity immediately',
        'default_severity': 'CRITICAL',
        'default_category': 'RISK',
        'requires_acknowledgment': True,
        'variables': ['details', 'risk_score', 'activity_type']
    },
    {
        'template_id': 'AUDIT_SUSPICIOUS',
        'name': 'Suspicious Audit Activity',
        'description': 'Sent for suspicious audit trail activities',
        'title_template': 'Suspicious Audit Activity',
        'message_template': 'Unusual activity detected in audit logs from IP {ip_address}',
        'action_hint_template': 'Review security settings',
        'default_severity': 'HIGH',
        'default_category': 'AUDIT',
        'requires_acknowledgment': True,
        'variables': ['ip_address', 'user_agent', 'action_type']
    },
    {
        'template_id': 'AUTOPILOT_ACTION_REQUIRED',
        'name': 'AutoPilot Action Required',
        'description': 'Sent when AutoPilot requires user action',
        'title_template': 'AutoPilot: Action Required',
        'message_template': 'AutoPilot has detected a scenario requiring your attention: {scenario}',
        'action_hint_template': 'Review AutoPilot recommendations',
        'default_severity': 'MEDIUM',
        'default_category': 'AUTOPILOT',
        'requires_acknowledgment': True,
        'variables': ['scenario', 'confidence', 'recommended_action']
    },
    {
        'template_id': 'FINANCE_LARGE_TRANSACTION',
        'name': 'Large Transaction Alert',
        'description': 'Sent for large financial transactions',
        'title_template': 'Large Transaction: {amount}',
        'message_template': 'A large transaction of {amount} has been processed from your account.',
        'action_hint_template': 'Verify transaction details',
        'default_severity': 'MEDIUM',
        'default_category': 'FINANCE',
        'requires_acknowledgment': False,
        'variables': ['amount', 'transaction_id', 'counterparty']
    },
    {
        'template_id': 'FRAUD_DETECTED',
        'name': 'Fraud Detected',
        'description': 'Sent when potential fraud is detected',
        'title_template': 'URGENT: Potential Fraud Detected',
        'message_template': 'Our system has detected potential fraudulent activity: {activity_details}',
        'action_hint_template': 'Contact support immediately',
        'default_severity': 'CRITICAL',
        'default_category': 'FRAUD',
        'requires_acknowledgment': True,
        'variables': ['activity_details', 'risk_level', 'recommended_steps']
    },
    {
        'template_id': 'SYSTEM_HEALTH',
        'name': 'System Health Alert',
        'description': 'Sent for system health monitoring alerts',
        'title_template': 'System Alert: {component}',
        'message_template': 'System component {component} is experiencing issues: {issue_description}',
        'action_hint_template': 'Check system status page',
        'default_severity': 'HIGH',
        'default_category': 'SYSTEM',
        'requires_acknowledgment': False,
        'variables': ['component', 'issue_description', 'status']
    },
]

class Command(BaseCommand):
    help = 'Seed default notification templates'
    
    def handle(self, *args, **options):
        created = 0
        updated = 0
        
        for template_data in DEFAULT_TEMPLATES:
            template_id = template_data.pop('template_id')
            
            obj, created_flag = NotificationTemplate.objects.update_or_create(
                template_id=template_id,
                defaults=template_data
            )
            
            if created_flag:
                created += 1
                self.stdout.write(f"Created template: {template_id}")
            else:
                updated += 1
                self.stdout.write(f"Updated template: {template_id}")
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully seeded {created} created, {updated} updated notification templates'
            )
        )