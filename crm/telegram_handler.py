from typing import Optional, Dict, Any

from .models import Client, ClientMessage


def find_client_by_telegram(username: str) -> Optional[Client]:
    """
    Поиск клиента по Telegram-username.

    1. Нормализуем username: убираем ведущий '@'.
    2. Ищем по Client.telegram:
       - сначала по 'USER_NAME'
       - потом по '@USER_NAME'
    """
    if not username:
        return None

    normalized_username = username.lstrip("@")

    client = (
        Client.objects.filter(telegram__iexact=normalized_username).first()
        or Client.objects.filter(telegram__iexact="@" + normalized_username).first()
    )

    return client


def handle_telegram_payload(
    username: Optional[str],
    text: Optional[str],
    chat_id: Optional[int] = None,
    raw_update: Optional[Dict[str, Any]] = None,
) -> Optional[ClientMessage]:
    """
    Обработка входящего сообщения Telegram, уже приведённого
    к простому payload'у с полями username, text и chat_id.

    Используется HTTP-эндпоинтом локальной CRM, в которую внешний
    Telegram-бот (на другом сервере / в другом проекте) шлёт JSON.

    Алгоритм:

    1. Если нет текста — считаем, что нам нечего сохранять.
    2. Если нет username — клиента по Telegram найти не сможем -> выходим.
    3. Ищем клиента по username (см. find_client_by_telegram).
    4. Если клиент найден — создаём ClientMessage.
    """

    if not text:
        print("[Telegram] Пустой текст сообщения, сохранение не требуется")
        return None

    if not username:
        # У пользователя может не быть username – тогда пока не привязываем
        print("[Telegram] Сообщение без username, клиент не может быть найден")
        return None

    client = find_client_by_telegram(username)
    if client is None:
        print(f"[Telegram] Клиент не найден для user @{username.lstrip('@')}")
        return None

    external_id = None
    # В external_id можно сохранить chat_id или @username (для отладки).
    if chat_id is not None:
        external_id = str(chat_id)
    else:
        external_id = f"@{username.lstrip('@')}"

    msg = ClientMessage.objects.create(
        client=client,
        sender="CLIENT",
        channel="TELEGRAM",
        external_id=external_id,
        text=text,
    )

    print(
        f"[Telegram] Сообщение от @{username.lstrip('@')} "
        f"привязано к клиенту {client.full_name} (ClientMessage #{msg.id})"
    )

    return msg