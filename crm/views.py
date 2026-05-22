from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, Count, Case, When, Value, IntegerField, Max
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET
from django.utils.html import strip_tags
from django.urls import reverse

from .models import (
    Client,
    ClientContact,
    ClientNote,
    CallTask,
    ClientMessage,
    ClientEmail,
    Notification,
    CallLog,
    InternalMessage,
    InternalAttachment, 
)
from .forms import ClientForm

import io
try:
    import qrcode
except ImportError:
    qrcode = None

import csv
import io as pyio
from datetime import datetime
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required

from .telegram_handler import handle_telegram_payload

User = get_user_model()

BUYER_PIPELINE = [
    ('B_COLD', 'Холодный контакт'),
    ('B_NEEDS', 'Выявление потребности'),
    ('B_OFFER', 'Предложение'),
    ('B_PAYMENT', 'Оплата'),
    ('B_DELIVERY', 'Исполнение'),
]

BUILDER_PIPELINE = [
    ('BU_COLD', 'Холодный контакт'),
    ('BU_CONTACT', 'Контакт'),
    ('BU_TASKS', 'Выявление задач'),
    ('BU_KP', 'КП'),
    ('BU_FIRST_CONTRACT', 'Первый договор'),
    ('BU_SUPPORT', 'Сопровождение и удержание'),
]


# --- Telegram webhook (локальный приёмник) ---

@csrf_exempt
@require_http_methods(["POST"])
def telegram_incoming(request):
    """
    HTTP-эндпоинт для приёма сообщений от внешнего Telegram-бота.

    Ожидаемый JSON от бота:

    {
        "username": "some_user",
        "text": "Привет",
        "chat_id": 123456789,
        "raw_update": {...}
    }
    """
    import json

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({"status": "error", "error": "invalid_json"}, status=400)

    username = payload.get("username")
    text = payload.get("text")
    chat_id = payload.get("chat_id")
    raw_update = payload.get("raw_update")

    msg = None
    try:
        msg = handle_telegram_payload(
            username=username,
            text=text,
            chat_id=chat_id,
            raw_update=raw_update,
        )
    except Exception as e:
        print(f"[Telegram] Ошибка обработки webhook-пейлоада: {e}")
        return JsonResponse({"status": "error", "error": "internal_error"}, status=500)

    if msg is None:
        return JsonResponse({"status": "no_client_or_no_message"}, status=200)

    return JsonResponse(
        {
            "status": "ok",
            "client_id": msg.client_id,
            "message_id": msg.id,
        }
    )


def debug_settings(request):
    return JsonResponse({
        "DEBUG": settings.DEBUG,
        "ALLOWED_HOSTS": settings.ALLOWED_HOSTS,
        "CSRF_TRUSTED_ORIGINS": getattr(settings, "CSRF_TRUSTED_ORIGINS", []),
    })


def _normalize_contact(value: str) -> str:
    if value is None:
        return ''
    v = value.strip()
    if '@' in v:
        return v.lower()
    if any(ch.isdigit() for ch in v):
        allowed = set('0123456789+')
        return ''.join(ch for ch in v if ch in allowed)
    return v.lower()


def _gather_all_contacts_for_client(client: Client):
    contacts = set()

    for v in [client.phone, client.email, client.telegram, client.whatsapp]:
        if v:
            contacts.add(_normalize_contact(v))

    for ec in ClientContact.objects.filter(client=client):
        if ec.value:
            contacts.add(_normalize_contact(ec.value))

    return contacts


def _find_conflicting_clients_for_value(current_client: Client, raw_value: str):
    norm = _normalize_contact(raw_value)
    if not norm:
        return []

    main_q = (
        Q(phone__isnull=False, phone__iexact=raw_value) |
        Q(email__isnull=False, email__iexact=raw_value) |
        Q(telegram__isnull=False, telegram__iexact=raw_value) |
        Q(whatsapp__isnull=False, whatsapp__iexact=raw_value)
    )

    other_clients_ids_from_extra = list(
        ClientContact.objects
        .filter(value__iexact=raw_value)
        .values_list('client_id', flat=True)
    )

    qs = Client.objects.filter(
        Q(id__in=other_clients_ids_from_extra) | main_q
    ).exclude(id=current_client.id).select_related('responsible').distinct()

    if qs.count() == 0:
        all_clients = Client.objects.exclude(id=current_client.id).select_related('responsible')
        conflict_ids = []
        for cl in all_clients:
            all_c = _gather_all_contacts_for_client(cl)
            if norm in all_c:
                conflict_ids.append(cl.id)
        if conflict_ids:
            qs = Client.objects.filter(id__in=conflict_ids).select_related('responsible')

    return list(qs)


@login_required
def dashboard(request):
    user = request.user

    my_clients_count = Client.objects.filter(responsible=user).count()

    now = timezone.now()
    overdue_count = CallTask.objects.filter(
        assigned_to=user,
        status='PLANNED',
        planned_at__lt=now
    ).count()

    today_count = CallTask.objects.filter(
        assigned_to=user,
        status='PLANNED',
        planned_at__date=now.date()
    ).count()

    upcoming_tasks = CallTask.objects.filter(
        assigned_to=user,
        status='PLANNED',
        planned_at__gte=now
    ).order_by('planned_at')[:10]

    notifications = list(
        Notification.objects.filter(
            user=user,
            is_read=False
        ).select_related('client').order_by('-created_at')
    )

    context = {
        'my_clients_count': my_clients_count,
        'overdue_count': overdue_count,
        'today_count': today_count,
        'upcoming_tasks': upcoming_tasks,
        'notifications': notifications,
    }
    return render(request, 'crm/dashboard.html', context)


@login_required
def client_list(request):
    query = request.GET.get('q')
    manager_id = request.GET.get('manager')
    client_type = request.GET.get('client_type', '').strip()
    pipeline_stage = request.GET.get('pipeline_stage', '').strip()

    if request.user.is_superuser:
        clients = Client.objects.all()
    else:
        clients = Client.objects.filter(responsible=request.user)

    selected_manager = None
    managers = None
    if request.user.is_superuser:
        managers = User.objects.filter(is_active=True).order_by('username')

        if manager_id:
            try:
                selected_manager = User.objects.get(pk=manager_id)
                clients = clients.filter(responsible=selected_manager)
            except User.DoesNotExist:
                selected_manager = None

    if query:
        clients = clients.filter(
            Q(full_name__icontains=query) |
            Q(phone__icontains=query)
        )

    if client_type in ['BUYER', 'BUILDER']:
        clients = clients.filter(client_type=client_type)

    if pipeline_stage:
        clients = clients.filter(pipeline_stage=pipeline_stage)

    clients = clients.order_by('full_name')

    if client_type == 'BUILDER':
        available_pipeline_stages = BUILDER_PIPELINE
    elif client_type == 'BUYER':
        available_pipeline_stages = BUYER_PIPELINE
    else:
        available_pipeline_stages = BUYER_PIPELINE + BUILDER_PIPELINE

    context = {
        'clients': clients,
        'query': query,
        'managers': managers,
        'selected_manager': selected_manager,
        'manager_id': manager_id,
        'client_type': client_type,
        'pipeline_stage': pipeline_stage,
        'pipeline_stages': available_pipeline_stages,
    }
    return render(request, 'crm/client_list.html', context)


