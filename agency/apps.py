from django.apps import AppConfig


class AgencyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'agency'
    verbose_name = 'Agency Mode'

    def ready(self):
        # Register signals
        try:
            import agency.signals  # noqa: F401
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Failed to import agency.signals')

        # Register EventHub handlers
        try:
            import agency.event_handlers  # noqa: F401
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Failed to import agency.event_handlers')

