# payments_core/apps.py
from django.apps import AppConfig

class PaymentsCoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'payments_core'
    
    def ready(self):
        """Import signals when app is ready"""
        import payments_core.signals