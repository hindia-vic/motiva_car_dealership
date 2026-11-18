with open('urls.py') as f:
    c = f.read()
if 'service_booking' not in c:
    c = c.replace("    path('faq/', views.FAQView.as_view(), name='faq'),\n", 
        "    path('faq/', views.FAQView.as_view(), name='faq'),\n    path('service-booking/', views.ServiceBookingCreateView.as_view(), name='service_booking'),\n    path('service-booking/thank-you/', views.service_booking_thank_you, name='service_booking_thank_you'),\n    path('my-services/', views.MyServiceBookingsView.as_view(), name='my_service_bookings'),\n")
    c = c.replace("    path('appointments/calendar/', views.AppointmentCalendarView.as_view(), name='appointment_calendar'),\n",
        "    path('appointments/calendar/', views.AppointmentCalendarView.as_view(), name='appointment_calendar'),\n    path('service-bookings/', views.ServiceBookingListView.as_view(), name='service_bookings_list'),\n    path('service-bookings/<int:pk>/', views.ServiceBookingDetailView.as_view(), name='service_booking_detail'),\n    path('service-bookings/<int:pk>/status/', views.service_booking_status, name='service_booking_status'),\n")
    with open('urls.py', 'w') as f:
        f.write(c)
    print('done')
else:
    print('exists')
