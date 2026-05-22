import imaplib
import email
from email.header import decode_header
import time
import re
from html import unescape

from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

from crm.email_handler import process_incoming_email


def html_to_text(html: str) -> str:
    """
    Очень простое преобразование HTML в текст:
    - заменяет <br> и <p> на переводы строк,
    - убирает все остальные теги,
    - декодирует HTML-сущности (&nbsp; и т.п.),
    - чистит лишние пробелы.
    """
    if not html:
        return ""

    # переводы строк
    html = re.sub(r'(?i)<br\s*/?>', '\n', html)
    html = re.sub(r'(?i)</p>', '\n', html)

    # убрать все теги
    text = re.sub(r'<[^>]+>', '', html)

    # HTML-сущности (&nbsp; &amp; и т.п.)
    text = unescape(text)

    # убрать подряд идущие пробелы/переводы строк по краям
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join([line for line in lines if line])

    return text.strip()


class Command(BaseCommand):
    help = "Постоянно опрашивает IMAP и сохраняет новые письма как ClientEmail"

    def handle(self, *args, **options):
        host = getattr(settings, 'IMAP_HOST', None)
        port = getattr(settings, 'IMAP_PORT', 993)
        use_ssl = getattr(settings, 'IMAP_USE_SSL', True)
        username = getattr(settings, 'IMAP_USERNAME', None)
        password = getattr(settings, 'IMAP_PASSWORD', None)

        # Интервал опроса (в секундах), можно задать в settings.IMAP_POLL_INTERVAL
        poll_interval = getattr(settings, 'IMAP_POLL_INTERVAL', 10)

        if not all([host, username, password]):
            self.stderr.write(self.style.ERROR("IMAP настройки не заданы (HOST/USERNAME/PASSWORD)"))
            return

        self.stdout.write(self.style.SUCCESS(
            f"IMAP fetcher запущен. Сервер: {host}, папка: INBOX, интервал опроса: {poll_interval} сек."
        ))

        while True:
            mail = None
            try:
                self.stdout.write(self.style.NOTICE("Подключение к IMAP..."))

                # Подключаемся
                if use_ssl:
                    mail = imaplib.IMAP4_SSL(host, port)
                else:
                    mail = imaplib.IMAP4(host, port)

                mail.login(username, password)
                mail.select("INBOX")  # выбираем папку входящих

                # Ищем все непрочитанные письма (флаг UNSEEN)
                status, messages = mail.search(None, 'UNSEEN')
                if status != 'OK':
                    self.stderr.write(self.style.ERROR("Не удалось выполнить поиск писем"))
                    # даже если не удалось, всё равно разорвём соединение и подождём
                    continue

                msg_nums = messages[0].split()
                self.stdout.write(self.style.SUCCESS(f"Найдено новых писем: {len(msg_nums)}"))

                for num in msg_nums:
                    status, msg_data = mail.fetch(num, "(RFC822)")
                    if status != 'OK':
                        self.stderr.write(self.style.ERROR(f"Не удалось получить письмо {num}"))
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    # From
                    from_addr = msg.get("From", "")

                    # Subject (с декодированием)
                    subject_raw = msg.get("Subject", "")
                    subject = ""
                    if subject_raw:
                        decoded = decode_header(subject_raw)
                        parts = []
                        for text, enc in decoded:
                            if isinstance(text, bytes):
                                encoding = (enc or 'utf-8').lower()
                                if encoding in ('unknown-8bit', 'x-unknown'):
                                    encoding = 'utf-8'
                                try:
                                    parts.append(text.decode(encoding, errors='ignore'))
                                except LookupError:
                                    parts.append(text.decode('utf-8', errors='ignore'))
                            else:
                                parts.append(text)
                        subject = " ".join(parts).strip()

                    # Дата
                    date_raw = msg.get("Date")
                    received_at = timezone.now()
                    if date_raw:
                        try:
                            dt = email.utils.parsedate_to_datetime(date_raw)
                            if dt.tzinfo is None:
                                dt = timezone.make_aware(dt, timezone=timezone.utc)
                            received_at = dt.astimezone(timezone.get_current_timezone())
                        except Exception:
                            # если не смогли распарсить дату, используем now()
                            received_at = timezone.now()

                    # Тело письма
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            content_disposition = str(part.get("Content-Disposition", ""))

                            if content_type in ["text/plain", "text/html"] and "attachment" not in content_disposition:
                                charset = part.get_content_charset() or 'utf-8'
                                try:
                                    raw = part.get_payload(decode=True).decode(charset, errors='ignore')
                                except Exception:
                                    raw = part.get_payload(decode=True).decode('utf-8', errors='ignore')

                                if content_type == "text/html":
                                    body = html_to_text(raw)
                                else:
                                    body = raw

                                if body:
                                    break
                    else:
                        charset = msg.get_content_charset() or 'utf-8'
                        try:
                            raw = msg.get_payload(decode=True).decode(charset, errors='ignore')
                        except Exception:
                            raw = msg.get_payload(decode=True).decode('utf-8', errors='ignore')

                        if msg.get_content_type() == "text/html":
                            body = html_to_text(raw)
                        else:
                            body = raw

                    # Обрабатываем письмо (создаёт клиента, ClientEmail и Notification)
                    try:
                        process_incoming_email(
                            from_addr=from_addr,
                            subject=subject,
                            body=body,
                            received_at=received_at,
                        )
                    except Exception as e:
                        self.stderr.write(self.style.ERROR(f"Ошибка при обработке письма {num}: {e}"))

                if mail is not None:
                    try:
                        mail.logout()
                    except Exception:
                        pass

                self.stdout.write(self.style.SUCCESS("Цикл обработки писем завершён."))

            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("Остановка IMAP fetcher (KeyboardInterrupt)."))
                break
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Ошибка при работе с IMAP: {e}"))
            finally:
                if mail is not None:
                    try:
                        mail.logout()
                    except Exception:
                        pass
                # Небольшая пауза перед следующим проходом
                time.sleep(poll_interval)