from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finnovaapp.models import CustomUser, Organization, OrganizationMembership


class BaseOrgTestCase(TestCase):
    """Common setup for org-scoped integration tests."""

    def setUp(self):
        self.owner = CustomUser.objects.create_user(
            username='owner',
            email='owner@example.com',
            password='pass12345',
        )
        self.finance = CustomUser.objects.create_user(
            username='finance',
            email='finance@example.com',
            password='pass12345',
        )
        self.ops = CustomUser.objects.create_user(
            username='ops',
            email='ops@example.com',
            password='pass12345',
        )
        self.viewer = CustomUser.objects.create_user(
            username='viewer',
            email='viewer@example.com',
            password='pass12345',
        )

        self.org = Organization.objects.create(name='Demo Org', segment=Organization.SEGMENT_AGENCY)

        OrganizationMembership.objects.create(user=self.owner, organization=self.org, role=OrganizationMembership.ROLE_OWNER)
        OrganizationMembership.objects.create(user=self.finance, organization=self.org, role=OrganizationMembership.ROLE_FINANCE)
        OrganizationMembership.objects.create(user=self.ops, organization=self.org, role=OrganizationMembership.ROLE_OPERATIONS)
        OrganizationMembership.objects.create(user=self.viewer, organization=self.org, role=OrganizationMembership.ROLE_VIEWER)

    def _login_with_org(self, user: CustomUser):
        self.client.force_login(user)
        session = self.client.session
        session['active_org_id'] = str(self.org.id)
        session.save()


class CoreNavigationTests(BaseOrgTestCase):
    def test_dashboard_requires_login(self):
        resp = self.client.get(reverse('finnovaapp:dashboard'))
        self.assertEqual(resp.status_code, 302)

    def test_dashboard_owner_ok(self):
        self._login_with_org(self.owner)
        resp = self.client.get(reverse('finnovaapp:dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_ops_console_role_allowed(self):
        self._login_with_org(self.ops)
        resp = self.client.get(reverse('finnovaapp:ops_console'))
        self.assertEqual(resp.status_code, 200)


class AgencyInvoiceFlowTests(BaseOrgTestCase):
    def setUp(self):
        super().setUp()
        from agency.models import Client, Project, Invoice

        self.Client = Client
        self.Project = Project
        self.Invoice = Invoice

        self.client_obj = Client.objects.create(
            organization=self.org,
            name='Acme',
            company_name='Acme Pvt Ltd',
            email='billing@acme.test',
        )
        self.project_obj = Project.objects.create(
            organization=self.org,
            client=self.client_obj,
            name='Website',
        )
        self.invoice = Invoice.objects.create(
            organization=self.org,
            client=self.client_obj,
            project=self.project_obj,
            invoice_number='INV-TEST-0001',
            title='Test invoice',
            amount=Decimal('2500.00'),
            due_date=timezone.now().date() + timedelta(days=7),
            status=Invoice.STATUS_SENT,
            created_by=self.owner,
        )

    def test_receivables_dashboard_owner_ok(self):
        self._login_with_org(self.owner)
        resp = self.client.get(reverse('agency:receivables_dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_invoice_pdf_download(self):
        self._login_with_org(self.owner)
        resp = self.client.get(reverse('agency:invoice_pdf', kwargs={'invoice_id': self.invoice.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/pdf', resp.get('Content-Type', ''))

    def test_ops_cannot_mark_paid(self):
        self._login_with_org(self.ops)
        resp = self.client.post(
            reverse('agency:invoice_mark_paid', kwargs={'invoice_id': self.invoice.id}),
            data={'reference': 'OPS-REF'},
            follow=True,
        )
        # ops should be redirected due to role_required
        self.assertNotEqual(resp.redirect_chain, [])
        self.invoice.refresh_from_db()
        self.assertNotEqual(self.invoice.status, self.Invoice.STATUS_PAID)

    def test_owner_can_mark_paid_and_posts_income(self):
        self._login_with_org(self.owner)
        resp = self.client.post(
            reverse('agency:invoice_mark_paid', kwargs={'invoice_id': self.invoice.id}),
            data={'reference': 'OWN-REF'},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, self.Invoice.STATUS_PAID)

        # Finance posting should have created an Income row (best-effort).
        from finance.models import Income

        self.assertTrue(
            Income.objects.filter(organization=self.org, payment_reference__in=['OWN-REF', 'INV-TEST-0001']).exists()
        )


class ClientPortalPaymentFlowTests(BaseOrgTestCase):
    def setUp(self):
        super().setUp()
        from agency.models import Client, Invoice

        self.Client = Client
        self.Invoice = Invoice

        self.client_obj = Client.objects.create(
            organization=self.org,
            name='Portal Client',
            email='client@portal.test',
        )
        self.invoice = Invoice.objects.create(
            organization=self.org,
            client=self.client_obj,
            invoice_number='INV-PORTAL-0001',
            amount=Decimal('999.00'),
            due_date=timezone.now().date() + timedelta(days=3),
            status=Invoice.STATUS_SENT,
        )

    def test_portal_list_and_pay(self):
        self._login_with_org(self.viewer)

        # List
        resp = self.client.get(reverse('agency:client_invoice_list'))
        self.assertEqual(resp.status_code, 200)

        # Pay page (GET)
        resp = self.client.get(reverse('agency:client_invoice_pay', kwargs={'invoice_id': self.invoice.id}))
        self.assertEqual(resp.status_code, 200)

        # Pay (POST) - dummy success
        resp = self.client.post(reverse('agency:client_invoice_pay', kwargs={'invoice_id': self.invoice.id}), follow=True)
        self.assertEqual(resp.status_code, 200)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, self.Invoice.STATUS_PAID)
