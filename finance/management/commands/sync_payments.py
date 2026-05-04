from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from finance.services.finance_engine import FinanceEngine
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Sync financial data with payments_core module'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            help='Sync for specific user (email)'
        )
        parser.add_argument(
            '--days-back',
            type=int,
            default=30,
            help='Sync payments from last N days'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force sync even if already processed'
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
        
        total_synced = 0
        total_errors = 0
        
        for user in users:
            try:
                self.stdout.write(f"Syncing payments for {user.email}...")
                
                result = FinanceEngine.sync_with_payments_core(
                    user, 
                    options['days_back']
                )
                
                if result['success']:
                    if result['synced_count'] > 0:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Synced {result['synced_count']} payments for {user.email}"
                            )
                        )
                    else:
                        self.stdout.write(
                            f"No new payments to sync for {user.email}"
                        )
                    
                    if result['errors']:
                        for error in result['errors'][:3]:  # Show first 3 errors
                            self.stdout.write(
                                self.style.WARNING(f"Error: {error}")
                            )
                    
                    total_synced += result['synced_count']
                else:
                    self.stdout.write(
                        self.style.ERROR(f"Sync failed for {user.email}")
                    )
                    total_errors += 1
                
            except Exception as e:
                logger.error(f"Payment sync failed for {user.email}: {str(e)}")
                self.stdout.write(
                    self.style.ERROR(f"Error: {str(e)}")
                )
                total_errors += 1
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\nSync completed! Total synced: {total_synced}, Errors: {total_errors}"
            )
        )