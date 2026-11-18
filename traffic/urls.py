from django.urls import path

from . import views

app_name = 'traffic'

urlpatterns = [
    path('', views.TrafficView.as_view(), name='traffic'),
]
