from pathlib import Path
import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DJANGO_DEBUG=(bool, False), SENTRY_ENABLED=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-unsafe-secret")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1").split(",") if h.strip()]
ENVIRONMENT = env("ENVIRONMENT", default="development")
INSTALLED_APPS = ["django.contrib.admin","django.contrib.auth","django.contrib.contenttypes","django.contrib.sessions","django.contrib.messages","django.contrib.staticfiles","django.contrib.sites","rest_framework","django_otp","django_otp.plugins.otp_totp","django_otp.plugins.otp_static","two_factor","apps.accounts","apps.audit","apps.integrations","apps.media","apps.notifications","apps.platform_ops","apps.organizations","apps.design","apps.artwork","apps.manufacturer_marketplace","apps.storefront","apps.checkout","apps.operations"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware","whitenoise.middleware.WhiteNoiseMiddleware","django.contrib.sessions.middleware.SessionMiddleware","django.middleware.locale.LocaleMiddleware","django.middleware.common.CommonMiddleware","django.middleware.csrf.CsrfViewMiddleware","django.contrib.auth.middleware.AuthenticationMiddleware","django_otp.middleware.OTPMiddleware","django.contrib.messages.middleware.MessageMiddleware","django.middleware.clickjacking.XFrameOptionsMiddleware","apps.platform_ops.middleware.MaintenanceModeMiddleware"]
ROOT_URLCONF="config.urls"; WSGI_APPLICATION="config.wsgi.application"; ASGI_APPLICATION="config.asgi.application"
TEMPLATES=[{"BACKEND":"django.template.backends.django.DjangoTemplates","DIRS":[BASE_DIR/"templates"],"APP_DIRS":True,"OPTIONS":{"context_processors":["django.template.context_processors.request","django.contrib.auth.context_processors.auth","django.contrib.messages.context_processors.messages","apps.platform_ops.context_processors.active_announcements"]}}]
DATABASES={"default":env.db("DATABASE_URL",default="postgresql://fabinzi:fabinzi@localhost:5432/fabinzi")}; AUTH_USER_MODEL="accounts.User"; SITE_ID=1; LOGIN_URL="two_factor:login"; LOGIN_REDIRECT_URL="app-home"; LOGOUT_REDIRECT_URL="home"
AUTH_PASSWORD_VALIDATORS=[{"NAME":"django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},{"NAME":"django.contrib.auth.password_validation.MinimumLengthValidator","OPTIONS":{"min_length":10}},{"NAME":"django.contrib.auth.password_validation.CommonPasswordValidator"},{"NAME":"django.contrib.auth.password_validation.NumericPasswordValidator"}]
LANGUAGE_CODE=env("DEFAULT_LANGUAGE",default="en"); LANGUAGES=[("en","English"),("ar","العربية")]; LOCALE_PATHS=[BASE_DIR/"locale"]; TIME_ZONE=env("TIME_ZONE",default="Africa/Cairo"); USE_I18N=True; USE_TZ=True
STATIC_URL="/static/"; STATIC_ROOT=BASE_DIR/"staticfiles"; STATICFILES_DIRS=[BASE_DIR/"static"]
STORAGES={"default":{"BACKEND":"django.core.files.storage.FileSystemStorage"},"staticfiles":{"BACKEND":"django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG else "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
DEFAULT_AUTO_FIELD="django.db.models.BigAutoField"
REST_FRAMEWORK={"DEFAULT_AUTHENTICATION_CLASSES":["rest_framework.authentication.SessionAuthentication"],"DEFAULT_PERMISSION_CLASSES":["rest_framework.permissions.IsAuthenticated"],"DEFAULT_VERSIONING_CLASS":"rest_framework.versioning.NamespaceVersioning"}
REDIS_URL=env("REDIS_URL",default="redis://localhost:6379/0"); CELERY_BROKER_URL=REDIS_URL; CELERY_RESULT_BACKEND=REDIS_URL; CELERY_TASK_ACKS_LATE=True; CELERY_TASK_REJECT_ON_WORKER_LOST=True; CELERY_TASK_TIME_LIMIT=300; CELERY_TASK_SOFT_TIME_LIMIT=270; CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP=True
INTEGRATION_ENCRYPTION_KEY=env("INTEGRATION_ENCRYPTION_KEY",default="")
if not DEBUG and not INTEGRATION_ENCRYPTION_KEY: raise ImproperlyConfigured("INTEGRATION_ENCRYPTION_KEY is required outside DEBUG mode")
SENTRY_ENABLED=env.bool("SENTRY_ENABLED",default=False); SENTRY_DSN=env("SENTRY_DSN",default="")
if SENTRY_ENABLED and SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(dsn=SENTRY_DSN,environment=ENVIRONMENT,send_default_pii=False,traces_sample_rate=0.05)
SESSION_COOKIE_HTTPONLY=True; CSRF_COOKIE_HTTPONLY=True; SESSION_COOKIE_SECURE=not DEBUG; CSRF_COOKIE_SECURE=not DEBUG; SECURE_SSL_REDIRECT=not DEBUG; SECURE_HSTS_SECONDS=31536000 if not DEBUG else 0; SECURE_HSTS_INCLUDE_SUBDOMAINS=not DEBUG; SECURE_HSTS_PRELOAD=not DEBUG; X_FRAME_OPTIONS="DENY"; SECURE_REFERRER_POLICY="same-origin"; FABINZI_ADMIN_PATH="/Maneg/"