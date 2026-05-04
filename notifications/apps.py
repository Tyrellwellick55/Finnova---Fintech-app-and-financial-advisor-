from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = 'notifications'
    verbose_name = 'Notification System'
    
    def ready(self):
        """
        Import signals when app is ready
        """
        import notifications.signals