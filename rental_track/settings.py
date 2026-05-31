"""
Django settings for rental_track project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')


SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-insecure-secret-key')

DEBUG = os.getenv('DJANGO_DEBUG', 'True').lower() in ('1', 'true', 'yes')

ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if h.strip()
]


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'django_htmx',

    'config',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    'django_htmx.middleware.HtmxMiddleware',
]

ROOT_URLCONF = 'rental_track.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.i18n',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'config.context_processors.navigation',
            ],
        },
    },
]

WSGI_APPLICATION = 'rental_track.wsgi.application'


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


LANGUAGE_CODE = 'ru'
TIME_ZONE = 'Asia/Tashkent'
USE_I18N = True
USE_TZ = True

from django.utils.translation import gettext_lazy as _  # noqa: E402

LANGUAGES = [
    ('ru', _('Русский')),
    ('uz', _("O‘zbekcha")),
]

LOCALE_PATHS = [BASE_DIR / 'locale']

LANGUAGE_COOKIE_NAME = 'django_language'
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365  # 1 year


STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'


CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'rental-track-default',
    }
}


# Коэффициент штрафа за просрочку: за каждый день просрочки начисляется
# outstanding * daily_price * RENTAL_OVERDUE_FINE_COEF.
from decimal import Decimal as _Decimal  # noqa: E402

RENTAL_OVERDUE_FINE_COEF = _Decimal('1.5')


# ---------- Telegram ----------
# Токен бота из @BotFather. Никогда не коммитить — только в .env.
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()

# Список chat_id админов через запятую: TELEGRAM_ADMIN_CHAT_IDS=123456,-100789
def _parse_chat_ids(raw: str):
    out = []
    for s in (raw or '').split(','):
        s = s.strip()
        if s.lstrip('-').isdigit():
            out.append(int(s))
    return out


TELEGRAM_ADMIN_CHAT_IDS = _parse_chat_ids(os.getenv('TELEGRAM_ADMIN_CHAT_IDS', ''))

# Час дня (0-23), в который шлются "за день" напоминания. Команда notify_debtors
# запускается каждый час cron'ом, но "daily" блок выполняется только в этот час.
try:
    TELEGRAM_REMINDER_HOUR = int(os.getenv('TELEGRAM_REMINDER_HOUR', '9'))
except ValueError:
    TELEGRAM_REMINDER_HOUR = 9


# ---------- PDF договора ----------
# Необязательный путь к TTF-шрифту с кириллицей/узбекской латиницей.
# Если не задан — config/contract_pdf.py ищет по списку кандидатов
# (bundled static/fonts, системный DejaVu на Linux, Arial Unicode на macOS).
CONTRACT_PDF_FONT_PATH = os.getenv('CONTRACT_PDF_FONT_PATH', '').strip() or None
CONTRACT_PDF_FONT_BOLD_PATH = (
    os.getenv('CONTRACT_PDF_FONT_BOLD_PATH', '').strip() or None
)
