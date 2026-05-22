import requests
from django.conf import settings
from django.utils import timezone


class UISClientError(Exception):
    """Ошибка при запросе к UIS API."""
    pass


def normalize_phone(phone: str) -> str:
    """
    Простейшая нормализация телефона:
    - оставляем цифры и '+'
    - дальше можно улучшить по требованиям UIS
    """
    if not phone:
        return ""
    return "".join(ch for ch in phone if ch.isdigit() or ch == '+')


def start_outbound_call(manager_number: str, client_number: str) -> dict:
    """
    Инициирует исходящий звонок через UIS:
    - с номера/внутреннего менеджера manager_number
    - на номер клиента client_number

    Возвращает словарь с данными о звонке:
    {
        "call_id": "...",
        "started_at": datetime или None,
        ...
    }

    ВНИМАНИЕ: endpoint и формат тела запроса нужно взять из документации UIS
    и при необходимости поменять.
    """
    if not getattr(settings, 'UIS_API_BASE_URL', None):
        raise UISClientError("UIS_API_BASE_URL не задан в settings.")
    if not getattr(settings, 'UIS_API_KEY', None):
        raise UISClientError("UIS_API_KEY не задан в settings.")

    base_url = settings.UIS_API_BASE_URL.rstrip('/')

    # ЗАМЕНИ ЭТО на реальный путь из документации UIS
    url = f"{base_url}/api/v1/calls/outbound"  # примерный путь

    payload = {
        # имена полей нужно подстроить под UIS
        "from": manager_number,
        "to": client_number,
        "record": True,  # если у UIS есть флаг "записывать разговор"
    }

    headers = {
        "Authorization": f"Bearer {settings.UIS_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
    except requests.RequestException as e:
        raise UISClientError(f"Ошибка сети при запросе к UIS: {e}")

    if resp.status_code != 200:
        raise UISClientError(f"UIS вернул статус {resp.status_code}: {resp.text}")

    try:
        data = resp.json()
    except ValueError:
        raise UISClientError(f"UIS вернул не-JSON ответ: {resp.text}")

    # Здесь нужно подстроиться под реальный формат UIS.
    # Предположим, что UIS вернёт что-то вроде:
    # {"success": true, "call_id": "123", "started_at": "2025-05-01T12:34:56Z"}
    call_id = data.get("call_id") or data.get("id")
    if not call_id:
        raise UISClientError(f"UIS не вернул call_id. Ответ: {data}")

    started_at_raw = data.get("started_at")
    started_at = None
    if started_at_raw:
        # ПАРСИНГ ДАТЫ: подстрой под формат UIS (ISO8601, timestamp и т.п.)
        try:
            started_at = timezone.datetime.fromisoformat(started_at_raw.replace("Z", "+00:00"))
            if timezone.is_naive(started_at):
                started_at = timezone.make_aware(started_at, timezone=timezone.utc)
        except Exception:
            started_at = None

    return {
        "call_id": call_id,
        "started_at": started_at,
        "raw": data,
    }