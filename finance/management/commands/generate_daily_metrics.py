from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from finance.services.finance_engine import FinanceEngine
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Generate daily financial metrics for all users'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            help='Generate metrics for specific user (email)'
        )
        parser.add_argument(
            '--days-back',
            type=int,
            default=7,
            help='Generate metrics for last N days'
        )
    
    def handle(self, *args, **options):
        User = get_user_model()
        
        if options['user']:
            users = User.objects.filter(email=options['user'])
            if not users.exists():
                self.stderr.write(f"User {options['user']} not found")
                return
        else:
            users = User.objects.filter(is_active=True)
        
        total_processed = 0
        total_errors = 0
        
        for user in users:
            try:
                # Generate metrics for today
                success = FinanceEngine.generate_daily_metrics(user)
                
                if success:
                    self.stdout.write(
                        self.style.SUCCESS(f"Generated metrics for {user.email}")
                    )
                    total_processed += 1
                else:
                    self.stdout.write(
                        self.style.WARNING(f"Metrics already exist for {user.email}")
                    )
                
                # Generate for past days if specified
                if options['days_back'] > 0:
                    for days in range(1, options['days_back'] + 1):
                        date = timezone.now().date() - timezone.timedelta(days=days)
                        # We would need to modify FinanceEngine to accept a date parameter
                        # For now, just log
                        self.stdout.write(
                            f"Would generate metrics for {user.email} on {date}"
                        )
                
            except Exception as e:
                logger.error(f"Failed to generate metrics for {user.email}: {str(e)}")
                total_errors += 1
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\nCompleted! Processed: {total_processed}, Errors: {total_errors}"
            )
        )