from django.db import models
from django.contrib.auth.models import User
from django.conf import settings


class Client(models.Model):
    CONTACT_TYPE_CHOICES = [
        ('PHONE', 'Телефон'),
        ('EMAIL', 'Email'),
        ('TELEGRAM', 'Telegram'),
        ('WHATSAPP', 'WhatsApp'),
    ]

    CLIENT_TYPE_CHOICES = [
        ('BUYER', 'Покупатель'),
        ('BUILDER', 'Строитель'),
    ]

    PIPELINE_STAGE_CHOICES = [
        ('B_COLD', 'Холодный контакт (покупатель)'),
        ('B_NEEDS', 'Выявление потребности (покупатель)'),
        ('B_OFFER', 'Предложение (покупатель)'),
        ('B_PAYMENT', 'Оплата (покупатель)'),
        ('B_DELIVERY', 'Исполнение (покупатель)'),
        ('BU_COLD', 'Холодный контакт (строитель)'),
        ('BU_CONTACT', 'Контакт (строитель)'),
        ('BU_TASKS', 'Выявление задач (строитель)'),
        ('BU_KP', 'КП (строитель)'),
        ('BU_FIRST_CONTRACT', 'Первый договор (строитель)'),
        ('BU_SUPPORT', 'Сопровождение и удержание (строитель)'),
    ]

    full_name = models.CharField("ФИО", max_length=255)
    phone = models.CharField("Телефон", max_length=50)
    email = models.EmailField("Email", max_length=255, blank=True, null=True)
    telegram = models.CharField("Telegram", max_length=100, blank=True, null=True)
    whatsapp = models.CharField("WhatsApp", max_length=100, blank=True, null=True)

    responsible = models.ForeignKey(
        User,
        verbose_name="Ответственный менеджер",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='clients'
    )

    client_type = models.CharField(
        "Тип клиента",
        max_length=20,
        choices=CLIENT_TYPE_CHOICES,
        default='BUYER',
    )

    pipeline_stage = models.CharField(
        "Этап воронки",
        max_length=30,
        choices=PIPELINE_STAGE_CHOICES,
        blank=True,
        null=True,
    )

    preferred_contact = models.CharField(
        "Приоритетный тип связи",
        max_length=20,
        choices=CONTACT_TYPE_CHOICES,
        blank=True,
        null=True,
    )

    # Новые поля для отчётов/карточки
    source = models.CharField(
        "Источник",
        max_length=255,
        blank=True,
        null=True,
        help_text="Откуда пришёл клиент (реклама, рекомендация и т.п.)",
    )
    request_text = models.CharField(
        "Запрос",
        max_length=500,
        blank=True,
        null=True,
        help_text="Краткий запрос клиента",
    )
    first_note = models.TextField(
        "Примечание при создании",
        blank=True,
        null=True,
        help_text="Подробное примечание при создании клиента",
    )

    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    def __str__(self):
        return f"{self.full_name} ({self.phone})"