@login_required
def start_client_call(request, pk):
    client = get_object_or_404(Client, pk=pk)

    dialed_number = (request.GET.get('number') or client.phone or '').strip()

    call_log = CallLog.objects.create(
        client=client,
        user=request.user,
        call_type='OUT',
        started_at=timezone.now(),
        dialed_number=dialed_number or None,
    )

    display_number = dialed_number or client.phone or "(номер не указан)"

    ClientNote.objects.create(
        client=client,
        note_type='CALL',
        meta_type='SYSTEM',
        text=f"Инициирован звонок (лог #{call_log.id}) на номер {display_number}.",
        author=request.user,
    )

    messages.success(request, f"Звонок на {display_number} зафиксирован в системе.")
    return redirect('crm:client_detail', pk=client.pk)


@login_required
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)

    notif_client_id = request.GET.get('notif_client')
    if notif_client_id and str(client.id) == str(notif_client_id):
        Notification.objects.filter(
            user=request.user,
            client=client,
            is_read=False
        ).update(is_read=True)

    all_users = User.objects.all().order_by('username')
    now = timezone.now()

    if client.client_type == 'BUILDER':
        pipeline = BUILDER_PIPELINE
    else:
        pipeline = BUYER_PIPELINE

    conflict_contact_client_ids = set()

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'transfer_client':
            new_responsible_id = request.POST.get('new_responsible')
            transfer_comment = request.POST.get('transfer_comment', '').strip()

            if not new_responsible_id:
                messages.error(request, "Не выбран новый ответственный менеджер.")
                return redirect('crm:client_detail', pk=client.pk)

            try:
                new_responsible = User.objects.get(pk=new_responsible_id)
            except User.DoesNotExist:
                messages.error(request, "Выбранный менеджер не найден.")
                return redirect('crm:client_detail', pk=client.pk)

            old_responsible = client.responsible

            if new_responsible != old_responsible:
                with transaction.atomic():
                    client.responsible = new_responsible
                    client.save(update_fields=['responsible'])

                    CallTask.objects.filter(
                        client=client,
                        status='PLANNED',
                        assigned_to=old_responsible,
                    ).update(assigned_to=new_responsible)

                    text = f"Клиент передан пользователю {new_responsible.username}."
                    if transfer_comment:
                        text += f" Комментарий: {transfer_comment}"

                    ClientNote.objects.create(
                        client=client,
                        note_type='TRANSFER',
                        meta_type='SYSTEM',
                        text=text,
                        author=request.user
                    )

                    Notification.objects.create(
                        user=new_responsible,
                        type='TRANSFER',
                        client=client,
                        message=f"Вам передан новый клиент: {client.full_name}"
                    )

                messages.success(
                    request,
                    f"Клиент успешно передан пользователю {new_responsible.username}."
                )
            else:
                messages.info(request, "Вы выбрали того же ответственного, изменения не внесены.")

            return redirect('crm:client_detail', pk=client.pk)

        elif action == 'add_task':
            planned_at_str = request.POST.get('planned_at')
            comment = request.POST.get('comment', '').strip()
            task_type = request.POST.get('task_type') or 'CALL'

            if not planned_at_str:
                messages.error(request, "Не указаны дата и время задачи.")
                return redirect('crm:client_detail', pk=client.pk)

            try:
                planned_at = timezone.make_aware(
                    timezone.datetime.fromisoformat(planned_at_str)
                )
            except Exception:
                messages.error(request, "Некорректный формат даты/времени.")
                return redirect('crm:client_detail', pk=client.pk)

            CallTask.objects.create(
                client=client,
                assigned_to=request.user,
                planned_at=planned_at,
                comment=comment,
                status='PLANNED',
                task_type=task_type,
            )

            messages.success(request, "Задача успешно создана.")
            return redirect('crm:client_detail', pk=client.pk)

        elif action == 'add_note':
            text = request.POST.get('text', '').strip()

            if not text:
                messages.error(request, "Текст заметки не может быть пустым.")
                return redirect('crm:client_detail', pk=client.pk)

            note = ClientNote.objects.create(
                client=client,
                note_type='NOTE',
                meta_type='ENTRY',
                text=text,
                author=request.user
            )

            ClientNote.objects.create(
                client=client,
                note_type='NOTE',
                meta_type='SYSTEM',
                text=f"Создана заметка #{note.id}.",
                author=request.user
            )

            messages.success(request, "Заметка добавлена.")
            return redirect('crm:client_detail', pk=client.pk)

        elif action == 'complete_task':
            task_id = request.POST.get('task_id')
            if not task_id:
                messages.error(request, "Не указана задача для завершения.")
                return redirect('crm:client_detail', pk=client.pk)

            try:
                task = CallTask.objects.get(pk=task_id, client=client)
            except CallTask.DoesNotExist:
                messages.error(request, "Задача не найдена.")
                return redirect('crm:client_detail', pk=client.pk)

            task.status = 'DONE'
            task.save(update_fields=['status'])

            ClientNote.objects.create(
                client=client,
                note_type='CALL',
                meta_type='SYSTEM',
                text=f"Задача #{task.id} выполнена. {task.comment or ''}",
                author=request.user
            )

            messages.success(request, "Задача отмечена как выполненная.")
            return redirect('crm:client_detail', pk=client.pk)

        elif action == 'send_email_reply':
            email_subject = request.POST.get('email_subject', '').strip()
            email_body = request.POST.get('email_body', '').strip()

            selected_email = (request.POST.get('email_to') or '').strip() or (client.email or '').strip()

            if not selected_email:
                messages.error(request, "Не выбран email для отправки.")
                return redirect('crm:client_detail', pk=client.pk)

            if not email_body:
                messages.error(request, "Текст письма не может быть пустым.")
                return redirect('crm:client_detail', pk=client.pk)

            first_name = (request.user.first_name or "").strip()
            last_name = (request.user.last_name or "").strip()

            if first_name or last_name:
                signature_name = (first_name + " " + last_name).strip()
            else:
                signature_name = request.user.username

            signature_html = f"<br><br><hr><p>{signature_name}</p>"

            if signature_name not in email_body:
                html_body = email_body + signature_html
            else:
                html_body = email_body

            text_body = strip_tags(html_body)

            attachments = request.FILES.getlist('attachments')

            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
            if not from_email:
                messages.error(request, "DEFAULT_FROM_EMAIL не задан в settings, отправка невозможна.")
                return redirect('crm:client_detail', pk=client.pk)

            try:
                msg = EmailMultiAlternatives(
                    subject=email_subject or '',
                    body=text_body or '',
                    from_email=from_email,
                    to=[selected_email],
                )

                msg.attach_alternative(html_body or '', "text/html")

                for f in attachments:
                    msg.attach(f.name, f.read(), f.content_type)

                msg.send()

                ClientEmail.objects.create(
                    client=client,
                    from_address=from_email,
                    subject=email_subject or '',
                    body=html_body or '',
                    received_at=timezone.now(),
                    direction='OUT',
                )

                ClientNote.objects.create(
                    client=client,
                    author=request.user,
                    note_type='EMAIL',
                    meta_type='SYSTEM',
                    text=f"Отправлено письмо клиенту на {selected_email}. Тема: {email_subject or '(без темы)'}",
                )

                messages.success(request, "Письмо отправлено клиенту.")
            except Exception as e:
                messages.error(request, f"Ошибка при отправке письма: {e}")

            # для AJAX-запроса мы не делаем redirect в JS, но здесь оставляем redirect для обычных запросов
            return redirect('crm:client_detail', pk=client.pk)

        elif action == 'finish_call':
            call_log_id = request.POST.get('call_log_id')
            if not call_log_id:
                messages.error(request, "Не указан идентификатор звонка.")
                return redirect('crm:client_detail', pk=client.pk)

            try:
                call_log = CallLog.objects.get(pk=call_log_id, client=client)
            except CallLog.DoesNotExist:
                messages.error(request, "Звонок не найден.")
                return redirect('crm:client_detail', pk=client.pk)

            if call_log.ended_at is not None:
                messages.info(request, "Этот звонок уже завершён.")
                return redirect('crm:client_detail', pk=client.pk)

            now_dt = timezone.now()
            call_log.ended_at = now_dt
            if call_log.started_at:
                delta = now_dt - call_log.started_at
                call_log.duration_seconds = int(delta.total_seconds())

            recording_file = request.FILES.get('call_recording')
            if recording_file:
                call_log.recording = recording_file

            call_log.save(update_fields=['ended_at', 'duration_seconds', 'recording'])

            ClientNote.objects.create(
                client=client,
                note_type='CALL',
                meta_type='SYSTEM',
                text=f"Звонок (лог #{call_log.id}) завершён. Длительность: {call_log.duration_seconds or 0} сек.",
                author=request.user
            )

            messages.success(request, "Звонок завершён и сохранён в карточке клиента.")
            return redirect('crm:client_detail', pk=client.pk)

        elif action == 'set_preferred_contact':
            new_type = request.POST.get('contact_type')
            if new_type not in ['PHONE', 'EMAIL', 'TELEGRAM', 'WHATSAPP']:
                messages.error(request, "Некорректный тип связи.")
                return redirect('crm:client_detail', pk=client.pk)

            contact_labels = dict(Client.CONTACT_TYPE_CHOICES)
            old_type = client.preferred_contact
            client.preferred_contact = new_type
            client.save(update_fields=['preferred_contact'])

            old_label = contact_labels.get(old_type, "не задан")
            new_label = contact_labels.get(new_type, new_type)

            ClientNote.objects.create(
                client=client,
                note_type='SYSTEM',
                meta_type='SYSTEM',
                text=f"Изменён приоритетный тип связи: {old_label} → {new_label}.",
                author=request.user
            )

            messages.success(request, "Приоритетный тип связи обновлён.")
            return redirect('crm:client_detail', pk=client.pk)

        elif action == 'add_contact':
            contact_type = request.POST.get('extra_contact_type') or 'OTHER'
            value = (request.POST.get('extra_contact_value') or '').strip()
            comment = (request.POST.get('extra_contact_comment') or '').strip()

            if not value:
                messages.error(request, "Контакт не может быть пустым.")
                return redirect('crm:client_detail', pk=client.pk)

            conflicts = _find_conflicting_clients_for_value(client, value)
            if conflicts:
                ec = ClientContact.objects.create(
                    client=client,
                    contact_type=contact_type,
                    value=value,
                    comment=comment or None,
                )
                conflict_contact_client_ids.add(ec.id)

                for other_client in conflicts:
                    if other_client.responsible and other_client.responsible != request.user:
                        Notification.objects.create(
                            user=other_client.responsible,
                            type='SYSTEM',
                            client=other_client,
                            message=(
                                f"Другой менеджер ({request.user.username}) добавил клиента "
                                f"с контактными данными, совпадающими с вашим клиентом "
                                f"({other_client.full_name}). Контакт: {value}"
                            )
                        )

                messages.warning(
                    request,
                    "Добавлен дополнительный контакт, но он уже встречается у другого клиента. "
                    "Проверьте дубликаты."
                )
            else:
                made_primary = False

                if contact_type == 'PHONE' and not (client.phone or '').strip():
                    client.phone = value
                    client.save(update_fields=['phone'])
                    made_primary = True
                elif contact_type == 'EMAIL' and not (client.email or '').strip():
                    client.email = value
                    client.save(update_fields=['email'])
                    made_primary = True
                elif contact_type == 'TELEGRAM' and not (client.telegram or '').strip():
                    client.telegram = value
                    client.save(update_fields=['telegram'])
                    made_primary = True
                elif contact_type == 'WHATSAPP' and not (client.whatsapp or '').strip():
                    client.whatsapp = value
                    client.save(update_fields=['whatsapp'])
                    made_primary = True

                if made_primary:
                    ClientNote.objects.create(
                        client=client,
                        note_type='SYSTEM',
                        meta_type='SYSTEM',
                        text=f"Установлен основной контакт ({contact_type}): {value}. Комментарий: {comment or '-'}",
                        author=request.user
                    )
                    messages.success(request, "Контакт добавлен как основной.")
                else:
                    ClientContact.objects.create(
                        client=client,
                        contact_type=contact_type,
                        value=value,
                        comment=comment or None,
                    )

                    ClientNote.objects.create(
                        client=client,
                        note_type='SYSTEM',
                        meta_type='SYSTEM',
                        text=f"Добавлен дополнительный контакт ({contact_type}): {value}. Комментарий: {comment or '-'}",
                        author=request.user
                    )

                    messages.success(request, "Дополнительный контакт добавлен.")

            return redirect('crm:client_detail', pk=client.pk)

        elif action == 'make_primary_contact':
            contact_id = request.POST.get('contact_id')
            if not contact_id:
                messages.error(request, "Не указан контакт.")
                return redirect('crm:client_detail', pk=client.pk)

            try:
                ec = ClientContact.objects.get(pk=contact_id, client=client)
            except ClientContact.DoesNotExist:
                messages.error(request, "Контакт не найден.")
                return redirect('crm:client_detail', pk=client.pk)

            field_map = {
                'PHONE': 'phone',
                'EMAIL': 'email',
                'TELEGRAM': 'telegram',
                'WHATSAPP': 'whatsapp',
            }
            field_name = field_map.get(ec.contact_type)

            if not field_name:
                messages.error(request, "Этот тип контакта нельзя сделать основным.")
                return redirect('crm:client_detail', pk=client.pk)

            old_value = getattr(client, field_name, None)
            setattr(client, field_name, ec.value)
            client.save(update_fields=[field_name])

            ClientNote.objects.create(
                client=client,
                note_type='SYSTEM',
                meta_type='SYSTEM',
                text=(
                    f"Сделан основным контакт ({ec.contact_type}): {ec.value}. "
                    f"Комментарий: {ec.comment or '-' }"
                    + (f" (старое значение: {old_value})" if old_value else "")
                ),
                author=request.user
            )

            messages.success(request, "Контакт сделан основным.")
            return redirect('crm:client_detail', pk=client.pk)

        elif action == 'delete_contact':
            contact_id = request.POST.get('contact_id')
            if not contact_id:
                messages.error(request, "Не указан контакт для удаления.")
                return redirect('crm:client_detail', pk=client.pk)

            try:
                ec = ClientContact.objects.get(pk=contact_id, client=client)
            except ClientContact.DoesNotExist:
                messages.error(request, "Контакт не найден.")
                return redirect('crm:client_detail', pk=client.pk)

            value = ec.value
            ctype = ec.contact_type
            ec.delete()

            ClientNote.objects.create(
                client=client,
                note_type='SYSTEM',
                meta_type='SYSTEM',
                text=f"Удалён дополнительный контакт ({ctype}): {value}.",
                author=request.user
            )

            messages.success(request, "Дополнительный контакт удалён.")
            return redirect('crm:client_detail', pk=client.pk)

        elif action == 'update_client_type':
            new_type = request.POST.get('client_type')
            if new_type not in ['BUYER', 'BUILDER']:
                messages.error(request, "Некорректный тип клиента.")
                return redirect('crm:client_detail', pk=client.pk)

            if new_type != client.client_type:
                old_label = dict(Client.CLIENT_TYPE_CHOICES).get(client.client_type, 'не указан')
                new_label = dict(Client.CLIENT_TYPE_CHOICES).get(new_type, new_type)

                client.client_type = new_type
                client.pipeline_stage = None
                client.save(update_fields=['client_type', 'pipeline_stage'])

                ClientNote.objects.create(
                    client=client,
                    note_type='SYSTEM',
                    meta_type='SYSTEM',
                    text=f"Изменён тип клиента: {old_label} → {new_label}. Этап воронки сброшен.",
                    author=request.user
                )

                messages.success(request, "Тип клиента обновлён, этап воронки сброшен.")
            return redirect('crm:client_detail', pk=client.pk)

        elif action == 'update_pipeline_stage':
            new_stage = request.POST.get('pipeline_stage')

            valid_stages = [code for code, _ in (BUILDER_PIPELINE if client.client_type == 'BUILDER' else BUYER_PIPELINE)]
            if new_stage not in valid_stages:
                messages.error(request, "Некорректный этап воронки.")
                return redirect('crm:client_detail', pk=client.pk)

            old_stage_code = client.pipeline_stage
            client.pipeline_stage = new_stage
            client.save(update_fields=['pipeline_stage'])

            def stage_label(client_obj, code):
                if not code:
                    return 'не задан'
                pipe = BUILDER_PIPELINE if client_obj.client_type == 'BUILDER' else BUYER_PIPELINE
                return dict(pipe).get(code, code)

            old_label = stage_label(client, old_stage_code)
            new_label = stage_label(client, new_stage)

            ClientNote.objects.create(
                client=client,
                note_type='SYSTEM',
                meta_type='SYSTEM',
                text=f"Изменён этап воронки: {old_label} → {new_label}.",
                author=request.user
            )

            messages.success(request, "Этап воронки обновлён.")
            return redirect('crm:client_detail', pk=client.pk)

        elif action == 'send_telegram_reply':
            # --- ОТВЕТ В TELEGRAM ЧЕРЕЗ ШЛЮЗ ---
            reply_text = (request.POST.get('telegram_reply_text') or '').strip()
            if not reply_text:
                messages.error(request, "Текст ответа в Telegram не может быть пустым.")
                return redirect('crm:client_detail', pk=client.pk)

            # Пытаемся взять последний chat_id из истории Telegram сообщений
            last_msg = ClientMessage.objects.filter(
                client=client,
                channel="TELEGRAM",
                external_id__isnull=False,
            ).order_by('-created_at').first()

            if not last_msg:
                messages.error(
                    request,
                    "Не найдено ни одного Telegram-сообщения с этим клиентом (нет chat_id)."
                )
                return redirect('crm:client_detail', pk=client.pk)

            try:
                chat_id = int(last_msg.external_id)
            except (TypeError, ValueError):
                messages.error(request, "Некорректный chat_id в истории сообщений.")
                return redirect('crm:client_detail', pk=client.pk)

            gateway_url = getattr(settings, 'TG_GATEWAY_URL', '').rstrip('/')
            if not gateway_url:
                messages.error(
                    request,
                    "TG_GATEWAY_URL не задан в settings, отправка в Telegram невозможна."
                )
                return redirect('crm:client_detail', pk=client.pk)

            send_url = f"{gateway_url}/send-message"

            import requests
            import json as pyjson

            try:
                resp = requests.post(
                    send_url,
                    data=pyjson.dumps({"chat_id": chat_id, "text": reply_text}),
                    headers={"Content-Type": "application/json"},
                    timeout=5,
                )
            except Exception as e:
                messages.error(request, f"Ошибка при отправке в Telegram-гейтвей: {e}")
                return redirect('crm:client_detail', pk=client.pk)

            # Фиксируем исходящее сообщение в истории диалога
            ClientMessage.objects.create(
                client=client,
                sender="MANAGER",
                channel="TELEGRAM",
                external_id=str(chat_id),
                text=reply_text,
            )

            messages.success(request, "Ответ отправлен клиенту в Telegram.")
            return redirect('crm:client_detail', pk=client.pk)

        else:
            messages.error(request, "Неизвестное действие.")
            return redirect('crm:client_detail', pk=client.pk)

    tasks_qs = CallTask.objects.filter(client=client).select_related('assigned_to')
    tasks = tasks_qs.annotate(
        sort_status=Case(
            When(status='PLANNED', planned_at__lt=now, then=Value(0)),
            When(status='PLANNED', planned_at__gte=now, then=Value(1)),
            When(status='DONE', then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        )
    ).order_by('sort_status', 'planned_at')

    client_notes = ClientNote.objects.filter(
        client=client,
        note_type='NOTE',
        meta_type='ENTRY',
        is_deleted=False,
    ).select_related('author').order_by('-pinned', '-created_at')

    history_notes = ClientNote.objects.filter(
        client=client
    ).exclude(
        note_type='NOTE',
        meta_type='ENTRY',
        is_deleted=True
    ).select_related('author').order_by('-created_at')

    dialog_messages = ClientMessage.objects.filter(client=client).order_by('created_at')
    emails = ClientEmail.objects.filter(client=client).order_by('-received_at')
    calls = CallLog.objects.filter(client=client).select_related('user').order_by('-created_at')[:10]

    active_call = CallLog.objects.filter(
        client=client,
        ended_at__isnull=True
    ).order_by('-started_at').first()

    extra_contacts = ClientContact.objects.filter(client=client).order_by('created_at')

    conflict_extra_ids = set()
    for ec in extra_contacts:
        conflicts = _find_conflicting_clients_for_value(client, ec.value)
        if conflicts:
            conflict_extra_ids.add(ec.id)

    last_msg_id = dialog_messages.last().id if dialog_messages.exists() else None

    context = {
        'client': client,
        'all_users': all_users,
        'tasks': tasks,
        'client_notes': client_notes,
        'notes': history_notes,
        'dialog_messages': dialog_messages,
        'last_dialog_message_id': last_msg_id,
        'emails': emails,
        'now': now,
        'calls': calls,
        'active_call': active_call,
        'extra_contacts': extra_contacts,
        'pipeline': pipeline,
        'conflict_extra_ids': conflict_extra_ids,
    }
    return render(request, 'crm/client_detail.html', context)


@login_required
def note_toggle_pin(request, pk, note_id):
    client = get_object_or_404(Client, pk=pk)
    note = get_object_or_404(
        ClientNote,
        pk=note_id,
        client=client,
        note_type='NOTE',
        meta_type='ENTRY',
        is_deleted=False
    )

    if request.method != 'POST':
        return redirect('crm:client_detail', pk=client.pk)

    note.pinned = not note.pinned
    note.save(update_fields=['pinned'])

    ClientNote.objects.create(
        client=client,
        note_type='NOTE',
        meta_type='SYSTEM',
        text=f"{'Закреплена' if note.pinned else 'Откреплена'} заметка #{note.id}.",
        author=request.user
    )

    return redirect('crm:client_detail', pk=client.pk)


@login_required
def note_delete(request, pk, note_id):
    client = get_object_or_404(Client, pk=pk)
    note = get_object_or_404(
        ClientNote,
        pk=note_id,
        client=client,
        note_type='NOTE',
        meta_type='ENTRY',
        is_deleted=False
    )

    if request.method != 'POST':
        return redirect('crm:client_detail', pk=client.pk)

    note.is_deleted = True
    note.pinned = False
    note.save(update_fields=['is_deleted', 'pinned'])

    ClientNote.objects.create(
        client=client,
        note_type='NOTE',
        meta_type='SYSTEM',
        text=f"Заметка #{note.id} удалена.",
        author=request.user
    )

    messages.success(request, "Заметка удалена.")
    return redirect('crm:client_detail', pk=client.pk)


@login_required
def note_edit(request, pk, note_id):
    client = get_object_or_404(Client, pk=pk)
    note = get_object_or_404(
        ClientNote,
        pk=note_id,
        client=client,
        note_type='NOTE',
        meta_type='ENTRY',
        is_deleted=False
    )

    if request.method == 'POST':
        new_text = request.POST.get('text', '').strip()
        if not new_text:
            messages.error(request, "Текст заметки не может быть пустым.")
            return redirect('crm:client_detail', pk=client.pk)

        if new_text != note.text:
            note.text = new_text
            note.save(update_fields=['text'])

            ClientNote.objects.create(
                client=client,
                note_type='NOTE',
                meta_type='SYSTEM',
                text=f"Заметка #{note.id} отредактирована.",
                author=request.user
            )

            messages.success(request, "Заметка обновлена.")
        return redirect('crm:client_detail', pk=client.pk)

    context = {
        'client': client,
        'note': note,
    }
    return render(request, 'crm/note_edit.html', context)


@login_required
def client_create(request):
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            phone = (form.cleaned_data.get('phone') or '').strip()
            email = (form.cleaned_data.get('email') or '').strip()
            telegram = (form.cleaned_data.get('telegram') or '').strip()
            whatsapp = (form.cleaned_data.get('whatsapp') or '').strip()

            # Новые поля
            source = (form.cleaned_data.get('source') or '').strip()
            request_text = (form.cleaned_data.get('request_text') or '').strip()
            first_note = (form.cleaned_data.get('first_note') or '').strip()

            duplicate_q = Q()
            if phone:
                duplicate_q |= Q(phone__iexact=phone)
            if email:
                duplicate_q |= Q(email__iexact=email)
            if telegram:
                duplicate_q |= Q(telegram__iexact=telegram)
            if whatsapp:
                duplicate_q |= Q(whatsapp__iexact=whatsapp)

            duplicate_exists = False
            if duplicate_q:
                duplicate_exists = Client.objects.filter(duplicate_q).exists()
                if not duplicate_exists:
                    norm_values = set()
                    for v in [phone, email, telegram, whatsapp]:
                        if v:
                            norm_values.add(_normalize_contact(v))
                    if norm_values:
                        extra_conflict = (
                            ClientContact.objects.filter(
                                value__in=list(norm_values)
                            ).exists()
                        )
                        duplicate_exists = extra_conflict

            if duplicate_exists:
                messages.error(
                    request,
                    "Нельзя создать клиента: в системе уже есть клиент "
                    "с таким телефоном/email/мессенджером (основным или дополнительным). "
                    "С этим клиентом уже работает другой менеджер."
                )
                return render(request, 'crm/client_form.html', {'form': form})

            client = form.save(commit=False)
            if client.responsible is None:
                client.responsible = request.user

            ctype = client.client_type or 'BUYER'
            client.client_type = ctype
            if ctype == 'BUILDER':
                client.pipeline_stage = 'BU_COLD'
            else:
                client.pipeline_stage = 'B_COLD'

            # Сохраняем новые поля
            client.source = source or None
            client.request_text = request_text or None
            client.first_note = first_note or None

            client.save()

            # Создаём заметку с этой информацией
            note_parts = []
            if source:
                note_parts.append(f"Источник: {source}")
            if request_text:
                note_parts.append(f"Запрос: {request_text}")
            if first_note:
                note_parts.append(f"Примечание: {first_note}")

            if note_parts:
                ClientNote.objects.create(
                    client=client,
                    author=request.user,
                    note_type='NOTE',
                    meta_type='ENTRY',
                    text="\n".join(note_parts),
                )

            messages.success(request, "Клиент успешно создан.")
            return redirect('crm:client_detail', pk=client.pk)
    else:
        form = ClientForm(initial={'client_type': 'BUYER', 'responsible': request.user})

    context = {
        'form': form,
    }
    return render(request, 'crm/client_form.html', context)


@login_required
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)

    if not request.user.is_superuser and client.responsible != request.user:
        messages.error(request, "У вас нет прав редактировать этого клиента.")
        return redirect('crm:client_detail', pk=client.pk)

    if request.method == 'POST':
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            new_phone = (form.cleaned_data.get('phone') or '').strip()
            new_email = (form.cleaned_data.get('email') or '').strip()
            new_telegram = (form.cleaned_data.get('telegram') or '').strip()
            new_whatsapp = (form.cleaned_data.get('whatsapp') or '').strip()

            duplicate_q = Q()
            if new_phone:
                duplicate_q |= Q(phone__iexact=new_phone)
            if new_email:
                duplicate_q |= Q(email__iexact=new_email)
            if new_telegram:
                duplicate_q |= Q(telegram__iexact=new_telegram)
            if new_whatsapp:
                duplicate_q |= Q(whatsapp__iexect=new_whatsapp)

            if duplicate_q:
                other_main_conflict = Client.objects.filter(duplicate_q).exclude(id=client.id).exists()
                if other_main_conflict:
                    messages.error(
                        request,
                        "Нельзя сохранить изменения: в системе уже есть другой клиент "
                        "с такими основными контактными данными."
                    )
                    return render(request, 'crm/client_form.html', {'form': form, 'client': client})

                norm_values = set()
                for v in [new_phone, new_email, new_telegram, new_whatsapp]:
                    if v:
                        norm_values.add(_normalize_contact(v))
                if norm_values:
                    extra_conflict = (
                        ClientContact.objects
                        .filter(value__in=list(norm_values))
                        .exclude(client=client)
                        .exists()
                    )
                    if extra_conflict:
                        messages.error(
                            request,
                            "Нельзя сохранить изменения: эти контакты уже используются "
                            "как дополнительные у другого клиента."
                        )
                        return render(request, 'crm/client_form.html', {'form': form, 'client': client})

            form.save()
            messages.success(request, "Данные клиента обновлены.")
            return redirect('crm:client_detail', pk=client.pk)
    else:
        form = ClientForm(instance=client)

    context = {
        'form': form,
        'client': client,
    }
    return render(request, 'crm/client_form.html', context)


