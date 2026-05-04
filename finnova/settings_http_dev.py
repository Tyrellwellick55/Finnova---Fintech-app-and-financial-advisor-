"""
Django settings for LOCAL DEVELOPMENT ONLY
Explicitly disables all HTTPS/SSL functionality
"""

import os
import shutil
import sqlite3
from pathlib import Path

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# FORCE development mode
DEBUG = True
FINNOVA_ENV = 'development'

# Create logs directory
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# Security - ALL SSL/HTTPS DISABLED FOR LOCAL DEV
SECRET_KEY = 'finnova-local-dev-key-change-before-production'
ALLOWED_HOSTS = ['*']  # Accept all hosts locally

# EXPLICITLY DISABLE ALL HTTPS
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_PROXY_SSL_HEADER = None
USE_X_FORWARDED_HOST = False
USE_X_FORWARDED_PROTO = False

# CSRF and sessions
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://localhost:8001',
    'http://127.0.0.1:8000',
    'http://127.0.0.1:8001',
    'http://localhost',
    'http://127.0.0.1',
]

# Apps
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

# Database - use same database as production (with all migrations)
if os.name == 'nt':
    SQLITE_DEFAULT_DIR = Path(os.environ.get('LOCALAPPDATA', BASE_DIR)) / 'Finnovault'
else:
    SQLITE_DEFAULT_DIR = BASE_DIR

DEFAULT_SQLITE_PATH = SQLITE_DEFAULT_DIR / 'db.sqlite3'
LEGACY_SQLITE_PATHS = [BASE_DIR / 'db.sqlite3', BASE_DIR / 'db_copy.sqlite3']
SQLITE_DB_PATH = Path(os.environ.get('FINNOVA_SQLITE_PATH', DEFAULT_SQLITE_PATH))

# Bootstrap from legacy if needed
if SQLITE_DB_PATH == DEFAULT_SQLITE_PATH:
    try:
        SQLITE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if not SQLITE_DB_PATH.exists():
        for legacy_db in LEGACY_SQLITE_PATHS:
            if legacy_db.exists():
                try:
                    import shutil
                    shutil.copy2(legacy_db, SQLITE_DB_PATH)
                except OSError:
                    SQLITE_DB_PATH = legacy_db
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

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
}

# Audit
AUDIT_ENABLED = True
AUDIT_RETENTION_DAYS = 90

# Bootstrap 5
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# Agency UI
FINNOVA_ENABLE_AGENCY_UI = True