class ClientContact(models.Model):
    CONTACT_TYPE_CHOICES = [
        ('PHONE', 'Телефон'),
        ('EMAIL', 'Email'),
        ('TELEGRAM', 'Telegram'),
        ('WHATSAPP', 'WhatsApp'),
        ('OTHER', 'Другое'),
    ]

    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name='extra_contacts',
        verbose_name="Клиент",
    )
    contact_type = models.CharField(
        "Тип контакта",
        max_length=20,
        choices=CONTACT_TYPE_CHOICES,
        default='OTHER',
    )
    value = models.CharField("Контакт", max_length=255)
    comment = models.CharField("Комментарий", max_length=255, blank=True, null=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Дополнительный контакт"
        verbose_name_plural = "Дополнительные контакты"
        ordering = ['created_at']

    def __str__(self):
        return f"{self.get_contact_type_display()} {self.value} ({self.client})"


class ClientNote(models.Model):
    NOTE_TYPE_CHOICES = [
        ('CALL', 'Звонок'),
        ('NOTE', 'Заметка'),
        ('TRANSFER', 'Передача клиента'),
        ('EMAIL', 'Email'),
        ('SYSTEM', 'Системное событие'),
    ]

    META_TYPE_CHOICES = [
        ('ENTRY', 'Обычная запись'),
        ('SYSTEM', 'Системное событие'),
    ]

    client = models.ForeignKey(
        Client,
        verbose_name="Клиент",
        on_delete=models.CASCADE,
        related_name='notes'
    )
    author = models.ForeignKey(
        User,
        verbose_name="Автор",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='client_notes'
    )
    note_type = models.CharField(
        "Тип записи",
        max_length=20,
        choices=NOTE_TYPE_CHOICES,
        default='NOTE'
    )
    meta_type = models.CharField(
        "Тип записи (служебный)",
        max_length=20,
        choices=META_TYPE_CHOICES,
        default='ENTRY',
        help_text="ENTRY — обычная запись, SYSTEM — служебное событие (email, изменения заметок и т.п.)"
    )
    text = models.TextField("Текст")
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    pinned = models.BooleanField("Закреплена", default=False)
    is_deleted = models.BooleanField("Удалена", default=False)

    def __str__(self):
        return f"{self.get_note_type_display()} для {self.client} от {self.author}"


class CallTask(models.Model):
    TASK_TYPE_CHOICES = [
        ('CALL', 'Звонок'),
        ('EMAIL', 'Письмо'),
        ('MESSAGE', 'Сообщение'),
        ('MEETING', 'Встреча'),
    ]

    STATUS_CHOICES = [
        ('PLANNED', 'Запланирован'),
        ('DONE', 'Выполнен'),
    ]

    client = models.ForeignKey(
        Client,
        verbose_name="Клиент",
        on_delete=models.CASCADE,
        related_name='call_tasks'
    )
    assigned_to = models.ForeignKey(
        User,
        verbose_name="Ответственный менеджер",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='call_tasks'
    )
    planned_at = models.DateTimeField("Когда выполнить")
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=STATUS_CHOICES,
        default='PLANNED'
    )
    task_type = models.CharField(
        "Тип задачи",
        max_length=20,
        choices=TASK_TYPE_CHOICES,
        default='CALL',
    )
    comment = models.CharField("Комментарий", max_length=255, blank=True, null=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    def __str__(self):
        return f"{self.get_task_type_display()} {self.client} ({self.planned_at}) - {self.get_status_display()}"


class ClientMessage(models.Model):
    SENDER_CHOICES = [
        ('CLIENT', 'Клиент'),
        ('MANAGER', 'Менеджер'),
    ]

    CHANNEL_CHOICES = [
        ('TELEGRAM', 'Telegram'),
    ]

    client = models.ForeignKey(
        Client,
        verbose_name="Клиент",
        on_delete=models.CASCADE,
        related_name='messages'
    )
    sender = models.CharField("Отправитель", max_length=20, choices=SENDER_CHOICES)
    channel = models.CharField("Канал", max_length=20, choices=CHANNEL_CHOICES, default='TELEGRAM')
    external_id = models.CharField(
        "Внешний ID",
        max_length=255,
        blank=True,
        null=True,
        help_text="ID пользователя в Telegram (или другом канале)"
    )
    text = models.TextField("Текст сообщения")
    created_at = models.DateTimeField("Время сообщения", auto_now_add=True)

    def __str__(self):
        return f"[{self.get_sender_display()}] {self.client}: {self.text[:30]}"


class ClientEmail(models.Model):
    DIRECTION_CHOICES = [
        ('IN', 'Входящее'),
        ('OUT', 'Исходящее'),
    ]

    client = models.ForeignKey(
        Client,
        verbose_name="Клиент",
        on_delete=models.CASCADE,
        related_name='emails'
    )
    from_address = models.EmailField("От кого (email)", max_length=255)
    subject = models.CharField("Тема", max_length=500, blank=True, null=True)
    body = models.TextField("Текст письма")
    received_at = models.DateTimeField("Получено/отправлено", auto_now_add=True)
    direction = models.CharField(
        "Направление",
        max_length=3,
        choices=DIRECTION_CHOICES,
        default='IN',
    )

    def __str__(self):
        return f"{self.get_direction_display()} письмо от {self.from_address} для {self.client.full_name}"


class Notification(models.Model):
    NOTIFICATION_TYPE_CHOICES = [
        ('EMAIL', 'Новое письмо'),
        ('TRANSFER', 'Передача клиента'),
        ('SYSTEM', 'Системное событие'),
        ('INTERNAL', 'Внутреннее сообщение'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='Пользователь'
    )
    type = models.CharField(
        'Тип уведомления',
        max_length=20,
        choices=NOTIFICATION_TYPE_CHOICES
    )
    client = models.ForeignKey(
        'Client',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications',
        verbose_name='Клиент'
    )
    client_email = models.ForeignKey(
        'ClientEmail',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications',
        verbose_name='Письмо клиента'
    )
    message = models.TextField('Текст уведомления')
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    is_read = models.BooleanField('Прочитано', default=False)

    class Meta:
        verbose_name = 'Уведомление'
        verbose_name_plural = 'Уведомления'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_type_display()}] {self.message[:50]}"


