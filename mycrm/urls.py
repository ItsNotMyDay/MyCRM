from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from crm.views import debug_settings   # ДОБАВЬ ЭТУ СТРОКУ

urlpatterns = [
    path("debug-settings/", debug_settings),   # ДОБАВЬ ЭТУ СТРОКУ

    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include(('crm.urls', 'crm'), namespace='crm')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
