from django.apps import AppConfig


class EventhubConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'eventhub'

    def ready(self):
        """Load event handlers.

        We avoid silently swallowing handler import issues. Missing handlers can
        mean missing audit logs / notifications, which destroys trust.
        """
        import importlib
        import logging

        logger = logging.getLogger(__name__)

        for module_path in [
            'audit.event_handlers',
            'notifications.event_handlers',
            'finance.event_handlers',
            'analytics_ai.event_handlers',
        ]:
            try:
                importlib.import_module(module_path)
            except Exception:
                # Log loudly; the app should still boot for local/dev use.
                logger.exception('Failed to import EventHub handler module: %s', module_path)
