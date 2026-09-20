from django.contrib import admin
from django.urls import include, path

from apps.phrases import views as phrase_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', phrase_views.home, name='home'),
    path('', include('apps.users.urls')),
]
