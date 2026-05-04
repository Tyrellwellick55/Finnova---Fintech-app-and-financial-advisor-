from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
import json

from .models import AuditLog, SecurityAlert, ComplianceRecord, AuditTrail
from .services import AuditService

User = get_user_model()


class AuditModelTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username='testuser1',
            email='test1@example.com',
            password='testpass123'
        )
        self.user2 = User.objects.create_user(
            username='testuser2',
            email='test2@example.com',
            password='testpass123'
        )
    
    def test_audit_log_creation(self):
        """Test creating an audit log"""
        log = AuditLog.objects.create(
            actor=self.user1,
            target_user=self.user2,
            source='FINANCE',
            action='CREATE',
            severity='MEDIUM',
            description='Test audit log creation',
            ip_address='127.0.0.1',
            metadata={'test': 'data'}
        )
        
        self.assertEqual(log.actor, self.user1)
        self.assertEqual(log.target_user, self.user2)
        self.assertEqual(log.source, 'FINANCE')
        self.assertEqual(log.action, 'CREATE')
        self.assertEqual(log.severity, 'MEDIUM')
        self.assertEqual(log.description, 'Test audit log creation')
        self.assertEqual(log.ip_address, '127.0.0.1')
        self.assertEqual(log.metadata, {'test': 'data'})
        self.assertIsNotNone(log.correlation_id)
    
    def test_audit_log_string_representation(self):
        """Test audit log string representation"""
        log = AuditLog.objects.create(
            source='SYSTEM',
            action='SYSTEM_EVENT',
            severity='LOW',
            description='Test log'
        )
        expected = f"[SYSTEM] SYSTEM_EVENT - {log.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
        self.assertEqual(str(log), expected)
    
    def test_security_alert_creation(self):
        """Test creating a security alert"""
        alert = SecurityAlert.objects.create(
            alert_type='LOGIN_ATTEMPT',
            title='Multiple failed logins',
            description='Detected 5 failed login attempts',
            user=self.user1,
            severity='HIGH',
            ip_address='192.168.1.1'
        )
        
        self.assertEqual(alert.alert_type, 'LOGIN_ATTEMPT')
        self.assertEqual(alert.title, 'Multiple failed logins')
        self.assertEqual(alert.user, self.user1)
        self.assertEqual(alert.severity, 'HIGH')
        self.assertEqual(alert.status, 'OPEN')
    
    def test_compliance_record_creation(self):
        """Test creating a compliance record"""
        record = ComplianceRecord.objects.create(
            compliance_type='GDPR',
            user=self.user1,
            description='GDPR compliance check',
            due_date=timezone.now().date() + timedelta(days=30)
        )
        
        self.assertEqual(record.compliance_type, 'GDPR')
        self.assertEqual(record.user, self.user1)
        self.assertEqual(record.status, 'PENDING')
        self.assertFalse(record.verified)
    
    def test_audit_trail_creation(self):
        """Test creating an audit trail"""
        trail = AuditTrail.objects.create(
            object_type='User',
            object_id='1',
            operation='UPDATE',
            user=self.user1,
            old_value={'username': 'old'},
            new_value={'username': 'new'},
            changes={'username': {'old': 'old', 'new': 'new'}}
        )
        
        self.assertEqual(trail.object_type, 'User')
        self.assertEqual(trail.object_id, '1')
        self.assertEqual(trail.operation, 'UPDATE')
        self.assertEqual(trail.user, self.user1)
        self.assertEqual(trail.changes, {'username': {'old': 'old', 'new': 'new'}})


class AuditServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
    
    def test_log_audit_event(self):
        """Test logging an audit event"""
        log = AuditService.log_audit_event(
            actor=self.user,
            source='FINANCE',
            action='CREATE',
            severity='MEDIUM',
            description='Test event',
            ip_address='127.0.0.1',
            metadata={'test': 'data'}
        )
        
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, self.user)
        self.assertEqual(log.source, 'FINANCE')
        self.assertEqual(log.description, 'Test event')
    
    def test_create_security_alert(self):
        """Test creating a security alert"""
        alert = AuditService.create_security_alert(
            alert_type='UNAUTHORIZED_ACCESS',
            title='Unauthorized access attempt',
            description='User attempted to access restricted resource',
            user=self.user,
            severity='HIGH'
        )
        
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_type, 'UNAUTHORIZED_ACCESS')
        self.assertEqual(alert.severity, 'CRITICAL')  # Auto-escalated
    
    def test_log_data_change(self):
        """Test logging data changes"""
        trail = AuditService.log_data_change(
            object_type='User',
            object_id='1',
            operation='UPDATE',
            user=self.user,
            old_value={'status': 'active'},
            new_value={'status': 'inactive'},
            changes={'status': {'old': 'active', 'new': 'inactive'}}
        )
        
        self.assertIsNotNone(trail)
        self.assertEqual(trail.object_type, 'User')
        self.assertEqual(trail.operation, 'UPDATE')
    
    def test_get_audit_stats(self):
        """Test getting audit statistics"""
        # Create some test logs
        for i in range(5):
            AuditLog.objects.create(
                source='SYSTEM',
                action='SYSTEM_EVENT',
                severity='LOW',
                description=f'Test log {i}'
            )
        
        stats = AuditService.get_audit_stats('today')
        
        self.assertIn('total_logs', stats)
        self.assertIn('by_severity', stats)
        self.assertIn('by_source', stats)
        self.assertEqual(stats['total_logs'], 5)
    
    def test_search_logs(self):
        """Test searching audit logs"""
        # Create test logs
        AuditLog.objects.create(
            actor=self.user,
            source='FINANCE',
            action='CREATE',
            severity='MEDIUM',
            description='Created new expense',
            metadata={'amount': 1000}
        )
        
        results = AuditService.search_logs(
            search_query='expense',
            limit=10
        )
        
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first().description, 'Created new expense')


class AuditViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            is_staff=True
        )
        self.client.login(username='testuser', password='testpass123')

        # Org-scoping: select an active organization for middleware + role checks
        from finnovaapp.models import Organization, OrganizationMembership
        self.org = Organization.objects.create(name='Test Org')
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org,
            role=OrganizationMembership.ROLE_OWNER,
            is_active=True,
        )
        session = self.client.session
        session['active_org_id'] = str(self.org.id)
        session.save()
        
        # Add permissions
        from django.contrib.auth.models import Permission
        view_perm = Permission.objects.get(codename='view_auditlog')
        self.user.user_permissions.add(view_perm)
        self.user.save()
    
    def test_dashboard_view(self):
        """Test audit dashboard view"""
        response = self.client.get('/audit/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'audit/dashboard.html')
    
    def test_log_list_view(self):
        """Test audit log list view"""
        response = self.client.get('/audit/logs/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'audit/log_list.html')
    
    def test_analytics_view(self):
        """Test analytics dashboard view"""
        response = self.client.get('/audit/analytics/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'audit/analytics.html')
    
    def test_stats_api(self):
        """Test statistics API endpoint"""
        response = self.client.get('/audit/api/stats/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertIn('stats', data)
    
    def test_search_api(self):
        """Test search API endpoint"""
        # Create a test log
        AuditLog.objects.create(
            source='SYSTEM',
            action='SYSTEM_EVENT',
            severity='LOW',
            description='Test log for search'
        )
        
        response = self.client.get('/audit/api/search/?q=search')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertGreater(data['count'], 0)


class AuditIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
    
    def test_audit_trail_integration(self):
        """Test integration between audit trail and audit log"""
        # Log a data change
        trail = AuditService.log_data_change(
            object_type='User',
            object_id=str(self.user.id),
            operation='UPDATE',
            user=self.user,
            old_value={'email': 'old@example.com'},
            new_value={'email': 'new@example.com'},
            changes={'email': {'old': 'old@example.com', 'new': 'new@example.com'}}
        )
        
        # Check that audit log was also created
        audit_log = AuditLog.objects.filter(
            action='DATA_UPDATE',
            actor=self.user
        ).first()
        
        self.assertIsNotNone(audit_log)
        self.assertIsNotNone(trail)
        self.assertEqual(audit_log.metadata.get('trail_id'), trail.id)
    
    def test_security_alert_auto_creation(self):
        """Test automatic security alert creation"""
        # Create multiple failed login logs
        for i in range(6):
            AuditService.log_audit_event(
                source='SECURITY',
                action='LOGIN',
                severity='HIGH',
                description='Failed login attempt',
                ip_address='192.168.1.100'
            )
        
        # Check that security alert was created
        alert = SecurityAlert.objects.filter(
            alert_type='LOGIN_ATTEMPT',
            ip_address='192.168.1.100'
        ).first()
        
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, 'HIGH')
    
    def test_compliance_status_update(self):
        """Test compliance status updates"""
        record = ComplianceRecord.objects.create(
            compliance_type='GDPR',
            user=self.user,
            description='Test compliance',
            due_date=timezone.now().date() - timedelta(days=1)  # Overdue
        )
        
        # Trigger status check
        record.is_overdue()
        record.refresh_from_db()
        
        self.assertEqual(record.status, 'OVERDUE')


class AuditPerformanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
    
    def test_bulk_log_creation(self):
        """Test performance of bulk log creation"""
        import time
        
        start_time = time.time()
        
        # Create 1000 logs
        for i in range(1000):
            AuditLog.objects.create(
                source='SYSTEM',
                action='SYSTEM_EVENT',
                severity='LOW',
                description=f'Performance test log {i}'
            )
        
        end_time = time.time()
        creation_time = end_time - start_time
        
        # Should complete in reasonable time
        self.assertLess(creation_time, 5.0)
        
        # Verify all logs were created
        self.assertEqual(AuditLog.objects.count(), 1000)
    
    def test_stats_caching(self):
        """Test statistics caching performance"""
        # First call should hit database
        start_time = timezone.now()
        stats1 = AuditService.get_audit_stats('today')
        time1 = (timezone.now() - start_time).total_seconds()
        
        # Second call should hit cache (much faster)
        start_time = timezone.now()
        stats2 = AuditService.get_audit_stats('today')
        time2 = (timezone.now() - start_time).total_seconds()
        
        # Cached call should be significantly faster
        self.assertLess(time2, time1 * 0.5)
        
        # Results should be identical
        self.assertEqual(stats1['total_logs'], stats2['total_logs'])


# Run tests with: python manage.py test audit.tests