DEBUG = True
AUTH_USER_MODEL = "NEMO.User"

DATETIME_FORMAT = "l, F jS, Y @ g:i A"
DATE_FORMAT = "m/d/Y"
TIME_FORMAT = "g:i A"
DATETIME_INPUT_FORMATS = ["%m/%d/%Y %I:%M %p"]
DATE_INPUT_FORMATS = ["%m/%d/%Y"]
TIME_INPUT_FORMATS = ["%I:%M %p"]

USE_I18N = False
USE_L10N = False
USE_TZ = True

ROOT_URLCONF = "NEMO.urls"
ALLOW_CONDITIONAL_URLS = True

STATIC_URL = "/static/"
MEDIA_URL = "/media/"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "login"
AUTHENTICATION_BACKENDS = ["NEMO.views.authentication.NginxKerberosAuthorizationHeaderAuthenticationBackend"]

SECRET_KEY = "test"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
    "django.contrib.humanize",
    "NEMO_custom_forms",
    "NEMO",
    "rest_framework",
    "django_filters",
    "mptt",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.common.BrokenLinkEmailsMiddleware",
    "NEMO.middleware.DeviceDetectionMiddleware",
    "NEMO.middleware.RemoteUserAuthenticationMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "NEMO.context_processors.hide_logout_button",  # Add a 'request context processor' in order to figure out whether to display the logout button. If the site is configured to use the LDAP authentication backend then we want to provide a logoff button (in the menu bar). Otherwise the Kerberos authentication backend is used and no logoff button is necessary.
                "NEMO.context_processors.base_context",  # Base context processor
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.debug",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.request",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

TIME_ZONE = "US/Eastern"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ("NEMO.permissions.BillingAPI",),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "./test_nemo.db",
    }
}
