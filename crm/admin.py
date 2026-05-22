from django.contrib import admin
from .models import Client, ClientNote, CallTask, ClientMessage, ClientEmail


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'email', 'responsible', 'created_at')
    search_fields = ('full_name', 'phone', 'email')
    list_filter = ('responsible',)


@admin.register(ClientNote)
class ClientNoteAdmin(admin.ModelAdmin):
    list_display = ('client', 'note_type', 'author', 'created_at')
    list_filter = ('note_type', 'author')
    search_fields = ('client__full_name', 'text')


@admin.register(CallTask)
class CallTaskAdmin(admin.ModelAdmin):
    list_display = ('client', 'assigned_to', 'planned_at', 'status')
    list_filter = ('status', 'assigned_to')
    search_fields = ('client__full_name', 'comment')
    
@admin.register(ClientEmail)
class ClientEmailAdmin(admin.ModelAdmin):
    list_display = ('client', 'from_address', 'subject', 'received_at')
    search_fields = ('client__full_name', 'from_address', 'subject', 'body')
    list_filter = ('from_address', 'received_at')