from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('phrase/ekle/', views.phrase_create, name='phrase_create'),
    path('phrase/<int:pk>/', views.phrase_detail, name='phrase_detail'),
    path('phrase/<int:pk>/duzenle/', views.phrase_update, name='phrase_update'),
    path('phrase/<int:pk>/sil/', views.phrase_delete, name='phrase_delete'),
]
