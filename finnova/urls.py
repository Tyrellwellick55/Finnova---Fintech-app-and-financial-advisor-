"""
Finnova — root URL configuration.

Module namespaces:
  finnovaapp   → /
  finance      → /finance/
  analytics-ai → /analytics-ai/
  autopilot    → /autopilot/
  agency       → /agency/
  notifications→ /notifications/
  audit        → /audit/
  payments     → /payments/
"""

from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.utils import timezone


def health_check(request):
    """Liveness probe — used by Railway, Render, and uptime monitors."""
    from django.db import connection
    try:
        connection.ensure_connection()
        db_ok = True
    except Exception:
        db_ok = False
    return JsonResponse(
        {"status": "ok" if db_ok else "degraded", "db": "ok" if db_ok else "error",
         "ts": timezone.now().isoformat()},
        status=200 if db_ok else 503,
    )


urlpatterns = [
    path("admin/",     admin.site.urls),
    path("health/",    health_check, name="health_check"),

    path("", include(("finnovaapp.urls", "finnovaapp"), namespace="finnovaapp")),

    path("finance/",       include(("finance.urls",          "finance"),       namespace="finance")),
    path("analytics-ai/",  include(("analytics_ai.urls",     "analytics_ai"),  namespace="analytics-ai")),
    path("autopilot/",     include(("finnova_autopilot.urls", "autopilot"),     namespace="autopilot")),
    path("agency/",        include(("agency.urls",            "agency"),        namespace="agency")),
    path("notifications/", include(("notifications.urls",    "notifications"), namespace="notifications")),
    path("audit/",         include(("audit.urls",             "audit"),         namespace="audit")),
    path("payments/",      include(("payments_core.urls",    "payments_core"), namespace="payments")),

    # Legacy compat
    path("analytics/<path:legacy_path>/",
         lambda req, **kw: __import__("analytics_ai.views", fromlist=["legacy_analytics_endpoint"]).legacy_analytics_endpoint(req, **kw),
         name="legacy_analytics_endpoint"),
    path("api/notifications/",
         lambda req, **kw: __import__("notifications.views", fromlist=["legacy_notifications_api"]).legacy_notifications_api(req, **kw),
         name="legacy_notifications_api_root"),
    path("api/notifications/<path:legacy_path>/",
         lambda req, **kw: __import__("notifications.views", fromlist=["legacy_notifications_api"]).legacy_notifications_api(req, **kw),
         name="legacy_notifications_api"),
]

handler400 = "finnovaapp.views.handler404"
handler403 = "finnovaapp.views.handler403"
handler404 = "finnovaapp.views.handler404"
handler500 = "finnovaapp.views.handler500"
