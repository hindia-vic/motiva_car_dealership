from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.NotificationListView.as_view(), name='list'),
    path('<int:pk>/open/', views.notification_open, name='open'),
    path('<int:pk>/read/', views.notification_mark_read, name='mark_read'),
    path('read-all/', views.notifications_mark_all_read, name='mark_all_read'),
]
