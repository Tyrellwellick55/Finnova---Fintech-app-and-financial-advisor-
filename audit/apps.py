import contextlib
from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AuditConfig(AppConfig):
    name = 'audit'
    verbose_name = _("Audit & Compliance")
    
    def ready(self):
        """Initialize the audit app"""
        import audit.signals  # Import signals

        # Register custom checks
        from django.core.checks import register, Tags

        @register(Tags.security)
        def check_audit_config(app_configs, **kwargs):
            from django.conf import settings

            errors = []

            # Check if audit is enabled
            if not hasattr(settings, 'AUDIT_ENABLED'):
                errors.append(
                    'audit.E001: AUDIT_ENABLED setting is required'
                )

            # Check retention settings
            if not hasattr(settings, 'AUDIT_RETENTION_DAYS'):
                errors.append(
                    'audit.E002: AUDIT_RETENTION_DAYS setting is required'
                )

            return errors

        # Initialize audit middleware if needed
        with contextlib.suppress(ImportError):
            from .middleware import AuditMiddleware