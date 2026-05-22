from email.utils import parseaddr
from email.header import decode_header

from django.utils import timezone
from django.contrib.auth.models import User

from .models import Client, ClientEmail, Notification


def decode_mime_header(value: str) -> str:
    """
    Декодирует строку вида '=?UTF-8?B?...?=' в обычный текст.
    """
    if not value:
        return ""
    decoded = decode_header(value)
    parts = []
    for text, enc in decoded:
        if isinstance(text, bytes):
            try:
                parts.append(text.decode(enc or 'utf-8', errors='ignore'))
            except Exception:
                parts.append(text.decode('utf-8', errors='ignore'))
        else:
            parts.append(text)
    return " ".join(parts).strip()


def process_incoming_email(from_addr: str, subject: str, body: str, received_at=None):
    """
    from_addr: строка вида "Имя <email@example.com>" или просто "email@example.com"
    subject: уже декодированная тема
    body: текст письма
    received_at: datetime (если None, используем now())
    """

    # 1. Разбор From
    name_raw, email_addr = parseaddr(from_addr)
    email_addr = (email_addr or "").strip().lower()

    if not email_addr:
        print("[Email] Не удалось извлечь email из from_addr:", from_addr)
        return

    # Декодируем имя отправителя (если оно было в MIME-формате)
    name = decode_mime_header(name_raw)

    # 2. Ищем существующего клиента по email
    client = Client.objects.filter(email__iexact=email_addr).first()

    # 3. Если нет – создаём нового клиента
    if client is None:
        admin_user = User.objects.filter(username='Admin', is_superuser=True).first()

        client = Client.objects.create(
            full_name=name or email_addr,  # если имени нет, используем email
            phone='',
            email=email_addr,
            telegram='',
            whatsapp='',
            responsible=admin_user,  # может быть None, если Admin не найден
        )
        print(f"[Email] Создан новый клиент для email {email_addr}: {client.full_name}")

    # 4. Создаём запись письма
    if received_at is None:
        received_at = timezone.now()

    email_obj = ClientEmail.objects.create(
        client=client,
        from_address=email_addr,
        subject=subject or '',
        body=body or '',
        received_at=received_at,
    )

    print(f"[Email] Письмо от {email_addr} привязано к клиенту {client.full_name}")

    # 5. Создаём уведомление для ответственного менеджера
    responsible = getattr(client, 'responsible', None)
    if responsible:
        msg_text = f"Новое письмо от клиента: {client.full_name}"
        if subject:
            msg_text += f" (тема: {subject})"

        Notification.objects.create(
            user=responsible,
            type='EMAIL',
            client=client,
            client_email=email_obj,
            message=msg_text,
        )