"""
Integration module for connecting notification system with other apps
"""

# In your finance app, add this:
"""
from notifications.integrations import finance_integration

# When a transaction occurs:
finance_integration.handle_transaction(transaction, 'COMPLETED')
"""

# In your payments_core app:
"""
from notifications.integrations import payments_integration

# When payment status changes:
payments_integration.handle_payment_status(payment, old_status, new_status)
"""

# In your audit app:
"""
from notifications.integrations import audit_integration

# When suspicious activity detected:
audit_integration.alert_suspicious_activity(audit_log, 'MULTIPLE_FAILED_LOGINS')
"""

# In your finnovaautopilot app:
"""
from notifications.integrations import autopilot_integration

# When autopilot event occurs:
autopilot_integration.handle_autopilot_event(event)
"""