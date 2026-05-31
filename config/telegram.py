"""Тонкая обёртка над Telegram Bot API на urllib (без зависимостей)."""
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

API_BASE = 'https://api.telegram.org'


class TelegramNotConfigured(RuntimeError):
    pass


def _token() -> str:
    token = (getattr(settings, 'TELEGRAM_BOT_TOKEN', '') or '').strip()
    if not token:
        raise TelegramNotConfigured('TELEGRAM_BOT_TOKEN не задан в окружении.')
    return token


def send_message(chat_id, text: str, parse_mode: str = 'HTML', timeout: float = 10.0):
    """Отправить сообщение в Telegram. Возвращает (ok: bool, body: dict|str).

    Никогда не падает наружу: сетевые/HTTP-ошибки ловятся и возвращаются как
    (False, описание).
    """
    try:
        token = _token()
    except TelegramNotConfigured as e:
        return False, str(e)

    url = f'{API_BASE}/bot{token}/sendMessage'
    payload = json.dumps({
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode,
        'disable_web_page_preview': True,
    }).encode('utf-8')
    req = urllib.request.Request(
        url, data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode('utf-8'))
            return bool(body.get('ok')), body
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode('utf-8'))
        except Exception:
            err_body = {'description': f'HTTP {e.code}'}
        logger.warning('Telegram HTTP %s: %s', e.code, err_body)
        return False, err_body
    except urllib.error.URLError as e:
        logger.warning('Telegram network error: %s', e)
        return False, {'description': f'URLError: {e.reason}'}
    except Exception as e:  # noqa: BLE001
        logger.exception('Telegram unexpected error')
        return False, {'description': repr(e)}
