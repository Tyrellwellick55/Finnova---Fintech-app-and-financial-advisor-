"""Management command: recover_missing_income

Finds every Invoice with status='PAID' and paid_date within the last 30 days,
checks if a matching Income record exists (by payment_reference), and if not,
calls post_income() to create it. Idempotent — safe to run multiple times.

Usage:
    python manage.py recover_missing_income
    python manage.py recover_missing_income --days 7
    python manage.py recover_missing_income --dry-run
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Recover missing Income records for PAID invoices. '
        'Checks the last 30 days by default. Idempotent.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='How many days back to scan (default: 30)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Print what would be created without actually creating anything.',
        )

    def handle(self, *args, **options):
        from agency.models import Invoice
        from finance.models import Income
        from finance.services.posting import post_income

        days = options['days']
        dry_run = options['dry_run']
        since = date.today() - timedelta(days=days)

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f'🔍  Scanning PAID invoices from the last {days} days '
                f'(since {since}){"  [DRY RUN]" if dry_run else ""}…'
            )
        )

        # Fetch all PAID invoices in the window that have a payment_reference
        invoices = (
            Invoice.objects.filter(
                status=Invoice.STATUS_PAID,
                paid_date__gte=since,
            )
            .select_related('client', 'organization', 'created_by')
            .order_by('paid_date')
        )

        total = invoices.count()
        self.stdout.write(f'   Found {total} PAID invoice(s) in window.')

        recovered = 0
        skipped_no_ref = 0
        skipped_exists = 0
        errors = 0

        for inv in invoices:
            ref = inv.payment_reference or f'INV-{inv.invoice_number}'

            # Resolve owner: prefer created_by, fall back to org members
            owner = inv.created_by
            if owner is None:
                try:
                    from finnovaapp.models import OrganizationMember
                    membership = (
                        OrganizationMember.objects.filter(
                            organization=inv.organization,
                            role__in=['OWNER', 'FINANCE'],
                        )
                        .select_related('user')
                        .first()
                    )
                    owner = membership.user if membership else None
                except Exception:
                    pass

            if owner is None:
                self.stdout.write(
                    self.style.WARNING(
                        f'   ⚠  Invoice {inv.invoice_number}: no owner found — skipping.'
                    )
                )
                skipped_no_ref += 1
                continue

            # Idempotency: check if Income already exists for this reference
            existing = Income.objects.filter(
                organization=inv.organization,
                user=owner,
                payment_reference=ref,
            ).first()

            if existing:
                skipped_exists += 1
                self.stdout.write(
                    f'   ✓  Invoice {inv.invoice_number}: Income already exists '
                    f'(id={existing.id}).'
                )
                continue

            # No matching income — recover it
            self.stdout.write(
                f'   →  Invoice {inv.invoice_number} ({inv.client.name}): '
                f'₹{inv.amount:,.2f} — creating Income record…'
            )

            if not dry_run:
                try:
                    with transaction.atomic():
                        income = post_income(
                            organization=inv.organization,
                            user=owner,
                            amount=inv.amount,
                            source=inv.client.name,
                            category='CLIENT_PAYMENT',
                            memo=f'Recovered from Invoice #{inv.invoice_number}',
                            description=inv.title or f'Invoice {inv.invoice_number}',
                            payment_reference=ref,
                        )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'      ✅ Created Income id={income.id}'
                        )
                    )
                    recovered += 1
                except Exception as exc:
                    logger.exception(
                        'recover_missing_income: failed for invoice %s', inv.id
                    )
                    self.stdout.write(
                        self.style.ERROR(
                            f'      ❌ Error: {exc}'
                        )
                    )
                    errors += 1
            else:
                self.stdout.write(
                    self.style.WARNING('      [DRY RUN] Would create Income record.')
                )
                recovered += 1

        # Summary
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('─' * 60))
        self.stdout.write(self.style.SUCCESS('Recovery complete:'))
        self.stdout.write(f'  Total invoices scanned : {total}')
        self.stdout.write(f'  Already had Income     : {skipped_exists}')
        self.stdout.write(f'  No owner found         : {skipped_no_ref}')
        self.stdout.write(
            f'  Recovered{"  (dry-run)" if dry_run else ""}          : {recovered}'
        )
        if errors:
            self.stdout.write(self.style.ERROR(f'  Errors                 : {errors}'))
        self.stdout.write(self.style.SUCCESS('─' * 60))
