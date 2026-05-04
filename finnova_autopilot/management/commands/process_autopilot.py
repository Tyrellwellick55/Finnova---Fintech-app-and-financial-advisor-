# finnova_autopilot/management/commands/process_autopilot.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from finnova_autopilot.signals import process_due_bills

class Command(BaseCommand):
    help = 'Process all due bills via autopilot'
    
    def handle(self, *args, **options):
        self.stdout.write(f"Starting autopilot processing at {timezone.now()}")
        
        results = process_due_bills()
        
        self.stdout.write(
            self.style.SUCCESS(
                f"Queued: {results.get('queued', 0)}, "
                f"Blocked: {results['blocked']}, "
                f"Skipped: {results['skipped']}, "
                f"Failed: {results['failed']}"
            )
        )