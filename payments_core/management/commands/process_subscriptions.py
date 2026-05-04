# payments_core/management/commands/process_subscriptions.py
from django.core.management.base import BaseCommand
from django.utils import timezone
import logging
from payments_core.subscription_engine import process_due_subscriptions

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Process due subscriptions'

    def handle(self, *args, **options):
        self.stdout.write('Starting subscription processing...')
        
        try:
            result = process_due_subscriptions()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully processed {result["processed"]} subscriptions. '
                    f'Failed: {result["failed"]}'
                )
            )
            
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Error processing subscriptions: {str(e)}'))
            logger.error(f'Error in subscription processing command: {str(e)}')