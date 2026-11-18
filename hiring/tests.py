"""Tests for car hire and tours & travel.

The feature has one rule that matters more than the rest: nothing is
confirmed on a customer's word. A booking is a request until staff have
taken the money and confirmed it, and that is what most of these tests
are about.
"""

import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cars.models import DealershipInfo
from cars.tests import make_photo

from . import rules
from .models import (
    HireAddOn, HireBooking, HireBookingAddOn, HireCar, HireCarImage,
)


def create_hire_car(**kwargs):
    """A sensible car in the hire fleet, overridable per test."""
    defaults = dict(
        make='Toyota',
        model='Prado',
        year=2022,
        color='White',
        body_type='suv',
        transmission='automatic',
        fuel_type='diesel',
        seats=7,
        luggage_capacity=4,
        hire_daily_rate=Decimal('8000.00'),
        tour_daily_rate=Decimal('12000.00'),
        allows_tours=True,
        status='available',
    )
    defaults.update(kwargs)
    return HireCar.objects.create(**defaults)


def create_booking(car=None, **kwargs):
    """A booking request on a car, with everything the form asks for."""
    car = car or create_hire_car()
    today = timezone.localdate()
    defaults = dict(
        hire_car=car,
        customer_name='Jane Doe',
        customer_email='jane@example.com',
        customer_phone='0700000000',
        service_type='self_drive',
        start_date=today + timedelta(days=3),
        end_date=today + timedelta(days=5),
        passengers=2,
        licence_number='DL-1234',
        id_number='ID-5678',
        quoted_price=Decimal('24000.00'),
        status='pending',
        payment_status='pending',
    )
    defaults.update(kwargs)
    return HireBooking.objects.create(**defaults)


def booking_post_data(**kwargs):
    """The fields the public booking form posts, as strings."""
    today = timezone.localdate()
    data = {
        'service_type': 'self_drive',
        'start_date': (today + timedelta(days=3)).isoformat(),
        'end_date': (today + timedelta(days=5)).isoformat(),
        'passengers': '2',
        'destination': '',
        'pickup_location': 'Nairobi',
        'licence_number': 'DL-1234',
        'id_number': 'ID-5678',
        'customer_name': 'Jane Doe',
        'customer_email': 'jane@example.com',
        'customer_phone': '0700000000',
        'notes': '',
    }
    data.update(kwargs)
    return data


def review_post_data(booking, **kwargs):
    """The fields the staff review form posts."""
    data = {
        'start_date': booking.start_date.isoformat(),
        'end_date': booking.end_date.isoformat(),
        'quoted_price': str(booking.quoted_price),
        'security_deposit': str(booking.security_deposit),
        'deposit_retained': str(booking.deposit_retained),
        'status': booking.status if booking.status in HireBooking.MANUAL_STATUSES else '',
        'payment_status': booking.payment_status,
        'payment_reference': booking.payment_reference,
        'driver_name': booking.driver_name,
        'staff_notes': booking.staff_notes,
        'rejection_reason': booking.rejection_reason,
    }
    if booking.deposit_received_at:
        data['deposit_received'] = 'on'
    if booking.deposit_refunded_at:
        data['deposit_refunded'] = 'on'
    data.update(kwargs)
    return data


def create_add_on(**kwargs):
    """An extra in the catalogue, overridable per test."""
    defaults = dict(
        name='Child seat',
        description='For children under 12.',
        price=Decimal('500.00'),
        unit='per_day',
        is_active=True,
        sort_order=0,
    )
    defaults.update(kwargs)
    return HireAddOn.objects.create(**defaults)


def extras_post_data(booking, lines, **kwargs):
    """The review form's data plus the add-on formset it posts."""
    data = review_post_data(booking, **kwargs)
    data.update({
        'extras-TOTAL_FORMS': str(len(lines)),
        'extras-INITIAL_FORMS': str(booking.extras.count()),
        'extras-MIN_NUM_FORMS': '0',
        'extras-MAX_NUM_FORMS': '1000',
    })
    for index, line in enumerate(lines):
        data[f'extras-{index}-id'] = str(line.get('id', ''))
        data[f'extras-{index}-add_on'] = str(line.get('add_on', ''))
        data[f'extras-{index}-quantity'] = str(line.get('quantity', 1))
        if line.get('DELETE'):
            data[f'extras-{index}-DELETE'] = 'on'
    return data


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------

class HireRulesTests(TestCase):
    def test_same_day_hire_is_one_day(self):
        day = timezone.localdate()
        self.assertEqual(rules.rental_days(day, day), 1)

    def test_both_ends_count(self):
        day = timezone.localdate()
        self.assertEqual(rules.rental_days(day, day + timedelta(days=2)), 3)

    def test_missing_dates_give_no_days(self):
        self.assertEqual(rules.rental_days(None, None), 0)

    def test_quote_multiplies_the_rate(self):
        self.assertEqual(rules.quote(Decimal('8000.00'), 3), Decimal('24000.00'))

    def test_quote_with_a_bad_rate_is_zero(self):
        self.assertEqual(rules.quote(None, 3), Decimal('0.00'))


