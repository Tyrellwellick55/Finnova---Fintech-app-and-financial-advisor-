from django.core.management.base import BaseCommand
from django.utils import timezone
from finance.models import (
    Expense, Income, FinancialMetric,
    FinancialReport
)
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Cleanup old financial data to manage database size'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--months',
            type=int,
            default=36,
            help='Keep data from last N months (default: 36)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )
        parser.add_argument(
            '--model',
            choices=['expense', 'income', 'metric', 'report', 'all'],
            default='all',
            help='Specific model to clean up'
        )
    
    def handle(self, *args, **options):
        cutoff_date = timezone.now() - timezone.timedelta(days=options['months'] * 30)
        
        self.stdout.write(
            f"Cleaning up data older than {cutoff_date.date()} "
            f"(last {options['months']} months)"
        )
        
        if options['dry_run']:
            self.stdout.write(self.style.WARNING("DRY RUN - No data will be deleted"))
        
        models_to_clean = []
        
        if options['model'] in ['expense', 'all']:
            models_to_clean.append(('Expenses', Expense.objects.filter(date__lt=cutoff_date)))
        
        if options['model'] in ['income', 'all']:
            models_to_clean.append(('Income', Income.objects.filter(date__lt=cutoff_date)))
        
        if options['model'] in ['metric', 'all']:
            models_to_clean.append(('Metrics', FinancialMetric.objects.filter(date__lt=cutoff_date)))
        
        if options['model'] in ['report', 'all']:
            # Keep reports for 2 years longer
            report_cutoff = cutoff_date - timezone.timedelta(days=730)
            models_to_clean.append(('Reports', FinancialReport.objects.filter(created_at__lt=report_cutoff)))
        
        total_deleted = 0
        
        for model_name, queryset in models_to_clean:
            count = queryset.count()
            
            if count > 0:
                self.stdout.write(f"{model_name}: {count} records to delete")
                
                if not options['dry_run']:
                    deleted, _ = queryset.delete()
                    self.stdout.write(
                        self.style.SUCCESS(f"Deleted {deleted} {model_name} records")
                    )
                    total_deleted += deleted
            else:
                self.stdout.write(f"{model_name}: No records to delete")
        
        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDRY RUN COMPLETE: Would delete {total_deleted} records"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nCleanup completed! Deleted {total_deleted} records"
                )
            )