class CallLog(models.Model):
    CALL_TYPE_CHOICES = [
        ('OUT', 'Исходящий'),
        ('IN', 'Входящий'),
    ]

    client = models.ForeignKey(
        Client,
        verbose_name="Клиент",
        on_delete=models.CASCADE,
        related_name='calls'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='call_logs'
    )
    call_type = models.CharField(
        "Тип звонка",
        max_length=10,
        choices=CALL_TYPE_CHOICES,
        default='OUT'
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    started_at = models.DateTimeField("Начало звонка", blank=True, null=True)
    ended_at = models.DateTimeField("Окончание звонка", blank=True, null=True)
    duration_seconds = models.PositiveIntegerField("Длительность (сек)", blank=True, null=True)

    dialed_number = models.CharField(
        "Набранный номер",
        max_length=100,
        blank=True,
        null=True,
        help_text="Номер, по которому фактически звонят (основной или доп.)"
    )

    uis_call_id = models.CharField(
        "ID звонка в UIS",
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
    )
    uis_recording_url = models.URLField(
        "Ссылка на запись UIS",
        blank=True,
        null=True,
    )
    recording = models.FileField(
        "Запись разговора",
        upload_to='call_recordings/',
        blank=True,
        null=True
    )

    notes = models.TextField("Заметки по звонку", blank=True)

    class Meta:
        verbose_name = "Лог звонка"
        verbose_name_plural = "Логи звонков"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_call_type_display()} звонок {self.client} от {self.user} ({self.created_at})"
        
class InternalMessage(models.Model):
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_internal_messages',
        verbose_name='Отправитель',
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_internal_messages',
        verbose_name='Получатель',
    )
    text = models.TextField('Текст сообщения')
    created_at = models.DateTimeField('Отправлено', auto_now_add=True)
    is_read = models.BooleanField('Прочитано', default=False)

    class Meta:
        verbose_name = 'Внутреннее сообщение'
        verbose_name_plural = 'Внутренние сообщения'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender} → {self.recipient}: {self.text[:30]}"
        
class InternalAttachment(models.Model):
    message = models.ForeignKey(
        InternalMessage,
        on_delete=models.CASCADE,
        related_name='attachments',
        verbose_name='Сообщение',
    )
    file = models.FileField(
        'Файл',
        upload_to='internal_attachments/%Y/%m/%d/'
    )
    original_name = models.CharField(
        'Имя файла',
        max_length=255,
        blank=True,
        null=True,
    )
    uploaded_at = models.DateTimeField('Загружено', auto_now_add=True)

    class Meta:
        verbose_name = 'Вложение внутреннего сообщения'
        verbose_name_plural = 'Вложения внутренних сообщений'
        ordering = ['uploaded_at']

    def __str__(self):
        return self.original_name or (self.file.name if self.file else 'Файл')