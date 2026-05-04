# finance/checks.py
from django.core.checks import Error, register, Tags

@register(Tags.compatibility)
def check_finance_config(app_configs, **kwargs):
    errors = []
    
    # Check required apps are installed
    required_apps = ['finnova_autopilot', 'analytics_ai', 'notifications']
    
    from django.apps import apps
    for app in required_apps:
        try:
            apps.get_app_config(app)
        except LookupError:
            errors.append(
                Error(
                    f'Finance app requires {app} to be installed',
                    hint=f'Add "{app}" to INSTALLED_APPS in settings.py',
                    id='finance.E001',
                )
            )
    
    return errors