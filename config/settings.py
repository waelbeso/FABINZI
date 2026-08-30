from datetime import timedelta
from pathlib import Path
import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    SENTRY_ENABLED=(bool, False),
    FABINZI_DEMO_SEED_ENABLED=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

_DEV_SECRET = "dev-only-unsafe-secret"
SECRET_KEY = env("DJANGO_SECRET_KEY", default=_DEV_SECRET)
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ENVIRONMENT = env("ENVIRONMENT", default="development").strip().lower()
if not DEBUG and SECRET_KEY == _DEV_SECRET:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be explicitly configured outside DEBUG mode")
_PRIVATE_MEDIA_LOCAL_ENVIRONMENTS = {"development", "dev", "test", "testing"}
_private_media_default = "local" if ENVIRONMENT in _PRIVATE_MEDIA_LOCAL_ENVIRONMENTS else "s3"
PRIVATE_MEDIA_STORAGE_MODE = env("PRIVATE_MEDIA_STORAGE_MODE", default=_private_media_default).strip().lower()
if PRIVATE_MEDIA_STORAGE_MODE not in {"local", "s3"}:
    raise ImproperlyConfigured("PRIVATE_MEDIA_STORAGE_MODE must be either 'local' or 's3'")
if PRIVATE_MEDIA_STORAGE_MODE == "local" and ENVIRONMENT not in _PRIVATE_MEDIA_LOCAL_ENVIRONMENTS:
    raise ImproperlyConfigured("Private local media storage is allowed only in development/test environments")
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1").split(",") if h.strip()]
FABINZI_PUBLIC_BASE_URL = env("FABINZI_PUBLIC_BASE_URL", default="http://localhost:8000").rstrip("/")
if not DEBUG and not FABINZI_PUBLIC_BASE_URL.startswith("https://"):
    raise ImproperlyConfigured("FABINZI_PUBLIC_BASE_URL must use HTTPS outside DEBUG mode")
_csrf_default = "" if DEBUG else FABINZI_PUBLIC_BASE_URL
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", default=_csrf_default).split(",") if o.strip()]
CSRF_FAILURE_VIEW = "apps.platform_ops.launch_views.csrf_failure"
FABINZI_DEMO_SEED_ENABLED = env.bool("FABINZI_DEMO_SEED_ENABLED", default=False)
DEMO_ADMIN_EMAIL = env("DEMO_ADMIN_EMAIL", default="demo.admin@fabinzi.example")
DEMO_ADMIN_PASSWORD = env("DEMO_ADMIN_PASSWORD", default="")
DEMO_DESIGNER_EMAIL = env("DEMO_DESIGNER_EMAIL", default="demo.designer@fabinzi.example")
DEMO_DESIGNER_PASSWORD = env("DEMO_DESIGNER_PASSWORD", default="")
DEMO_MANUFACTURER_EMAIL = env("DEMO_MANUFACTURER_EMAIL", default="demo.manufacturer@fabinzi.example")
DEMO_MANUFACTURER_PASSWORD = env("DEMO_MANUFACTURER_PASSWORD", default="")
DEMO_CUSTOMER_EMAIL = env("DEMO_CUSTOMER_EMAIL", default="demo.customer@fabinzi.example")
DEMO_CUSTOMER_PASSWORD = env("DEMO_CUSTOMER_PASSWORD", default="")

