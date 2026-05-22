from django.urls import path
from . import views

app_name = 'crm'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    # API для приёма сообщений от внешнего Telegram-бота
    path('api/telegram/', views.telegram_incoming, name='telegram_incoming'),

    # Клиенты
    path('clients/', views.client_list, name='client_list'),
    path('clients/new/', views.client_create, name='client_create'),
    path('clients/<int:pk>/', views.client_detail, name='client_detail'),
    path('clients/<int:pk>/edit/', views.client_edit, name='client_edit'),
    path('clients/<int:pk>/call/qr/', views.call_qr, name='call_qr'),
    path('clients/<int:pk>/start_call/', views.start_client_call, name='client_start_call'),

    # Поллинг диалога Telegram
    path('clients/<int:pk>/messages/poll/', views.client_messages_poll, name='client_messages_poll'),

    # Поллинг писем email
    path('clients/<int:pk>/emails/poll/', views.client_emails_poll, name='client_emails_poll'),

    # Задачи
    path('tasks/', views.task_list, name='task_list'),

    # Заметки
    path('clients/<int:pk>/notes/<int:note_id>/pin/', views.note_toggle_pin, name='note_toggle_pin'),
    path('clients/<int:pk>/notes/<int:note_id>/delete/', views.note_delete, name='note_delete'),
    path('clients/<int:pk>/notes/<int:note_id>/edit/', views.note_edit, name='note_edit'),

    # Отчёты
    path('reports/', views.reports, name='reports'),

    # Массовая рассылка
    path('bulk-mail/', views.bulk_mail, name='bulk_mail'),

    # Импорт звонков UIS
    path('uis/import/', views.uis_import_calls, name='uis_import_calls'),

    # Уведомления
    path('notifications/poll/', views.notifications_poll, name='notifications_poll'),
    path('notifications/mark-read/', views.notifications_mark_read, name='notifications_mark_read'),
    path('tasks/bulk-clients/', views.bulk_clients, name='bulk_clients'),
    path('internal/', views.internal_messages, name='internal_messages'),
]