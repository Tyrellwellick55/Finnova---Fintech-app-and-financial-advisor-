"""
Django settings for MainProject project.
"""

import os
import shutil
import sqlite3
from pathlib import Path

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Create logs directory
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# Security
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'finnova-local-dev-key-change-this-before-production-use-2026-very-long')
FINNOVA_ENV = os.environ.get('FINNOVA_ENV', 'development').strip().lower()
DEBUG = os.environ.get('FINNOVA_DEBUG', '1' if FINNOVA_ENV != 'production' else '0').lower() in {'1', 'true', 'yes', 'on'}
_default_allowed_hosts = 'localhost,127.0.0.1,0.0.0.0,[::1],testserver' if DEBUG else 'localhost,127.0.0.1'
ALLOWED_HOSTS = [host.strip() for host in os.environ.get('FINNOVA_ALLOWED_HOSTS', _default_allowed_hosts).split(',') if host.strip()]
_default_csrf_origins = ['http://localhost:8000', 'http://127.0.0.1:8000', 'http://localhost:8001', 'http://127.0.0.1:8001'] if DEBUG else []
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ.get('FINNOVA_CSRF_TRUSTED_ORIGINS', ','.join(_default_csrf_origins)).split(',') if origin.strip()]

# Safer defaults for future deployments, but localhost-first in development.
SESSION_COOKIE_SECURE = os.environ.get('FINNOVA_SESSION_COOKIE_SECURE', '1' if (not DEBUG) else '0').lower() in {'1', 'true', 'yes', 'on'}
CSRF_COOKIE_SECURE = os.environ.get('FINNOVA_CSRF_COOKIE_SECURE', '1' if (not DEBUG) else '0').lower() in {'1', 'true', 'yes', 'on'}
SECURE_SSL_REDIRECT = os.environ.get('FINNOVA_SECURE_SSL_REDIRECT', '1' if (not DEBUG and FINNOVA_ENV == 'production') else '0').lower() in {'1', 'true', 'yes', 'on'}
SECURE_HSTS_SECONDS = 0 if DEBUG else int(os.environ.get('FINNOVA_HSTS_SECONDS', '3600'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = False

# Apps - MINIMAL VERSION
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'finnovaapp',
    'eventhub.apps.EventhubConfig',
    'agency.apps.AgencyConfig',
    # YOUR APPS ONLY (no external packages for now)
    'analytics_ai',
    'audit',
    'notifications',
    'finnova_autopilot',
    'payments_core',
    'finance',
    'crispy_forms',
    'crispy_bootstrap5',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'finnovaapp.middleware.OrganizationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'finnova.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'finnovaapp.context_processors.user_context',
                'finnova_autopilot.context_processors.autopilot_context',
            ],
            'builtins': [
                'finance.templatetags.math_extras',
                'analytics_ai.templatetags.ai_filters',
            ],
        },
    },
]

WSGI_APPLICATION = 'finnova.wsgi.application'

# Database
def _sqlite_is_usable(path: Path) -> bool:
    try:
        with sqlite3.connect(path) as connection:
            # Read check
            connection.execute('PRAGMA schema_version;').fetchone()
            # Write-lock check (captures OneDrive/journal disk I/O failures)
            connection.execute('BEGIN IMMEDIATE;')
            connection.execute('ROLLBACK;')
        return True
    except sqlite3.Error:
        return False


if os.name == 'nt':
    SQLITE_DEFAULT_DIR = Path(os.environ.get('LOCALAPPDATA', BASE_DIR)) / 'Finnovault'
else:
    SQLITE_DEFAULT_DIR = BASE_DIR

DEFAULT_SQLITE_PATH = SQLITE_DEFAULT_DIR / 'db.sqlite3'
LEGACY_SQLITE_PATHS = [BASE_DIR / 'db.sqlite3', BASE_DIR / 'db_copy.sqlite3']
SQLITE_DB_PATH = Path(os.environ.get('FINNOVA_SQLITE_PATH', DEFAULT_SQLITE_PATH))

# Bootstrap local DB from legacy project DB when moving off OneDrive-backed paths.
if SQLITE_DB_PATH == DEFAULT_SQLITE_PATH:
    try:
        SQLITE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    if not SQLITE_DB_PATH.exists():
        for legacy_db in LEGACY_SQLITE_PATHS:
            if legacy_db.exists():
                try:
                    shutil.copy2(legacy_db, SQLITE_DB_PATH)
                except OSError:
                    SQLITE_DB_PATH = legacy_db
                break

# If selected DB is unreadable/unwritable, fail over to first usable legacy candidate.
if SQLITE_DB_PATH.exists() and not _sqlite_is_usable(SQLITE_DB_PATH):
    for candidate_db in [DEFAULT_SQLITE_PATH, *LEGACY_SQLITE_PATHS]:
        if candidate_db == SQLITE_DB_PATH:
            continue
        if candidate_db.exists() and _sqlite_is_usable(candidate_db):
            SQLITE_DB_PATH = candidate_db
            break

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': SQLITE_DB_PATH,
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Custom User Model
AUTH_USER_MODEL = 'finnovaapp.CustomUser'

