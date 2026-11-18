"""URLs for car hire and tours & travel.

Public:
    /hire/                        the fleet
    /hire/tours/                  tours and travel
    /hire/car/<pk>/               one car, with the booking form
    /hire/thank-you/              after a booking request is sent
    /my-hires/                    the customer's own bookings
    /my-hires/<pk>/               one of the customer's own bookings

Staff:
    /hire-fleet/                  the fleet
    /hire-fleet/new/              add a car
    /hire-fleet/<pk>/edit/        edit a car
    /hire-bookings/               booking requests
    /hire-bookings/<pk>/          work through a request
    /hire-bookings/<pk>/status/   change a status from the list
"""

from django.urls import path

from . import views

app_name = 'hiring'

urlpatterns = [
    # Public
    path('hire/', views.HireCarListView.as_view(), name='hire_car_list'),
    path('hire/tours/', views.HireToursView.as_view(), name='hire_tours'),
    path('hire/thank-you/', views.hire_booking_thank_you, name='hire_booking_thank_you'),
    path('hire/car/<int:pk>/', views.HireCarDetailView.as_view(), name='hire_car_detail'),
    path('my-hires/', views.MyHireBookingsView.as_view(), name='my_hire_bookings'),
    path('my-hires/<int:pk>/', views.HireBookingDetailView.as_view(), name='hire_booking_detail'),
    path('my-hires/<int:pk>/pay/', views.hire_booking_pay, name='hire_booking_pay'),

    # Staff
    path('hire-fleet/', views.StaffHireCarListView.as_view(), name='staff_hire_cars'),
    path('hire-fleet/new/', views.StaffHireCarCreateView.as_view(), name='staff_hire_car_create'),
    path('hire-fleet/<int:pk>/edit/', views.StaffHireCarEditView.as_view(), name='staff_hire_car_edit'),
    path('hire-fleet/calendar/', views.StaffHireCalendarView.as_view(), name='staff_hire_calendar'),
    path('hire-fleet/<int:pk>/calendar/', views.StaffHireCarCalendarView.as_view(), name='staff_hire_car_calendar'),
    path('hire-bookings/', views.StaffHireBookingListView.as_view(), name='staff_hire_bookings'),
    path('hire-bookings/<int:pk>/', views.StaffHireBookingReviewView.as_view(), name='staff_hire_booking_review'),
    path('hire-bookings/<int:pk>/status/', views.hire_booking_status, name='hire_booking_status'),
]

