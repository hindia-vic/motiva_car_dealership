import tempfile

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    Appointment, Car, CarImage, ContactInfo, ContactMessage, Customer,
    NewsletterSubscription, Order, Inquiry, Post, SalesTransaction, SavedSearch,
    Testimonial,
)


def create_car(vin='1HGCM82633A004352', status='available'):
    return Car.objects.create(
        make='Toyota',
        model='Camry',
        year=2021,
        vin=vin,
        color='Blue',
        body_type='sedan',
        transmission='automatic',
        fuel_type='gasoline',
        purchase_price=20000.00,
        asking_price=24000.00,
        status=status,
    )


def create_customer(email='customer@example.com'):
    return Customer.objects.create(
        first_name='Jane',
        last_name='Doe',
        email=email,
        phone_number='555-123-4567',
        address='123 Main St',
        city='Springfield',
        state='CA',
        zip_code='90210',
    )


class StaffBaseTest(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff', email='staff@example.com', password='pass-12345')
        self.staff.is_staff = True
        self.staff.save()
        self.customer_user = User.objects.create_user('customer', email='cust@example.com', password='pass-12345')

        self.client.force_login(self.staff)


class StaffGatingTests(StaffBaseTest):
    def test_anonymous_redirected_home_from_staff_views(self):
        self.client.logout()
        for url_name, kwargs in [
            ('cars:customer_list', {}),
            ('cars:sales_list', {}),
            ('cars:reports', {}),
        ]:
            response = self.client.get(reverse(url_name, kwargs=kwargs))
            self.assertRedirects(response, reverse('cars:home'), msg_prefix=url_name)

    def test_non_staff_redirected_home_from_staff_views(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:customer_list'))
        self.assertRedirects(response, reverse('cars:home'))


class CustomerDetailTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.customer = create_customer()

    def test_customer_list_renders_without_reverse_match_error(self):
        """Regression: customer_list.html references cars:customer_detail which previously 404'd the page"""
        response = self.client.get(reverse('cars:customer_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Jane')

    def test_customer_detail_renders(self):
        response = self.client.get(reverse('cars:customer_detail', args=[self.customer.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Jane')
        self.assertContains(response, 'Purchase History')

    def test_customer_detail_404(self):
        response = self.client.get(reverse('cars:customer_detail', args=[99999]))
        self.assertEqual(response.status_code, 404)

    def test_customer_detail_requires_staff(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:customer_detail', args=[self.customer.id]))
        self.assertRedirects(response, reverse('cars:home'))


class SalesViewsTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.car = create_car()
        self.customer = create_customer()
        self.sale = SalesTransaction.objects.create(
            car=self.car,
            customer=self.customer,
            sale_price=24000.00,
            total_amount=24500.00,
            payment_method='cash',
            status='completed',
            invoice_number='INV-1001',
        )

    def test_sales_list_renders(self):
        response = self.client.get(reverse('cars:sales_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'INV-1001')

    def test_sales_list_filters_by_status(self):
        response = self.client.get(reverse('cars:sales_list'), {'status': 'pending'})
        self.assertNotContains(response, 'INV-1001')

    def test_sales_detail_renders(self):
        response = self.client.get(reverse('cars:sales_detail', args=[self.sale.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'INV-1001')

    def test_sales_list_requires_staff(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:sales_list'))
        self.assertRedirects(response, reverse('cars:home'))


class InquiryStatusUpdateTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.car = create_car()
        self.inquiry = Inquiry.objects.create(
            car=self.car,
            customer_name='Jane Doe',
            customer_email='jane@example.com',
            customer_phone='555-123-4567',
            message='Interested in this car',
        )

    def test_staff_updates_status(self):
        response = self.client.post(
            reverse('cars:inquiry_status_update', args=[self.inquiry.id]),
            {'status': 'contacted'},
        )
        self.assertRedirects(response, reverse('cars:inquiries_list'))
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, 'contacted')

    def test_update_redirects_back_to_next(self):
        response = self.client.post(
            reverse('cars:inquiry_status_update', args=[self.inquiry.id]),
            {'status': 'closed', 'next': f"{reverse('cars:inquiries_list')}?status=new"},
        )
        self.assertRedirects(response, f"{reverse('cars:inquiries_list')}?status=new")

    def test_non_staff_cannot_update(self):
        self.client.force_login(self.customer_user)
        response = self.client.post(
            reverse('cars:inquiry_status_update', args=[self.inquiry.id]),
            {'status': 'contacted'},
        )
        self.assertRedirects(response, reverse('cars:home'))
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, 'new')

    def test_invalid_status_rejected(self):
        self.client.post(
            reverse('cars:inquiry_status_update', args=[self.inquiry.id]),
            {'status': 'made_up'},
        )
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, 'new')

    def test_get_not_allowed(self):
        response = self.client.get(reverse('cars:inquiry_status_update', args=[self.inquiry.id]))
        self.assertRedirects(response, reverse('cars:inquiries_list'))


class OrderStatusUpdateTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.car = create_car()
        self.order = Order.objects.create(
            car=self.car,
            customer_name='Jane Doe',
            customer_email='jane@example.com',
            customer_phone='555-123-4567',
            customer_address='123 Main St',
            price=24000.00,
        )

    def test_staff_updates_status(self):
        response = self.client.post(
            reverse('cars:order_status_update', args=[self.order.id]),
            {'status': 'confirmed'},
        )
        self.assertRedirects(response, reverse('cars:orders_list'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'confirmed')

    def test_non_staff_cannot_update(self):
        self.client.force_login(self.customer_user)
        self.client.post(
            reverse('cars:order_status_update', args=[self.order.id]),
            {'status': 'confirmed'},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')


class ReportsTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.car = create_car()
        self.customer = create_customer()
        SalesTransaction.objects.create(
            car=self.car,
            customer=self.customer,
            sale_price=24000.00,
            total_amount=24500.00,
            payment_method='financing',
            status='completed',
            invoice_number='INV-2001',
        )
        Inquiry.objects.create(
            car=self.car,
            customer_name='Jane Doe',
            customer_email='jane@example.com',
            customer_phone='555-123-4567',
            message='Hello',
        )
        Order.objects.create(
            car=self.car,
            customer_name='Jane Doe',
            customer_email='jane@example.com',
            customer_phone='555-123-4567',
            customer_address='123 Main St',
            price=24000.00,
        )

    def test_reports_renders_for_staff(self):
        response = self.client.get(reverse('cars:reports'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Total Revenue')

    def test_reports_hides_from_non_staff(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:reports'))
        self.assertRedirects(response, reverse('cars:home'))


class HomeViewTests(TestCase):
    def test_home_renders(self):
        response = self.client.get(reverse('cars:home'))
        self.assertEqual(response.status_code, 200)

    def test_home_displays_customer_feedback(self):
        response = self.client.get(reverse('cars:home'))
        self.assertContains(response, 'What Our Customers Say')
        self.assertContains(response, 'Sandra M.')


class AboutViewTests(TestCase):
    def test_about_page_renders_vision_and_mission(self):
        response = self.client.get(reverse('cars:about'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Our Vision')
        self.assertContains(response, 'Our Mission')

    def test_about_page_is_public(self):
        self.client.logout()
        response = self.client.get(reverse('cars:about'))
        self.assertEqual(response.status_code, 200)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailNotificationTests(TestCase):
    def setUp(self):
        self.car = create_car()

    def test_inquiry_submission_sends_staff_email(self):
        response = self.client.post(reverse('cars:inquiry', args=[self.car.id]), {
            'customer_name': 'Jane Doe',
            'customer_email': 'jane@example.com',
            'customer_phone': '555-123-4567',
            'message': 'Interested in this vehicle',
        })
        self.assertRedirects(response, reverse('cars:inquiry_thank_you'))
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn(settings.DEALERSHIP_NOTIFY_EMAIL, email.to)
        self.assertIn('Toyota', email.subject)
        self.assertIn('Jane Doe', email.body)
        self.assertIn('Interested in this vehicle', email.body)

    def test_order_submission_sends_staff_email(self):
        response = self.client.post(reverse('cars:order', args=[self.car.id]), {
            'customer_name': 'John Smith',
            'customer_email': 'john@example.com',
            'customer_phone': '555-987-6543',
            'customer_address': '456 Oak Ave',
            'price': '24000.00',
            'trade_in_value': '0.00',
            'down_payment': '0.00',
            'financing_needed': 'on',
            'notes': 'Prefer weekend delivery',
        })
        self.assertRedirects(response, reverse('cars:order_thank_you'))
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn(settings.DEALERSHIP_NOTIFY_EMAIL, email.to)
        self.assertIn('Toyota', email.subject)
        self.assertIn('John Smith', email.body)
        self.assertIn('Prefer weekend delivery', email.body)

    def test_email_failure_does_not_block_submission(self):
        """A broken mail backend must never break the submission flow"""
        from unittest.mock import patch

        with patch('cars.emails.send_mail', side_effect=RuntimeError('SMTP down')):
            response = self.client.post(reverse('cars:inquiry', args=[self.car.id]), {
                'customer_name': 'Jane Doe',
                'customer_email': 'jane@example.com',
                'customer_phone': '555-123-4567',
                'message': 'Still interested',
            })
        self.assertRedirects(response, reverse('cars:inquiry_thank_you'))
        self.assertTrue(Inquiry.objects.filter(customer_email='jane@example.com').exists())


def make_image_file(name='test.png', color='red'):
    """Build a tiny valid PNG in memory"""
    from io import BytesIO
    from PIL import Image

    buf = BytesIO()
    Image.new('RGB', (100, 60), color).save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CarImageTests(TestCase):
    def setUp(self):
        self.car = create_car()

    def test_car_image_saves_and_belongs_to_car(self):
        CarImage.objects.create(car=self.car, image=make_image_file('front.png'), caption='Exterior')
        self.assertEqual(self.car.images.count(), 1)
        image = self.car.images.first()
        self.assertIn(f'cars/car_{self.car.id}/', image.image.name)

    def test_only_one_primary_image(self):
        primary = CarImage.objects.create(car=self.car, image=make_image_file('a.png', 'red'), is_primary=True)
        CarImage.objects.create(car=self.car, image=make_image_file('b.png', 'blue'), is_primary=True)
        primary.refresh_from_db()
        self.assertFalse(primary.is_primary)
        self.assertEqual(CarImage.objects.filter(car=self.car, is_primary=True).count(), 1)

    def test_detail_page_renders_image(self):
        CarImage.objects.create(car=self.car, image=make_image_file('front.png'), caption='Exterior')
        response = self.client.get(reverse('cars:car_detail', args=[self.car.id]))
        self.assertContains(response, 'carousel-item')
        self.assertContains(response, 'Exterior')

    def test_detail_page_placeholder_without_image(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.car.id]))
        self.assertContains(response, 'No photos available for this vehicle yet.')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CarCreateEditTests(StaffBaseTest):
    def post_data(self, **overrides):
        data = {
            'make': 'Honda',
            'model': 'Civic',
            'year': '2022',
            'vin': 'JH4KA7560MC000000',
            'color': 'White',
            'body_type': 'sedan',
            'transmission': 'automatic',
            'fuel_type': 'gasoline',
            'mileage': '15000',
            'engine_size': '1.5L',
            'horsepower': '158',
            'purchase_price': '15000.00',
            'asking_price': '18500.00',
            'condition': 'used',
            'status': 'available',
            'air_conditioning': 'on',
            'power_steering': 'on',
            'description': 'Well maintained, single owner.',
        }
        data.update(overrides)
        return data

    def test_anonymous_redirected_home_from_add_car(self):
        self.client.logout()
        response = self.client.get(reverse('cars:car_create'))
        self.assertRedirects(response, reverse('cars:home'))
        response = self.client.post(reverse('cars:car_create'), self.post_data())
        self.assertRedirects(response, reverse('cars:home'))

    def test_non_staff_redirected_home_from_add_car(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:car_create'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_staff_get_add_car_page(self):
        response = self.client.get(reverse('cars:car_create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Car')

    def test_staff_can_create_car(self):
        images = [make_image_file('front.png', 'red'), make_image_file('side.png', 'blue')]
        response = self.client.post(reverse('cars:car_create'), {**self.post_data(), 'images': images})
        car = Car.objects.get(vin='JH4KA7560MC000000')
        self.assertRedirects(response, reverse('cars:car_detail', args=[car.id]))
        self.assertEqual(Car.objects.count(), 1)
        self.assertEqual(car.make, 'Honda')
        self.assertEqual(car.images.count(), 2)
        self.assertTrue(car.images.first().is_primary)
        self.assertFalse(car.images.last().is_primary)

    def test_duplicate_vin_rejected(self):
        create_car()
        response = self.client.post(reverse('cars:car_create'), self.post_data(vin='1HGCM82633A004352'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Car.objects.count(), 1)
        self.assertContains(response, 'already exists')

    def test_invalid_image_file_rejected(self):
        bad_file = SimpleUploadedFile('bad.txt', b'not an image', content_type='text/plain')
        response = self.client.post(
            reverse('cars:car_create'), {**self.post_data(), 'images': [bad_file]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not valid images')
        self.assertEqual(Car.objects.count(), 0)

    def test_staff_get_edit_car_page(self):
        car = create_car()
        response = self.client.get(reverse('cars:car_edit', args=[car.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit Car')

    def test_staff_can_edit_car(self):
        car = create_car()
        existing = CarImage.objects.create(car=car, image=make_image_file('cur.png'), is_primary=True)
        response = self.client.post(
            reverse('cars:car_edit', args=[car.id]),
            {**self.post_data(vin='1HGCM82633A004352', model='Accord', asking_price='25000.00'),
             'images': [make_image_file('new.png', 'green')]},
        )
        self.assertRedirects(response, reverse('cars:car_detail', args=[car.id]))
        car.refresh_from_db()
        self.assertEqual(car.model, 'Accord')
        self.assertEqual(car.asking_price, 25000.00)
        self.assertEqual(car.images.count(), 2)
        existing.refresh_from_db()
        self.assertTrue(existing.is_primary)
        new_image = car.images.exclude(pk=existing.pk).get()
        self.assertFalse(new_image.is_primary)


def future_day(days=2):
    return (timezone.localdate() + timezone.timedelta(days=days)).isoformat()


class TestimonialHomeTests(TestCase):
    def test_seeded_testimonials_show_on_home(self):
        response = self.client.get(reverse('cars:home'))
        self.assertContains(response, 'What Our Customers Say')
        self.assertContains(response, 'Sandra M.')
        self.assertContains(response, 'Marcus T.')
        self.assertContains(response, 'Priya K.')

    def test_hidden_testimonial_not_shown(self):
        Testimonial.objects.create(
            customer_name='Hidden Guest', vehicle='2024 Tesla Model 3',
            quote='Secret review', rating=3, is_visible=False)
        response = self.client.get(reverse('cars:home'))
        self.assertNotContains(response, 'Hidden Guest')


class ReviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('reviewer', email='reviewer@example.com', password='pass-12345')

    def valid_data(self, **overrides):
        data = {
            'customer_name': 'Happy Buyer',
            'vehicle': '2023 Honda Civic',
            'quote': 'Fantastic service from start to finish!',
            'rating': '5',
        }
        data.update(overrides)
        return data

    def test_page_lists_visible_reviews_only(self):
        Testimonial.objects.create(
            customer_name='Visible Guest', vehicle='2021 Mazda CX-5',
            quote='Great buying experience', rating=4, is_visible=True)
        Testimonial.objects.create(
            customer_name='Pending Guest', vehicle='2020 Ford Focus',
            quote='Awaiting moderation', rating=2, is_visible=False)
        response = self.client.get(reverse('cars:reviews'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Visible Guest')
        self.assertContains(response, 'Great buying experience')
        self.assertNotContains(response, 'Pending Guest')

    def test_anonymous_sees_login_cta(self):
        response = self.client.get(reverse('cars:reviews'))
        self.assertContains(response, 'Sign In to Leave a Review')

    def test_anonymous_post_redirects_to_login(self):
        response = self.client.post(reverse('cars:reviews'), self.valid_data())
        self.assertRedirects(response, reverse('accounts:login'))
        self.assertEqual(Testimonial.objects.filter(customer_name='Happy Buyer').count(), 0)

    def test_logged_in_submits_pending_review_and_email_sent(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('cars:reviews'), self.valid_data())
        self.assertRedirects(response, reverse('cars:reviews'))

        testimonial = Testimonial.objects.get(customer_name='Happy Buyer')
        self.assertEqual(testimonial.user, self.user)
        self.assertEqual(testimonial.rating, 5)
        self.assertFalse(testimonial.is_visible)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(settings.DEALERSHIP_NOTIFY_EMAIL, mail.outbox[0].to)
        self.assertIn('[New Review]', mail.outbox[0].subject)
        self.assertIn('Fantastic service', mail.outbox[0].body)

        list_response = self.client.get(reverse('cars:reviews'))
        self.assertNotContains(list_response, 'Happy Buyer')

    def test_pending_review_appears_after_staff_approval(self):
        testimonial = Testimonial.objects.create(
            customer_name='Waiting Buyer', vehicle='2022 Subaru Outback',
            quote='Patiently waiting for approval', rating=4, is_visible=False)
        response = self.client.get(reverse('cars:reviews'))
        self.assertNotContains(response, 'Waiting Buyer')

        testimonial.is_visible = True
        testimonial.save(update_fields=['is_visible'])
        response = self.client.get(reverse('cars:reviews'))
        self.assertContains(response, 'Waiting Buyer')

    def test_short_quote_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('cars:reviews'), self.valid_data(quote='Tiny!'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Testimonial.objects.filter(customer_name='Happy Buyer').count(), 0)

    def test_rating_out_of_range_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('cars:reviews'), self.valid_data(rating='9'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Testimonial.objects.filter(customer_name='Happy Buyer').count(), 0)

    def test_email_failure_does_not_block_submission(self):
        from unittest.mock import patch

        self.client.force_login(self.user)
        with patch('cars.emails.send_mail', side_effect=RuntimeError('SMTP down')):
            response = self.client.post(reverse('cars:reviews'), self.valid_data())
        self.assertRedirects(response, reverse('cars:reviews'))
        self.assertEqual(Testimonial.objects.filter(customer_name='Happy Buyer').count(), 1)

    def test_form_prefills_customer_name_for_logged_in_user(self):
        Testimonial.objects.create(
            customer_name='Old Review', vehicle='2021 Kia Soul',
            quote='Here is an old verified review', rating=5, is_visible=True)
        self.client.force_login(self.user)
        response = self.client.get(reverse('cars:reviews'))
        self.assertContains(response, 'reviewer')


class AppointmentCreateTests(TestCase):
    def setUp(self):
        self.car = create_car()
        self.data = {
            'customer_name': 'Dave Rider',
            'customer_email': 'dave@example.com',
            'customer_phone': '555-111-2222',
            'preferred_date': future_day(),
            'preferred_time': '10:30',
            'message': 'I would like a manual transmission.',
        }

    def test_test_drive_form_renders(self):
        response = self.client.get(reverse('cars:test_drive', args=[self.car.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Book a Test Drive')

    def test_submission_creates_appointment_and_notifies_staff(self):
        response = self.client.post(reverse('cars:test_drive', args=[self.car.id]), self.data)
        self.assertRedirects(response, reverse('cars:car_appointment_thank_you'))
        appointment = Appointment.objects.get(customer_email='dave@example.com')
        self.assertEqual(appointment.car, self.car)
        self.assertEqual(appointment.status, 'pending')
        self.assertIsNone(appointment.user)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(settings.DEALERSHIP_NOTIFY_EMAIL, mail.outbox[0].to)
        self.assertIn('Test Drive Request', mail.outbox[0].subject)

    def test_submission_links_logged_in_user(self):
        user = User.objects.create_user('rider', email='rider@example.com', password='pass-12345')
        self.client.force_login(user)
        self.client.post(reverse('cars:test_drive', args=[self.car.id]), self.data)
        appointment = Appointment.objects.get(customer_email='dave@example.com')
        self.assertEqual(appointment.user, user)

    def test_past_date_rejected(self):
        self.data['preferred_date'] = future_day(days=-2)
        response = self.client.post(reverse('cars:test_drive', args=[self.car.id]), self.data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'must be scheduled for a future date')
        self.assertFalse(Appointment.objects.filter(customer_email='dave@example.com').exists())


class AppointmentStaffTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff', password='pass-12345', is_staff=True)
        self.customer = User.objects.create_user('customer', password='pass-12345')
        self.car = create_car()
        self.appointment = Appointment.objects.create(
            car=self.car, customer_name='Dave Rider', customer_email='dave@example.com',
            customer_phone='555-111-2222',
            preferred_date=timezone.localdate() + timezone.timedelta(days=2),
            preferred_time=timezone.datetime.strptime('10:30', '%H:%M').time(),
        )

    def test_list_requires_staff(self):
        response = self.client.get(reverse('cars:appointments_list'))
        self.assertRedirects(response, reverse('cars:home'))
        self.client.force_login(self.customer)
        response = self.client.get(reverse('cars:appointments_list'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_list_shows_appointments_for_staff(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('cars:appointments_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dave Rider')

    def test_approve_pending_sends_customer_email(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('cars:appointment_status_update', args=[self.appointment.pk]),
            {'status': 'approved'})
        self.assertRedirects(response, reverse('cars:appointments_list'))
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'approved')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('dave@example.com', mail.outbox[0].to)
        self.assertIn('confirmed', mail.outbox[0].subject)

    def test_pending_status_change_sends_no_email(self):
        self.client.force_login(self.staff)
        self.client.post(
            reverse('cars:appointment_status_update', args=[self.appointment.pk]),
            {'status': 'pending'})
        self.assertEqual(len(mail.outbox), 0)

    def test_non_staff_cannot_update_status(self):
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse('cars:appointment_status_update', args=[self.appointment.pk]),
            {'status': 'approved'})
        self.assertRedirects(response, reverse('cars:home'))
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'pending')


class MyActivityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password='pass-12345')
        self.other = User.objects.create_user('bob', password='pass-12345')
        self.car = create_car()
        self.inquiry = Inquiry.objects.create(
            user=self.user, car=self.car, customer_name='Alice',
            customer_email='alice@example.com', customer_phone='555-111',
            message='Hello')
        self.order = Order.objects.create(
            user=self.user, car=self.car, customer_name='Alice',
            customer_email='alice@example.com', customer_phone='555-111',
            customer_address='1 Main St', price='24000.00')
        self.appointment = Appointment.objects.create(
            user=self.user, car=self.car, customer_name='Alice',
            customer_email='alice@example.com', customer_phone='555-111',
            preferred_date=timezone.localdate() + timezone.timedelta(days=3),
            preferred_time=timezone.datetime.strptime('11:00', '%H:%M').time())
        Inquiry.objects.create(
            user=self.other, car=self.car, customer_name='Bob',
            customer_email='bob@example.com', customer_phone='555-222',
            message='Other user inquiry')
        self.other_inquiry = Inquiry.objects.get(customer_email='bob@example.com')

    def test_requires_login(self):
        response = self.client.get(reverse('cars:my_activity'))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('cars:my_activity')}")

    def test_lists_own_activity_only(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('cars:my_activity'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['inquiries']), 1)
        self.assertEqual(len(response.context['orders']), 1)
        self.assertEqual(len(response.context['appointments']), 1)
        self.assertNotIn(self.other_inquiry, response.context['inquiries'])
        self.assertNotContains(response, 'bob@example.com')
        self.assertContains(response, 'My Account')
        self.assertContains(response, '2021 Toyota Camry')


class NewsletterTests(TestCase):
    def test_subscribe_creates_subscription(self):
        response = self.client.post(reverse('cars:newsletter_subscribe'), {'email': 'news@example.com'})
        self.assertRedirects(response, reverse('cars:home'))
        self.assertTrue(NewsletterSubscription.objects.filter(email='news@example.com').exists())

    def test_subscribe_is_idempotent(self):
        NewsletterSubscription.objects.create(email='news@example.com', is_active=False)
        response = self.client.post(reverse('cars:newsletter_subscribe'), {'email': 'news@example.com'})
        self.assertRedirects(response, reverse('cars:home'))
        sub = NewsletterSubscription.objects.get(email='news@example.com')
        self.assertTrue(sub.is_active)
        self.assertEqual(NewsletterSubscription.objects.filter(email='news@example.com').count(), 1)

    def test_invalid_email_rejected(self):
        response = self.client.post(reverse('cars:newsletter_subscribe'), {'email': 'not-an-email'})
        self.assertRedirects(response, reverse('cars:home'))
        self.assertFalse(NewsletterSubscription.objects.filter(email='not-an-email').exists())

    def test_get_request_redirects_home(self):
        response = self.client.get(reverse('cars:newsletter_subscribe'))
        self.assertRedirects(response, reverse('cars:home'))


class ContactTests(TestCase):
    def test_contact_page_renders(self):
        response = self.client.get(reverse('cars:contact'))
        self.assertEqual(response.status_code, 200)

    def test_valid_message_saved_and_notified(self):
        response = self.client.post(reverse('cars:contact'), {
            'name': 'Grace Hopper',
            'email': 'grace@example.com',
            'subject': 'Financing question',
            'message': 'Do you offer 0% APR?',
        })
        self.assertRedirects(response, reverse('cars:contact'))
        self.assertTrue(ContactMessage.objects.filter(email='grace@example.com').exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(settings.DEALERSHIP_NOTIFY_EMAIL, mail.outbox[0].to)
        self.assertIn('Financing question', mail.outbox[0].subject)
        self.assertIn('Grace Hopper', mail.outbox[0].body)

    def test_invalid_message_not_saved(self):
        response = self.client.post(reverse('cars:contact'), {
            'name': '',
            'email': 'not-an-email',
            'subject': '',
            'message': '',
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ContactMessage.objects.exists())
        self.assertEqual(len(mail.outbox), 0)


class ResponsiveTemplateTests(StaffBaseTest):
    """Regression tests for mobile/responsive fixes."""

    def setUp(self):
        super().setUp()
        self.sale = SalesTransaction.objects.create(
            car=create_car(),
            customer=create_customer(),
            sale_price=24000.00,
            total_amount=24500.00,
            payment_method='cash',
            status='completed',
            invoice_number='INV-RESP',
        )

    def test_global_css_has_responsive_rules(self):
        response = self.client.get(reverse('cars:home'))
        self.assertContains(response, 'minmax(min(300px, 100%), 1fr)')
        self.assertContains(response, '.pagination {')
        self.assertContains(response, 'flex-wrap: wrap;')
        self.assertContains(response, 'overflow-wrap: anywhere;')
        self.assertContains(response, '.table .price-tag')
        self.assertContains(response, 'font-size: 1rem;')

    def test_home_no_longer_uses_hardcoded_300px_grid(self):
        response = self.client.get(reverse('cars:home'))
        self.assertNotContains(response, 'minmax(300px, 1fr)')

    def test_reviews_page_has_featured_grid_css(self):
        response = self.client.get(reverse('cars:reviews'))
        self.assertContains(response, 'featured-cars-grid')
        self.assertContains(response, 'minmax(min(300px, 100%), 1fr)')

    def test_lead_list_headers_wrap_on_mobile(self):
        for name in ['inquiries_list', 'orders_list', 'appointments_list']:
            response = self.client.get(reverse(f'cars:{name}'))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'flex-wrap flex-column flex-sm-row', msg_prefix=name)

    def test_customer_and_sales_list_headers_wrap_on_mobile(self):
        Customer.objects.create(
            first_name='Resp', last_name='Customer', email='resp@example.com',
            phone_number='555-0000', address='1 Main St', city='Springfield',
            state='CA', zip_code='90210',
        )
        for name in ['customer_list', 'sales_list']:
            response = self.client.get(reverse(f'cars:{name}'))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'card-header bg-light d-flex flex-wrap', msg_prefix=name)

    def test_sales_detail_price_table_is_responsive(self):
        response = self.client.get(reverse('cars:sales_detail', args=[self.sale.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<div class="table-responsive">')
        self.assertContains(response, 'price-tag')

class CsvExportTests(StaffBaseTest):
    """Staff CSV exports for sales, customers, inquiries, and orders"""

    def setUp(self):
        super().setUp()
        self.car = create_car()
        self.customer = create_customer()
        self.sale = SalesTransaction.objects.create(
            car=self.car,
            customer=self.customer,
            sale_price=24000.00,
            total_amount=24000.00,
            payment_method='cash',
            status='completed',
            invoice_number='INV-EXP-1',
        )
        self.inquiry = Inquiry.objects.create(
            car=self.car,
            customer_name='Jane Doe',
            customer_email='jane@example.com',
            customer_phone='555-123-4567',
            message='Export me please',
        )
        self.order = Order.objects.create(
            car=self.car,
            customer_name='Jane Doe',
            customer_email='jane@example.com',
            customer_phone='555-123-4567',
            customer_address='123 Main St',
            price=24000.00,
        )

    def assert_csv(self, response, filename):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn(filename, response['Content-Disposition'])

    def test_sales_export(self):
        response = self.client.get(reverse('cars:sales_export'))
        self.assert_csv(response, 'sales.csv')
        content = response.content.decode()
        self.assertIn('Invoice', content)
        self.assertIn('INV-EXP-1', content)

    def test_customers_export(self):
        response = self.client.get(reverse('cars:customer_export'))
        self.assert_csv(response, 'customers.csv')
        content = response.content.decode()
        self.assertIn('First Name', content)
        self.assertIn('Jane', content)

    def test_inquiries_export(self):
        response = self.client.get(reverse('cars:inquiries_export'))
        self.assert_csv(response, 'inquiries.csv')
        content = response.content.decode()
        self.assertIn('Export me please', content)

    def test_orders_export(self):
        response = self.client.get(reverse('cars:orders_export'))
        self.assert_csv(response, 'orders.csv')
        content = response.content.decode()
        self.assertIn('Order ID', content)
        self.assertIn('24000.00', content)

    def test_sales_export_honors_filters(self):
        response = self.client.get(reverse('cars:sales_export'), {'status': 'pending'})
        self.assert_csv(response, 'sales.csv')
        content = response.content.decode()
        self.assertIn('Invoice', content)
        self.assertNotIn('INV-EXP-1', content)

    def test_non_staff_redirected_from_exports(self):
        self.client.force_login(self.customer_user)
        for name in ['sales_export', 'customer_export', 'inquiries_export', 'orders_export']:
            response = self.client.get(reverse(f'cars:{name}'))
            self.assertRedirects(response, reverse('cars:home'), msg_prefix=name)

    def test_anonymous_redirected_from_exports(self):
        self.client.logout()
        for name in ['sales_export', 'customer_export', 'inquiries_export', 'orders_export']:
            response = self.client.get(reverse(f'cars:{name}'))
            self.assertRedirects(response, reverse('cars:home'), msg_prefix=name)

    def test_list_pages_link_to_exports(self):
        for name in ['sales_list', 'customer_list', 'inquiries_list', 'orders_list']:
            response = self.client.get(reverse(f'cars:{name}'))
            self.assertEqual(response.status_code, 200, name)
            self.assertContains(response, 'Export CSV', msg_prefix=name)


class PdfExportTests(CsvExportTests):
    """Staff PDF report export (ReportLab)"""

    def test_staff_can_download_sales_pdf(self):
        response = self.client.get(reverse('cars:sales_pdf_export'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('sales-report.pdf', response['Content-Disposition'])
        # PDF starts with the %PDF magic header
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_non_staff_redirected_from_pdf_export(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:sales_pdf_export'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_anonymous_redirected_from_pdf_export(self):
        self.client.logout()
        response = self.client.get(reverse('cars:sales_pdf_export'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_sales_pdf_honors_filters(self):
        response = self.client.get(reverse('cars:sales_pdf_export'), {'status': 'pending'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_pdf_export_degrades_gracefully_when_reportlab_missing(self):
        """A missing ReportLab must never 500 the site — redirect with an install hint"""
        from unittest.mock import patch

        from django.contrib.messages import get_messages

        with patch('cars.views.stream_pdf', side_effect=ImportError(
                "PDF export requires the 'reportlab' package.")):
            response = self.client.get(reverse('cars:sales_pdf_export'))
        # fetch_redirect_response=False: assertRedirects would otherwise fetch
        # the target itself and consume the flash message before we check it.
        self.assertRedirects(response, reverse('cars:sales_list'), fetch_redirect_response=False)
        queued = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('reportlab' in text for text in queued))


class CustomerCreateEditTests(StaffBaseTest):
    """Staff customer create/edit forms"""

    def valid_data(self, **overrides):
        data = {
            'first_name': 'John',
            'last_name': 'Smith',
            'email': 'john.smith@example.com',
            'phone_number': '555-999-0000',
            'address': '42 Elm St',
            'city': 'Springfield',
            'state': 'NY',
            'zip_code': '10001',
            'country': 'USA',
        }
        data.update(overrides)
        return data

    def test_create_form_renders_for_staff(self):
        response = self.client.get(reverse('cars:customer_create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Customer')

    def test_non_staff_redirected_from_create(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:customer_create'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_non_staff_redirected_from_edit(self):
        customer = create_customer()
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:customer_edit', args=[customer.id]))
        self.assertRedirects(response, reverse('cars:home'))

    def test_create_customer(self):
        response = self.client.post(reverse('cars:customer_create'), self.valid_data())
        customer = Customer.objects.get(email='john.smith@example.com')
        self.assertRedirects(response, reverse('cars:customer_detail', args=[customer.id]))
        self.assertEqual(customer.first_name, 'John')

    def test_create_customer_invalid_renders_form(self):
        response = self.client.post(reverse('cars:customer_create'), self.valid_data(email=''))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')
        self.assertFalse(Customer.objects.filter(first_name='John').exists())

    def test_edit_customer(self):
        customer = create_customer()
        response = self.client.post(
            reverse('cars:customer_edit', args=[customer.id]),
            self.valid_data(first_name='Janet'),
        )
        self.assertRedirects(response, reverse('cars:customer_detail', args=[customer.id]))
        customer.refresh_from_db()
        self.assertEqual(customer.first_name, 'Janet')

    def test_customer_list_links_to_create_and_edit(self):
        customer = create_customer()
        response = self.client.get(reverse('cars:customer_list'))
        self.assertContains(response, reverse('cars:customer_create'))
        self.assertContains(response, reverse('cars:customer_edit', args=[customer.id]))


class SaleCreateEditTests(StaffBaseTest):
    """Staff sale record create/edit forms"""

    def setUp(self):
        super().setUp()
        self.car = create_car()
        self.customer = create_customer()

    def valid_data(self, **overrides):
        data = {
            'car': self.car.id,
            'customer': self.customer.id,
            'salesperson': 'Alice Agent',
            'sale_price': '23500.00',
            'trade_in_value': '1500.00',
            'down_payment': '2000.00',
            'payment_method': 'financing',
            'status': 'pending',
        }
        data.update(overrides)
        return data

    def test_create_form_renders_for_staff(self):
        response = self.client.get(reverse('cars:sale_create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Record Sale')

    def test_non_staff_redirected_from_create(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:sale_create'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_create_sale_computes_total_and_invoice(self):
        response = self.client.post(reverse('cars:sale_create'), self.valid_data())
        sale = SalesTransaction.objects.get(customer=self.customer)
        self.assertRedirects(response, reverse('cars:sales_detail', args=[sale.id]))
        self.assertEqual(sale.total_amount, sale.sale_price - sale.trade_in_value)
        self.assertTrue(sale.invoice_number.startswith('INV-'))

    def test_create_generates_unique_invoice_numbers(self):
        self.client.post(reverse('cars:sale_create'), self.valid_data())
        self.client.post(reverse('cars:sale_create'), self.valid_data())
        invoices = SalesTransaction.objects.values_list('invoice_number', flat=True)
        self.assertEqual(len(invoices), len(set(invoices)))

    def test_create_sale_without_trade_in_defaults_total(self):
        data = self.valid_data()
        del data['trade_in_value']
        self.client.post(reverse('cars:sale_create'), data)
        sale = SalesTransaction.objects.get(customer=self.customer)
        self.assertEqual(sale.total_amount, sale.sale_price)

    def test_create_sale_excludes_sold_cars(self):
        sold = create_car(vin='SOLDVIN000000001', status='sold')
        sold.make = 'Ford'
        sold.save()
        response = self.client.get(reverse('cars:sale_create'))
        self.assertContains(response, 'Toyota')
        self.assertNotContains(response, 'Ford')

    def test_create_sale_invalid_renders_form(self):
        response = self.client.post(reverse('cars:sale_create'), self.valid_data(sale_price=''))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')
        self.assertEqual(SalesTransaction.objects.count(), 0)

    def test_edit_sale_recomputes_total(self):
        sale = SalesTransaction.objects.create(
            car=self.car,
            customer=self.customer,
            sale_price=24000.00,
            total_amount=24000.00,
            payment_method='cash',
            status='completed',
            invoice_number='INV-EDIT-1',
        )
        response = self.client.post(
            reverse('cars:sale_edit', args=[sale.id]),
            self.valid_data(sale_price='22000.00', trade_in_value='2000.00'),
        )
        self.assertRedirects(response, reverse('cars:sales_detail', args=[sale.id]))
        sale.refresh_from_db()
        self.assertEqual(sale.total_amount, sale.sale_price - sale.trade_in_value)
        self.assertEqual(sale.invoice_number, 'INV-EDIT-1')

    def test_non_staff_redirected_from_edit(self):
        sale = SalesTransaction.objects.create(
            car=self.car,
            customer=self.customer,
            sale_price=24000.00,
            total_amount=24000.00,
            payment_method='cash',
            status='completed',
            invoice_number='INV-EDIT-2',
        )
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:sale_edit', args=[sale.id]))
        self.assertRedirects(response, reverse('cars:home'))

    def test_sales_list_links_to_create_and_edit(self):
        sale = SalesTransaction.objects.create(
            car=self.car,
            customer=self.customer,
            sale_price=24000.00,
            total_amount=24000.00,
            payment_method='cash',
            status='completed',
            invoice_number='INV-LINKS-1',
        )
        response = self.client.get(reverse('cars:sales_list'))
        self.assertContains(response, reverse('cars:sale_create'))
        self.assertContains(response, reverse('cars:sale_edit', args=[sale.id]))


class TestimonialModerationTests(StaffBaseTest):
    """Staff review approval dashboard"""

    def setUp(self):
        super().setUp()
        self.pending = Testimonial.objects.create(
            customer_name='Pending Pat',
            quote='Great service, awaiting approval.',
            rating=4,
            is_visible=False,
        )
        self.published = Testimonial.objects.create(
            customer_name='Published Pam',
            quote='Wonderful experience overall.',
            rating=5,
            is_visible=True,
        )

    def test_list_renders_for_staff(self):
        response = self.client.get(reverse('cars:testimonial_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pending Pat')
        self.assertContains(response, 'Published Pam')
        self.assertContains(response, 'Pending Approval')

    def test_filter_pending_only(self):
        response = self.client.get(reverse('cars:testimonial_list'), {'visible': '0'})
        self.assertContains(response, 'Pending Pat')
        self.assertNotContains(response, 'Published Pam')

    def test_filter_published_only(self):
        response = self.client.get(reverse('cars:testimonial_list'), {'visible': '1'})
        self.assertContains(response, 'Published Pam')
        self.assertNotContains(response, 'Pending Pat')

    def test_non_staff_redirected_from_list(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:testimonial_list'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_staff_approves_review(self):
        response = self.client.post(
            reverse('cars:testimonial_visibility_update', args=[self.pending.id]),
            {'visible': '1'},
        )
        self.assertRedirects(response, reverse('cars:testimonial_list'))
        self.pending.refresh_from_db()
        self.assertTrue(self.pending.is_visible)

    def test_staff_hides_review(self):
        response = self.client.post(
            reverse('cars:testimonial_visibility_update', args=[self.published.id]),
            {'visible': '0'},
        )
        self.assertRedirects(response, reverse('cars:testimonial_list'))
        self.published.refresh_from_db()
        self.assertFalse(self.published.is_visible)

    def test_invalid_visibility_value_rejected(self):
        self.client.post(
            reverse('cars:testimonial_visibility_update', args=[self.pending.id]),
            {'visible': 'maybe'},
        )
        self.pending.refresh_from_db()
        self.assertFalse(self.pending.is_visible)

    def test_get_not_allowed(self):
        response = self.client.get(reverse('cars:testimonial_visibility_update', args=[self.pending.id]))
        self.assertRedirects(response, reverse('cars:testimonial_list'))
        self.pending.refresh_from_db()
        self.assertFalse(self.pending.is_visible)

    def test_non_staff_cannot_toggle(self):
        self.client.force_login(self.customer_user)
        self.client.post(
            reverse('cars:testimonial_visibility_update', args=[self.pending.id]),
            {'visible': '1'},
        )
        self.pending.refresh_from_db()
        self.assertFalse(self.pending.is_visible)

    def test_toggle_redirects_back_to_next(self):
        target = f"{reverse('cars:testimonial_list')}?visible=0"
        response = self.client.post(
            reverse('cars:testimonial_visibility_update', args=[self.pending.id]),
            {'visible': '1', 'next': target},
        )
        self.assertRedirects(response, target)

    def test_dashboard_links_to_reviews(self):
        response = self.client.get(reverse('cars:dashboard'))
        self.assertContains(response, reverse('cars:testimonial_list'))


class ContactInfoEditTests(StaffBaseTest):
    """Staff editing of the 'Visit or Call' section on the contact page"""

    def valid_data(self, **overrides):
        data = {
            'address': '99 New Road\nMetropolis, NY',
            'phone': '(555) 999-0000',
            'email': 'hello@example.com',
            'hours': 'Mon - Fri: 8:00 AM - 6:00 PM\nSunday: Closed',
        }
        data.update(overrides)
        return data

    def test_edit_form_renders_for_staff(self):
        response = self.client.get(reverse('cars:contact_info_edit'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit Visit or Call Info')

    def test_non_staff_redirected_from_edit(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:contact_info_edit'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_anonymous_redirected_from_edit(self):
        self.client.logout()
        response = self.client.get(reverse('cars:contact_info_edit'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_staff_updates_contact_info(self):
        response = self.client.post(reverse('cars:contact_info_edit'), self.valid_data())
        self.assertRedirects(response, reverse('cars:contact'))
        info = ContactInfo.get_solo()
        self.assertEqual(info.phone, '(555) 999-0000')
        self.assertEqual(info.email, 'hello@example.com')

    def test_invalid_email_renders_form(self):
        response = self.client.post(reverse('cars:contact_info_edit'), self.valid_data(email=''))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')
        self.assertEqual(ContactInfo.get_solo().phone, '(555) 123-4567')

    def test_blank_hours_rejected(self):
        response = self.client.post(reverse('cars:contact_info_edit'), self.valid_data(hours=''))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')
        self.assertEqual(ContactInfo.get_solo().hours, 'Mon – Sat: 9:00 AM – 7:00 PM\nSunday: Closed')

    def test_contact_page_shows_defaults_for_visitors(self):
        self.client.logout()
        response = self.client.get(reverse('cars:contact'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '123 Main Street')
        self.assertContains(response, '(555) 123-4567')
        self.assertContains(response, 'sales@car-dealership.local')
        self.assertContains(response, 'Sunday: Closed')

    def test_contact_page_shows_updated_info(self):
        ContactInfo.get_solo()
        self.client.post(reverse('cars:contact_info_edit'), self.valid_data())
        self.client.logout()
        response = self.client.get(reverse('cars:contact'))
        self.assertContains(response, '99 New Road')
        self.assertContains(response, '(555) 999-0000')
        self.assertNotContains(response, '123 Main Street')

    def test_contact_page_invalid_post_still_renders_contact_info(self):
        self.client.logout()
        response = self.client.post(reverse('cars:contact'), {})
        self.assertContains(response, '123 Main Street', status_code=400)

    def test_edit_button_shown_only_to_staff(self):
        contact_url = reverse('cars:contact_info_edit')
        response = self.client.get(reverse('cars:contact'))
        self.assertContains(response, contact_url)

        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:contact'))
        self.assertNotContains(response, contact_url)

        self.client.logout()
        response = self.client.get(reverse('cars:contact'))
        self.assertNotContains(response, contact_url)

    def test_staff_nav_links_to_contact_info(self):
        response = self.client.get(reverse('cars:dashboard'))
        self.assertContains(response, reverse('cars:contact_info_edit'))


class BrowseSortTests(TestCase):
    """Sorting options on the public browse page"""

    def setUp(self):
        self.car1 = create_car(vin='VIN-SORT-0000001')
        self.car1.asking_price = 30000.00
        self.car1.year = 2019
        self.car1.mileage = 12000
        self.car1.save()
        self.car2 = create_car(vin='VIN-SORT-0000002')
        self.car2.asking_price = 15000.00
        self.car2.year = 2023
        self.car2.mileage = 40000
        self.car2.save()

    def get_ids(self, **params):
        response = self.client.get(reverse('cars:browse_cars'), params)
        return [car.pk for car in response.context['cars']]

    def test_default_sort_newest(self):
        self.assertEqual(self.get_ids(), [self.car2.pk, self.car1.pk])

    def test_sort_price_ascending(self):
        self.assertEqual(self.get_ids(sort='price_asc'), [self.car2.pk, self.car1.pk])

    def test_sort_price_descending(self):
        self.assertEqual(self.get_ids(sort='price_desc'), [self.car1.pk, self.car2.pk])

    def test_sort_year_descending(self):
        self.assertEqual(self.get_ids(sort='year_desc'), [self.car2.pk, self.car1.pk])

    def test_sort_mileage_ascending(self):
        self.assertEqual(self.get_ids(sort='mileage_asc'), [self.car1.pk, self.car2.pk])

    def test_invalid_sort_falls_back_to_newest(self):
        self.assertEqual(self.get_ids(sort='bogus'), [self.car2.pk, self.car1.pk])


class CompareTests(TestCase):
    """Vehicle comparison page"""

    def setUp(self):
        self.car1 = create_car(vin='VIN-COMPARE-001')
        self.car2 = create_car(vin='VIN-COMPARE-002')
        self.car2.make = 'Honda'
        self.car2.model = 'Accord'
        self.car2.save()

    def test_compare_page_renders_selected_cars(self):
        url = reverse('cars:compare') + f"?ids={self.car1.pk},{self.car2.pk}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Compare Vehicles')
        self.assertContains(response, 'Toyota')
        self.assertContains(response, 'Honda')

    def test_compare_preserves_selection_order(self):
        url = reverse('cars:compare') + f"?ids={self.car2.pk},{self.car1.pk}"
        response = self.client.get(url)
        cars = list(response.context['cars'])
        self.assertEqual([c.pk for c in cars], [self.car2.pk, self.car1.pk])

    def test_compare_excludes_sold_cars(self):
        sold = create_car(vin='VIN-COMPARE-003')
        sold.status = 'sold'
        sold.save()
        url = reverse('cars:compare') + f"?ids={sold.pk},{self.car1.pk}"
        response = self.client.get(url)
        cars = list(response.context['cars'])
        self.assertEqual([c.pk for c in cars], [self.car1.pk])

    def test_compare_empty_state(self):
        response = self.client.get(reverse('cars:compare'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No vehicles selected')


class PaymentCalculatorTests(TestCase):
    """Payment calculator widget on the car detail page"""

    def setUp(self):
        self.car = create_car()
        self.car.asking_price = 30000.00
        self.car.save()

    def test_calculator_present_and_prefilled(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.car.id]))
        self.assertContains(response, 'Estimate Your Monthly Payment')
        self.assertContains(response, 'id="calc-price"')
        self.assertContains(response, 'value="30000.00"')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SavedSearchTests(TestCase):
    """Saved search / price-drop alert subscriptions"""

    def setUp(self):
        self.car = create_car()
        self.car.asking_price = 25000.00
        self.car.save()

    def test_create_search_sends_current_matches(self):
        response = self.client.post(reverse('cars:saved_search_create'), {
            'email': 'buyer@example.com',
            'make': 'Toyota',
            'price_min': '',
            'price_max': '',
            'year_min': '',
            'year_max': '',
            'body_type': '',
            'fuel_type': '',
            'next': reverse('cars:browse_cars'),
        })
        self.assertRedirects(response, reverse('cars:browse_cars'))
        search = SavedSearch.objects.get(email='buyer@example.com')
        self.assertEqual(search.make, 'Toyota')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('buyer@example.com', mail.outbox[0].to)
        self.assertIn('Toyota Camry', mail.outbox[0].body)

    def test_create_search_without_matches_still_saved(self):
        """Valid search that today matches nothing is still saved for later alerts"""
        response = self.client.post(reverse('cars:saved_search_create'), {
            'email': 'buyer@example.com',
            'make': 'Toyota',
            'price_min': '',
            'price_max': '5000',  # below every car's price: no current matches
            'year_min': '',
            'year_max': '',
            'body_type': '',
            'fuel_type': '',
        })
        self.assertRedirects(response, reverse('cars:browse_cars'))
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(SavedSearch.objects.filter(email='buyer@example.com', make='Toyota').exists())

    def test_invalid_form_rejected(self):
        response = self.client.post(reverse('cars:saved_search_create'), {'email': 'not-an-email'})
        self.assertRedirects(response, reverse('cars:browse_cars'))
        self.assertFalse(SavedSearch.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_logged_in_user_search_linked_to_account(self):
        user = User.objects.create_user('buyer', password='pass-12345')
        self.client.force_login(user)
        self.client.post(reverse('cars:saved_search_create'), {
            'email': 'buyer@example.com',
            'make': '',
            'price_min': '',
            'price_max': '',
            'year_min': '',
            'year_max': '',
            'body_type': '',
            'fuel_type': '',
        })
        search = SavedSearch.objects.get(email='buyer@example.com')
        self.assertEqual(search.user, user)

    def test_search_shows_on_my_activity_and_can_be_deleted(self):
        user = User.objects.create_user('buyer', password='pass-12345')
        search = SavedSearch.objects.create(user=user, email='buyer@example.com', make='Toyota')
        self.client.force_login(user)
        response = self.client.get(reverse('cars:my_activity'))
        self.assertContains(response, 'Toyota')
        response = self.client.post(reverse('cars:saved_search_delete', args=[search.pk]))
        self.assertRedirects(response, reverse('cars:my_activity'))
        self.assertFalse(SavedSearch.objects.filter(pk=search.pk).exists())

    def test_cannot_delete_others_search(self):
        user = User.objects.create_user('buyer', password='pass-12345')
        other = User.objects.create_user('other', password='pass-12345')
        search = SavedSearch.objects.create(user=other, email='other@example.com', make='Toyota')
        self.client.force_login(user)
        response = self.client.post(reverse('cars:saved_search_delete', args=[search.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(SavedSearch.objects.filter(pk=search.pk).exists())

    def test_management_command_emails_new_matches(self):
        search = SavedSearch.objects.create(email='buyer@example.com', make='Toyota')
        # Nothing new yet
        from io import StringIO
        from django.core.management import call_command
        call_command('check_saved_searches', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 0)

        # A new matching car arrives
        new_car = create_car(vin='VIN-NEW-00000001')
        new_car.make = 'Toyota'
        new_car.asking_price = 20000.00
        new_car.save()
        call_command('check_saved_searches', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('buyer@example.com', mail.outbox[0].to)
        search.refresh_from_db()
        self.assertIsNotNone(search.last_checked_at)


class BlogTests(TestCase):
    """Public news/blog pages"""

    def setUp(self):
        self.post = Post.objects.create(
            title='2025 Model Year Roundup',
            slug='2025-model-year-roundup',
            excerpt='A quick look at the newest models.',
            body='Long form content about the new models.',
            is_published=True,
        )
        Post.objects.create(
            title='Draft Post',
            slug='draft-post',
            body='Should not be visible yet.',
            is_published=False,
        )

    def test_list_shows_published_only(self):
        response = self.client.get(reverse('cars:blog_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2025 Model Year Roundup')
        self.assertNotContains(response, 'Draft Post')

    def test_detail_renders(self):
        response = self.client.get(reverse('cars:blog_detail', args=[self.post.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2025 Model Year Roundup')
        self.assertContains(response, 'Long form content')

    def test_draft_detail_404(self):
        response = self.client.get(reverse('cars:blog_detail', args=['draft-post']))
        self.assertEqual(response.status_code, 404)

    def test_home_shows_latest_news(self):
        response = self.client.get(reverse('cars:home'))
        self.assertContains(response, 'Latest News')
        self.assertContains(response, '2025 Model Year Roundup')


class StaticContentPageTests(TestCase):
    """Financing and FAQ content pages"""

    def test_financing_renders(self):
        response = self.client.get(reverse('cars:financing'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Financing Options')

    def test_faq_renders(self):
        response = self.client.get(reverse('cars:faq'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Frequently Asked Questions')


class SeoTests(TestCase):
    """robots.txt and sitemap.xml"""

    def setUp(self):
        self.car = create_car()
        Post.objects.create(title='Seo Post', slug='seo-post', body='Content.')

    def test_robots_txt_renders(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')
        self.assertContains(response, '/admin/')
        self.assertContains(response, '/sitemap.xml')

    def test_sitemap_xml_renders_and_includes_cars_and_posts(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '/car/')
        self.assertContains(response, '/news/seo-post/')
        self.assertContains(response, '/browse/')

    def test_car_detail_has_seo_meta(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.car.id]))
        self.assertContains(response, 'og:title')
        self.assertContains(response, 'og:url')
        self.assertContains(response, 'og:description')
        self.assertContains(response, 'canonical')
        # No og:image when the vehicle has no photos
        self.assertNotContains(response, 'og:image')
