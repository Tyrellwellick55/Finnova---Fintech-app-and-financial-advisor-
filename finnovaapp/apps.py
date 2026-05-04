# apps.py
from django.apps import AppConfig


class FinnovaappConfig(AppConfig):
    name = 'finnovaapp'
    
    def ready(self):
        # Import signals
        import finnovaapp.signals