# ---------------------------------------------------------------------------
# The models
# ---------------------------------------------------------------------------

class HireBookingModelTests(TestCase):
    def test_reference_is_generated(self):
        booking = create_booking()
        self.assertTrue(booking.reference.startswith('HIRE-'))
        self.assertEqual(len(booking.reference.split('-')), 3)

    def test_references_are_unique(self):
        car = create_hire_car()
        references = {create_booking(car=car).reference for _ in range(5)}
        self.assertEqual(len(references), 5)

    def test_days_and_quote_follow_the_service(self):
        booking = create_booking()
        self.assertEqual(booking.days, 3)
        self.assertEqual(booking.price_quote(), Decimal('24000.00'))

    def test_a_tour_quotes_at_the_tour_rate(self):
        booking = create_booking(service_type='tour')
        self.assertEqual(booking.price_quote(), Decimal('36000.00'))

    def test_is_settled_only_when_paid(self):
        booking = create_booking(payment_status='partial')
        self.assertFalse(booking.is_settled())
        booking.payment_status = 'paid'
        self.assertTrue(booking.is_settled())

    def test_overlapping_finds_a_clash(self):
        car = create_hire_car()
        booking = create_booking(car=car, status='confirmed')
        self.assertEqual(
            HireBooking.overlapping(car, booking.start_date, booking.end_date).count(),
            1,
        )

    def test_rejected_bookings_do_not_clash(self):
        car = create_hire_car()
        booking = create_booking(car=car, status='rejected')
        self.assertEqual(
            HireBooking.overlapping(car, booking.start_date, booking.end_date).count(),
            0,
        )

    def test_blocking_ignores_pending_requests(self):
        car = create_hire_car()
        booking = create_booking(car=car, status='pending')
        self.assertEqual(
            HireBooking.blocking(car, booking.start_date, booking.end_date).count(),
            0,
        )

    def test_blocking_finds_a_confirmed_booking(self):
        car = create_hire_car()
        booking = create_booking(car=car, status='confirmed')
        self.assertEqual(
            HireBooking.blocking(car, booking.start_date, booking.end_date).count(),
            1,
        )

    def test_next_free_from_is_the_day_after_the_last_booking(self):
        car = create_hire_car()
        today = timezone.localdate()
        booking = create_booking(
            car=car,
            status='confirmed',
            start_date=today,
            end_date=today + timedelta(days=2),
        )
        self.assertEqual(
            car.next_free_from(), booking.end_date + timedelta(days=1)
        )

    def test_next_free_from_is_none_when_the_car_is_free(self):
        self.assertIsNone(create_hire_car().next_free_from())


# ---------------------------------------------------------------------------
# Browsing the fleet
# ---------------------------------------------------------------------------

