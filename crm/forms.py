from django import forms
from .models import Client


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        # НЕ включаем 'responsible', чтобы форма его не трогала
        fields = [
            'full_name',
            'phone',
            'email',
            'telegram',
            'whatsapp',
            'client_type',
            'source',
            'request_text',
            'first_note',
        ]
        labels = {
            'full_name': 'ФИО',
            'phone': 'Телефон',
            'email': 'Email',
            'telegram': 'Telegram',
            'whatsapp': 'WhatsApp',
            'client_type': 'Тип клиента',
            'source': 'Источник',
            'request_text': 'Запрос',
            'first_note': 'Примечание',
        }
        widgets = {
            'first_note': forms.Textarea(attrs={'rows': 4}),
        }