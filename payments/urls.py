from django.urls import path

from . import views

app_name = 'payments'

urlpatterns = [
    path('mpesa/callback/', views.mpesa_callback, name='mpesa_callback'),
    path('status/<str:reference>/', views.payment_status, name='payment_status'),

    # Staff reconciliation
    path('transactions/', views.transactions_list, name='transactions_list'),
    path('transactions/export/', views.transactions_export, name='transactions_export'),
    path('transactions/<str:reference>/query/', views.transaction_query, name='transaction_query'),
]