# Default primary key
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Structured Logging ───────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {process:d} {thread:d} | {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        'simple': {
            'format': '[{asctime}] {levelname} {name} | {message}',
            'style': '{',
            'datefmt': '%H:%M:%S',
        },
        'json': {
            'format': '{{"time":"{asctime}","level":"{levelname}","logger":"{name}","msg":"{message}"}}',
            'style': '{',
            'datefmt': '%Y-%m-%dT%H:%M:%S',
        },
    },
    'filters': {
        'require_debug_false': {'()': 'django.utils.log.RequireDebugFalse'},
        'require_debug_true':  {'()': 'django.utils.log.RequireDebugTrue'},
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'level': 'DEBUG',
        },
        'app_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / 'app.log'),
            'maxBytes': 10 * 1024 * 1024,  # 10 MB
            'backupCount': 5,
            'formatter': 'verbose',
            'level': 'INFO',
        },
        'error_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / 'error.log'),
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
            'level': 'ERROR',
        },
        'audit_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / 'audit.log'),
            'maxBytes': 20 * 1024 * 1024,
            'backupCount': 10,
            'formatter': 'verbose',
            'level': 'INFO',
        },
        'security_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / 'security.log'),
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 10,
            'formatter': 'verbose',
            'level': 'WARNING',
        },
        'payment_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / 'payments.log'),
            'maxBytes': 20 * 1024 * 1024,
            'backupCount': 10,
            'formatter': 'verbose',
            'level': 'DEBUG',
        },
    },
    'loggers': {
        # Django internals
        'django': {
            'handlers': ['console', 'app_file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['error_file', 'console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['security_file', 'console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'WARNING',  # Set to DEBUG to log all SQL (noisy)
            'propagate': False,
        },
        # Finnova modules
        'finnovaapp': {
            'handlers': ['console', 'app_file', 'error_file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'finance': {
            'handlers': ['console', 'app_file', 'error_file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'payments_core': {
            'handlers': ['console', 'payment_file', 'error_file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'finnova_autopilot': {
            'handlers': ['console', 'app_file', 'error_file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'analytics_ai': {
            'handlers': ['console', 'app_file', 'error_file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'audit': {
            'handlers': ['console', 'audit_file', 'security_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'notifications': {
            'handlers': ['console', 'app_file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'agency': {
            'handlers': ['console', 'app_file', 'error_file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'eventhub': {
            'handlers': ['console', 'app_file', 'error_file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['console', 'app_file', 'error_file'],
        'level': 'WARNING',
    },
}


# Audit Settings
AUDIT_ENABLED = True
AUDIT_RETENTION_DAYS = 90

# For Bootstrap 5
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# Optional organization/receivables workspace visibility
FINNOVA_ENABLE_AGENCY_UI = os.environ.get('FINNOVA_ENABLE_AGENCY_UI', '1').lower() in {'1', 'true', 'yes', 'on'}


# ── Email ─────────────────────────────────────────────────────────────────────
EMAIL_BACKEND = os.environ.get(
    'FINNOVA_EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend'
)
EMAIL_HOST         = os.environ.get('FINNOVA_EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT         = int(os.environ.get('FINNOVA_EMAIL_PORT', '587'))
EMAIL_USE_TLS      = os.environ.get('FINNOVA_EMAIL_TLS', '1').lower() in {'1', 'true', 'yes'}
EMAIL_HOST_USER    = os.environ.get('FINNOVA_EMAIL_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('FINNOVA_EMAIL_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('FINNOVA_FROM_EMAIL', 'Finnova <noreply@finnova.com>')
SERVER_EMAIL        = DEFAULT_FROM_EMAIL
SUPPORT_EMAIL       = os.environ.get('FINNOVA_SUPPORT_EMAIL', 'support@finnova.com')

# ── Cache ─────────────────────────────────────────────────────────────────────
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'finnova-cache',
        'TIMEOUT': 300,
        'OPTIONS': {'MAX_ENTRIES': 1000},
    }
}

# ── Session ───────────────────────────────────────────────────────────────────
SESSION_ENGINE          = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE      = 60 * 60 * 8   # 8 hours
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# ── File upload ───────────────────────────────────────────────────────────────
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024   # 5 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# ── App-level constants ───────────────────────────────────────────────────────
FINNOVA_VERSION    = os.environ.get('FINNOVA_VERSION', '1.0.0')
FINNOVA_APP_NAME   = 'Finnova'
FINNOVA_CURRENCY   = 'INR'
FINNOVA_TIMEZONE   = 'Asia/Kolkata'

# Gateway keys (override via environment in production)
RAZORPAY_KEY_ID     = os.environ.get('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', '')
STRIPE_SECRET_KEY   = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_PUBLISHABLE  = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
