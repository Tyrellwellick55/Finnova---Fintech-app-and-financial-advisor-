from rest_framework import permissions


class IsAuditAdmin(permissions.BasePermission):
    """
    Permission check for audit administrators.
    """
    def has_permission(self, request, view):
        return request.user.has_perm('audit.manage_audit_settings')


class CanViewAuditLogs(permissions.BasePermission):
    """
    Permission check for viewing audit logs.
    """
    def has_permission(self, request, view):
        return request.user.has_perm('audit.view_auditlog')


class CanExportAuditLogs(permissions.BasePermission):
    """
    Permission check for exporting audit logs.
    """
    def has_permission(self, request, view):
        return request.user.has_perm('audit.export_audit_logs')


class CanManageSecurityAlerts(permissions.BasePermission):
    """
    Permission check for managing security alerts.
    """
    def has_permission(self, request, view):
        return request.user.has_perm('audit.change_securityalert')


class AuditActionPermission(permissions.BasePermission):
    """
    Dynamic permission based on audit action type.
    """
    def has_permission(self, request, view):
        # Get action from view
        action = getattr(view, 'action', None)

        if action in ['list', 'retrieve']:
            return request.user.has_perm('audit.view_auditlog')
        elif action == 'export':
            return request.user.has_perm('audit.export_audit_logs')
        elif action == 'stats':
            return request.user.has_perm('audit.view_audit_dashboard')

        return False