class HireBrowseTests(TestCase):
    def setUp(self):
        self.available = create_hire_car(model='Prado')
        self.no_tours = create_hire_car(model='Vitz', allows_tours=False, tour_daily_rate=0)
        self.in_maintenance = create_hire_car(model='Hilux', status='maintenance')
        self.retired = create_hire_car(model='Probox', status='retired')

    def test_the_list_shows_only_available_cars(self):
        response = self.client.get(reverse('hiring:hire_car_list'))
        self.assertContains(response, 'Prado')
        self.assertContains(response, 'Vitz')
        self.assertContains(response, '2 cars')
        self.assertNotContains(response, 'Hilux')
        self.assertNotContains(response, 'Probox')

    def test_the_tours_page_shows_only_cars_that_take_a_driver(self):
        response = self.client.get(reverse('hiring:hire_tours'))
        self.assertContains(response, 'Prado')
        self.assertNotContains(response, 'Vitz')

    def test_a_confirmed_booking_hides_the_car_for_those_dates(self):
        create_booking(car=self.available, status='confirmed')
        today = timezone.localdate()
        response = self.client.get(reverse('hiring:hire_car_list'), {
            'start_date': (today + timedelta(days=3)).isoformat(),
            'end_date': (today + timedelta(days=5)).isoformat(),
        })
        self.assertNotContains(response, 'Prado')

    def test_a_pending_request_does_not_hide_the_car(self):
        create_booking(car=self.available, status='pending')
        today = timezone.localdate()
        response = self.client.get(reverse('hiring:hire_car_list'), {
            'start_date': (today + timedelta(days=3)).isoformat(),
            'end_date': (today + timedelta(days=5)).isoformat(),
        })
        self.assertContains(response, 'Prado')

    def test_the_detail_page_offers_the_booking_form(self):
        response = self.client.get(
            reverse('hiring:hire_car_detail', args=[self.available.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Request this car')
        self.assertContains(response, 'licence_number')

    def test_the_public_hire_pages_have_seo_descriptions(self):
        for name in ('hiring:hire_car_list', 'hiring:hire_tours'):
            response = self.client.get(reverse(name))
            self.assertContains(response, 'name="description"', msg_prefix=name)
            self.assertContains(
                response, 'property="og:description"', msg_prefix=name,
            )

        response = self.client.get(
            reverse('hiring:hire_car_detail', args=[self.available.pk])
        )
        self.assertContains(response, 'name="description"')
        self.assertContains(response, 'Prado')

    def test_a_car_in_maintenance_is_not_bookable(self):
        response = self.client.get(
            reverse('hiring:hire_car_detail', args=[self.in_maintenance.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Request this car')
        self.assertContains(response, 'not available at the moment')


# ---------------------------------------------------------------------------
# Asking for a car
# ---------------------------------------------------------------------------

class HireBookingRequestTests(TestCase):
    def setUp(self):
        self.car = create_hire_car()

    def test_a_guest_can_send_a_request(self):
        response = self.client.post(
            reverse('hiring:hire_car_detail', args=[self.car.pk]),
            booking_post_data(),
        )
        self.assertRedirects(response, reverse('hiring:hire_booking_thank_you'))

        booking = HireBooking.objects.get()
        self.assertIsNone(booking.user)
        self.assertEqual(booking.status, 'pending')
        self.assertEqual(booking.payment_status, 'pending')
        self.assertEqual(booking.quoted_price, Decimal('24000.00'))

    def test_a_signed_in_customer_has_the_booking_linked(self):
        user = User.objects.create_user('jane', email='jane@example.com', password='pass-12345')
        self.client.force_login(user)
        self.client.post(
            reverse('hiring:hire_car_detail', args=[self.car.pk]),
            booking_post_data(),
        )
        self.assertEqual(HireBooking.objects.get().user, user)

    def test_the_name_and_email_are_prefilled_for_a_signed_in_customer(self):
        user = User.objects.create_user(
            'jane', email='jane@example.com', password='pass-12345',
            first_name='Jane', last_name='Doe',
        )
        self.client.force_login(user)
        response = self.client.get(
            reverse('hiring:hire_car_detail', args=[self.car.pk])
        )
        self.assertContains(response, 'value="Jane Doe"')
        self.assertContains(response, 'value="jane@example.com"')

    def test_staff_are_emailed_about_the_request(self):
        self.client.post(
            reverse('hiring:hire_car_detail', args=[self.car.pk]),
            booking_post_data(),
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Hire Request', mail.outbox[0].subject)
        self.assertIn('Jane Doe', mail.outbox[0].body)
        self.assertIn('DL-1234', mail.outbox[0].body)

    def test_the_conversion_source_is_recorded(self):
        self.client.cookies['vid'] = 'visitor-abc-123'
        self.client.post(
            reverse('hiring:hire_car_detail', args=[self.car.pk]),
            booking_post_data(),
        )
        self.assertEqual(HireBooking.objects.get().visitor_id, 'visitor-abc-123')

    def test_a_return_before_the_pick_up_is_rejected(self):
        today = timezone.localdate()
        response = self.client.post(
            reverse('hiring:hire_car_detail', args=[self.car.pk]),
            booking_post_data(
                start_date=(today + timedelta(days=5)).isoformat(),
                end_date=(today + timedelta(days=3)).isoformat(),
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'return date cannot be before')
        self.assertFalse(HireBooking.objects.exists())

    def test_a_date_in_the_past_is_rejected(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        response = self.client.post(
            reverse('hiring:hire_car_detail', args=[self.car.pk]),
            booking_post_data(
                start_date=yesterday.isoformat(),
                end_date=(yesterday + timedelta(days=2)).isoformat(),
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already passed')
        self.assertFalse(HireBooking.objects.exists())

    def test_more_passengers_than_seats_is_rejected(self):
        response = self.client.post(
            reverse('hiring:hire_car_detail', args=[self.car.pk]),
            booking_post_data(passengers='9'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'carries 7 people')
        self.assertFalse(HireBooking.objects.exists())

    def test_a_tour_on_a_self_drive_only_car_is_rejected(self):
        car = create_hire_car(model='Vitz', allows_tours=False, tour_daily_rate=0)
        self.client.post(
            reverse('hiring:hire_car_detail', args=[car.pk]),
            booking_post_data(service_type='tour', destination='Naivasha'),
        )
        self.assertFalse(HireBooking.objects.exists())

    def test_a_tour_without_a_destination_is_rejected(self):
        response = self.client.post(
            reverse('hiring:hire_car_detail', args=[self.car.pk]),
            booking_post_data(service_type='tour', destination=''),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tell us where the car is going')
        self.assertFalse(HireBooking.objects.exists())

    def test_a_clash_with_a_confirmed_booking_is_rejected(self):
        create_booking(car=self.car, status='confirmed')
        response = self.client.post(
            reverse('hiring:hire_car_detail', args=[self.car.pk]),
            booking_post_data(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already out for those dates')
        # Only the confirmed booking that caused the clash is there.
        self.assertEqual(HireBooking.objects.count(), 1)

    def test_a_clash_with_another_request_is_allowed(self):
        create_booking(car=self.car, status='pending')
        response = self.client.post(
            reverse('hiring:hire_car_detail', args=[self.car.pk]),
            booking_post_data(),
        )
        self.assertRedirects(response, reverse('hiring:hire_booking_thank_you'))
        self.assertEqual(HireBooking.objects.count(), 2)

    def test_the_licence_and_id_are_required(self):
        response = self.client.post(
            reverse('hiring:hire_car_detail', args=[self.car.pk]),
            booking_post_data(licence_number='', id_number=''),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required.')
        self.assertFalse(HireBooking.objects.exists())

    def test_a_honeypot_submission_is_dropped(self):
        response = self.client.post(
            reverse('hiring:hire_car_detail', args=[self.car.pk]),
            booking_post_data(website='http://spam.example.com'),
        )
        self.assertFalse(HireBooking.objects.exists())
        self.assertNotEqual(response.status_code, 500)

    def test_the_thank_you_page_shows_the_reference(self):
        self.client.post(
            reverse('hiring:hire_car_detail', args=[self.car.pk]),
            booking_post_data(),
        )
        booking = HireBooking.objects.get()
        response = self.client.get(reverse('hiring:hire_booking_thank_you'))
        self.assertContains(response, booking.reference)

    def test_a_car_in_maintenance_cannot_be_requested(self):
        car = create_hire_car(model='Hilux', status='maintenance')
        response = self.client.post(
            reverse('hiring:hire_car_detail', args=[car.pk]),
            booking_post_data(),
        )
        self.assertRedirects(response, reverse('hiring:hire_car_list'))
        self.assertFalse(HireBooking.objects.exists())


# ---------------------------------------------------------------------------
# Following a booking
# ---------------------------------------------------------------------------

class MyHireTests(TestCase):
    def setUp(self):
        self.car = create_hire_car()
        self.user = User.objects.create_user('jane', email='jane@example.com', password='pass-12345')
        self.other = User.objects.create_user('john', email='john@example.com', password='pass-12345')
        self.booking = create_booking(car=self.car, user=self.user)
        self.other_booking = create_booking(car=self.car, user=self.other)

    def test_my_hires_needs_a_login(self):
        response = self.client.get(reverse('hiring:my_hire_bookings'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_a_customer_sees_only_their_own_bookings(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('hiring:my_hire_bookings'))
        self.assertContains(response, self.booking.reference)
        self.assertNotContains(response, self.other_booking.reference)

    def test_a_customer_cannot_open_someone_elses_booking(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('hiring:hire_booking_detail', args=[self.other_booking.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_a_customer_can_open_their_own_booking(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('hiring:hire_booking_detail', args=[self.booking.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.booking.reference)

    def test_staff_can_open_any_booking(self):
        staff = User.objects.create_user('staff', password='pass-12345')
        staff.is_staff = True
        staff.save()
        self.client.force_login(staff)
        response = self.client.get(
            reverse('hiring:hire_booking_detail', args=[self.other_booking.pk])
        )
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Staff: the fleet
# ---------------------------------------------------------------------------

class StaffBaseTest(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff', email='staff@example.com', password='pass-12345')
        self.staff.is_staff = True
        self.staff.save()
        self.customer_user = User.objects.create_user('customer', password='pass-12345')
        self.client.force_login(self.staff)


class StaffHireGatingTests(StaffBaseTest):
    def test_anonymous_is_redirected_home(self):
        self.client.logout()
        for name in (
            'hiring:staff_hire_cars',
            'hiring:staff_hire_car_create',
            'hiring:staff_hire_bookings',
        ):
            response = self.client.get(reverse(name))
            self.assertRedirects(response, reverse('cars:home'), msg_prefix=name)

    def test_a_customer_is_redirected_home(self):
        self.client.force_login(self.customer_user)
        for name in (
            'hiring:staff_hire_cars',
            'hiring:staff_hire_car_create',
            'hiring:staff_hire_bookings',
        ):
            response = self.client.get(reverse(name))
            self.assertRedirects(response, reverse('cars:home'), msg_prefix=name)

    def test_the_review_page_is_staff_only(self):
        booking = create_booking()
        self.client.force_login(self.customer_user)
        response = self.client.get(
            reverse('hiring:staff_hire_booking_review', args=[booking.pk])
        )
        self.assertRedirects(response, reverse('cars:home'))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class StaffFleetTests(StaffBaseTest):
    def fleet_data(self, **kwargs):
        data = {
            'make': 'Toyota',
            'model': 'Fortuner',
            'year': '2023',
            'color': 'Silver',
            'body_type': 'suv',
            'transmission': 'automatic',
            'fuel_type': 'diesel',
            'seats': '7',
            'luggage_capacity': '3',
            'hire_daily_rate': '9000',
            'tour_daily_rate': '14000',
            'allows_tours': 'on',
            'status': 'available',
            'description': 'Clean and comfortable.',
        }
        data.update(kwargs)
        return data

    def test_the_fleet_list_shows_the_cars(self):
        car = create_hire_car(model='Prado')
        response = self.client.get(reverse('hiring:staff_hire_cars'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Prado')

    def test_a_car_can_be_added(self):
        response = self.client.post(
            reverse('hiring:staff_hire_car_create'), self.fleet_data()
        )
        car = HireCar.objects.get()
        self.assertRedirects(
            response, reverse('hiring:staff_hire_car_edit', args=[car.pk])
        )
        self.assertEqual(car.hire_daily_rate, Decimal('9000.00'))
        self.assertEqual(car.tour_daily_rate, Decimal('14000.00'))

    def test_a_photo_can_be_uploaded_with_the_car(self):
        self.client.post(
            reverse('hiring:staff_hire_car_create'),
            self.fleet_data(images=make_photo()),
        )
        image = HireCarImage.objects.get()
        self.assertTrue(image.is_primary)
        self.assertTrue(image.image.name.startswith('hiring/car_'))

    def test_a_second_photo_does_not_replace_the_main_one(self):
        car = create_hire_car()
        HireCarImage.objects.create(hire_car=car, image=make_photo(), is_primary=True)
        self.client.post(
            reverse('hiring:staff_hire_car_edit', args=[car.pk]),
            self.fleet_data(images=make_photo('second.jpg', color='blue')),
        )
        self.assertEqual(car.images.count(), 2)
        self.assertEqual(car.images.filter(is_primary=True).count(), 1)

    def test_a_non_image_upload_is_rejected(self):
        response = self.client.post(
            reverse('hiring:staff_hire_car_create'),
            self.fleet_data(images=SimpleUploadedFile('notes.txt', b'hello', content_type='text/plain')),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(HireCar.objects.exists())

    def test_offering_tours_needs_a_tour_rate(self):
        response = self.client.post(
            reverse('hiring:staff_hire_car_create'),
            self.fleet_data(tour_daily_rate='0'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(HireCar.objects.exists())

    def test_a_self_drive_only_car_needs_no_tour_rate(self):
        self.client.post(
            reverse('hiring:staff_hire_car_create'),
            self.fleet_data(tour_daily_rate='0', allows_tours=''),
        )
        car = HireCar.objects.get()
        self.assertFalse(car.allows_tours)

    def test_a_car_can_be_retired_instead_of_deleted(self):
        car = create_hire_car()
        self.client.post(
            reverse('hiring:staff_hire_car_edit', args=[car.pk]),
            self.fleet_data(status='retired'),
        )
        car.refresh_from_db()
        self.assertEqual(car.status, 'retired')

    def test_a_car_with_bookings_cannot_be_deleted(self):
        from django.db.models import ProtectedError

        car = create_hire_car()
        create_booking(car=car)
        with self.assertRaises(ProtectedError):
            car.delete()

    def test_the_edit_page_loads(self):
        car = create_hire_car()
        response = self.client.get(
            reverse('hiring:staff_hire_car_edit', args=[car.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Prado')


# ---------------------------------------------------------------------------
# Staff: working through a booking
# ---------------------------------------------------------------------------

class StaffBookingReviewTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.car = create_hire_car()
        self.booking = create_booking(car=self.car)

    def review_url(self, booking=None):
        booking = booking or self.booking
        return reverse('hiring:staff_hire_booking_review', args=[booking.pk])

    def test_the_list_shows_the_requests(self):
        response = self.client.get(reverse('hiring:staff_hire_bookings'))
        self.assertContains(response, self.booking.reference)
        self.assertContains(response, 'Jane Doe')

    def test_the_review_page_shows_the_licence_and_id(self):
        response = self.client.get(self.review_url())
        self.assertContains(response, 'DL-1234')
        self.assertContains(response, 'ID-5678')

    def test_confirming_needs_the_money_first(self):
        self.client.post(self.review_url(), review_post_data(
            self.booking, status='confirmed',
        ))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending')

    def test_a_part_payment_is_enough_to_confirm(self):
        self.client.post(self.review_url(), review_post_data(
            self.booking,
            status='confirmed',
            payment_status='partial',
            payment_reference='MPESA-1',
        ))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')

    def test_a_paid_booking_can_be_confirmed(self):
        self.client.post(self.review_url(), review_post_data(
            self.booking,
            status='confirmed',
            payment_status='paid',
            payment_reference='MPESA-ABC123',
        ))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')
        self.assertIsNotNone(self.booking.payment_received_at)
        self.assertIsNotNone(self.booking.reviewed_at)
        self.assertEqual(self.booking.reviewed_by, self.staff)

    def test_confirming_emails_the_customer(self):
        self.client.post(self.review_url(), review_post_data(
            self.booking,
            status='confirmed',
            payment_status='paid',
            payment_reference='MPESA-ABC123',
        ))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('confirmed', mail.outbox[0].subject)
        self.assertIn(self.booking.reference, mail.outbox[0].body)

    def test_marking_paid_needs_a_reference(self):
        response = self.client.post(self.review_url(), review_post_data(
            self.booking, payment_status='paid', payment_reference='',
        ), follow=True)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.payment_status, 'pending')
        self.assertContains(response, 'Record the M-Pesa or bank reference')

    def test_the_amount_can_be_overridden(self):
        self.client.post(self.review_url(), review_post_data(
            self.booking, quoted_price='27500',
        ))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.quoted_price, Decimal('27500.00'))

    def test_the_dates_can_be_moved(self):
        today = timezone.localdate()
        self.client.post(self.review_url(), review_post_data(
            self.booking,
            start_date=(today + timedelta(days=10)).isoformat(),
            end_date=(today + timedelta(days=12)).isoformat(),
        ))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.start_date, today + timedelta(days=10))
        self.assertEqual(self.booking.days, 3)

    def test_turning_a_booking_down_needs_a_reason(self):
        self.client.post(self.review_url(), review_post_data(
            self.booking, status='rejected', rejection_reason='',
        ))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending')

    def test_turning_a_booking_down_emails_the_customer(self):
        self.client.post(self.review_url(), review_post_data(
            self.booking,
            status='rejected',
            rejection_reason='The car is already booked for a wedding.',
        ))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'rejected')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('wedding', mail.outbox[0].body)

    def test_a_confirmed_clash_stops_the_second_booking(self):
        first = create_booking(car=self.car, status='confirmed', payment_status='paid')
        response = self.client.post(self.review_url(), review_post_data(
            self.booking,
            status='confirmed',
            payment_status='paid',
            payment_reference='MPESA-XYZ',
        ), follow=True)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending')
        self.assertContains(response, first.reference)

    def test_moving_the_booking_off_a_clash_lets_it_be_confirmed(self):
        create_booking(car=self.car, status='confirmed')
        today = timezone.localdate()
        self.client.post(self.review_url(), review_post_data(
            self.booking,
            status='confirmed',
            payment_status='paid',
            payment_reference='MPESA-XYZ',
            start_date=(today + timedelta(days=20)).isoformat(),
            end_date=(today + timedelta(days=22)).isoformat(),
        ))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')

    def test_the_quick_status_button_confirms_a_paid_booking(self):
        self.booking.payment_status = 'paid'
        self.booking.payment_reference = 'MPESA-1'
        self.booking.save()
        response = self.client.post(
            reverse('hiring:hire_booking_status', args=[self.booking.pk]),
            {'status': 'confirmed'},
        )
        self.assertRedirects(response, reverse('hiring:staff_hire_bookings'))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')

    def test_the_quick_status_button_will_not_confirm_an_unpaid_booking(self):
        self.client.post(
            reverse('hiring:hire_booking_status', args=[self.booking.pk]),
            {'status': 'confirmed'},
        )
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending')

    def test_the_quick_status_button_sends_a_rejection_to_the_review_page(self):
        response = self.client.post(
            reverse('hiring:hire_booking_status', args=[self.booking.pk]),
            {'status': 'rejected'},
        )
        self.assertRedirects(response, self.review_url())
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending')

    def test_the_quick_status_button_marks_a_returned_car_completed(self):
        self.booking.status = 'active'
        self.booking.save()
        self.client.post(
            reverse('hiring:hire_booking_status', args=[self.booking.pk]),
            {'status': 'completed'},
        )
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'completed')

    def test_a_completed_booking_shows_its_status_on_the_review_page(self):
        self.booking.status = 'completed'
        self.booking.save()
        response = self.client.get(self.review_url())
        self.assertContains(response, 'selected')

    def test_saving_with_the_status_left_alone_keeps_it(self):
        self.booking.status = 'confirmed'
        self.booking.payment_status = 'paid'
        self.booking.payment_reference = 'MPESA-1'
        self.booking.save()
        self.client.post(self.review_url(), review_post_data(
            self.booking, status='', staff_notes='Called the customer.',
        ))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')
        self.assertEqual(self.booking.staff_notes, 'Called the customer.')


# ---------------------------------------------------------------------------
# Where the feature is wired in
# ---------------------------------------------------------------------------

class HireIntegrationTests(TestCase):
    def test_the_home_page_shows_the_fleet_strip(self):
        create_hire_car()
        response = self.client.get(reverse('cars:home'))
        self.assertContains(response, 'Car Hire &amp; Tours')

    def test_the_sitemap_lists_the_hire_cars(self):
        car = create_hire_car()
        response = self.client.get('/sitemap.xml')
        self.assertContains(
            response, reverse('hiring:hire_car_detail', args=[car.pk]), status_code=200
        )

    def test_the_email_brand_falls_back_when_the_dealership_is_unnamed(self):
        # The emails must never fail just because the shop has no name yet.
        self.assertTrue(DealershipInfo.display_name())


# ---------------------------------------------------------------------------
# Add-ons and the security deposit
# ---------------------------------------------------------------------------

class SecurityDepositRuleTests(TestCase):
    def test_the_deposit_is_a_fifth_of_the_hire(self):
        self.assertEqual(
            rules.suggested_security_deposit(Decimal('10000')),
            Decimal('2000.00'),
        )

    def test_the_deposit_is_rounded_up_to_the_next_500(self):
        self.assertEqual(
            rules.suggested_security_deposit(Decimal('24000')),
            Decimal('5000.00'),
        )

    def test_a_free_hire_suggests_no_deposit(self):
        self.assertEqual(
            rules.suggested_security_deposit(Decimal('0')), Decimal('0.00')
        )


class HireAddOnModelTests(TestCase):
    def setUp(self):
        self.booking = create_booking()  # three days: 3, 4 and 5 in the future

    def test_a_new_line_snapshots_the_catalogue(self):
        add_on = create_add_on(price=Decimal('750'))
        line = HireBookingAddOn.objects.create(
            booking=self.booking, add_on=add_on,
        )
        self.assertEqual(line.name, 'Child seat')
        self.assertEqual(line.unit_price, Decimal('750.00'))
        self.assertEqual(line.unit, 'per_day')

    def test_a_per_day_extra_is_charged_for_every_day(self):
        line = HireBookingAddOn.objects.create(
            booking=self.booking,
            add_on=create_add_on(price=Decimal('500')),
            quantity=2,
        )
        self.assertEqual(line.line_total(), Decimal('3000.00'))

    def test_a_per_booking_extra_is_charged_once(self):
        line = HireBookingAddOn.objects.create(
            booking=self.booking,
            add_on=create_add_on(price=Decimal('500'), unit='per_booking'),
            quantity=2,
        )
        self.assertEqual(line.line_total(), Decimal('1000.00'))

    def test_the_hire_total_is_the_quote_plus_the_extras(self):
        HireBookingAddOn.objects.create(
            booking=self.booking,
            add_on=create_add_on(price=Decimal('500')),
        )
        self.assertEqual(self.booking.extras_total(), Decimal('1500.00'))
        self.assertEqual(self.booking.hire_total(), Decimal('25500.00'))

    def test_the_total_due_includes_the_refundable_deposit(self):
        self.booking.security_deposit = Decimal('5000')
        self.assertEqual(self.booking.total_due(), Decimal('29000.00'))

    def test_the_deposit_follows_its_timestamps(self):
        self.assertEqual(self.booking.deposit_state(), 'due')
        self.booking.deposit_received_at = timezone.now()
        self.assertEqual(self.booking.deposit_state(), 'held')
        self.booking.deposit_refunded_at = timezone.now()
        self.assertEqual(self.booking.deposit_state(), 'refunded')

    def test_what_is_kept_reduces_the_refund(self):
        self.booking.security_deposit = Decimal('5000')
        self.booking.deposit_retained = Decimal('1500')
        self.assertEqual(self.booking.deposit_to_refund(), Decimal('3500.00'))


class HireBookingExtrasTests(TestCase):
    """The public form: extras and the deposit the request carries."""

    def setUp(self):
        self.car = create_hire_car()
        self.add_on = create_add_on()
        self.url = reverse('hiring:hire_car_detail', args=[self.car.pk])

    def book(self, **overrides):
        return self.client.post(self.url, booking_post_data(**overrides))

    def test_a_ticked_extra_is_saved_on_the_booking(self):
        response = self.book(extras=[str(self.add_on.pk)])
        self.assertRedirects(response, reverse('hiring:hire_booking_thank_you'))

        line = HireBooking.objects.get().extras.get()
        self.assertEqual(line.add_on, self.add_on)
        self.assertEqual(line.name, 'Child seat')
        self.assertEqual(line.unit_price, Decimal('500.00'))
        self.assertEqual(line.quantity, 1)

    def test_an_unticked_extra_is_not_added(self):
        self.book()
        self.assertEqual(HireBookingAddOn.objects.count(), 0)

    def test_a_retired_extra_is_not_offered_or_accepted(self):
        retired = create_add_on(name='Old satnav', is_active=False)
        response = self.client.get(self.url)
        self.assertNotContains(response, 'Old satnav')

        response = self.book(extras=[str(retired.pk)])
        self.assertEqual(response.status_code, 200)
        self.assertFalse(HireBooking.objects.exists())

    def test_the_security_deposit_is_suggested_on_the_request(self):
        self.book()
        booking = HireBooking.objects.get()
        self.assertEqual(booking.security_deposit, Decimal('5000.00'))

    def test_a_self_drive_booking_needs_a_licence(self):
        response = self.book(licence_number='')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'licence number')
        self.assertFalse(HireBooking.objects.exists())

    def test_a_tour_does_not_need_the_customer_licence(self):
        response = self.book(
            service_type='tour',
            destination='Naivasha',
            licence_number='',
        )
        self.assertRedirects(response, reverse('hiring:hire_booking_thank_you'))
        self.assertEqual(HireBooking.objects.get().licence_number, '')

    def test_the_thank_you_page_shows_the_deposit_and_extras(self):
        response = self.client.post(
            self.url,
            booking_post_data(extras=[str(self.add_on.pk)]),
            follow=True,
        )
        self.assertContains(response, 'Child seat')
        self.assertContains(response, 'Security deposit')
        self.assertContains(response, '5,000')


class StaffBookingExtrasTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.car = create_hire_car()
        self.booking = create_booking(car=self.car)
        self.add_on = create_add_on()
        self.url = reverse('hiring:staff_hire_booking_review', args=[self.booking.pk])

    def test_the_review_page_offers_extras_and_the_deposit(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Security deposit')
        self.assertContains(response, 'Child seat')
        self.assertContains(response, 'extras-TOTAL_FORMS')

    def test_staff_can_add_an_extra(self):
        self.client.post(self.url, extras_post_data(
            self.booking, [{'add_on': self.add_on.pk, 'quantity': 2}],
        ))
        line = self.booking.extras.get()
        self.assertEqual(line.quantity, 2)
        self.assertEqual(line.line_total(), Decimal('3000.00'))

    def test_staff_can_change_a_quantity(self):
        line = HireBookingAddOn.objects.create(
            booking=self.booking, add_on=self.add_on,
        )
        self.client.post(self.url, extras_post_data(
            self.booking,
            [{'id': line.pk, 'add_on': self.add_on.pk, 'quantity': 3}],
        ))
        line.refresh_from_db()
        self.assertEqual(line.quantity, 3)
        self.assertEqual(line.line_total(), Decimal('4500.00'))

    def test_staff_can_remove_an_extra(self):
        line = HireBookingAddOn.objects.create(
            booking=self.booking, add_on=self.add_on,
        )
        self.client.post(self.url, extras_post_data(
            self.booking,
            [{'id': line.pk, 'add_on': self.add_on.pk, 'quantity': 1,
              'DELETE': True}],
        ))
        self.assertEqual(self.booking.extras.count(), 0)

    def test_the_deposit_can_be_recorded_as_received(self):
        self.client.post(self.url, review_post_data(
            self.booking,
            security_deposit='5000',
            deposit_received='on',
        ))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.security_deposit, Decimal('5000.00'))
        self.assertIsNotNone(self.booking.deposit_received_at)
        self.assertEqual(self.booking.deposit_state(), 'held')

    def test_a_refund_records_what_was_kept(self):
        self.booking.deposit_received_at = timezone.now()
        self.booking.security_deposit = Decimal('5000')
        self.booking.save()
        self.client.post(self.url, review_post_data(
            self.booking,
            security_deposit='5000',
            deposit_received='on',
            deposit_refunded='on',
            deposit_retained='1500',
        ))
        self.booking.refresh_from_db()
        self.assertIsNotNone(self.booking.deposit_refunded_at)
        self.assertEqual(self.booking.deposit_retained, Decimal('1500.00'))
        self.assertEqual(self.booking.deposit_to_refund(), Decimal('3500.00'))

    def test_more_cannot_be_kept_than_the_deposit(self):
        response = self.client.post(self.url, review_post_data(
            self.booking,
            security_deposit='1000',
            deposit_retained='2000',
            deposit_received='on',
        ))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.deposit_retained, Decimal('0.00'))
        self.assertContains(response, 'more than the deposit')

    def test_a_refund_needs_the_deposit_recorded_as_received(self):
        self.client.post(self.url, review_post_data(
            self.booking,
            security_deposit='5000',
            deposit_refunded='on',
        ))
        self.booking.refresh_from_db()
        self.assertIsNone(self.booking.deposit_refunded_at)

    def test_the_confirmation_email_shows_the_total_and_deposit(self):
        HireBookingAddOn.objects.create(
            booking=self.booking, add_on=self.add_on,
        )
        self.booking.security_deposit = Decimal('5000')
        self.booking.save()
        self.client.post(self.url, review_post_data(
            self.booking,
            status='confirmed',
            payment_status='paid',
            payment_reference='MPESA-1',
        ))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Child seat', mail.outbox[0].body)
        self.assertIn('refundable', mail.outbox[0].body)
        self.assertIn('Total due', mail.outbox[0].body)
