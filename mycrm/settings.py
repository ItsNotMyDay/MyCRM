from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-rjmu@utrmy!w3jw4f+e#-c7p$^ps^%v0%&f!17!(6s5$4=6i8p'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = [
    'mycrm-itsnotmyday.amvera.io',
    '127.0.0.1',
    'localhost',
    'small-sites-smoke.loca.lt',
    '192.168.1.103',   # твой локальный IP
    '100.66.145.61',   # если ты реально заходишь и по этому адресу
]
TG_GATEWAY_URL = "https://tggetway-itsnotmyday.waw0.amvera.tech"
CSRF_TRUSTED_ORIGINS = [
    'https://strong-emus-melt.loca.lt',
    'http://192.168.1.103:8000',
    'http://100.66.145.61:8000',
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'crm',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'mycrm.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            BASE_DIR / "templates",
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'mycrm.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'

LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
LOGIN_URL = '/accounts/login/'

TELEGRAM_BOT_TOKEN = "8709724893:AAEyuInDzF0vjUa2Sybs_d75YXIeeVzzHRQ"
#TELEGRAM_PROXY_URL = "socks5://UuYAQM:G6Cszn@158.46.162.85:8000"

IMAP_HOST = "imap.mail.ru"
IMAP_PORT = 993
IMAP_USE_SSL = True

IMAP_USERNAME = "woewodin-kirill2.0@mail.ru"
IMAP_PASSWORD = "rrHcX83g7cnPrH7qcwyJ"

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.mail.ru"
EMAIL_PORT = 587
EMAIL_USE_TLS = True

EMAIL_HOST_USER = "woewodin-kirill2.0@mail.ru"
EMAIL_HOST_PASSWORD = "rrHcX83g7cnPrH7qcwyJ"  # пароль приложения
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# Медиа-файлы (записи звонков и др.)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# --- Настройки UIS (пример) ---
UIS_API_BASE_URL = "https://api.uiscom.ru"
UIS_API_KEY = "ВАШ_UIS_API_KEY"
UIS_DEFAULT_MANAGER_NUMBER = "+7XXXXXXXXXX"
UIS_WEBHOOK_SECRET = "случайная_строка_для_подписи"