@login_required
def task_list(request):
    """
    Страница задач.
    GET  — показывает задачи пользователя.
    POST:
      - superuser + action=bulk_create_tasks: массовое создание задач;
      - action=complete_task_from_list: отметить задачу выполненной и остаться на странице.
    """
    user = request.user

    # Массовая постановка задач (модальное окно)
    if user.is_superuser and request.method == 'POST' and request.POST.get('action') == 'bulk_create_tasks':
        task_type = request.POST.get('task_type') or 'CALL'
        planned_at_str = request.POST.get('planned_at') or ''
        comment = (request.POST.get('comment') or '').strip()
        client_ids = request.POST.getlist('client_ids')

        if not client_ids:
            messages.error(request, "Не выбрано ни одного клиента для постановки задач.")
            return redirect('crm:task_list')

        if not planned_at_str:
            messages.error(request, "Не указаны дата и время задачи.")
            return redirect('crm:task_list')

        try:
            planned_at = timezone.make_aware(
                timezone.datetime.fromisoformat(planned_at_str)
            )
        except Exception:
            messages.error(request, "Некорректный формат даты/времени.")
            return redirect('crm:task_list')

        clients_qs = Client.objects.filter(id__in=client_ids).select_related('responsible')
        created_count = 0

        for client in clients_qs:
            assigned_to = client.responsible or user
            CallTask.objects.create(
                client=client,
                assigned_to=assigned_to,
                planned_at=planned_at,
                status='PLANNED',
                task_type=task_type,
                comment=comment,
            )
            created_count += 1

        messages.success(request, f"Создано задач: {created_count}.")
        return redirect('crm:task_list')

    # Отметить задачу выполненной из списка задач
    if request.method == 'POST' and request.POST.get('action') == 'complete_task_from_list':
        task_id = request.POST.get('task_id')
        if not task_id:
            messages.error(request, "Не указана задача для завершения.")
            return redirect('crm:task_list')

        try:
            task = CallTask.objects.get(pk=task_id, assigned_to=request.user)
        except CallTask.DoesNotExist:
            messages.error(request, "Задача не найдена или у вас нет прав на её изменение.")
            return redirect('crm:task_list')

        if task.status != 'DONE':
            task.status = 'DONE'
            task.save(update_fields=['status'])
            messages.success(request, "Задача отмечена как выполненная.")

        return redirect('crm:task_list')

    # ----- Обычный режим (GET) -----
    status = request.GET.get('status', '')
    period = request.GET.get('period', 'today')

    tasks = CallTask.objects.filter(assigned_to=request.user)

    if status in ['PLANNED', 'DONE']:
        tasks = tasks.filter(status=status)

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timezone.timedelta(days=1)
    week_end = today_start + timezone.timedelta(days=7)

    if period == 'today':
        tasks = tasks.filter(planned_at__gte=today_start, planned_at__lt=today_end)
    elif period == 'week':
        tasks = tasks.filter(planned_at__gte=today_start, planned_at__lt=week_end)
    elif period == 'overdue':
        tasks = tasks.filter(planned_at__lt=now, status='PLANNED')
    elif period == 'all':
        pass

    tasks = tasks.annotate(
        sort_status=Case(
            When(status='PLANNED', planned_at__lt=now, then=Value(0)),
            When(status='PLANNED', planned_at__gte=now, then=Value(1)),
            When(status='DONE', then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        )
    ).order_by('sort_status', 'planned_at')

    # Данные для модалки
    clients_for_modal = []
    managers = None
    pipeline_stages_for_filter = BUYER_PIPELINE + BUILDER_PIPELINE

    if user.is_superuser:
        clients_for_modal = (
            Client.objects
            .all()
            .select_related('responsible')
            .order_by('full_name')
        )
        managers = User.objects.filter(is_active=True).order_by('username')

    context = {
        'tasks': tasks,
        'status': status,
        'period': period,
        'now': timezone.now(),

        'is_superuser': user.is_superuser,
        'clients_for_modal': clients_for_modal,
        'managers': managers,
        'pipeline_stages_for_filter': pipeline_stages_for_filter,
    }
    return render(request, 'crm/task_list.html', context)

@require_GET
@login_required
def bulk_clients(request):
    """
    Возвращает HTML-таблицу клиентов и список этапов воронки
    для модального окна массовой постановки задач (AJAX).
    Доступно только суперпользователю.
    """
    if not request.user.is_superuser:
        return JsonResponse({'error': 'forbidden'}, status=403)

    f_client_type = request.GET.get('f_client_type', '').strip()
    f_pipeline_stage = request.GET.get('f_pipeline_stage', '').strip()
    f_manager_id = request.GET.get('f_manager', '').strip()
    f_query = request.GET.get('f_q', '').strip()

    qs = Client.objects.all().select_related('responsible')

    if f_client_type in ['BUYER', 'BUILDER']:
        qs = qs.filter(client_type=f_client_type)

    if f_pipeline_stage:
        qs = qs.filter(pipeline_stage=f_pipeline_stage)

    if f_manager_id:
        qs = qs.filter(responsible_id=f_manager_id)

    if f_query:
        qs = qs.filter(
            Q(full_name__icontains=f_query) |
            Q(phone__icontains=f_query) |
            Q(email__icontains=f_query)
        )

    qs = qs.order_by('full_name')

    # Этапы воронки зависят от типа
    if f_client_type == 'BUILDER':
        stages = BUILDER_PIPELINE
    elif f_client_type == 'BUYER':
        stages = BUYER_PIPELINE
    else:
        stages = BUYER_PIPELINE + BUILDER_PIPELINE

    # Рендерим только tbody таблицы клиентов
    clients_tbody_html = render_to_string(
        'crm/partials/bulk_clients_tbody.html',
        {'clients_for_modal': qs},
        request=request,
    )

    # Рендерим options для селекта этапов
    stages_options_html = render_to_string(
        'crm/partials/bulk_stages_options.html',
        {
            'pipeline_stages_for_filter': stages,
            'selected_stage': f_pipeline_stage,
        },
        request=request,
    )

    return JsonResponse({
        'clients_tbody_html': clients_tbody_html,
        'stages_options_html': stages_options_html,
    })
@login_required
def bulk_mail(request):
    user = request.user

    manager_id = request.GET.get('manager')
    query = request.GET.get('q', '').strip()

    if user.is_superuser:
        clients_qs = Client.objects.all()
        managers = User.objects.filter(is_active=True).order_by('username')
        selected_manager = None
        if manager_id:
            try:
                selected_manager = User.objects.get(pk=manager_id)
                clients_qs = clients_qs.filter(responsible=selected_manager)
            except User.DoesNotExist:
                selected_manager = None
    else:
        clients_qs = Client.objects.filter(responsible=user)
        managers = None
        selected_manager = None

    if query:
        clients_qs = clients_qs.filter(
            Q(full_name__icontains=query) |
            Q(email__icontains=query) |
            Q(phone__icontains=query)
        )

    clients_qs = clients_qs.order_by('full_name')

    if request.method == 'POST':
        subject = request.POST.get('email_subject', '').strip()
        body = request.POST.get('email_body', '').strip()
        selected_client_ids = request.POST.getlist('client_ids')

        if not subject:
            messages.error(request, "Тема письма не может быть пустой.")
            return redirect('crm:bulk_mail')

        if not body:
            messages.error(request, "Тело письма не может быть пустым.")
            return redirect('crm:bulk_mail')

        if not selected_client_ids:
            messages.error(request, "Не выбрано ни одного клиента для рассылки.")
            return redirect('crm:bulk_mail')

        attachments = request.FILES.getlist('attachments')

        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
        if not from_email:
            messages.error(request, "DEFAULT_FROM_EMAIL не задан в settings, отправка невозможна.")
            return redirect('crm:bulk_mail')

        first_name = (user.first_name or "").strip()
        last_name = (user.last_name or "").strip()
        if first_name or last_name:
            signature_name = (first_name + " " + last_name).strip()
        else:
            signature_name = user.username

        signature_html = f"<br><br><hr><p>{signature_name}</p>"

        if signature_name not in body:
            html_body = body + signature_html
        else:
            html_body = body

        text_body = strip_tags(html_body)

        allowed_clients = clients_qs.filter(id__in=selected_client_ids).select_related('responsible')

        if not allowed_clients.exists():
            messages.error(request, "Выбранные клиенты недоступны или не найдены.")
            return redirect('crm:bulk_mail')

        sent_count = 0
        errors = []

        for client in allowed_clients:
            if not client.email:
                continue

            try:
                msg = EmailMultiAlternatives(
                    subject=subject,
                    body=text_body,
                    from_email=from_email,
                    to=[client.email],
                )
                msg.attach_alternative(html_body, "text/html")

                for f in attachments:
                    f.open('rb')
                    msg.attach(f.name, f.read(), f.content_type)
                    f.close()

                msg.send()

                ClientEmail.objects.create(
                    client=client,
                    from_address=from_email,
                    subject=subject,
                    body=html_body,
                    received_at=timezone.now(),
                    direction='OUT',
                )

                ClientNote.objects.create(
                    client=client,
                    author=user,
                    note_type='EMAIL',
                    meta_type='SYSTEM',
                    text=f"Клиент включён в массовую рассылку. Тема: {subject}",
                )

                sent_count += 1
            except Exception as e:
                errors.append(f"{client.full_name} ({client.email}): {e}")

        if sent_count:
            messages.success(request, f"Рассылка отправлена {sent_count} клиентам.")
        if errors:
            messages.error(request, "Не удалось отправить некоторым клиентам: " + "; ".join(errors))

        return redirect('crm:bulk_mail')

    context = {
        'clients': clients_qs,
        'managers': managers,
        'selected_manager': selected_manager,
        'manager_id': manager_id or '',
        'query': query,
    }
    return render(request, 'crm/bulk_mail.html', context)

@login_required
def reports(request):
    if not request.user.is_superuser:
        messages.error(request, "У вас нет доступа к отчётам.")
        return redirect('crm:dashboard')

    clients = (
        Client.objects
        .select_related('responsible')
        .prefetch_related('extra_contacts')
        .order_by('created_at', 'id')
    )

    pipeline_labels = dict(Client.PIPELINE_STAGE_CHOICES)

    report_rows = []
    for client in clients:
        date = client.created_at.date()

        # Контактная информация
        contact_parts = []

        if client.phone:
            contact_parts.append(f"Телефон: {client.phone}")
        if client.email:
            contact_parts.append(f"Email: {client.email}")
        if client.telegram:
            contact_parts.append(f"Telegram: {client.telegram}")
        if client.whatsapp:
            contact_parts.append(f"WhatsApp: {client.whatsapp}")

        for ec in client.extra_contacts.all():
            label = dict(ClientContact.CONTACT_TYPE_CHOICES).get(ec.contact_type, ec.contact_type)
            if ec.comment:
                contact_parts.append(f"{label}: {ec.value} ({ec.comment})")
            else:
                contact_parts.append(f"{label}: {ec.value}")

        contact_info = "; ".join(contact_parts) if contact_parts else "—"

        # Ответственный менеджер
        if client.responsible:
            manager_name = client.responsible.get_full_name().strip() or client.responsible.username
        else:
            manager_name = "Не назначен"

        # Этап воронки
        pipeline_stage_label = pipeline_labels.get(client.pipeline_stage, "не задан")

        report_rows.append({
            "date": date,
            "client": client,
            "full_name": client.full_name,
            "contact_info": contact_info,
            "manager_name": manager_name,
            "pipeline_stage_label": pipeline_stage_label,
            "request": client.request_text or "",
            "source": client.source or "",
            "status": "",  # пока пусто
            "note": client.first_note or "",
        })

    context = {
        "rows": report_rows,
    }
    return render(request, 'crm/reports.html', context)
    
@login_required
def notifications_poll(request):
    user = request.user

    qs = (
        Notification.objects
        .filter(user=user, is_read=False)
        .select_related('client')
        .order_by('-created_at')
    )

    notifications = list(qs)

    data = []
    for n in notifications:
        item = {
            'id': n.id,
            'type': n.type,
            'message': n.message,
            'created_at': timezone.localtime(n.created_at).strftime('%d.%m.%Y %H:%M'),
            'client': None,
        }
        if n.client:
            item['client'] = {
                'id': n.client.id,
                'full_name': n.client.full_name,
            }
        data.append(item)

    return JsonResponse({'notifications': data})


@login_required
def notifications_mark_read(request):
    if request.method != 'POST':
        return HttpResponseBadRequest('Invalid method')

    notif_id = request.POST.get('id')
    if not notif_id:
        return HttpResponseBadRequest('Missing id')

    try:
        notif = Notification.objects.get(pk=notif_id, user=request.user)
    except Notification.DoesNotExist:
        return JsonResponse({'status': 'not_found'})

    notif.is_read = True
    notif.save(update_fields=['is_read'])
    return JsonResponse({'status': 'ok'})


@login_required
def call_qr(request, pk):
    client = get_object_or_404(Client, pk=pk)

    active_call = CallLog.objects.filter(
        client=client,
        ended_at__isnull=True
    ).order_by('-started_at').first()

    if active_call and active_call.dialed_number:
        raw_phone = active_call.dialed_number
    else:
        raw_phone = client.phone

    if not raw_phone:
        return HttpResponseBadRequest('Client has no phone')

    if qrcode is None:
        return HttpResponseBadRequest('qrcode library is not installed')

    phone = str(raw_phone).strip().replace(' ', '')
    tel_link = f"tel:{phone}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(tel_link)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return HttpResponse(buf.getvalue(), content_type='image/png')


@login_required
@staff_member_required
@require_http_methods(["GET", "POST"])
def uis_import_calls(request):
    """
    Импорт звонков из CSV-отчёта UIS.
    """
    if request.method == "POST":
        file = request.FILES.get("file")
        if not file:
            messages.error(request, "Файл не выбран.")
            return redirect("crm:uis_import_calls")

        raw = file.read()
        text = None
        for encoding in ("utf-8-sig", "cp1251"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                text = None

        if text is None:
            messages.error(request, "Не удалось определить кодировку файла (пробовал UTF-8 и CP1251).")
            return redirect("crm:uis_import_calls")

        lines = text.splitlines()
        data_lines = []
        header_found = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("Статус;Тип;Дата и время;Номер абонента;Длительность звонка;"):
                header_found = True
                data_lines.append(line)
            elif header_found:
                data_lines.append(line)

        if not header_found:
            messages.error(request, "Не найден заголовок с колонками (строка, начинающаяся с 'Статус;Тип;Дата и время').")
            return redirect("crm:uis_import_calls")

        f = pyio.StringIO("\n".join(data_lines))

        reader = csv.DictReader(f, delimiter=';')

        imported = 0
        skipped_no_client = 0
        skipped_bad_row = 0

        def parse_hms(s: str):
            if not s:
                return None
            parts = s.split(":")
            if len(parts) != 3:
                return None
            try:
                h, m, sec = map(int, parts)
                return h * 3600 + m * 60 + sec
            except ValueError:
                return None

        for row in reader:
            try:
                status = (row.get("Статус") or "").strip()
                call_type_raw = (row.get("Тип") or "").strip()
                dt_str = (row.get("Дата и время") or "").strip()
                number_raw = (row.get("Номер абонента") or "").strip()
                duration_str = (row.get("Длительность звонка") or "").strip()
                wait_str = (row.get("Длительность ожидания ответа") or "").strip()
                employee = (row.get("Сотрудник") or "").strip()
            except Exception:
                skipped_bad_row += 1
                continue

            if not dt_str or not number_raw:
                skipped_bad_row += 1
                continue

            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                dt = timezone.make_aware(dt)
            except Exception:
                skipped_bad_row += 1
                continue

            call_type = "IN"
            if "исход" in call_type_raw.lower():
                call_type = "OUT"

            duration_seconds = parse_hms(duration_str)
            wait_seconds = parse_hms(wait_str)

            norm_number = _normalize_contact(number_raw)

            client = Client.objects.filter(
                phone__isnull=False
            ).filter(
                phone__icontains=number_raw
            ).first()

            if not client:
                all_clients = Client.objects.all().select_related('responsible')
                matched_client = None
                for cl in all_clients:
                    all_numbers = set()
                    if cl.phone:
                        all_numbers.add(_normalize_contact(cl.phone))
                    for ec in ClientContact.objects.filter(client=cl, contact_type='PHONE'):
                        if ec.value:
                            all_numbers.add(_normalize_contact(ec.value))
                    if norm_number and norm_number in all_numbers:
                        matched_client = cl
                        break
                client = matched_client

            if not client:
                skipped_no_client += 1
                continue

            exists = CallLog.objects.filter(
                client=client,
                started_at=dt,
                duration_seconds=duration_seconds,
                call_type=call_type,
            ).exists()
            if exists:
                continue

            notes_parts = []
            if status:
                notes_parts.append(f"Статус: {status}")
            if employee:
                notes_parts.append(f"Сотрудник: {employee}")
            if wait_seconds is not None:
                notes_parts.append(f"Ожидание: {wait_seconds} сек.")
            notes = "; ".join(notes_parts)

            CallLog.objects.create(
                client=client,
                user=request.user,
                call_type=call_type,
                created_at=dt,
                started_at=dt,
                ended_at=dt + timezone.timedelta(seconds=duration_seconds or 0),
                duration_seconds=duration_seconds,
                notes=notes,
            )

            imported += 1

        messages.success(
            request,
            f"Импорт завершён. Добавлено звонков: {imported}. "
            f"Без клиента: {skipped_no_client}. Ошибочных строк: {skipped_bad_row}."
        )
        return redirect("crm:uis_import_calls")

    return render(request, "crm/uis_import.html", {})


# --- ПОЛЛИНГ ДИАЛОГА TELEGRAM ---

@login_required
def client_messages_poll(request, pk):
    """
    Возвращает новые сообщения диалога Telegram для клиента после last_id.
    """
    client = get_object_or_404(Client, pk=pk)
    if not request.user.is_superuser and client.responsible != request.user:
        return JsonResponse({"messages": []})

    try:
        last_id = int(request.GET.get("last_id") or 0)
    except ValueError:
        last_id = 0

    qs = ClientMessage.objects.filter(client=client)
    if last_id > 0:
        qs = qs.filter(id__gt=last_id)

    qs = qs.order_by("created_at")

    messages_data = []
    for m in qs:
        messages_data.append({
            "id": m.id,
            "sender": m.sender,
            "created_at": timezone.localtime(m.created_at).strftime("%d.%m.%Y %H:%M"),
            "text": m.text,
        })

    return JsonResponse({"messages": messages_data})


# --- ПОЛЛИНГ ПИСЕМ EMAIL ---

@login_required
def client_emails_poll(request, pk):
    """
    Возвращает новые письма клиента после last_id в JSON.
    Используется для "живого" обновления списка писем.
    """
    client = get_object_or_404(Client, pk=pk)
    if not request.user.is_superuser and client.responsible != request.user:
        return JsonResponse({"emails": []})

    try:
        last_id = int(request.GET.get("last_id") or 0)
    except ValueError:
        last_id = 0

    qs = ClientEmail.objects.filter(client=client)
    if last_id > 0:
        qs = qs.filter(id__gt=last_id)

    qs = qs.order_by("received_at")

    emails_data = []
    for e in qs:
        emails_data.append({
            "id": e.id,
            "direction": e.direction,
            "subject": e.subject or "(без темы)",
            "from_address": e.from_address,
            "received_at": timezone.localtime(e.received_at).strftime("%d.%m.%Y %H:%M"),
            "body": e.body,
        })

    return JsonResponse({"emails": emails_data})
   

@login_required
def internal_messages(request):
    user = request.user

    # Все активные пользователи, кроме самого себя (исходный порядок по username)
    users = User.objects.filter(is_active=True).exclude(id=user.id).order_by('username')

    # С кем сейчас общаемся
    try:
        selected_user_id = int(request.GET.get('user') or 0)
    except ValueError:
        selected_user_id = 0

    selected_user = None
    if selected_user_id:
        selected_user = users.filter(id=selected_user_id).first()

    # Отправка сообщения
    if request.method == 'POST' and selected_user:
        html_text = (request.POST.get('html_text') or '').strip()
        files = request.FILES.getlist('attachments')

        if not html_text and not files:
            messages.error(request, "Сообщение не может быть пустым.")
            return redirect(f"{reverse('crm:internal_messages')}?user={selected_user.id}")

        message = InternalMessage.objects.create(
            sender=user,
            recipient=selected_user,
            text=html_text or '',
        )

        for f in files:
            InternalAttachment.objects.create(
                message=message,
                file=f,
                original_name=f.name,
            )

        # Уведомление для получателя
        Notification.objects.create(
            user=selected_user,
            type='INTERNAL',
            client=None,
            client_email=None,
            message=f"Новое внутреннее сообщение от {user.get_full_name() or user.username}",
        )

        messages.success(request, "Сообщение отправлено.")
        return redirect(f"{reverse('crm:internal_messages')}?user={selected_user.id}")

    # История диалога
    dialogue_messages = []
    if selected_user:
        dialogue_messages = (
            InternalMessage.objects
            .filter(
                Q(sender=user, recipient=selected_user) |
                Q(sender=selected_user, recipient=user)
            )
            .prefetch_related('attachments')
            .order_by('created_at')
        )

        # Помечаем входящие как прочитанные
        InternalMessage.objects.filter(
            sender=selected_user,
            recipient=user,
            is_read=False,
        ).update(is_read=True)

    # Непрочитанные сообщения по собеседникам
    unread_by_user_id = {}
    unread_qs = (
        InternalMessage.objects
        .filter(recipient=user, is_read=False)
        .values('sender_id')
        .annotate(cnt=Count('id'))
    )
    for row in unread_qs:
        unread_by_user_id[row['sender_id']] = row['cnt']

    # Время последнего сообщения от собеседника к текущему пользователю
    last_incoming_by_user_id = {}
    last_incoming_qs = (
        InternalMessage.objects
        .filter(recipient=user)
        .values('sender_id')
        .annotate(last_dt=Max('created_at'))
    )
    for row in last_incoming_qs:
        last_incoming_by_user_id[row['sender_id']] = row['last_dt']

    # users_with_unread: список (user, unread_count, last_dt)
    users_with_unread = []
    for u in users:
        cnt = unread_by_user_id.get(u.id, 0)
        last_dt = last_incoming_by_user_id.get(u.id)  # может быть None, если диалога не было
        users_with_unread.append((u, cnt, last_dt))

    # Сортируем:
    #  - сначала по наличию last_dt (те, у кого None, в конец),
    #  - затем по last_dt по убыванию (новые диалоги выше),
    #  - если оба None — сохраняем исходный order_by('username').
    # Для этого используем key с кортежем:
    #   (has_last, sort_value)
    # где has_last = 0 если есть дата, 1 если нет (чтобы None были внизу),
    # sort_value = -timestamp для обратного порядка.
    from datetime import datetime as _dt

    def sort_key(item):
        _u, _cnt, last_dt = item
        if last_dt is None:
            return (1, 0)  # в конец
        # преобразуем в timestamp (seconds) и инвертируем для сортировки по убыванию
        ts = last_dt.timestamp() if hasattr(last_dt, 'timestamp') else 0
        return (0, -ts)

    users_with_unread.sort(key=sort_key)

    # В шаблон отдаём (user, unread_count)
    users_with_unread_simple = [(u, cnt) for (u, cnt, last_dt) in users_with_unread]

    context = {
        'users_with_unread': users_with_unread_simple,
        'selected_user': selected_user,
        'dialogue_messages': dialogue_messages,
    }
    return render(request, 'crm/internal_messages.html', context)