INSTALLED_APPS = [
    "django.contrib.admin","django.contrib.auth","django.contrib.contenttypes","django.contrib.sessions","django.contrib.messages","django.contrib.staticfiles","django.contrib.sites",
    "rest_framework","rest_framework_simplejwt.token_blacklist","django_otp","django_otp.plugins.otp_totp","django_otp.plugins.otp_static","two_factor",
    "apps.accounts","apps.audit","apps.integrations","apps.media","apps.notifications","apps.platform_ops","apps.organizations","apps.design","apps.artwork","apps.manufacturer_marketplace","apps.storefront","apps.checkout","apps.operations","apps.finance",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware","whitenoise.middleware.WhiteNoiseMiddleware","django.contrib.sessions.middleware.SessionMiddleware","django.middleware.locale.LocaleMiddleware","apps.platform_ops.middleware.PublicLocaleMiddleware","django.middleware.common.CommonMiddleware","django.middleware.csrf.CsrfViewMiddleware","django.contrib.auth.middleware.AuthenticationMiddleware","django_otp.middleware.OTPMiddleware","django.contrib.messages.middleware.MessageMiddleware","django.middleware.clickjacking.XFrameOptionsMiddleware","apps.platform_ops.middleware.SecurityHeadersMiddleware","apps.platform_ops.middleware.MaintenanceModeMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
TEMPLATES = [{"BACKEND":"django.template.backends.django.DjangoTemplates","DIRS":[BASE_DIR/"templates"],"APP_DIRS":True,"OPTIONS":{"context_processors":["django.template.context_processors.request","django.contrib.auth.context_processors.auth","django.contrib.messages.context_processors.messages","apps.platform_ops.context_processors.active_announcements","apps.platform_ops.context_processors.seo_context"]}}]

DATABASES = {"default": env.db("DATABASE_URL", default="postgresql://fabinzi:fabinzi@localhost:5432/fabinzi")}
AUTH_USER_MODEL = "accounts.User"
SITE_ID = 1
LOGIN_URL = "two_factor:login"
LOGIN_REDIRECT_URL = "app-home"
LOGOUT_REDIRECT_URL = "home"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME":"django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME":"django.contrib.auth.password_validation.MinimumLengthValidator","OPTIONS":{"min_length":10}},
    {"NAME":"django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME":"django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = env("DEFAULT_LANGUAGE", default="en")
LANGUAGES = [("en","English"),("ar","العربية")]
LOCALE_PATHS = [BASE_DIR/"locale"]
TIME_ZONE = env("TIME_ZONE", default="Africa/Cairo")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR/"staticfiles"
STATICFILES_DIRS = [BASE_DIR/"static"]
MEDIA_ROOT = BASE_DIR/"mediafiles"
MEDIA_URL = "/media/"
STORAGES = {
    "default": {"BACKEND":"django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND":"django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG else "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES":["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES":["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_VERSIONING_CLASS":"rest_framework.versioning.NamespaceVersioning",
    "DEFAULT_THROTTLE_CLASSES":["rest_framework.throttling.AnonRateThrottle","rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES":{
        "anon":env("API_ANON_RATE",default="120/hour"),
        "user":env("API_USER_RATE",default="1200/hour"),
        "customer_login":env("API_CUSTOMER_LOGIN_RATE",default="10/minute"),
        "customer_refresh":env("API_CUSTOMER_REFRESH_RATE",default="30/minute"),
        "customer_upload":env("API_CUSTOMER_UPLOAD_RATE",default="30/hour"),
        "customer_place":env("API_CUSTOMER_PLACE_RATE",default="20/hour"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
}

CACHES = {"default":{"BACKEND":"django.core.cache.backends.locmem.LocMemCache","LOCATION":"fabinzi-runtime-throttles"}}

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 270
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {"dispatch-pending-notifications":{"task":"apps.notifications.tasks.dispatch_pending_deliveries","schedule":60.0}}

INTEGRATION_ENCRYPTION_KEY = env("INTEGRATION_ENCRYPTION_KEY", default="")
if DEBUG and not INTEGRATION_ENCRYPTION_KEY:
    INTEGRATION_ENCRYPTION_KEY = "DEBUG"
if not DEBUG and not INTEGRATION_ENCRYPTION_KEY:
    raise ImproperlyConfigured("INTEGRATION_ENCRYPTION_KEY is required outside DEBUG mode")

SENTRY_ENABLED = env.bool("SENTRY_ENABLED", default=False)
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_ENABLED and SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(dsn=SENTRY_DSN, environment=ENVIRONMENT, send_default_pii=False, traces_sample_rate=0.05)

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=not DEBUG)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
FABINZI_ADMIN_PATH = "/Maneg/"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SAMESITE = "Lax"
FORMS_URLFIELD_ASSUME_HTTPS = True
