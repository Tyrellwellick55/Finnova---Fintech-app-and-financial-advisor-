# finance/apps.py
import contextlib
from django.apps import AppConfig

class FinanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'finance'
    verbose_name = 'Financial Management'

    def ready(self):
        # Import signals here to avoid AppRegistryNotReady
        import finance.signals
        import finance.event_handlers

        # Import and register custom checks
        from django.core.checks import register
        from .checks import check_finance_config

        register(check_finance_config)

        # Initialize AI models if needed
        with contextlib.suppress(ImportError):
            from analytics_ai.algorithms import initialize_ai_models
            initialize_ai_models()
