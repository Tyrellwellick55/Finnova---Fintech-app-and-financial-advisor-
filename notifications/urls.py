from django.urls import path, include

from .views import notification_page, legacy_notifications_api, unread_count_api

app_name = "notifications"

# ── Optional DRF router (only when djangorestframework is installed) ──────────
try:
    from rest_framework.routers import DefaultRouter
    from .views import NotificationViewSet, NotificationPreferenceViewSet

    _router = DefaultRouter()
    _router.register(r'notifications', NotificationViewSet, basename='notification')
    _router.register(r'preferences', NotificationPreferenceViewSet, basename='notification-preference')

    _drf_api_urls = [
        path('api/', include(_router.urls)),
        path(
            'api/notifications/<uuid:pk>/read/',
            NotificationViewSet.as_view({'post': 'mark_read'}),
            name='notification-mark-read',
        ),
        path(
            'api/notifications/<uuid:pk>/acknowledge/',
            NotificationViewSet.as_view({'post': 'acknowledge'}),
            name='notification-acknowledge',
        ),
    ]
except ImportError:
    _drf_api_urls = []

urlpatterns = [
    # ── HTML pages (user-facing) ──────────────────────────────────────────────
    path('',               notification_page, {'page_slug': 'notification_list'},            name='notification_list'),
    path('mark_all_read/', notification_page, {'page_slug': 'mark_all_read'},               name='mark_all_read'),
    path('bulk_action/',   notification_page, {'page_slug': 'bulk_action'},                 name='bulk_action'),
    path('history/',       notification_page, {'page_slug': 'notification_history'},        name='notification_history'),
    path('preferences/',   notification_page, {'page_slug': 'notification_preferences'},    name='notification_preferences'),
    path('quiet-hours/',   notification_page, {'page_slug': 'notification_quiet_hours'},    name='notification_quiet_hours'),
    path('archive/',       notification_page, {'page_slug': 'notification_archive'},        name='notification_archive'),
    path('digest-settings/',notification_page,{'page_slug': 'notification_digest_settings'},name='notification_digest_settings'),
    path('detail/',        notification_page, {'page_slug': 'notification_detail'},         name='notification_detail'),
    path('detail/<uuid:notification_id>/', notification_page, {'page_slug': 'notification_detail'}, name='notification_detail_item'),
    path('<uuid:notification_id>/',        notification_page, {'page_slug': 'notification_detail'}, name='notification_detail_legacy'),

    # ── Staff/admin-only pages ────────────────────────────────────────────────
    path('templates/',          notification_page, {'page_slug': 'notification_templates'},    name='notification_templates'),
    path('templates/form/',     notification_page, {'page_slug': 'notification_template_form'},name='notification_template_form'),
    path('templates/create/',   notification_page, {'page_slug': 'notification_template_form'},name='notification_template_create'),
    path('templates/<str:template_id>/edit/', notification_page, {'page_slug': 'notification_template_form'}, name='notification_template_edit'),
    path('analytics/',          notification_page, {'page_slug': 'notification_analytics'},    name='notification_analytics'),
    path('admin/send/',         notification_page, {'page_slug': 'notification_admin_send'},   name='notification_admin_send'),
    path('error-log/',          notification_page, {'page_slug': 'notification_error_log'},    name='notification_error_log'),

    # ── Lightweight badge API (no DRF needed — polled by base.html every 60s) ──
    path('api/unread-count/', unread_count_api, name='unread_count'),

    # ── DRF REST API ─────────────────────────────────────────────────────────
    *_drf_api_urls,
]
