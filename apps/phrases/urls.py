from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('phrase/', views.phrase_list, name='phrase_list'),
    path('phrase/ekle/', views.phrase_create, name='phrase_create'),
    path('phrase/<int:pk>/', views.phrase_detail, name='phrase_detail'),
    path('phrase/<int:pk>/duzenle/', views.phrase_update, name='phrase_update'),
    path('phrase/<int:pk>/sil/', views.phrase_delete, name='phrase_delete'),
    path('phrase/<int:pk>/tekrar-ogren/', views.phrase_relearn, name='phrase_relearn'),
    path('phrase/<int:pk>/swipe/', views.phrase_swipe, name='phrase_swipe'),
    path('phrase/<int:pk>/swipe/geri-al/', views.phrase_swipe_undo, name='phrase_swipe_undo'),
]
