"""
Django settings for bgc_data_portal project.
"""

import sys
from pathlib import Path
import os
import dj_database_url
from django.core.exceptions import ImproperlyConfigured

# from csp.constants import NONCE, SELF

# Load environment variables from .env file
BASE_DIR = Path(__file__).resolve().parent.parent

# Environment helpers


# Core settings
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN")
PROJECT_USER_TOKEN = os.getenv("PROJECT_USER_TOKEN")
DEBUG = os.getenv("DJANGO_DEBUG", default="False").lower() == "true"

IS_COLLECTSTATIC = "collectstatic" in sys.argv

# Allowed hosts
ALLOWED_HOSTS_ENV = os.getenv("ALLOWED_HOSTS", "")
if not ALLOWED_HOSTS_ENV:
    if DEBUG or IS_COLLECTSTATIC:
        ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
    else:
        raise ImproperlyConfigured("Set the ALLOWED_HOSTS environment variable")
else:
    ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS_ENV.split(",") if h.strip()]

CSRF_TRUSTED_ORIGINS = [
    x.strip() for x in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if x.strip()
]
CORS_TRUSTED_ORIGINS = [
    x.strip() for x in os.getenv("CORS_TRUSTED_ORIGINS", "").split(",") if x.strip()
]

# Allow overriding the externally mounted base path (used for URL reversing, static paths, etc.)
# Default remains the production prefix to keep existing behaviour, but can be overridden in dev.
FORCE_SCRIPT_NAME = os.getenv("DJANGO_FORCE_SCRIPT_NAME", "")

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

STATIC_URL = f"{FORCE_SCRIPT_NAME}/static/"

# Internal IPs
INTERNAL_IPS = [
    "127.0.0.1",
    "0.0.0.0",
]

DEBUG_TOOLBAR_CONFIG = {"SHOW_TOOLBAR_CALLBACK": lambda _request: DEBUG}

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "ninja",
    "matomo",
    "rest_framework",
    "mgnify_bgcs",
    "django_celery_results",
    "pgvector",
    "csp",
    "discovery",
]

if DEBUG:
    INSTALLED_APPS += ["debug_toolbar"]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "csp.middleware.CSPMiddleware",
]

if DEBUG:
    MIDDLEWARE += [
        "debug_toolbar.middleware.DebugToolbarMiddleware",
    ]

ROOT_URLCONF = "bgc_data_portal.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "bgc_data_portal", "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "bgc_data_portal.context_processors.use_matomo",
            ],
            "libraries": {
                "table_tags": "bgc_data_portal.templatetags.table_tags",
            },
        },
    },
]

WSGI_APPLICATION = "bgc_data_portal.wsgi.application"

# Database
DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        conn_max_age=600,
    )
}

# Celery
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND")
CELERY_RESULT_EXPIRES = int(os.getenv("CELERY_RESULT_EXPIRES", "3600"))
CELERY_IGNORE_RESULT = False
CELERY_STORE_NULL_RESULT = True
CELERY_TASK_ROUTES = {
    "discovery.tasks.recompute_scores": {"queue": "scores"},
}


# REST Framework
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/minute",
    },
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Static files
# STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # NOT the same as STATICFILES_DIRS

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

# For development, you might also want:
# if DEBUG:
#     from django.conf.urls.static import static
#     urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# if DEBUG:
# STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
# else:
# STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Default primary key
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Caching
DJANGO_CACHE_BACKEND = os.getenv("DJANGO_CACHE_BACKEND")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": DJANGO_CACHE_BACKEND,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SERIALIZER": "django_redis.serializers.pickle.PickleSerializer",
        },
    }
}
CACHE_TIMEOUT = 60 * 60 * 24 * 7  # 1 week

# Matomo
MATOMO_URL = os.getenv("MATOMO_URL")
MATOMO_SITE_ID = (
    int(os.getenv("MATOMO_SITE_ID")) if os.getenv("MATOMO_SITE_ID") else None
)

# Content Security Policy (CSP)
# CONTENT_SECURITY_POLICY = {
#     "DIRECTIVES": {
#     "default-src": [SELF],
#     "script-src":  [SELF, NONCE],
#     "style-src":   [SELF, NONCE],
#     },
# }

# Logging

DJANGO_MANAGED_LOG_LEVEL = "DEBUG" if DEBUG else "INFO"
LOG_LEVEL = os.getenv("LOG_LEVEL", DJANGO_MANAGED_LOG_LEVEL).upper()


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "level": DJANGO_MANAGED_LOG_LEVEL,
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "formatter": "simple",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": DJANGO_MANAGED_LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": DJANGO_MANAGED_LOG_LEVEL,
            "propagate": False,
        },
    },
}
