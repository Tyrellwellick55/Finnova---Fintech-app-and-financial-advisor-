from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from audit.models import AuditLog, SecurityAlert
from audit.services import AuditService
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Cleanup old audit logs and archive them'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='Delete logs older than N days (default: 90)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )
        parser.add_argument(
            '--archive-only',
            action='store_true',
            help='Only archive, do not delete'
        )
    
    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        archive_only = options['archive_only']
        
        self.stdout.write(f"Starting audit log cleanup (days: {days}, dry-run: {dry_run})")
        
        # Get retention days from settings if available
        retention_days = getattr(settings, 'AUDIT_RETENTION_DAYS', days)
        
        # Cleanup audit logs
        deleted_logs = AuditService.cleanup_old_logs(retention_days)
        
        # Also cleanup old security alerts (keep for 180 days)
        cutoff_date = timezone.now() - timezone.timedelta(days=180)
        old_alerts = SecurityAlert.objects.filter(
            resolved_at__lt=cutoff_date,
            status='RESOLVED'
        )
        
        alert_count = old_alerts.count()
        
        if not dry_run and not archive_only:
            deleted_alerts, _ = old_alerts.delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_alerts} old security alerts"))
        else:
            self.stdout.write(f"Would delete {alert_count} old security alerts")
        
        # Archive statistics
        self.stdout.write(self.style.SUCCESS(
            f"\nCleanup completed:\n"
            f"- Deleted {deleted_logs} audit logs older than {retention_days} days\n"
            f"- Would delete {alert_count} old security alerts\n"
            f"- Current audit logs: {AuditLog.objects.count()}\n"
            f"- Current security alerts: {SecurityAlert.objects.count()}"
        ))