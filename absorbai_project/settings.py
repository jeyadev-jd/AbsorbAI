import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file if present (python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

SECRET_KEY = os.environ.get('SECRET_KEY', '')
if not SECRET_KEY:
    if os.environ.get('DEBUG', 'false').lower() == 'true':
        SECRET_KEY = 'django-insecure-dev-only-key-do-not-use-in-production'
    else:
        raise RuntimeError('SECRET_KEY environment variable is required in production')

DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

_cors_available = False
try:
    import corsheaders  # noqa: F401
    _cors_available = True
except ImportError:
    pass

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
] + (['corsheaders'] if _cors_available else [])

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
] + (['corsheaders.middleware.CorsMiddleware'] if _cors_available else []) + [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.RateLimitMiddleware',
]

# ── CORS ─────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000').split(',')
CORS_ALLOW_CREDENTIALS = True

ROOT_URLCONF = 'absorbai_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'absorbai_project.wsgi.application'

# ── Auth ──────────────────────────────────────────────────────────────────────
AUTH_USER_MODEL = 'core.AbsorbUser'

# ── Database ──────────────────────────────────────────────────────────────────
_DATABASE_URL = os.environ.get('DATABASE_URL', '')

if _DATABASE_URL:
    import dj_database_url
    DATABASES = {'default': dj_database_url.parse(_DATABASE_URL, conn_max_age=600)}
else:
    # Fallback: Postgres via individual env vars, then SQLite
    _PG_HOST = os.environ.get('POSTGRES_HOST', '')
    if _PG_HOST:
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': os.environ.get('POSTGRES_DB', 'absorbai'),
                'USER': os.environ.get('POSTGRES_USER', 'absorbai'),
                'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
                'HOST': _PG_HOST,
                'PORT': os.environ.get('POSTGRES_PORT', '5432'),
                'CONN_MAX_AGE': 600,
            }
        }
    else:
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': BASE_DIR / 'db.sqlite3',
            }
        }

# ── Redis / Cache ─────────────────────────────────────────────────────────────
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

_redis_available = False
try:
    import django_redis  # noqa: F401
    _redis_available = True
except ImportError:
    pass

if _redis_available:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
            'TIMEOUT': 600,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }

# ── Celery ────────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', REDIS_URL)
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300  # 5 min hard limit per task

# ── Engine versioning ─────────────────────────────────────────────────────────
ENGINE_VERSION = os.environ.get('ENGINE_VERSION', '1.0.0')
DRUG_DB_VERSION = os.environ.get('DRUG_DB_VERSION', '1.0.0')

# ── Password validation ───────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Logging ──────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'absorbai.log',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'core': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}

# ── Startup checks ───────────────────────────────────────────────────────────
import logging as _logging
_boot_logger = _logging.getLogger('absorbai.boot')

if not _redis_available:
    _boot_logger.warning('django-redis not installed — using in-memory cache (not suitable for production)')

if not _cors_available:
    _boot_logger.warning('django-cors-headers not installed — CORS headers will not be set')

try:
    import celery  # noqa: F401
except ImportError:
    _boot_logger.warning('celery not installed — background tasks will use threading fallback')

try:
    import scipy  # noqa: F401
except ImportError:
    _boot_logger.error('scipy not installed — PK/PD engine will not function')

try:
    import networkx  # noqa: F401
except ImportError:
    _boot_logger.error('networkx not installed — knowledge graph will not function')

# ── Rate limiting (simple in-memory, per-IP) ─────────────────────────────────
RATE_LIMIT_REQUESTS = int(os.environ.get('RATE_LIMIT_REQUESTS', '60'))
RATE_LIMIT_WINDOW = int(os.environ.get('RATE_LIMIT_WINDOW', '60'))
