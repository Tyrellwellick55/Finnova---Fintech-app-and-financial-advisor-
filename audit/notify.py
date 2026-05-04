from django.urls import reverse

from notifications.services import NotificationService


def notify_suspicious_activity(audit_log):
    """Create a user-facing notification for suspicious audit events."""
    NotificationService.create_notification(
        user=getattr(audit_log, 'actor', None),
        source='audit.trail',
        event_type='AUDIT',
        severity='HIGH',
        title='Suspicious Activity Detected',
        message=f"Suspicious activity detected: {audit_log.action} from IP {audit_log.actor_ip or 'Unknown'}",
        action_hint='Review your recent account activity.',
        related_app='audit',
        related_model='AuditLog',
        related_id=str(audit_log.id),
        action_url=reverse('audit:log_detail', args=[audit_log.id]),
    )


def notify_compliance_alert(user, compliance_issue):
    """Notify about compliance issues."""
    NotificationService.create_notification(
        user=user,
        source='audit.compliance',
        event_type='COMPLIANCE',
        severity='CRITICAL',
        title='Compliance Alert',
        message=f'Compliance issue detected: {compliance_issue.description}',
        related_app='audit',
        related_model='ComplianceIssue',
        related_id=str(compliance_issue.id),
        requires_acknowledgment=True,
        action_hint='Review compliance requirements',
        action_url=reverse('audit:compliance'),
    )


def notify_audit_report(user, report):
    """Send audit report notification."""
    NotificationService.create_notification(
        user=user,
        source='audit.reporting',
        event_type='AUDIT',
        severity='INFO',
        title=f'Audit Report Generated: {getattr(report, "title", getattr(report, "name", "Report"))}',
        message='A new audit report is ready for review.',
        related_app='audit',
        related_model='AuditReport',
        related_id=str(report.id),
        action_hint='Open reports',
        action_url=reverse('audit:reports'),
    )
