from django.apps import AppConfig

class FinnovaautopilotConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'finnova_autopilot'
    verbose_name = 'Finnova Autopilot'
    
    def ready(self):
        import finnova_autopilot.signals
        # Other initialization