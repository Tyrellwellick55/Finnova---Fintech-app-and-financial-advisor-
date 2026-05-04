"""seed_demo management command — Phase 6

Creates the full VC-presentation demo dataset for Priya Sharma.
Idempotent: safe to run multiple times.
--reset: wipes Priya's records and rebuilds from scratch.

Usage:
    python manage.py seed_demo
    python manage.py seed_demo --reset
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone


DEMO_EMAIL    = "priya@finnovadesigns.in"
DEMO_PASSWORD = "Demo1234!"
DEMO_FIRST    = "Priya"
DEMO_LAST     = "Sharma"
ORG_NAME      = "Priya Design Studio"

CLIENTS = ["Techwave Pvt Ltd", "StartupCo India", "RetailX Solutions"]

# Monthly income targets — 6 months of realistic agency revenue
MONTHLY_INCOMES = [
    {"month_offset": 5, "amounts": [80000, 22000]},   # 6 months ago
    {"month_offset": 4, "amounts": [95000, 18000]},   # 5 months ago
    {"month_offset": 3, "amounts": [105000, 28000]},  # 4 months ago
    {"month_offset": 2, "amounts": [112000, 32000]},  # 3 months ago
    {"month_offset": 1, "amounts": [125000, 18600]},  # 2 months ago
    {"month_offset": 0, "amounts": [141600]},          # this month — matches invoice
]

MONTHLY_EXPENSES = [
    ("Rent",        25000, "RENT"),
    ("Software",     8500, "SOFTWARE"),
    ("Contractor",  15000, "SALARY"),
    ("Miscellaneous", 10000, "OTHER"),  # Blueprint: misc ₹10k
]

# ── helpers ──────────────────────────────────────────────────────────────────

def _month_start(offset: int) -> date:
    today = date.today()
    month = today.month - offset
    year  = today.year
    while month < 1:
        month += 12
        year  -= 1
    return date(year, month, 1)


def _mid_month(offset: int) -> date:
    start = _month_start(offset)
    return start.replace(day=15)


class Command(BaseCommand):
    help = "Seed VC-ready demo data for priya@finnovadesigns.in"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true", default=False,
            help="Delete all of Priya's records and recreate from scratch.",
        )

    def _out(self, msg):
        self.stdout.write(msg)

    def _ok(self, msg):
        self.stdout.write(self.style.SUCCESS(f"  ✅  {msg}"))

    def _warn(self, msg):
        self.stdout.write(self.style.WARNING(f"  ⚠   {msg}"))

    # ── entry point ──────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        User = get_user_model()

        if options["reset"]:
            self._out(self.style.MIGRATE_HEADING("🗑   --reset: removing Priya's existing records…"))
            try:
                u = User.objects.get(email=DEMO_EMAIL)
                self._reset_user_data(u)
            except User.DoesNotExist:
                self._warn("User not found — nothing to reset.")

        self._out(self.style.MIGRATE_HEADING("🌱  seed_demo: building demo dataset…"))
        self._create_all()
        self._out(self.style.SUCCESS("🎉  seed_demo complete.  Login: priya@finnovadesigns.in / Demo1234!"))

    # ── reset ────────────────────────────────────────────────────────────────

    def _reset_user_data(self, user):
        from finnovaapp.models import Organization, OrganizationMembership

        # Delete org + cascade
        Organization.objects.filter(name=ORG_NAME).delete()
        self._ok("Deleted org and cascaded records.")

        # Delete user-scoped finance records
        for model_path in [
            ("finance.models", "Income"),
            ("finance.models", "Expense"),
            ("finnova_autopilot.models", "SavingsGoal"),
            ("finnova_autopilot.models", "SmartBill"),
            ("finnova_autopilot.models", "AutopilotProfile"),
            ("finnova_autopilot.models", "FinancialHealthScore"),
            ("finnova_autopilot.models", "ApprovalRequest"),
            ("analytics_ai.models", "FinancialInsight"),
        ]:
            try:
                import importlib
                mod = importlib.import_module(model_path[0])
                cls = getattr(mod, model_path[1])
                deleted, _ = cls.objects.filter(user=user).delete()
                self._ok(f"Deleted {deleted} {model_path[1]} records.")
            except Exception as exc:
                self._warn(f"Could not delete {model_path[1]}: {exc}")

    # ── main create ──────────────────────────────────────────────────────────

    def _create_all(self):
        user = self._create_user()
        org  = self._create_org(user)
        clients = self._create_clients(org)
        account = self._create_finance_account(user, org)
        self._create_income_records(user, org, account, clients)
        self._create_expense_records(user, org, account)
        self._create_savings_goals(user, org)
        self._create_smart_bills(user, org)
        invoice, income = self._create_techwave_invoice_and_income(user, org, clients[0], account)
        approval = self._create_income_split_approval(user, org, income)
        self._create_financial_insights(user, org)
        self._create_health_score(user, org)
        self._create_autopilot_profile(user, org)
        self._create_audit_trail(user, org, invoice, income, approval)

    # ── step functions ───────────────────────────────────────────────────────

    def _create_user(self):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            email=DEMO_EMAIL,
            defaults={
                "username": "priya_sharma",
                "first_name": DEMO_FIRST,
                "last_name": DEMO_LAST,
                "is_active": True,
            },
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
            self._ok(f"Created user {DEMO_EMAIL}")
        else:
            # Always reset password on re-run
            user.set_password(DEMO_PASSWORD)
            user.save()
            self._ok(f"User already exists — password reset.")

        # Set profile metadata
        try:
            from finnovaapp.models import UserProfile
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.metadata = {
                "business_type": "agency",
                "gst_registered": "yes",
                "gstin": "29AAAAA0000A1Z5",
                "income_pattern": "project",
                "savings_target_pct": 20,
            }
            profile.save()
            self._ok("Profile metadata set (GST registered, agency, 20% savings target).")
        except Exception as exc:
            self._warn(f"Profile metadata: {exc}")

        return user

    def _create_org(self, user):
        from finnovaapp.models import Organization, OrganizationMembership
        org, created = Organization.objects.get_or_create(
            name=ORG_NAME,
            defaults={
                "industry": "Agency / Services",
                "gstin": "29AAAAA0000A1Z5",
                "is_active": True,
                "metadata": {"segment": "freelance_agency"},
            },
        )
        if created:
            self._ok(f"Created org: {ORG_NAME}")
        OrganizationMembership.objects.get_or_create(
            organization=org, user=user,
            defaults={"role": "OWNER", "is_active": True},
        )
        return org

    def _create_clients(self, org):
        try:
            from agency.models import Client
        except ImportError:
            self._warn("agency app not available — skipping clients.")
            return [None, None, None]

        result = []
        for name in CLIENTS:
            c, created = Client.objects.get_or_create(
                organization=org, name=name,
                defaults={
                    "email": f"billing@{name.split()[0].lower()}.in",
                    "is_active": True,
                },
            )
            result.append(c)
            if created:
                self._ok(f"Created client: {name}")
        return result

    def _create_finance_account(self, user, org):
        try:
            from finance.models import Account
        except ImportError:
            self._warn("finance.Account not available.")
            return None

        acct, created = Account.objects.get_or_create(
            user=user, organization=org, name="Primary Wallet",
            defaults={
                "account_type": "WALLET",
                "opening_balance": Decimal("0.00"),
                "current_balance": Decimal("141600.00"),
                "currency": "INR",
                "is_primary": True,
                "is_active": True,
                "include_in_total": True,
            },
        )
        if created:
            self._ok("Created primary finance account.")
        return acct

    def _create_income_records(self, user, org, account, clients):
        try:
            from finance.models import Income
        except ImportError:
            self._warn("finance.Income not available.")
            return

        client_names = [c.name if c else "Client" for c in clients]
        sources = client_names + ["Consulting Fee", "Retainer"]

        for month_data in MONTHLY_INCOMES[:-1]:  # all months except current (handled separately)
            offset = month_data["month_offset"]
            amounts = month_data["amounts"]
            for i, amount in enumerate(amounts):
                pay_day = _mid_month(offset).replace(day=min(10 + i * 7, 28))
                source = sources[i % len(sources)]
                ref = f"DEMO-INC-{offset}-{i}"
                if not Income.objects.filter(user=user, payment_reference=ref).exists():
                    Income.objects.create(
                        user=user, organization=org, account=account,
                        amount=Decimal(str(amount)),
                        source=source,
                        category="BUSINESS",
                        date=pay_day,
                        description=f"Project payment — {source}",
                        payment_reference=ref,
                        is_verified=True,
                    )
        self._ok("Created 6 months of income records (₹80k–₹1.4L/month).")

    def _create_expense_records(self, user, org, account):
        try:
            from finance.models import Expense
        except ImportError:
            self._warn("finance.Expense not available.")
            return

        for offset in range(6):
            for desc, amount, category in MONTHLY_EXPENSES:
                pay_day = _month_start(offset).replace(day=5)
                ref = f"DEMO-EXP-{offset}-{desc[:4].upper()}"
                if not Expense.objects.filter(user=user, payment_reference=ref).exists():
                    Expense.objects.create(
                        user=user, organization=org, account=account,
                        amount=Decimal(str(amount)),
                        description=desc,
                        category=category,
                        date=pay_day,
                        payment_reference=ref,
                    )
        self._ok("Created 6 months of expense records (rent, software, contractor, misc).")

    def _create_savings_goals(self, user, org):
        try:
            from finnova_autopilot.models import SavingsGoal
        except ImportError:
            self._warn("SavingsGoal not available.")
            return

        goals = [
            {
                "goal_name": "Emergency Fund",
                "target_amount": Decimal("300000"),
                "current_saved": Decimal("135000"),
                "status": "ACTIVE",
                "is_auto_save": True,
                "priority": 1,
                "metadata": {"auto_contribute_pct": 20},
            },
            {
                "goal_name": "Equipment Upgrade",
                "target_amount": Decimal("80000"),
                "current_saved": Decimal("17600"),
                "status": "ACTIVE",
                "is_auto_save": True,
                "priority": 2,
                "metadata": {"auto_contribute_pct": 10},
            },
        ]
        for g in goals:
            _, created = SavingsGoal.objects.get_or_create(
                user=user, goal_name=g["goal_name"],
                defaults={k: v for k, v in g.items() if k != "goal_name"},
            )
            if created:
                self._ok(f"Created SavingsGoal: {g['goal_name']}")

    def _create_smart_bills(self, user, org):
        try:
            from finnova_autopilot.models import SmartBill
        except ImportError:
            self._warn("SmartBill not available.")
            return

        today = date.today()
        bills = [
            {"biller_name": "Adobe Creative Cloud", "biller_category": "SOFTWARE", "amount": Decimal("4999"), "due_date": today + timedelta(days=8)},
            {"biller_name": "Figma Team",            "biller_category": "SOFTWARE", "amount": Decimal("3200"), "due_date": today + timedelta(days=14)},
            {"biller_name": "Server Hosting",        "biller_category": "UTILITIES","amount": Decimal("1800"), "due_date": today + timedelta(days=22)},
        ]
        for b in bills:
            _, created = SmartBill.objects.get_or_create(
                user=user, biller_name=b["biller_name"],
                defaults={
                    **{k: v for k, v in b.items() if k != "biller_name"},
                    "organization": org,
                    "status": "PENDING",
                    "is_recurring": True,
                    "recurrence_pattern": "MONTHLY",
                },
            )
            if created:
                self._ok(f"Created SmartBill: {b['biller_name']} ₹{b['amount']}")

    def _create_techwave_invoice_and_income(self, user, org, techwave_client, account):
        invoice = income = None
        today = date.today()

        # Invoice
        try:
            from agency.models import Invoice
            if techwave_client:
                invoice, created = Invoice.objects.get_or_create(
                    organization=org,
                    invoice_number="INV-2024-001",
                    defaults={
                        "client": techwave_client,
                        "title": "Q4 Design & Strategy Retainer",
                        "amount": Decimal("141600"),
                        "issued_date": today - timedelta(days=10),
                        "due_date": today - timedelta(days=3),
                        "status": "PAID",
                        "paid_date": today,
                        "payment_reference": "TWPAY-141600",
                        "created_by": user,
                    },
                )
                if created:
                    self._ok("Created Techwave invoice INV-2024-001 ₹1,41,600 (PAID).")
        except Exception as exc:
            self._warn(f"Invoice creation: {exc}")

        # Matching Income record
        try:
            from finance.models import Income
            income, created = Income.objects.get_or_create(
                user=user,
                payment_reference="TWPAY-141600",
                defaults={
                    "organization": org,
                    "account": account,
                    "amount": Decimal("141600"),
                    "source": "Techwave Pvt Ltd",
                    "category": "CLIENT_PAYMENT",
                    "date": today,
                    "description": "Q4 Design & Strategy Retainer — INV-2024-001",
                    "is_verified": True,
                    "metadata": {"invoice_number": "INV-2024-001", "client": "Techwave Pvt Ltd"},
                },
            )
            if created:
                self._ok("Created matching Income record for Techwave invoice.")
        except Exception as exc:
            self._warn(f"Income for invoice: {exc}")

        return invoice, income

    def _create_income_split_approval(self, user, org, income):
        try:
            from finnova_autopilot.models import ApprovalRequest, SavingsGoal
        except ImportError:
            self._warn("ApprovalRequest not available.")
            return None

        gross = Decimal("141600")
        gst   = (gross * Decimal("18") / Decimal("118")).quantize(Decimal("0.01"))
        net   = gross - gst
        tax   = (net * Decimal("0.08")).quantize(Decimal("0.01"))
        after = net - tax

        goals = list(SavingsGoal.objects.filter(user=user, is_auto_save=True, status="ACTIVE"))
        savings_allocs = []
        remaining = after
        for goal in goals:
            pct = Decimal(str((goal.metadata or {}).get("auto_contribute_pct", 20)))
            gap = goal.target_amount - goal.current_saved
            if gap <= 0 or remaining <= 0:
                continue
            contrib = min(remaining * pct / 100, gap, remaining).quantize(Decimal("0.01"))
            if contrib > 0:
                savings_allocs.append({
                    "goal_id": str(goal.id),
                    "name": goal.goal_name,
                    "pct": float(pct),
                    "amount": str(contrib),
                    "target": str(goal.target_amount),
                    "progress_pct": round(float(goal.current_saved / goal.target_amount * 100), 1),
                })
                remaining -= contrib

        bills_reserved = Decimal("4999") + Decimal("3200") + Decimal("1800")
        spendable = max(remaining - bills_reserved, Decimal("0"))

        split_meta = {
            "gross_amount": str(gross),
            "gst_amount":   str(gst),
            "gst_pct":      "18",
            "tax_amount":   str(tax),
            "tax_pct":      "8",
            "savings_allocations": savings_allocs,
            "bills_reserved": str(bills_reserved),
            "bills_count":    3,
            "upcoming_bills": [
                {"biller_name": "Adobe Creative Cloud", "amount": 4999},
                {"biller_name": "Figma Team",           "amount": 3200},
                {"biller_name": "Server Hosting",       "amount": 1800},
            ],
            "spendable":     str(spendable),
            "spendable_pct": str(round(float(spendable / gross * 100), 1)),
            "source_label":  "Techwave Pvt Ltd",
            "income_id":     str(income.id) if income else "",
        }

        approval, created = ApprovalRequest.objects.get_or_create(
            user=user,
            request_type="INCOME_SPLIT",
            status="PENDING",
            defaults={
                "organization": org,
                "title": "Income split — ₹1,41,600 from Techwave Pvt Ltd",
                "description": "Autopilot has prepared a split plan for your latest income. Review and approve to allocate GST reserve, advance tax, savings, and spendable.",
                "amount": gross,
                "metadata": split_meta,
            },
        )
        if created:
            self._ok("Created pending INCOME_SPLIT ApprovalRequest with full split plan.")
        return approval

    def _create_financial_insights(self, user, org):
        try:
            from analytics_ai.models import FinancialInsight
        except ImportError:
            self._warn("FinancialInsight not available.")
            return

        insights = [
            {
                "insight_type": "RISK",
                "title": "Client concentration risk detected",
                "description": "Techwave Pvt Ltd accounts for over 60% of revenue this month. A single client dependency increases business risk — consider diversifying your client portfolio.",
                "severity": "MEDIUM",
                "related_percentage": Decimal("62.5"),
                "action_required": True,
            },
            {
                "insight_type": "SAVINGS",
                "title": "Strong savings rate this month",
                "description": "Your savings rate hit 21.3% this month — above your 20% target. Emergency Fund is 45% complete. At this rate, you'll reach your target in ~7 months.",
                "severity": "INFO",
                "related_percentage": Decimal("21.3"),
                "action_required": False,
            },
            {
                "insight_type": "CASHFLOW",
                "title": "Healthy profit margin",
                "description": "Operating expenses are 39% of gross income, leaving a healthy 61% margin. Software and contractor costs are well within benchmark for a design studio of your size.",
                "severity": "INFO",
                "related_percentage": Decimal("61.0"),
                "action_required": False,
            },
        ]

        for ins in insights:
            _, created = FinancialInsight.objects.get_or_create(
                user=user,
                insight_type=ins["insight_type"],
                title=ins["title"],
                defaults={k: v for k, v in ins.items() if k not in ("insight_type", "title")},
            )
            if created:
                self._ok(f"Created FinancialInsight: {ins['title'][:50]}…")

    def _create_health_score(self, user, org):
        try:
            from finnova_autopilot.models import FinancialHealthScore
        except ImportError:
            self._warn("FinancialHealthScore not available.")
            return

        _, created = FinancialHealthScore.objects.get_or_create(
            user=user,
            defaults={
                "overall_score": 710,
                "grade": "B",
                "components": {
                    "savings_rate": 85,
                    "expense_control": 72,
                    "income_stability": 68,
                    "emergency_fund": 45,
                    "debt_ratio": 95,
                },
                "strengths": ["Low debt", "Consistent income", "Active savings"],
                "weaknesses": ["Client concentration", "Emergency fund below target"],
                "opportunities": ["Raise retainer rates by 10%", "Add second revenue stream"],
                "threats": ["Single client >60% revenue"],
                "trend": "IMPROVING",
                "percentile": 72,
            },
        )
        if created:
            self._ok("Created FinancialHealthScore: 710 / B")

    def _create_autopilot_profile(self, user, org):
        try:
            from finnova_autopilot.models import AutopilotProfile
        except ImportError:
            self._warn("AutopilotProfile not available.")
            return

        _, created = AutopilotProfile.objects.get_or_create(
            user=user,
            defaults={
                "organization": org,
                "is_active": True,
                "income_split_enabled": True,
                "bill_pay_enabled": True,
                "savings_auto_enabled": True,
                "metadata": {"onboarded_via": "seed_demo"},
            },
        )
        if created:
            self._ok("Created AutopilotProfile (is_active=True).")
        else:
            # Make sure it's active
            AutopilotProfile.objects.filter(user=user).update(is_active=True)
            self._ok("AutopilotProfile already exists — set is_active=True.")

    def _create_audit_trail(self, user, org, invoice, income, approval):
        """F1: Create 8 realistic AuditLog entries showing the full Priya demo flow."""
        try:
            from audit.models import AuditLog
        except ImportError:
            self._warn("AuditLog not available — skipping audit trail.")
            return

        # Map blueprint action names to valid ACTION_CATEGORIES choices
        # Valid: CREATE, READ, UPDATE, DELETE, LOGIN, LOGOUT, PAYMENT, TRANSACTION, SETTING, SECURITY, ERROR, SYSTEM
        entries = [
            ("LOGIN",       "INFO",  "User priya@finnovadesigns.in logged in from Chrome/Mac"),
            ("CREATE",      "INFO",  "Invoice INV-2024-001 created for Techwave Pvt Ltd — ₹1,41,600"),
            ("SYSTEM",      "INFO",  "Invoice INV-2024-001 sent to client via portal link"),
            ("PAYMENT",     "INFO",  "Payment received: ₹1,41,600 via Razorpay — Invoice INV-2024-001 marked PAID"),
            ("TRANSACTION", "INFO",  "Income ₹1,41,600 auto-posted to Finance ledger from invoice payment"),
            ("SYSTEM",      "INFO",  "Autopilot triggered income split plan for ₹1,41,600 income"),
            ("CREATE",      "INFO",  "Income split approval request created — GST ₹21,600 reserved, Tax ₹14,400 provisioned"),
            ("SYSTEM",      "INFO",  "GST collected this quarter updated: ₹21,600 from Techwave invoice"),
        ]

        created_count = 0
        for action, severity, description in entries:
            try:
                AuditLog.objects.create(
                    actor=user,
                    organization=org,
                    action=action,
                    severity=severity,
                    description=description,
                    actor_ip='127.0.0.1',
                    source='SYSTEM',
                    details={
                        "demo": True,
                        "invoice_id": str(invoice.id) if invoice else None,
                        "income_id": str(income.id) if income else None,
                        "approval_id": str(approval.id) if approval else None,
                    }
                )
                created_count += 1
            except Exception as exc:
                self._warn(f"AuditLog entry failed ({action}): {exc}")

        if created_count > 0:
            self._ok(f"Created {created_count} AuditLog entries for demo audit trail.")
