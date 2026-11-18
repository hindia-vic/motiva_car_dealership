import json
import tempfile

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .antispam import client_ip
from .forms import ContactForm
from .chatbot import get_reply as chatbot_get_reply
from .listing import listing_fee
from .models import (
    AboutInfo, Appointment, Car, CarImage, ContactInfo, ContactMessage, Customer,
    NewsletterSubscription, Order, Inquiry, Post, SalesTransaction, SavedSearch,
    Testimonial, CarPriceHistory, CarStatusHistory, DealershipInfo, ChatSession,
    ChatMessage, ListingRequest, ListingRequestPhoto, FinancingApplication,
)
from accounts.models import Favorite


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

    def test_status_change_emails_customer(self):
        self.client.post(
            reverse('cars:inquiry_status_update', args=[self.inquiry.id]),
            {'status': 'contacted'},
        )
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn('jane@example.com', email.to)
        self.assertIn('Toyota', email.subject)
        self.assertIn('Jane Doe', email.body)

    def test_same_status_does_not_email(self):
        self.inquiry.status = 'contacted'
        self.inquiry.save()
        self.client.post(
            reverse('cars:inquiry_status_update', args=[self.inquiry.id]),
            {'status': 'contacted'},
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_internal_status_change_does_not_email(self):
        # 'closed' is a valid change but is not customer-facing.
        self.client.post(
            reverse('cars:inquiry_status_update', args=[self.inquiry.id]),
            {'status': 'closed'},
        )
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, 'closed')
        self.assertEqual(len(mail.outbox), 0)

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

    def test_status_change_emails_customer(self):
        self.client.post(
            reverse('cars:order_status_update', args=[self.order.id]),
            {'status': 'confirmed'},
        )
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn('jane@example.com', email.to)
        self.assertIn('Toyota', email.subject)

    def test_ready_for_pickup_email(self):
        self.client.post(
            reverse('cars:order_status_update', args=[self.order.id]),
            {'status': 'ready_for_pickup'},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('ready for pickup', mail.outbox[0].subject.lower())

    def test_same_status_does_not_email(self):
        self.order.status = 'confirmed'
        self.order.save()
        self.client.post(
            reverse('cars:order_status_update', args=[self.order.id]),
            {'status': 'confirmed'},
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_pending_status_does_not_email(self):
        # Moving back to 'pending' is a change, but not one we email about.
        self.order.status = 'confirmed'
        self.order.save()
        self.client.post(
            reverse('cars:order_status_update', args=[self.order.id]),
            {'status': 'pending'},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')
        self.assertEqual(len(mail.outbox), 0)

    def test_non_staff_cannot_update(self):
        self.client.force_login(self.customer_user)
        self.client.post(
            reverse('cars:order_status_update', args=[self.order.id]),
            {'status': 'confirmed'},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')


class AntiSpamTests(TestCase):
    """Honeypot, link heuristic, and per-IP rate limiting on public forms."""

    def setUp(self):
        cache.clear()
        self.car = create_car()

    def tearDown(self):
        cache.clear()

    def test_honeypot_field_is_rendered(self):
        response = self.client.get(reverse('cars:contact'))
        self.assertContains(response, 'name="website"')

    def test_honeypot_blocks_contact_submission(self):
        response = self.client.post(reverse('cars:contact'), {
            'name': 'Spam Bot',
            'email': 'bot@example.com',
            'subject': 'Cheap deals',
            'message': 'Buy now',
            'website': 'http://spam.example.com',
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ContactMessage.objects.filter(email='bot@example.com').exists())

    def test_honeypot_blocks_inquiry_submission(self):
        response = self.client.post(reverse('cars:inquiry', args=[self.car.id]), {
            'customer_name': 'Spam Bot',
            'customer_email': 'bot@example.com',
            'customer_phone': '555-0000',
            'message': 'Buy now',
            'website': 'http://spam.example.com',
        })
        self.assertEqual(response.status_code, 200)  # form re-rendered with errors
        self.assertFalse(Inquiry.objects.filter(customer_email='bot@example.com').exists())

    def test_honeypot_blocks_newsletter_subscription(self):
        response = self.client.post(reverse('cars:newsletter_subscribe'), {
            'email': 'bot@example.com',
            'website': 'spam',
        })
        self.assertRedirects(response, reverse('cars:home'))
        self.assertFalse(NewsletterSubscription.objects.filter(email='bot@example.com').exists())

    def test_empty_honeypot_allows_submission(self):
        response = self.client.post(reverse('cars:newsletter_subscribe'), {
            'email': 'real@example.com',
        })
        self.assertRedirects(response, reverse('cars:home'))
        self.assertTrue(NewsletterSubscription.objects.filter(email='real@example.com').exists())

    def test_link_heuristic_rejects_many_urls(self):
        form = ContactForm(data={
            'name': 'Spammer',
            'email': 'spam@example.com',
            'subject': 'Hi',
            'message': ' '.join(
                f'http://spam{i}.example.com' for i in range(6)
            ),
        })
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)

    @override_settings(ANTISPAM_RATE_LIMITS_ENABLED=True)
    def test_rate_limit_blocks_repeat_submissions(self):
        for i in range(5):
            self.client.post(reverse('cars:newsletter_subscribe'), {
                'email': f'user{i}@example.com',
            })
        # The sixth submission from the same IP is blocked.
        self.client.post(reverse('cars:newsletter_subscribe'), {
            'email': 'sixth@example.com',
        })
        self.assertEqual(NewsletterSubscription.objects.count(), 5)
        self.assertFalse(NewsletterSubscription.objects.filter(email='sixth@example.com').exists())

    @override_settings(ANTISPAM_RATE_LIMITS_ENABLED=False)
    def test_rate_limit_can_be_disabled(self):
        for i in range(8):
            self.client.post(reverse('cars:newsletter_subscribe'), {
                'email': f'bulk{i}@example.com',
            })
        self.assertEqual(NewsletterSubscription.objects.count(), 8)


class ClientIpTests(TestCase):
    """``client_ip`` only trusts forwarded headers when explicitly configured."""

    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, remote='10.0.0.5', forwarded=None):
        extra = {'REMOTE_ADDR': remote}
        if forwarded is not None:
            extra['HTTP_X_FORWARDED_FOR'] = forwarded
        return self.factory.get('/', **extra)

    @override_settings(TRUST_X_FORWARDED_FOR=False)
    def test_forwarded_header_ignored_by_default(self):
        request = self._request(forwarded='203.0.113.9')
        self.assertEqual(client_ip(request), '10.0.0.5')

    @override_settings(TRUST_X_FORWARDED_FOR=False)
    def test_remote_addr_used_when_header_absent(self):
        self.assertEqual(client_ip(self._request()), '10.0.0.5')

    @override_settings(TRUST_X_FORWARDED_FOR=True, X_FORWARDED_FOR_PROXY_COUNT=1)
    def test_trusted_proxy_uses_rightmost_hop(self):
        # A client can pad the left of the header; the proxy appends the real
        # peer address on the right, so that is the hop to trust.
        request = self._request(forwarded='1.2.3.4, 203.0.113.9')
        self.assertEqual(client_ip(request), '203.0.113.9')

    @override_settings(TRUST_X_FORWARDED_FOR=True, X_FORWARDED_FOR_PROXY_COUNT=2)
    def test_proxy_count_selects_correct_hop(self):
        request = self._request(forwarded='1.2.3.4, 198.51.100.7, 203.0.113.9')
        self.assertEqual(client_ip(request), '198.51.100.7')

    @override_settings(TRUST_X_FORWARDED_FOR=True, X_FORWARDED_FOR_PROXY_COUNT=1)
    def test_invalid_forwarded_value_falls_back_to_remote(self):
        request = self._request(forwarded='not-an-ip')
        self.assertEqual(client_ip(request), '10.0.0.5')

    @override_settings(TRUST_X_FORWARDED_FOR=True, X_FORWARDED_FOR_PROXY_COUNT=1)
    def test_short_forwarded_chain_falls_back_to_remote(self):
        request = self._request(forwarded='')
        self.assertEqual(client_ip(request), '10.0.0.5')


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

    def test_navbar_shows_primary_action(self):
        response = self.client.get(reverse('cars:home'))
        self.assertContains(response, 'Find Your Car')

    def test_uses_local_bootstrap_assets(self):
        response = self.client.get(reverse('cars:home'))
        self.assertContains(response, 'vendor/bootstrap/css/bootstrap.min.css')
        self.assertContains(response, 'vendor/bootstrap-icons/bootstrap-icons.css')
        self.assertNotContains(response, 'cdn.jsdelivr.net')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class HeroSliderTests(TestCase):
    def test_hero_uses_inventory_photos_when_available(self):
        car = create_car()
        image = CarImage.objects.create(car=car, image=make_image_file('hero.png'))

        response = self.client.get(reverse('cars:home'))

        self.assertContains(response, 'hero-modern has-slider')
        self.assertContains(response, 'class="hero-slide is-active"')
        self.assertContains(response, image.image.url)

    def test_hero_without_photos_keeps_the_gradient(self):
        response = self.client.get(reverse('cars:home'))

        self.assertContains(response, '<section class="hero-modern">')
        self.assertNotContains(response, 'class="hero-slider"')
        self.assertNotContains(response, 'class="hero-modern has-slider"')

    def test_hero_shows_one_photo_per_car(self):
        for index in range(2):
            car = create_car(vin=f'1HGCM82633A{index:06d}')
            CarImage.objects.create(
                car=car, image=make_image_file(f'hero{index}.png'),
            )

        response = self.client.get(reverse('cars:home'))
        html = response.content.decode()

        self.assertEqual(html.count('<img class="hero-slide'), 2)
        self.assertEqual(html.count('hero-slide is-active'), 1)

    def test_hero_skips_cars_without_photos(self):
        create_car(vin='1HGCM82633A000001')
        with_photo = create_car(vin='1HGCM82633A000002')
        CarImage.objects.create(
            car=with_photo, image=make_image_file('hero.png'),
        )

        response = self.client.get(reverse('cars:home'))
        html = response.content.decode()

        self.assertEqual(html.count('<img class="hero-slide'), 1)


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

    def test_order_submission_sends_staff_and_customer_email(self):
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
        self.assertEqual(len(mail.outbox), 2)

        staff_email = next(
            email for email in mail.outbox
            if settings.DEALERSHIP_NOTIFY_EMAIL in email.to
        )
        self.assertIn('Toyota', staff_email.subject)
        self.assertIn('John Smith', staff_email.body)
        self.assertIn('Prefer weekend delivery', staff_email.body)

        customer_email = next(
            email for email in mail.outbox if 'john@example.com' in email.to
        )
        self.assertIn('order', customer_email.subject.lower())
        self.assertIn('deposit', customer_email.body.lower())

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


def make_photo(name='photo.jpg', width=3000, height=2000, color='red'):
    """Build a photo in memory, big enough to need resizing."""
    from io import BytesIO
    from PIL import Image

    buf = BytesIO()
    Image.new('RGB', (width, height), color).save(buf, 'JPEG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


def make_photo_with_exif_orientation(name='rotated.jpg', width=200, height=100):
    """Build a photo whose EXIF says it should be rotated a quarter turn."""
    from io import BytesIO
    from PIL import Image

    image = Image.new('RGB', (width, height), 'red')
    exif = image.getexif()
    exif[0x0112] = 6          # "rotate 90 degrees clockwise"
    buf = BytesIO()
    image.save(buf, 'JPEG', exif=exif)
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


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
        self.assertContains(response, 'id="galleryMainImage"')
        self.assertContains(response, 'Exterior')
        # A single photo shows no thumbnail row or scroll track
        self.assertNotContains(response, 'id="galleryThumbs"')
        self.assertNotContains(response, 'id="galleryTrack"')

    def test_detail_page_renders_thumbnail_row_for_multiple_images(self):
        CarImage.objects.create(car=self.car, image=make_image_file('front.png'), caption='Front', is_primary=True)
        CarImage.objects.create(car=self.car, image=make_image_file('back.png', 'blue'), caption='Back')
        response = self.client.get(reverse('cars:car_detail', args=[self.car.id]))
        self.assertContains(response, 'id="galleryThumbs"')
        self.assertContains(response, 'id="galleryTrack"')
        self.assertContains(response, 'id="galleryTrackFill"')
        self.assertContains(response, 'class="gallery-thumb active"')
        self.assertContains(response, 'data-caption="Back"')
        self.assertContains(response, 'aria-label="View photo 2 of 2"')

    def test_detail_page_placeholder_without_image(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.car.id]))
        self.assertContains(response, 'No photos available for this vehicle yet.')

    def test_gallery_images_are_not_cropped(self):
        CarImage.objects.create(car=self.car, image=make_image_file('front.png'), caption='Exterior')
        response = self.client.get(reverse('cars:car_detail', args=[self.car.id]))
        html = response.content.decode()
        # Gallery only defines `contain` twice (main image + thumbnails), so the
        # whole photo is shown rather than cropped.
        self.assertEqual(html.count('object-fit: contain'), 2)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ImagePipelineTests(TestCase):
    """Uploaded photos are resized, re-encoded and given a thumbnail."""

    def setUp(self):
        self.car = create_car(vin='VIN-IMG-PIPE-001')

    @staticmethod
    def stored_size(image_field):
        from PIL import Image

        with image_field.open('rb') as handle:
            return Image.open(handle).size

    def test_uploaded_photo_is_resized(self):
        CarImage.objects.create(car=self.car, image=make_photo('big.jpg'))
        photo = self.car.images.first()
        width, height = self.stored_size(photo.image)
        self.assertLessEqual(width, settings.CAR_IMAGE_MAX_WIDTH)
        self.assertLessEqual(height, settings.CAR_IMAGE_MAX_WIDTH)

    def test_uploaded_photo_gets_a_thumbnail(self):
        CarImage.objects.create(car=self.car, image=make_photo('big.jpg'))
        photo = self.car.images.first()
        self.assertTrue(photo.thumbnail)
        width, _ = self.stored_size(photo.thumbnail)
        self.assertLessEqual(width, settings.CAR_IMAGE_THUMBNAIL_WIDTH)

    def test_photo_is_stored_as_a_jpeg_with_a_random_name(self):
        CarImage.objects.create(car=self.car, image=make_photo('big.jpg'))
        photo = self.car.images.first()
        self.assertTrue(photo.image.name.endswith('.jpg'))
        self.assertNotIn('big', photo.image.name)

    def test_exif_orientation_is_applied_and_exif_is_stripped(self):
        from PIL import Image

        CarImage.objects.create(car=self.car, image=make_photo_with_exif_orientation())
        photo = self.car.images.first()
        with photo.image.open('rb') as handle:
            stored = Image.open(handle)
            # The orientation tag said "rotate a quarter turn", so the
            # stored picture is now upright.
            self.assertEqual(stored.size, (100, 200))
            self.assertEqual(len(stored.getexif()), 0)

    def test_thumbnail_url_falls_back_to_the_full_image(self):
        CarImage.objects.create(car=self.car, image=make_photo('a.jpg'))
        photo = self.car.images.first()
        # A photo from before the image pipeline existed has no thumbnail.
        photo.thumbnail = None
        photo.save()
        photo.refresh_from_db()
        self.assertEqual(photo.thumbnail_url(), photo.image.url)

    def test_saving_a_caption_does_not_reprocess_the_photo(self):
        CarImage.objects.create(car=self.car, image=make_photo('big.jpg'))
        photo = self.car.images.first()
        name = photo.image.name
        size = photo.image.size

        photo.caption = 'Front bumper'
        photo.save()
        photo.refresh_from_db()

        self.assertEqual(photo.image.name, name)
        self.assertEqual(photo.image.size, size)

    def test_deleting_a_photo_removes_the_files(self):
        import os

        CarImage.objects.create(car=self.car, image=make_photo('big.jpg'))
        photo = self.car.images.first()
        image_path = photo.image.path
        thumbnail_path = photo.thumbnail.path
        self.assertTrue(os.path.exists(image_path))

        photo.delete()

        self.assertFalse(os.path.exists(image_path))
        self.assertFalse(os.path.exists(thumbnail_path))

    def test_reprocess_command_builds_the_thumbnail(self):
        from django.core.management import call_command

        CarImage.objects.create(car=self.car, image=make_photo('big.jpg'))
        photo = self.car.images.first()
        photo.thumbnail = None
        photo.save()

        call_command('reprocess_images')

        photo.refresh_from_db()
        self.assertTrue(photo.thumbnail)
        width, _ = self.stored_size(photo.thumbnail)
        self.assertLessEqual(width, settings.CAR_IMAGE_THUMBNAIL_WIDTH)

    def test_reprocess_command_dry_run_changes_nothing(self):
        from django.core.management import call_command

        CarImage.objects.create(car=self.car, image=make_photo('big.jpg'))
        photo = self.car.images.first()
        photo.thumbnail = None
        photo.save()
        name = photo.image.name

        call_command('reprocess_images', '--dry-run')

        photo.refresh_from_db()
        self.assertEqual(photo.image.name, name)
        self.assertFalse(photo.thumbnail)


class TradeInValuationTests(TestCase):
    """The trade-in estimate, the page and the order form widget."""

    def setUp(self):
        self.car = create_car(vin='VIN-TRADEIN-001')

    def estimate(self, **kwargs):
        from .tradein import estimate

        params = {
            'year': 2018,
            'make': 'Toyota',
            'model': 'Camry',
            'mileage': 60000,
            'condition': 'good',
        }
        params.update(kwargs)
        return estimate(**params)

    # -- the rules ---------------------------------------------------

    def test_estimate_returns_a_sane_range(self):
        low, high, mid = self.estimate()
        self.assertGreater(mid, 0)
        self.assertLess(low, mid)
        self.assertLess(mid, high)

    def test_older_vehicles_are_worth_less(self):
        _, _, newer = self.estimate(year=2019)
        _, _, older = self.estimate(year=2014)
        self.assertLess(older, newer)

    def test_high_mileage_is_worth_less(self):
        _, _, low_miles = self.estimate(mileage=40000)
        _, _, high_miles = self.estimate(mileage=150000)
        self.assertLess(high_miles, low_miles)

    def test_condition_changes_the_value(self):
        _, _, poor = self.estimate(condition='poor')
        _, _, excellent = self.estimate(condition='excellent')
        self.assertLess(poor, excellent)

    def test_a_premium_brand_is_worth_more(self):
        _, _, toyota = self.estimate(make='Toyota')
        _, _, bmw = self.estimate(make='BMW')
        self.assertGreater(bmw, toyota)

    def test_a_future_year_has_no_estimate(self):
        from .tradein import current_year

        self.assertEqual(self.estimate(year=current_year() + 5), (0, 0, 0))

    def test_a_missing_year_has_no_estimate(self):
        self.assertEqual(self.estimate(year=None), (0, 0, 0))

    def test_estimates_are_rounded_to_the_nearest_1000(self):
        _, _, mid = self.estimate()
        self.assertEqual(mid % 1000, 0)

    def test_breakdown_explains_the_number(self):
        from .tradein import breakdown

        result = breakdown(2018, 'Toyota', 'Camry', 60000, 'good', 'sedan')
        self.assertTrue(result['valid'])
        self.assertEqual(result['age'], 8)
        self.assertEqual(result['new_price'], 3510000)
        self.assertEqual(result['mid'], self.estimate()[2])

    def test_breakdown_names_the_vehicle(self):
        from .tradein import breakdown

        result = breakdown(2018, 'Toyota', 'Camry', 60000, 'good', 'sedan')
        self.assertEqual(result['make'], 'Toyota')
        self.assertEqual(result['model'], 'Camry')
        self.assertEqual(result['year'], 2018)

    # -- the page ----------------------------------------------------

    def test_trade_in_page_renders(self):
        response = self.client.get(reverse('cars:trade_in'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Trade-In Value Estimator')

    def test_trade_in_page_shows_an_estimate_when_posted(self):
        response = self.client.post(reverse('cars:trade_in'), {
            'year': '2018',
            'make': 'Toyota',
            'model': 'Camry',
            'mileage': '60000',
            'condition': 'good',
            'body_type': 'sedan',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Your estimated trade-in value')

    def test_trade_in_page_names_the_vehicle_it_valued(self):
        response = self.client.post(reverse('cars:trade_in'), {
            'year': '2018',
            'make': 'Toyota',
            'model': 'Camry',
            'mileage': '60000',
            'condition': 'good',
            'body_type': 'sedan',
        })
        self.assertContains(response, 'Toyota')
        self.assertContains(response, 'Camry')

    def test_trade_in_page_reports_bad_input(self):
        response = self.client.post(reverse('cars:trade_in'), {'year': 'abc'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter a whole number')

    # -- the JSON endpoint -------------------------------------------

    def test_estimate_endpoint_returns_json(self):
        response = self.client.post(reverse('cars:trade_in_estimate'), {
            'year': '2018',
            'make': 'Toyota',
            'model': 'Camry',
            'mileage': '60000',
            'condition': 'good',
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('low', data)
        self.assertIn('high', data)
        self.assertIn('mid', data)
        self.assertLess(data['low'], data['mid'])
        self.assertLess(data['mid'], data['high'])

    def test_estimate_endpoint_rejects_missing_details(self):
        response = self.client.post(reverse('cars:trade_in_estimate'), {'year': '2018'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_estimate_endpoint_only_accepts_post(self):
        response = self.client.get(reverse('cars:trade_in_estimate'))
        self.assertEqual(response.status_code, 405)

    # -- the order form ----------------------------------------------

    def test_order_form_shows_the_trade_in_widget(self):
        response = self.client.get(reverse('cars:order', args=[self.car.id]))
        self.assertContains(response, 'trade-in-estimate-btn')

    def test_car_page_shows_the_trade_in_widget(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.car.id]))
        self.assertContains(response, 'trade-in-estimate-btn')

    def test_order_saves_the_trade_in_details(self):
        self.client.post(reverse('cars:order', args=[self.car.id]), {
            'customer_name': 'John Smith',
            'customer_email': 'john@example.com',
            'customer_phone': '555-987-6543',
            'customer_address': '456 Oak Ave',
            'price': '24000.00',
            'trade_in_value': '6500.00',
            'down_payment': '0.00',
            'notes': '',
            'trade_in_year': '2018',
            'trade_in_make': 'Toyota',
            'trade_in_model': 'Camry',
            'trade_in_mileage': '60000',
            'trade_in_condition': 'good',
            'trade_in_body_type': 'sedan',
            'trade_in_estimate': '6500.00',
        })
        order = Order.objects.get(customer_email='john@example.com')
        self.assertEqual(order.trade_in_year, 2018)
        self.assertEqual(order.trade_in_make, 'Toyota')
        self.assertEqual(order.trade_in_model, 'Camry')
        self.assertEqual(order.trade_in_mileage, 60000)
        self.assertEqual(order.trade_in_condition, 'good')
        self.assertEqual(order.trade_in_body_type, 'sedan')

    def test_the_stored_estimate_is_our_own_number(self):
        """The hidden estimate field is the customer's to change, so it is
        worked out again from the details they gave us."""
        from .tradein import estimate

        self.client.post(reverse('cars:order', args=[self.car.id]), {
            'customer_name': 'John Smith',
            'customer_email': 'john@example.com',
            'customer_phone': '555-987-6543',
            'customer_address': '456 Oak Ave',
            'price': '24000.00',
            'trade_in_value': '6500.00',
            'down_payment': '0.00',
            'notes': '',
            'trade_in_year': '2018',
            'trade_in_make': 'Toyota',
            'trade_in_model': 'Camry',
            'trade_in_mileage': '60000',
            'trade_in_condition': 'good',
            'trade_in_body_type': 'sedan',
            # A number the customer typed into the hidden field.
            'trade_in_estimate': '999999.00',
        })
        order = Order.objects.get(customer_email='john@example.com')
        _, _, mid = estimate(2018, 'Toyota', 'Camry', 60000, 'good', 'sedan')
        self.assertEqual(float(order.trade_in_estimate), float(mid))
        self.assertNotEqual(float(order.trade_in_estimate), 999999.00)

    def test_the_body_type_changes_the_estimate(self):
        from .tradein import estimate

        self.client.post(reverse('cars:order', args=[self.car.id]), {
            'customer_name': 'John Smith',
            'customer_email': 'john@example.com',
            'customer_phone': '555-987-6543',
            'customer_address': '456 Oak Ave',
            'price': '24000.00',
            'trade_in_value': '0.00',
            'down_payment': '0.00',
            'notes': '',
            'trade_in_year': '2018',
            'trade_in_make': 'Toyota',
            'trade_in_model': 'Camry',
            'trade_in_mileage': '60000',
            'trade_in_condition': 'good',
            'trade_in_body_type': 'suv',
        })
        order = Order.objects.get(customer_email='john@example.com')
        _, _, suv = estimate(2018, 'Toyota', 'Camry', 60000, 'good', 'suv')
        _, _, sedan = estimate(2018, 'Toyota', 'Camry', 60000, 'good', 'sedan')
        self.assertEqual(float(order.trade_in_estimate), float(suv))
        self.assertGreater(suv, sedan)

    def test_order_without_trade_in_details_still_works(self):
        self.client.post(reverse('cars:order', args=[self.car.id]), {
            'customer_name': 'John Smith',
            'customer_email': 'john@example.com',
            'customer_phone': '555-987-6543',
            'customer_address': '456 Oak Ave',
            'price': '24000.00',
            'trade_in_value': '0.00',
            'down_payment': '0.00',
            'notes': '',
        })
        order = Order.objects.get(customer_email='john@example.com')
        self.assertEqual(order.trade_in_year, None)
        self.assertEqual(order.trade_in_condition, '')

    def test_chatbot_links_to_the_trade_in_page(self):
        result = chatbot_get_reply('Do you take trade-ins?')
        self.assertIn(reverse('cars:trade_in'), [link['url'] for link in result['links']])


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
        self.assertContains(response, 'Unsupported file type')
        self.assertEqual(Car.objects.count(), 0)

    def test_renamed_non_image_rejected(self):
        # A file with an image extension but the wrong content is caught too.
        bad_file = SimpleUploadedFile('fake.jpg', b'not an image', content_type='image/jpeg')
        response = self.client.post(
            reverse('cars:car_create'), {**self.post_data(), 'images': [bad_file]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'could not be read as an image')
        self.assertEqual(Car.objects.count(), 0)

    @override_settings(MAX_UPLOAD_SIZE_MB=0)
    def test_oversized_photo_rejected(self):
        photo = make_photo('big.jpg')
        response = self.client.post(
            reverse('cars:car_create'), {**self.post_data(), 'images': [photo]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'too large')
        self.assertEqual(Car.objects.count(), 0)

    def test_valid_photo_is_stored_with_a_thumbnail(self):
        photo = make_photo('front.jpg')
        response = self.client.post(
            reverse('cars:car_create'), {**self.post_data(), 'images': [photo]}
        )
        car = Car.objects.get(vin='JH4KA7560MC000000')
        self.assertRedirects(response, reverse('cars:car_detail', args=[car.id]))
        self.assertEqual(car.images.count(), 1)
        self.assertTrue(car.images.first().thumbnail)

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

    def test_sale_form_offers_the_online_orders(self):
        order = Order.objects.create(
            car=self.car,
            customer_name='John Smith',
            customer_email='john@example.com',
            customer_phone='555-987-6543',
            customer_address='456 Oak Ave',
            price=24000,
            trade_in_value=6500,
        )
        response = self.client.get(reverse('cars:sale_create'))
        self.assertContains(response, 'Online Order')
        self.assertContains(response, str(order.pk))

    def test_sale_prefills_the_claimed_trade_in_value(self):
        order = Order.objects.create(
            car=self.car,
            customer_name='John Smith',
            customer_email='john@example.com',
            customer_phone='555-987-6543',
            customer_address='456 Oak Ave',
            price=24000,
            trade_in_value=6500,
        )
        data = self.valid_data(trade_in_value='')
        data['order'] = order.id
        self.client.post(reverse('cars:sale_create'), data)
        sale = SalesTransaction.objects.get(customer=self.customer)
        self.assertEqual(sale.order, order)
        self.assertEqual(float(sale.trade_in_value), 6500.00)

    def test_sale_keeps_a_staff_entered_trade_in_value(self):
        order = Order.objects.create(
            car=self.car,
            customer_name='John Smith',
            customer_email='john@example.com',
            customer_phone='555-987-6543',
            customer_address='456 Oak Ave',
            price=24000,
            trade_in_value=6500,
        )
        data = self.valid_data(trade_in_value='5000.00')
        data['order'] = order.id
        self.client.post(reverse('cars:sale_create'), data)
        sale = SalesTransaction.objects.get(customer=self.customer)
        self.assertEqual(float(sale.trade_in_value), 5000.00)

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

    def test_staff_can_save_whatsapp_number(self):
        response = self.client.post(
            reverse('cars:contact_info_edit'),
            self.valid_data(whatsapp='+1 (415) 555-1234'),
        )
        self.assertRedirects(response, reverse('cars:contact'))
        self.assertEqual(ContactInfo.get_solo().whatsapp, '+1 (415) 555-1234')

    def test_contact_page_shows_whatsapp_button_when_set(self):
        ContactInfo.get_solo()
        self.client.post(
            reverse('cars:contact_info_edit'),
            self.valid_data(whatsapp='+1 (415) 555-1234'),
        )
        self.client.logout()
        response = self.client.get(reverse('cars:contact'))
        self.assertContains(response, 'Chat on WhatsApp')
        # Punctuation is stripped so wa.me gets a clean international number
        self.assertContains(response, 'https://wa.me/14155551234')

    def test_contact_page_hides_whatsapp_button_when_blank(self):
        self.client.logout()
        response = self.client.get(reverse('cars:contact'))
        self.assertNotContains(response, 'Chat on WhatsApp')

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


class AboutInfoEditTests(StaffBaseTest):
    """Staff editing of the content shown on the About page"""

    def valid_data(self, **overrides):
        data = {
            'page_tagline': 'Friendly people, great cars',
            'vision_text': 'To be the friendliest dealership in the state.',
            'mission_text': 'To make car buying simple and transparent.',
            'value_one_title': 'Great Cars',
            'value_one_text': 'Hand-picked, inspected inventory.',
            'value_two_title': 'Fair Deals',
            'value_two_text': 'Honest pricing every day.',
            'value_three_title': 'Lifetime Care',
            'value_three_text': 'Service that lasts as long as you own the car.',
        }
        data.update(overrides)
        return data

    def test_edit_form_renders_for_staff(self):
        response = self.client.get(reverse('cars:about_info_edit'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit About Page')

    def test_non_staff_redirected_from_edit(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:about_info_edit'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_anonymous_redirected_from_edit(self):
        self.client.logout()
        response = self.client.get(reverse('cars:about_info_edit'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_staff_updates_about_info(self):
        response = self.client.post(reverse('cars:about_info_edit'), self.valid_data())
        self.assertRedirects(response, reverse('cars:about'))
        info = AboutInfo.get_solo()
        self.assertEqual(info.value_one_title, 'Great Cars')
        self.assertEqual(info.mission_text, 'To make car buying simple and transparent.')

    def test_blank_required_field_renders_form(self):
        response = self.client.post(reverse('cars:about_info_edit'), self.valid_data(vision_text=''))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')
        self.assertEqual(AboutInfo.get_solo().value_one_title, 'Quality You Can Trust')

    def test_about_page_shows_defaults_for_visitors(self):
        self.client.logout()
        response = self.client.get(reverse('cars:about'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Vision, mission, and the values that guide us')
        self.assertContains(response, 'Quality You Can Trust')
        self.assertContains(response, 'Honest Pricing')
        self.assertContains(response, 'Support For Life')

    def test_about_page_shows_updated_content(self):
        AboutInfo.get_solo()
        self.client.post(reverse('cars:about_info_edit'), self.valid_data())
        self.client.logout()
        response = self.client.get(reverse('cars:about'))
        self.assertContains(response, 'Great Cars')
        self.assertContains(response, 'To make car buying simple and transparent.')
        self.assertNotContains(response, 'Quality You Can Trust')

    def test_edit_button_shown_only_to_staff(self):
        edit_url = reverse('cars:about_info_edit')
        response = self.client.get(reverse('cars:about'))
        self.assertContains(response, edit_url)

        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:about'))
        self.assertNotContains(response, edit_url)

        self.client.logout()
        response = self.client.get(reverse('cars:about'))
        self.assertNotContains(response, edit_url)

    def test_staff_nav_links_to_about_info(self):
        response = self.client.get(reverse('cars:dashboard'))
        self.assertContains(response, reverse('cars:about_info_edit'))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class DealershipInfoEditTests(StaffBaseTest):
    """Staff editing of the dealership name and logo"""

    def test_edit_form_renders_for_staff(self):
        response = self.client.get(reverse('cars:dealership_info_edit'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dealership Settings')

    def test_non_staff_redirected_from_edit(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:dealership_info_edit'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_anonymous_redirected_from_edit(self):
        self.client.logout()
        response = self.client.get(reverse('cars:dealership_info_edit'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_staff_updates_name(self):
        response = self.client.post(
            reverse('cars:dealership_info_edit'),
            {'name': 'Acme Motors'},
        )
        self.assertRedirects(response, reverse('cars:dealership_info_edit'))
        self.assertEqual(DealershipInfo.get_solo().name, 'Acme Motors')

    def test_blank_name_renders_form(self):
        response = self.client.post(reverse('cars:dealership_info_edit'), {'name': ''})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')
        self.assertEqual(DealershipInfo.get_solo().name, 'Car Dealership')

    def test_staff_uploads_logo(self):
        response = self.client.post(
            reverse('cars:dealership_info_edit'),
            {'name': 'Acme Motors', 'logo': make_image_file('logo.png')},
        )
        self.assertRedirects(response, reverse('cars:dealership_info_edit'))
        info = DealershipInfo.get_solo()
        self.assertTrue(info.logo)
        self.assertIn('branding/', info.logo.name)

    def test_oversized_logo_rejected(self):
        import os
        from io import BytesIO
        from PIL import Image

        buf = BytesIO()
        Image.frombytes('RGB', (1600, 1600), os.urandom(1600 * 1600 * 3)).save(buf, 'PNG')
        big = SimpleUploadedFile('big.png', buf.getvalue(), content_type='image/png')
        self.assertGreater(len(buf.getvalue()), 5 * 1024 * 1024)
        response = self.client.post(
            reverse('cars:dealership_info_edit'),
            {'name': 'Acme Motors', 'logo': big},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'smaller than 5 MB')
        self.assertFalse(DealershipInfo.get_solo().logo)

    def test_name_shown_in_navbar_and_footer(self):
        info = DealershipInfo.get_solo()
        info.name = 'Acme Motors'
        info.save()
        self.client.logout()
        response = self.client.get(reverse('cars:home'))
        self.assertContains(response, 'Acme Motors')

    def test_logo_shown_in_navbar(self):
        info = DealershipInfo.get_solo()
        info.logo = make_image_file('logo.png')
        info.save()
        self.client.logout()
        response = self.client.get(reverse('cars:home'))
        self.assertContains(response, info.logo.url)

    def test_default_name_shown_for_visitors(self):
        self.client.logout()
        response = self.client.get(reverse('cars:home'))
        self.assertContains(response, 'Car Dealership')

    def test_staff_nav_links_to_dealership_info(self):
        response = self.client.get(reverse('cars:dashboard'))
        self.assertContains(response, reverse('cars:dealership_info_edit'))

    def test_nav_link_shown_only_to_staff(self):
        info_url = reverse('cars:dealership_info_edit')
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:home'))
        self.assertNotContains(response, info_url)

        self.client.logout()
        response = self.client.get(reverse('cars:home'))
        self.assertNotContains(response, info_url)


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

    def test_compare_keeps_sold_cars_in_the_selection(self):
        # A shortlist should not lose a vehicle just because someone else
        # bought it while the customer was deciding.
        sold = create_car(vin='VIN-COMPARE-003')
        sold.status = 'sold'
        sold.save()
        url = reverse('cars:compare') + f"?ids={sold.pk},{self.car1.pk}"
        response = self.client.get(url)
        cars = list(response.context['cars'])
        self.assertEqual([c.pk for c in cars], [sold.pk, self.car1.pk])

    def test_compare_empty_state(self):
        response = self.client.get(reverse('cars:compare'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No vehicles selected')

    def test_detail_page_offers_compare(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.car1.pk]))
        self.assertContains(response, 'compare-check')
        self.assertContains(response, 'id="compareBar"')
        self.assertContains(response, 'Compare Now')
        self.assertContains(response, f'id="compare-{self.car1.pk}"')


class SoldCarVisibilityTests(TestCase):
    """Sold vehicles stay visible; reserved and in-maintenance ones do not."""

    def setUp(self):
        self.available = create_car(vin='VIN-VISIBLE-001')
        self.sold = create_car(vin='VIN-VISIBLE-002', status='sold')
        self.sold.make = 'Honda'
        self.sold.model = 'Accord'
        self.sold.save()
        self.reserved = create_car(vin='VIN-VISIBLE-003', status='reserved')
        self.maintenance = create_car(vin='VIN-VISIBLE-004', status='maintenance')

    def test_browse_lists_sold_cars(self):
        response = self.client.get(reverse('cars:browse_cars'))
        self.assertEqual(response.status_code, 200)
        pks = [car.pk for car in response.context['cars']]
        self.assertIn(self.sold.pk, pks)

    def test_browse_hides_reserved_and_maintenance_cars(self):
        response = self.client.get(reverse('cars:browse_cars'))
        pks = [car.pk for car in response.context['cars']]
        self.assertNotIn(self.reserved.pk, pks)
        self.assertNotIn(self.maintenance.pk, pks)

    def test_browse_facets_cover_the_listed_cars(self):
        # The filter lists have to match what is actually listed, otherwise a
        # visitor can pick a make that returns nothing.
        response = self.client.get(reverse('cars:browse_cars'))
        self.assertIn('Honda', list(response.context['makes']))
        self.assertIn('Toyota', list(response.context['makes']))

    def test_sold_badge_is_shown_on_the_browse_card(self):
        response = self.client.get(reverse('cars:browse_cars'))
        self.assertContains(response, 'Sold')

    def test_available_cars_do_not_get_a_sold_badge(self):
        Car.objects.exclude(pk=self.available.pk).delete()
        response = self.client.get(reverse('cars:browse_cars'))
        self.assertNotContains(response, '>Sold<')

    def test_sold_car_detail_page_still_works(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.sold.pk]))
        self.assertEqual(response.status_code, 200)

    def test_sold_car_detail_page_hides_the_enquiry_forms(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.sold.pk]))
        self.assertNotContains(response, 'Send an Inquiry')
        self.assertNotContains(response, 'Place an Order')
        self.assertNotContains(response, 'Book a Test Drive')

    def test_sold_car_detail_page_explains_the_sale(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.sold.pk]))
        self.assertContains(response, 'no longer available')
        self.assertContains(response, 'Browse All Vehicles')

    def test_sold_car_detail_page_offers_similar_vehicles(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.sold.pk]))
        # The available Toyota is a similar vehicle (same body type).
        self.assertContains(response, 'Similar Vehicles Available Now')
        self.assertContains(response, reverse('cars:car_detail', args=[self.available.pk]))

    def test_reserved_car_detail_page_hides_the_forms_too(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.reserved.pk]))
        self.assertNotContains(response, 'Send an Inquiry')

    def test_available_car_detail_page_still_has_the_forms(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.available.pk]))
        self.assertContains(response, 'Send an Inquiry')
        self.assertContains(response, 'Place an Order')
        self.assertContains(response, 'Book a Test Drive')

    def test_model_helpers(self):
        self.assertTrue(self.sold.is_publicly_listed())
        self.assertFalse(self.sold.is_available())
        self.assertFalse(self.reserved.is_publicly_listed())
        self.assertTrue(self.available.is_available())
        self.assertEqual(self.sold.status_badge_class(), 'bg-secondary')
        self.assertEqual(self.available.status_badge_class(), 'bg-success')


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

    def test_edit_requires_login(self):
        search = SavedSearch.objects.create(email='guest@example.com', make='Toyota')
        response = self.client.get(reverse('cars:saved_search_edit', args=[search.pk]))
        self.assertRedirects(response, reverse('accounts:login'))

    def test_owner_can_edit_search_and_sees_matches(self):
        user = User.objects.create_user('buyer', password='pass-12345')
        search = SavedSearch.objects.create(
            user=user, email='buyer@example.com', make='Toyota', notify_price_drops=False,
        )
        self.client.force_login(user)

        response = self.client.get(reverse('cars:saved_search_edit', args=[search.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Matching Now')
        self.assertContains(response, '2021 Toyota Camry')

        response = self.client.post(reverse('cars:saved_search_edit', args=[search.pk]), {
            'email': 'buyer@example.com',
            'make': 'Toyota',
            'price_min': '',
            'price_max': '',
            'year_min': '',
            'year_max': '',
            'body_type': '',
            'fuel_type': '',
            'notify_price_drops': 'on',
        })
        self.assertRedirects(response, reverse('cars:my_activity'))
        search.refresh_from_db()
        self.assertTrue(search.notify_price_drops)

    def test_cannot_edit_others_search(self):
        user = User.objects.create_user('buyer', password='pass-12345')
        other = User.objects.create_user('other', password='pass-12345')
        search = SavedSearch.objects.create(user=other, email='other@example.com', make='Toyota')
        self.client.force_login(user)
        response = self.client.get(reverse('cars:saved_search_edit', args=[search.pk]))
        self.assertEqual(response.status_code, 404)

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


class SimilarAndRecentlyViewedTests(TestCase):
    """Similar vehicles and session-based recently viewed lists on the detail page"""

    def setUp(self):
        self.car = create_car(vin='VIN-SIM-000000001')
        self.similar = create_car(vin='VIN-SIM-000000002')
        self.similar.make = 'Honda'
        self.similar.model = 'Civic'
        self.similar.body_type = 'sedan'
        self.similar.year = 2019
        self.similar.save()

    def test_similar_cars_match_body_type_and_exclude_self(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.car.pk]))
        similar = list(response.context['similar_cars'])
        self.assertIn(self.similar, similar)
        self.assertNotIn(self.car, similar)
        self.assertContains(response, 'Similar Vehicles')

    def test_recently_viewed_tracks_previous_cars(self):
        self.client.get(reverse('cars:car_detail', args=[self.car.pk]))
        response = self.client.get(reverse('cars:car_detail', args=[self.similar.pk]))
        recent = list(response.context['recently_viewed'])
        self.assertIn(self.car, recent)
        self.assertNotIn(self.similar, recent)
        self.assertContains(response, 'Recently Viewed')

    def test_recently_viewed_empty_on_first_visit(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.car.pk]))
        self.assertEqual(list(response.context['recently_viewed']), [])


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
        self.assertNotContains(response, reverse('admin:index'))
        self.assertContains(response, '/sitemap.xml')

    def test_robots_txt_keeps_private_customer_areas_out(self):
        response = self.client.get('/robots.txt')
        self.assertContains(response, 'Disallow: /my-hires/')
        self.assertContains(response, 'Disallow: /my-financing/')
        self.assertContains(response, 'Disallow: /my-services/')

    def test_sitemap_xml_renders_and_includes_cars_and_posts(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '/car/')
        self.assertContains(response, '/news/seo-post/')
        self.assertContains(response, '/browse/')

    def test_sitemap_includes_the_trade_in_page(self):
        response = self.client.get('/sitemap.xml')
        self.assertContains(response, reverse('cars:trade_in'))

    def test_sitemap_includes_public_content_and_hire_pages(self):
        response = self.client.get('/sitemap.xml')

        for name in (
            'cars:advanced_search', 'cars:privacy_policy',
            'cars:terms_of_service', 'hiring:hire_car_list',
            'hiring:hire_tours',
        ):
            self.assertContains(response, reverse(name), msg_prefix=name)

    def test_sitemap_excludes_reserved_cars(self):
        reserved = create_car(vin='RESERVED000000001', status='reserved')

        response = self.client.get('/sitemap.xml')

        self.assertNotContains(
            response, reverse('cars:car_detail', args=[reserved.pk]),
        )

    def test_public_pages_have_descriptions_and_og_tags(self):
        for name in (
            'cars:about', 'cars:contact', 'cars:reviews',
            'cars:advanced_search', 'cars:privacy_policy',
            'cars:terms_of_service',
        ):
            response = self.client.get(reverse(name))
            self.assertContains(response, 'name="description"', msg_prefix=name)
            self.assertContains(response, 'property="og:description"', msg_prefix=name)

    def test_car_detail_has_seo_meta(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.car.id]))
        self.assertContains(response, 'og:title')
        self.assertContains(response, 'og:url')
        self.assertContains(response, 'og:description')
        self.assertContains(response, 'canonical')
        # No og:image when the vehicle has no photos
        self.assertNotContains(response, 'og:image')


class CarAlertTests(TestCase):
    """Price-drop and back-in-stock alerts"""

    def setUp(self):
        self.car = create_car(status='available')

    def test_price_history_recorded_on_drop(self):
        self.car.asking_price = 21000.00
        self.car.save()
        history = CarPriceHistory.objects.filter(car=self.car)
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().old_price, 24000.00)
        self.assertEqual(history.first().new_price, 21000.00)
        self.assertTrue(history.first().is_drop)

    def test_price_increase_is_not_recorded(self):
        self.car.asking_price = 27000.00
        self.car.save()
        self.assertFalse(CarPriceHistory.objects.filter(car=self.car).exists())

    def test_no_history_when_price_unchanged(self):
        self.car.mileage = 9999
        self.car.save()
        self.assertFalse(CarPriceHistory.objects.filter(car=self.car).exists())

    def test_creation_records_no_history(self):
        new_car = create_car(vin='VIN-BRAND-NEW-0001')
        self.assertFalse(CarPriceHistory.objects.filter(car=new_car).exists())
        self.assertFalse(CarStatusHistory.objects.filter(car=new_car).exists())

    def test_update_fields_skips_unrelated_field(self):
        # Saving only the mileage must not create a price row even if the
        # in-memory asking_price looks different from the database.
        self.car.asking_price = 10000.00
        self.car.save(update_fields=['mileage'])
        self.assertFalse(CarPriceHistory.objects.filter(car=self.car).exists())

    def test_back_in_stock_recorded(self):
        self.car.status = 'sold'
        self.car.save()
        self.car.status = 'available'
        self.car.save()
        history = CarStatusHistory.objects.filter(car=self.car)
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().new_status, 'available')

    def test_status_change_to_non_available_not_recorded(self):
        self.car.status = 'sold'
        self.car.save()
        self.assertFalse(CarStatusHistory.objects.filter(car=self.car).exists())

    def test_favoriting_records_price(self):
        user = User.objects.create_user('fan', email='fan@example.com', password='pass-12345')
        self.client.force_login(user)
        self.client.post(reverse('accounts:toggle_favorite', args=[self.car.id]))
        favorite = Favorite.objects.get(user=user, car=self.car)
        self.assertEqual(favorite.price_at_save, self.car.asking_price)

    def test_price_drop_command_emails_favoriter(self):
        from io import StringIO
        from django.core.management import call_command
        user = User.objects.create_user('fan', email='fan@example.com', password='pass-12345')
        Favorite.objects.create(user=user, car=self.car, price_at_save=24000.00)
        self.car.asking_price = 21000.00
        self.car.save()

        call_command('send_car_alerts', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('fan@example.com', mail.outbox[0].to)
        self.assertIn('KSh 21,000', mail.outbox[0].body)
        self.assertIsNotNone(CarPriceHistory.objects.get(car=self.car).notified_at)

    def test_price_drop_command_emails_saved_search_subscriber(self):
        from io import StringIO
        from django.core.management import call_command
        SavedSearch.objects.create(email='sub@example.com', make='Toyota', price_max=22000)
        self.car.asking_price = 21000.00
        self.car.save()

        call_command('send_car_alerts', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('sub@example.com', mail.outbox[0].to)

    def test_opt_out_suppresses_favorite_email(self):
        from io import StringIO
        from django.core.management import call_command
        user = User.objects.create_user('fan', email='fan@example.com', password='pass-12345')
        user.profile.notify_price_drops = False
        user.profile.save(update_fields=['notify_price_drops'])
        Favorite.objects.create(user=user, car=self.car, price_at_save=24000.00)
        self.car.asking_price = 21000.00
        self.car.save()

        call_command('send_car_alerts', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 0)

    def test_alert_sent_only_once(self):
        from io import StringIO
        from django.core.management import call_command
        user = User.objects.create_user('fan', email='fan@example.com', password='pass-12345')
        Favorite.objects.create(user=user, car=self.car, price_at_save=24000.00)
        self.car.asking_price = 21000.00
        self.car.save()

        call_command('send_car_alerts', stdout=StringIO())
        call_command('send_car_alerts', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)

    def test_back_in_stock_command_emails_favoriter(self):
        from io import StringIO
        from django.core.management import call_command
        user = User.objects.create_user('fan', email='fan@example.com', password='pass-12345')
        Favorite.objects.create(user=user, car=self.car, price_at_save=24000.00)
        self.car.status = 'reserved'
        self.car.save()
        self.car.status = 'available'
        self.car.save()

        call_command('send_car_alerts', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('fan@example.com', mail.outbox[0].to)
        self.assertIn('available again', mail.outbox[0].body)

    def test_dry_run_sends_nothing_and_keeps_pending(self):
        from io import StringIO
        from django.core.management import call_command
        user = User.objects.create_user('fan', email='fan@example.com', password='pass-12345')
        Favorite.objects.create(user=user, car=self.car, price_at_save=24000.00)
        self.car.asking_price = 21000.00
        self.car.save()

        call_command('send_car_alerts', '--dry-run', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNone(CarPriceHistory.objects.get(car=self.car).notified_at)

    def test_alert_preferences_toggle(self):
        user = User.objects.create_user('fan', password='pass-12345')
        self.client.force_login(user)
        response = self.client.post(reverse('accounts:alert_preferences'), {
            'notify_price_drops': 'on',
            # notify_back_in_stock omitted -> unchecked
        })
        self.assertRedirects(response, reverse('cars:my_activity'))
        user.profile.refresh_from_db()
        self.assertTrue(user.profile.notify_price_drops)
        self.assertFalse(user.profile.notify_back_in_stock)

    def test_staff_send_alerts_button(self):
        staff = User.objects.create_user('staff2', password='pass-12345')
        staff.is_staff = True
        staff.save()
        user = User.objects.create_user('fan', email='fan@example.com', password='pass-12345')
        Favorite.objects.create(user=user, car=self.car, price_at_save=24000.00)
        self.car.asking_price = 21000.00
        self.car.save()

        self.client.force_login(staff)
        response = self.client.post(reverse('cars:send_alerts_now'))
        self.assertRedirects(response, reverse('cars:dashboard'))
        self.assertEqual(len(mail.outbox), 1)

    def test_send_alerts_button_requires_staff(self):
        user = User.objects.create_user('fan', password='pass-12345')
        self.client.force_login(user)
        response = self.client.post(reverse('cars:send_alerts_now'))
        self.assertRedirects(response, reverse('cars:home'))


class HealthCheckTests(TestCase):
    """The /health liveness probe used by platform / uptime monitors."""

    def test_health_returns_ok_json(self):
        response = self.client.get(reverse('health'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_health_has_no_trailing_slash_redirect(self):
        # A redirect would be treated as unhealthy by some monitors.
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)

    def test_health_is_public(self):
        self.client.logout()
        response = self.client.get(reverse('health'))
        self.assertEqual(response.status_code, 200)


class ChatBotEngineTests(TestCase):
    """The built-in, offline intent engine in cars/chatbot.py."""

    def test_greeting(self):
        result = chatbot_get_reply('Hi there!')
        self.assertEqual(result['intent'], 'greeting')
        self.assertFalse(result['escalate'])
        self.assertTrue(result['reply'])

    def test_financing_intent_links_to_financing_page(self):
        result = chatbot_get_reply('Do you offer financing?')
        self.assertEqual(result['intent'], 'financing')
        self.assertIn(reverse('cars:financing'),
                      [link['url'] for link in result['links']])

    def test_hours_uses_live_contact_info(self):
        info = ContactInfo.get_solo()
        info.hours = 'Mon-Fri 9-5'
        info.save()
        result = chatbot_get_reply('What are your opening hours?')
        self.assertIn('Mon-Fri 9-5', result['reply'])

    def test_location_uses_live_address(self):
        info = ContactInfo.get_solo()
        info.address = '42 Test Avenue'
        info.save()
        result = chatbot_get_reply('Where are you located?')
        self.assertIn('42 Test Avenue', result['reply'])

    def test_trade_in_intent(self):
        result = chatbot_get_reply('Do you take trade-ins?')
        self.assertEqual(result['intent'], 'trade_in')

    def test_test_drive_intent(self):
        result = chatbot_get_reply('How do I book a test drive?')
        self.assertEqual(result['intent'], 'test_drive')

    def test_contact_intent_shows_phone(self):
        info = ContactInfo.get_solo()
        info.phone = '(555) 000-1111'
        info.save()
        result = chatbot_get_reply('How can I contact you?')
        self.assertIn('(555) 000-1111', result['reply'])

    def test_inventory_lists_matching_car(self):
        create_car(vin='VIN-CHAT-1')
        result = chatbot_get_reply('Do you have any Toyota cars in stock?')
        self.assertEqual(result['intent'], 'inventory')
        self.assertIn('Toyota', result['reply'])
        self.assertIn('Camry', result['reply'])

    def test_inventory_with_no_matches(self):
        result = chatbot_get_reply('Do you have any Ferraris?')
        self.assertEqual(result['intent'], 'inventory')
        self.assertIn('couldn', result['reply'].lower())
        self.assertIn(reverse('cars:browse_cars'),
                      [link['url'] for link in result['links']])

    def test_pricing_intent(self):
        create_car(vin='VIN-CHAT-2')
        result = chatbot_get_reply('How much does a car cost?')
        self.assertEqual(result['intent'], 'pricing')

    def test_unknown_question_escalates(self):
        result = chatbot_get_reply('What is the airspeed velocity of a swallow?')
        self.assertEqual(result['intent'], 'unknown')
        self.assertTrue(result['escalate'])

    def test_long_message_is_truncated_not_crashing(self):
        result = chatbot_get_reply('a' * 5000)
        self.assertTrue(result['reply'])
        self.assertLessEqual(len(result['suggestions']), 10)

    def test_no_llm_configured_uses_rules(self):
        result = chatbot_get_reply('Do you offer financing?')
        self.assertEqual(result['intent'], 'financing')


class ChatBotLlmTests(TestCase):
    """The optional LLM upgrade and its fallback behaviour."""

    @override_settings(CHATBOT_PROVIDER='openai', CHATBOT_API_KEY='test-key')
    def test_llm_answer_used_when_available(self):
        fake = {'choices': [{'message': {'content': 'LLM says hello'}}]}
        with mock.patch('cars.chatbot._post_json', return_value=fake) as patched:
            result = chatbot_get_reply('Anything at all')
        self.assertTrue(patched.called)
        self.assertEqual(result['reply'], 'LLM says hello')
        self.assertFalse(result['escalate'])

    @override_settings(CHATBOT_PROVIDER='openai', CHATBOT_API_KEY='test-key')
    def test_llm_failure_falls_back_to_rules(self):
        with mock.patch('cars.chatbot._post_json', side_effect=RuntimeError('down')):
            result = chatbot_get_reply('Do you offer financing?')
        self.assertEqual(result['intent'], 'financing')
        self.assertIn('financing', result['reply'].lower())

    @override_settings(CHATBOT_PROVIDER='openai', CHATBOT_API_KEY='')
    def test_no_api_key_skips_llm(self):
        with mock.patch('cars.chatbot._post_json') as patched:
            result = chatbot_get_reply('Do you offer financing?')
        self.assertFalse(patched.called)
        self.assertEqual(result['intent'], 'financing')


class ChatBotViewTests(TestCase):
    """The /chatbot/ JSON endpoint and transcript logging."""

    def setUp(self):
        self.url = reverse('cars:chatbot_message')
        cache.clear()

    def post(self, payload):
        return self.client.post(
            self.url, data=json.dumps(payload), content_type='application/json'
        )

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_empty_message_rejected(self):
        response = self.post({'message': '   '})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_reply_is_json_and_logs_messages(self):
        response = self.post({'message': 'What are your hours?', 'session_key': 'abc12345'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('reply', data)
        self.assertIn('suggestions', data)
        self.assertEqual(data['session_key'], 'abc12345')

        session = ChatSession.objects.get(session_key='abc12345')
        self.assertEqual(session.messages.count(), 2)
        self.assertEqual(session.messages.first().sender, 'user')
        self.assertEqual(session.messages.last().sender, 'bot')

    def test_unknown_session_key_is_replaced(self):
        response = self.post({'message': 'hello', 'session_key': '../../etc/passwd'})
        self.assertEqual(response.status_code, 200)
        key = response.json()['session_key']
        self.assertNotEqual(key, '../../etc/passwd')
        self.assertTrue(ChatSession.objects.filter(session_key=key).exists())

    def test_session_key_is_reused(self):
        self.post({'message': 'hello', 'session_key': 'reuse123'})
        self.post({'message': 'what are your hours?', 'session_key': 'reuse123'})
        self.assertEqual(ChatSession.objects.filter(session_key='reuse123').count(), 1)
        self.assertEqual(
            ChatSession.objects.get(session_key='reuse123').messages.count(), 4
        )

    def test_unknown_question_returns_escalate(self):
        response = self.post({'message': 'What is the weather in Paris?'})
        self.assertTrue(response.json()['escalate'])

    def test_message_is_truncated(self):
        response = self.post({'message': 'x' * 5000, 'session_key': 'long1234'})
        self.assertEqual(response.status_code, 200)
        stored = ChatMessage.objects.filter(sender='user').first()
        self.assertLessEqual(len(stored.text), 500)

    @override_settings(ANTISPAM_RATE_LIMITS_ENABLED=True)
    def test_rate_limited(self):
        cache.clear()
        last = None
        for _ in range(31):
            last = self.post({'message': 'hello'})
        self.assertEqual(last.status_code, 302)


class ChatBotHandoffTests(TestCase):
    """Turning a conversation into a contact message for staff."""

    def setUp(self):
        self.url = reverse('cars:chatbot_handoff')
        cache.clear()

    def post(self, payload):
        return self.client.post(
            self.url, data=json.dumps(payload), content_type='application/json'
        )

    def test_requires_name_and_email(self):
        response = self.post({'name': '', 'email': 'not-an-email'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('name', response.json()['errors'])
        self.assertIn('email', response.json()['errors'])
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_creates_linked_contact_message_and_emails_staff(self):
        self.client.post(
            reverse('cars:chatbot_message'),
            data=json.dumps({'message': 'I need help with financing', 'session_key': 'hand1234'}),
            content_type='application/json',
        )
        response = self.post({
            'name': 'Jane Buyer',
            'email': 'jane@example.com',
            'session_key': 'hand1234',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])

        session = ChatSession.objects.get(session_key='hand1234')
        self.assertTrue(session.is_escalated)
        self.assertIsNotNone(session.contact_message)
        message = session.contact_message
        self.assertEqual(message.name, 'Jane Buyer')
        self.assertIn('Jane Buyer', message.subject)
        self.assertIn('financing', message.message)
        self.assertEqual(len(mail.outbox), 1)


class ChatBotStaffGatingTests(StaffBaseTest):
    """Staff-only transcript views and widget visibility."""

    def test_widget_shown_to_staff(self):
        response = self.client.get(reverse('cars:home'))
        self.assertContains(response, 'id="chatbotPanel"')

    def test_widget_shown_to_visitors(self):
        self.client.logout()
        response = self.client.get(reverse('cars:home'))
        self.assertContains(response, 'id="chatbotPanel"')

    @override_settings(CHATBOT_ENABLED=False)
    def test_widget_hidden_when_disabled(self):
        self.client.logout()
        response = self.client.get(reverse('cars:home'))
        self.assertNotContains(response, 'id="chatbotPanel"')

    def test_transcript_list_requires_staff(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:chatbot_sessions'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_transcript_list_visible_to_staff(self):
        response = self.client.get(reverse('cars:chatbot_sessions'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Chat Transcripts')

    def test_transcript_detail_shows_messages(self):
        session = ChatSession.objects.create(session_key='detail123')
        ChatMessage.objects.create(session=session, sender='user', text='Hi there')
        ChatMessage.objects.create(session=session, sender='bot', text='Hello!')

        response = self.client.get(
            reverse('cars:chatbot_session_detail', args=[session.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hi there')
        self.assertContains(response, 'Hello!')

    def test_staff_nav_links_to_transcripts(self):
        response = self.client.get(reverse('cars:dashboard'))
        self.assertContains(response, reverse('cars:chatbot_sessions'))


class MoneyFormattingTests(TestCase):
    """Every price on the site is shown in Kenyan shillings."""

    def setUp(self):
        self.car = create_car(vin='VIN-MONEY-001')

    # -- the helper ---------------------------------------------------

    def test_format_money_adds_the_symbol_and_separators(self):
        from .money import format_money

        self.assertEqual(format_money(3120000), 'KSh 3,120,000')
        self.assertEqual(format_money('3120000'), 'KSh 3,120,000')
        self.assertEqual(format_money(3120000.25), 'KSh 3,120,000')

    def test_format_money_can_show_cents(self):
        from .money import format_money

        self.assertEqual(format_money(45231.5, decimals=2), 'KSh 45,231.50')

    def test_format_money_copes_with_a_missing_value(self):
        from .money import format_money

        self.assertEqual(format_money(None), '')
        self.assertEqual(format_money(''), '')
        self.assertEqual(format_money('not a number'), '')

    def test_the_symbol_comes_from_the_settings(self):
        from .money import format_money

        with override_settings(CURRENCY_SYMBOL='KES'):
            self.assertEqual(format_money(1000), 'KES 1,000')

    # -- the pages ---------------------------------------------------

    def test_the_car_page_shows_the_price_in_shillings(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.car.pk]))
        self.assertContains(response, 'KSh 24,000')

    def test_the_car_page_has_no_dollar_sign_left(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.car.pk]))
        self.assertNotContains(response, '$')

    def test_the_browse_page_shows_the_price_in_shillings(self):
        response = self.client.get(reverse('cars:browse_cars'))
        self.assertContains(response, 'KSh 24,000')

    def test_the_financing_calculator_uses_the_currency(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.car.pk]))
        self.assertContains(response, 'currencySymbol = "KSh"')

    def test_the_trade_in_page_shows_shillings(self):
        response = self.client.post(reverse('cars:trade_in'), {
            'year': '2018',
            'make': 'Toyota',
            'model': 'Camry',
            'mileage': '60000',
            'condition': 'good',
            'body_type': 'sedan',
        })
        self.assertContains(response, 'KSh')

    def test_the_trade_in_estimate_endpoint_returns_shillings(self):
        response = self.client.post(reverse('cars:trade_in_estimate'), {
            'year': '2018',
            'make': 'Toyota',
            'model': 'Camry',
            'mileage': '60000',
            'condition': 'good',
            'body_type': 'sedan',
        })
        data = json.loads(response.content)
        self.assertGreater(data['mid'], 1000000)
        self.assertEqual(data['mid'] % 1000, 0)

    # -- the messages ------------------------------------------------

    def test_the_inquiry_email_shows_shillings(self):
        inquiry = Inquiry.objects.create(
            car=self.car,
            customer_name='Jane Doe',
            customer_email='jane@example.com',
            customer_phone='555-123-4567',
            message='Interested in this car',
        )
        from .emails import send_inquiry_notification

        send_inquiry_notification(inquiry)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('KSh 24,000', mail.outbox[0].body)

    def test_the_chatbot_quotes_the_price_in_shillings(self):
        reply = chatbot_get_reply('what is the price?')
        self.assertIn('KSh 24,000', reply['reply'])

    def test_a_saved_search_summary_shows_shillings(self):
        search = SavedSearch.objects.create(
            email='shopper@example.com',
            make='Toyota',
            price_min=2000000,
            price_max=4000000,
        )
        self.assertIn('KSh 2,000,000', search.summary())
        self.assertIn('KSh 4,000,000', search.summary())

    # -- the exports -------------------------------------------------

    def test_the_sales_export_names_the_currency_in_the_header(self):
        staff = User.objects.create_user('staff2', email='staff2@example.com', password='pass-12345')
        staff.is_staff = True
        staff.save()
        self.client.force_login(staff)
        response = self.client.get(reverse('cars:sales_export'))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        self.assertIn('Sale Price (KES)', body)
        self.assertIn('Total Amount (KES)', body)

    def test_the_orders_export_names_the_currency_in_the_header(self):
        staff = User.objects.create_user('staff3', email='staff3@example.com', password='pass-12345')
        staff.is_staff = True
        staff.save()
        self.client.force_login(staff)
        response = self.client.get(reverse('cars:orders_export'))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        self.assertIn('Price (KES)', body)


class PriceConversionCommandTests(TestCase):
    """The dollar-to-shilling conversion is an explicit, reversible act."""

    def setUp(self):
        self.car = create_car(vin='VIN-CONVERT-001')
        self.sale = SalesTransaction.objects.create(
            car=self.car,
            customer=Customer.objects.create(
                first_name='Sam',
                last_name='Buyer',
                email='sam@example.com',
            ),
            sale_price=24000.00,
            trade_in_value=3000.00,
            total_amount=21000.00,
            down_payment=5000.00,
            financed_amount=16000.00,
            payment_method='financing',
            status='pending',
        )

    def convert(self, *args):
        from io import StringIO
        from django.core.management import call_command

        out = StringIO()
        call_command('convert_prices_to_shillings', *args, stdout=out)
        return out.getvalue()

    def test_a_dry_run_changes_nothing(self):
        self.convert('--dry-run')
        self.car.refresh_from_db()
        self.sale.refresh_from_db()
        self.assertEqual(self.car.asking_price, 24000.00)
        self.assertEqual(self.sale.sale_price, 24000.00)
        self.assertEqual(self.sale.total_amount, 21000.00)

    def test_the_prices_are_converted(self):
        self.convert()
        self.car.refresh_from_db()
        self.sale.refresh_from_db()
        self.assertEqual(self.car.asking_price, 3120000.00)
        self.assertEqual(self.car.purchase_price, 2600000.00)
        self.assertEqual(self.sale.sale_price, 3120000.00)
        self.assertEqual(self.sale.trade_in_value, 390000.00)
        self.assertEqual(self.sale.total_amount, 2730000.00)
        self.assertEqual(self.sale.down_payment, 650000.00)
        self.assertEqual(self.sale.financed_amount, 2080000.00)

    def test_a_saved_price_is_converted_too(self):
        user = User.objects.create_user('fan2', email='fan2@example.com', password='pass-12345')
        Favorite.objects.create(user=user, car=self.car, price_at_save=24000.00)
        self.convert()
        favorite = Favorite.objects.get(user=user, car=self.car)
        self.assertEqual(favorite.price_at_save, 3120000.00)

    def test_the_rate_is_the_reviewed_constant(self):
        from cars.management.commands.convert_prices_to_shillings import RATE

        self.assertEqual(RATE, 130)

# ==================== LIST YOUR CAR ====================

LISTING_FEE = Decimal('2500.00')


def listing_request_data(**overrides):
    """A complete set of details for a listing request."""
    data = {
        'owner_name': 'Jane Doe',
        'owner_email': 'jane@example.com',
        'owner_phone': '0712345678',
        'make': 'Toyota',
        'model': 'Hilux',
        'year': '2019',
        'vin': 'JTEBU5JR8A5000001',
        'color': 'White',
        'body_type': 'suv',
        'transmission': 'automatic',
        'fuel_type': 'diesel',
        'mileage': '68000',
        'engine_size': '2.8L',
        'logbook_number': 'KCT 12345A',
        'logbook_owner_name': 'Jane Doe',
        'asking_price': '3500000',
        'description': 'Good condition, serviced regularly.',
    }
    data.update(overrides)
    return data


def listing_request_photos():
    """The files a customer has to send: a photo of the car and of the logbook."""
    return {
        'photos': [make_image_file('car.png', 'blue')],
        'logbook_photo': make_image_file('logbook.png', 'white'),
    }


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ListingRequestTests(TestCase):
    """The public side: asking us to list a car."""

    def setUp(self):
        self.user = User.objects.create_user(
            'jane', email='jane@example.com', password='pass-12345'
        )
        self.other = User.objects.create_user(
            'bob', email='bob@example.com', password='pass-12345'
        )

    def test_the_fee_is_two_thousand_five_hundred_shillings(self):
        self.assertEqual(listing_fee(), LISTING_FEE)

    def test_the_form_requires_a_signed_in_customer(self):
        response = self.client.get(reverse('cars:listing_request_create'))
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('cars:listing_request_create')}",
        )

    def test_the_form_renders_for_a_signed_in_customer(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('cars:listing_request_create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'List Your Car')
        self.assertContains(response, '2,500')

    def test_a_request_is_created_with_the_fee_and_the_owner(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('cars:listing_request_create'),
            {**listing_request_data(), **listing_request_photos()},
        )
        self.assertRedirects(response, reverse('cars:listing_request_thank_you'))

        listing = ListingRequest.objects.get()
        self.assertEqual(listing.user, self.user)
        self.assertEqual(listing.owner_email, 'jane@example.com')
        self.assertEqual(listing.vin, 'JTEBU5JR8A5000001')
        self.assertEqual(listing.fee_amount, LISTING_FEE)
        self.assertEqual(listing.payment_status, 'pending')
        self.assertEqual(listing.status, 'submitted')
        self.assertFalse(listing.vehicle_verified)
        self.assertFalse(listing.logbook_verified)
        self.assertTrue(listing.reference.startswith('LSR-'))

    def test_the_photos_and_the_logbook_are_stored_with_the_request(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse('cars:listing_request_create'),
            {**listing_request_data(), **listing_request_photos()},
        )
        listing = ListingRequest.objects.get()
        self.assertEqual(listing.vehicle_photos().count(), 1)
        self.assertEqual(listing.logbook_photos().count(), 1)
        # The logbook scan stays with the request; it is a private document.
        self.assertIn(f'listing_requests/request_{listing.id}/', listing.photos.first().photo.name)

    def test_the_fee_is_copied_onto_the_request(self):
        """Raising the fee later must not rewrite what a customer was quoted."""
        self.client.force_login(self.user)
        self.client.post(
            reverse('cars:listing_request_create'),
            {**listing_request_data(), **listing_request_photos()},
        )
        with override_settings(LISTING_FEE=Decimal('5000')):
            self.assertEqual(listing_fee(), Decimal('5000'))
        self.assertEqual(ListingRequest.objects.get().fee_amount, LISTING_FEE)

    def test_staff_are_emailed_about_a_new_request(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse('cars:listing_request_create'),
            {**listing_request_data(), **listing_request_photos()},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Listing Request', mail.outbox[0].subject)
        self.assertIn('JTEBU5JR8A5000001', mail.outbox[0].body)

    def test_a_car_photo_is_required(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('cars:listing_request_create'),
            {**listing_request_data(), 'logbook_photo': make_image_file('logbook.png')},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'at least one photo of the car')
        self.assertFalse(ListingRequest.objects.exists())

    def test_a_logbook_photo_is_required(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('cars:listing_request_create'),
            {**listing_request_data(), 'photos': [make_image_file('car.png')]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'photo of the logbook')
        self.assertFalse(ListingRequest.objects.exists())

    def test_a_file_that_is_not_an_image_is_rejected(self):
        self.client.force_login(self.user)
        bad = SimpleUploadedFile('bad.txt', b'not an image', content_type='text/plain')
        response = self.client.post(
            reverse('cars:listing_request_create'),
            {**listing_request_data(), 'photos': [bad],
             'logbook_photo': make_image_file('logbook.png')},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Unsupported file type')
        self.assertFalse(ListingRequest.objects.exists())

    def test_a_vin_already_in_the_inventory_is_rejected(self):
        create_car(vin='JTEBU5JR8A5000001')
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('cars:listing_request_create'),
            {**listing_request_data(), **listing_request_photos()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already listed on our website')
        self.assertFalse(ListingRequest.objects.exists())

    def test_a_second_open_request_for_the_same_car_is_rejected(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse('cars:listing_request_create'),
            {**listing_request_data(), **listing_request_photos()},
        )
        response = self.client.post(
            reverse('cars:listing_request_create'),
            {**listing_request_data(), **listing_request_photos()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already have a request open')
        self.assertEqual(ListingRequest.objects.count(), 1)

    def test_the_owner_only_sees_their_own_requests(self):
        mine = self._make_request(self.user)
        theirs = self._make_request(self.other)
        self.client.force_login(self.user)
        response = self.client.get(reverse('cars:my_listing_requests'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(mine, response.context['listing_requests'])
        self.assertNotIn(theirs, response.context['listing_requests'])

    def test_the_owner_cannot_open_somebody_elses_request(self):
        theirs = self._make_request(self.other)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('cars:listing_request_detail', args=[theirs.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_the_owner_can_follow_their_own_request(self):
        listing = self._make_request(self.user)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('cars:listing_request_detail', args=[listing.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, listing.reference)

    def _make_request(self, user):
        self.client.force_login(user)
        self.client.post(
            reverse('cars:listing_request_create'),
            {**listing_request_data(owner_email=user.email),
             **listing_request_photos()},
        )
        self.client.logout()
        return ListingRequest.objects.latest('created_at')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ListingRequestStaffTests(StaffBaseTest):
    """The staff side: verifying the request and publishing the listing."""

    def setUp(self):
        super().setUp()
        self.owner = User.objects.create_user(
            'owner', email='owner@example.com', password='pass-12345'
        )
        self.client.logout()
        self.client.force_login(self.owner)
        self.client.post(
            reverse('cars:listing_request_create'),
            {**listing_request_data(owner_email=self.owner.email),
             **listing_request_photos()},
        )
        self.client.logout()
        self.client.force_login(self.staff)
        self.listing = ListingRequest.objects.get()
        # The request itself notified staff; the tests below look at the
        # emails that the review sends.
        mail.outbox = []

    def publish_payload(self, **overrides):
        payload = {
            'make': 'Toyota',
            'model': 'Hilux',
            'year': '2019',
            'vin': 'JTEBU5JR8A5000001',
            'color': 'White',
            'body_type': 'suv',
            'transmission': 'automatic',
            'fuel_type': 'diesel',
            'mileage': '68000',
            'engine_size': '2.8L',
            'purchase_price': '0',
            'asking_price': '3500000',
            'condition': 'used',
            'status': 'available',
        }
        payload.update(overrides)
        return payload

    def verify(self, **overrides):
        """Tick the verification boxes and record the fee."""
        payload = {
            'status': 'under_review',
            'vehicle_verified': 'on',
            'logbook_verified': 'on',
            'payment_status': 'paid',
            'payment_reference': 'QHJ1234XYZ',
            'staff_notes': '',
            'rejection_reason': '',
            'action': 'save',
        }
        payload.update(overrides)
        return self.client.post(
            reverse('cars:listing_request_update', args=[self.listing.pk]),
            payload,
        )

    def test_the_staff_list_needs_staff(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:listing_requests_list'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_the_staff_list_shows_the_request(self):
        response = self.client.get(reverse('cars:listing_requests_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.listing.reference)
        self.assertContains(response, 'Jane Doe')

    def test_the_review_page_renders(self):
        response = self.client.get(
            reverse('cars:listing_request_review', args=[self.listing.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.listing.reference)
        self.assertContains(response, 'vehicle_verified')

    def test_the_verification_and_the_fee_are_recorded(self):
        self.verify()
        self.listing.refresh_from_db()
        self.assertTrue(self.listing.vehicle_verified)
        self.assertTrue(self.listing.logbook_verified)
        self.assertEqual(self.listing.payment_status, 'paid')
        self.assertEqual(self.listing.payment_reference, 'QHJ1234XYZ')
        self.assertIsNotNone(self.listing.payment_received_at)
        self.assertEqual(self.listing.reviewed_by, self.staff)

    def test_publishing_is_blocked_until_the_car_is_inspected(self):
        self.verify(vehicle_verified='')
        self.listing.refresh_from_db()
        self.assertFalse(self.listing.vehicle_verified)

        response = self.client.post(
            reverse('cars:listing_request_publish', args=[self.listing.pk]),
            self.publish_payload(),
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Car.objects.filter(vin='JTEBU5JR8A5000001').exists())
        self.listing.refresh_from_db()
        self.assertNotEqual(self.listing.status, 'listed')

    def test_publishing_is_blocked_until_the_logbook_is_verified(self):
        self.verify(logbook_verified='')
        self.listing.refresh_from_db()
        self.assertFalse(self.listing.logbook_verified)

        self.client.post(
            reverse('cars:listing_request_publish', args=[self.listing.pk]),
            self.publish_payload(),
        )
        self.assertFalse(Car.objects.filter(vin='JTEBU5JR8A5000001').exists())

    def test_publishing_is_blocked_until_the_fee_is_settled(self):
        self.verify(payment_status='pending')
        self.listing.refresh_from_db()
        self.assertFalse(self.listing.is_settled())

        self.client.post(
            reverse('cars:listing_request_publish', args=[self.listing.pk]),
            self.publish_payload(),
        )
        self.assertFalse(Car.objects.filter(vin='JTEBU5JR8A5000001').exists())

    def test_a_waived_fee_also_lets_the_listing_go_live(self):
        self.verify(payment_status='waived')
        self.listing.refresh_from_db()
        self.assertTrue(self.listing.is_settled())

        self.client.post(
            reverse('cars:listing_request_publish', args=[self.listing.pk]),
            self.publish_payload(),
        )
        self.assertTrue(Car.objects.filter(vin='JTEBU5JR8A5000001').exists())

    def test_publishing_creates_the_listing_on_the_owners_behalf(self):
        self.verify()
        response = self.client.post(
            reverse('cars:listing_request_publish', args=[self.listing.pk]),
            self.publish_payload(),
        )
        car = Car.objects.get(vin='JTEBU5JR8A5000001')
        self.assertRedirects(response, reverse('cars:car_detail', args=[car.pk]))
        self.assertEqual(car.status, 'available')
        self.assertEqual(car.asking_price, 3500000.00)

        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, 'listed')
        self.assertEqual(self.listing.car, car)
        self.assertEqual(self.listing.reviewed_by, self.staff)

    def test_the_owners_photos_become_the_listings_photos(self):
        self.verify()
        self.client.post(
            reverse('cars:listing_request_publish', args=[self.listing.pk]),
            self.publish_payload(),
        )
        car = Car.objects.get(vin='JTEBU5JR8A5000001')
        self.assertEqual(car.images.count(), 1)
        self.assertTrue(car.images.first().is_primary)

    def test_the_owner_is_emailed_when_the_listing_goes_live(self):
        self.verify()
        mail.outbox = []
        self.client.post(
            reverse('cars:listing_request_publish', args=[self.listing.pk]),
            self.publish_payload(),
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('is now listed on our website', mail.outbox[0].subject)

    def test_a_request_cannot_be_published_twice(self):
        self.verify()
        self.client.post(
            reverse('cars:listing_request_publish', args=[self.listing.pk]),
            self.publish_payload(),
        )
        self.client.post(
            reverse('cars:listing_request_publish', args=[self.listing.pk]),
            self.publish_payload(),
        )
        self.assertEqual(Car.objects.filter(vin='JTEBU5JR8A5000001').count(), 1)

    def test_rejecting_a_request_needs_a_reason(self):
        response = self.client.post(
            reverse('cars:listing_request_update', args=[self.listing.pk]),
            {'action': 'reject', 'rejection_reason': '   '},
        )
        self.assertEqual(response.status_code, 302)
        self.listing.refresh_from_db()
        self.assertNotEqual(self.listing.status, 'rejected')

    def test_rejecting_a_request_emails_the_owner(self):
        self.client.post(
            reverse('cars:listing_request_update', args=[self.listing.pk]),
            {'action': 'reject', 'rejection_reason': 'The logbook is not in your name.'},
        )
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, 'rejected')
        self.assertEqual(self.listing.rejection_reason, 'The logbook is not in your name.')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('owner@example.com', mail.outbox[0].to)

    def test_the_owner_sees_the_rejection_reason(self):
        self.client.post(
            reverse('cars:listing_request_update', args=[self.listing.pk]),
            {'action': 'reject', 'rejection_reason': 'The logbook is not in your name.'},
        )
        self.client.logout()
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse('cars:listing_request_detail', args=[self.listing.pk])
        )
        self.assertContains(response, 'The logbook is not in your name.')

    def test_a_request_can_be_marked_as_awaiting_payment(self):
        self.verify(status='awaiting_payment', payment_status='pending')
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, 'awaiting_payment')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Listing fee due', mail.outbox[0].subject)

    def test_the_publish_view_needs_staff(self):
        self.client.force_login(self.customer_user)
        self.client.post(
            reverse('cars:listing_request_publish', args=[self.listing.pk]),
            self.publish_payload(),
        )
        self.assertFalse(Car.objects.filter(vin='JTEBU5JR8A5000001').exists())


FINANCING_RATE = Decimal('14.5')


def financing_data(**overrides):
    """A complete application for a 3,000,000 car with a 600,000 deposit.

    The income is high enough that the repayment stays under a third of it,
    so the default payload is one the website accepts.
    """
    data = {
        'customer_name': 'Jane Doe',
        'customer_email': 'jane@example.com',
        'customer_phone': '0712345678',
        'employment_status': 'employed',
        'employer_name': 'Acme Ltd',
        'job_title': 'Engineer',
        'monthly_income': '250000',
        'monthly_expenses': '50000',
        'price': '3000000',
        'deposit_amount': '600000',
        'trade_in_value': '0',
        'loan_term_months': '36',
        'car_label': 'Toyota Hilux',
    }
    data.update(overrides)
    return data


class FinancingRulesTests(TestCase):
    """The arithmetic, kept out of the templates and the admin."""

    def test_the_interest_rate_is_fourteen_and_a_half_percent(self):
        from .financing import interest_rate
        self.assertEqual(interest_rate(), FINANCING_RATE)

    def test_the_rate_is_overridable_from_settings(self):
        from .financing import interest_rate
        with override_settings(FINANCING_INTEREST_RATE=Decimal('12')):
            self.assertEqual(interest_rate(), Decimal('12'))

    def test_the_minimum_deposit_is_ten_percent_of_the_price(self):
        from .financing import min_deposit
        self.assertEqual(min_deposit(3000000), Decimal('300000.00'))

    def test_the_monthly_repayment_amortises_the_loan(self):
        from .financing import monthly_payment
        payment = monthly_payment(2400000, FINANCING_RATE, 36)
        self.assertGreater(payment, Decimal('80000'))
        self.assertLess(payment, Decimal('85000'))

    def test_the_total_repaid_is_the_payment_times_the_months(self):
        from .financing import monthly_payment, total_repayable
        payment = monthly_payment(2400000, FINANCING_RATE, 36)
        self.assertEqual(total_repayable(2400000, FINANCING_RATE, 36), payment * 36)

    def test_a_repayment_may_not_exceed_a_third_of_income(self):
        from .financing import affordability_ok
        self.assertTrue(affordability_ok(250000, Decimal('82000')))
        self.assertFalse(affordability_ok(100000, Decimal('82000')))

    def test_a_loan_with_no_principal_costs_nothing(self):
        from .financing import monthly_payment
        self.assertEqual(monthly_payment(0, FINANCING_RATE, 36), Decimal('0'))


class FinancingApplicationTests(TestCase):
    """The public side: applying for finance."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            'jane', email='jane@example.com', password='pass-12345'
        )
        self.other = User.objects.create_user(
            'bob', email='bob@example.com', password='pass-12345'
        )

    def tearDown(self):
        cache.clear()

    def apply(self, **overrides):
        return self.client.post(
            reverse('cars:financing_apply'),
            financing_data(**overrides),
        )

    def test_the_financing_page_offers_the_application(self):
        response = self.client.get(reverse('cars:financing'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('cars:financing_apply'))
        self.assertContains(response, '14.5')

    def test_the_form_can_be_filled_in_without_an_account(self):
        response = self.client.get(reverse('cars:financing_apply'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Apply for Financing')

    def test_an_application_is_created_with_a_quote(self):
        response = self.apply()
        self.assertRedirects(response, reverse('cars:financing_thank_you'))

        application = FinancingApplication.objects.get()
        self.assertIsNone(application.user)
        self.assertEqual(application.customer_email, 'jane@example.com')
        self.assertEqual(application.requested_amount, Decimal('2400000.00'))
        self.assertEqual(application.interest_rate, FINANCING_RATE)
        self.assertEqual(application.loan_term_months, 36)
        self.assertGreater(application.estimated_monthly, Decimal('0'))
        self.assertEqual(application.status, 'submitted')
        self.assertTrue(application.reference.startswith('FIN-'))

    def test_a_signed_in_customer_has_the_application_linked_to_them(self):
        self.client.force_login(self.user)
        self.apply()
        self.assertEqual(FinancingApplication.objects.get().user, self.user)

    def test_the_form_can_be_prefilled_from_a_car(self):
        car = create_car(vin='JTEBU5JR8A5000002')
        car.asking_price = Decimal('3000000')
        car.save(update_fields=['asking_price'])

        response = self.client.get(
            f"{reverse('cars:financing_apply')}?car={car.pk}"
        )
        self.assertContains(response, '3000000')

        self.client.post(reverse('cars:financing_apply'), {
            **financing_data(price=''), 'car': str(car.pk),
        })
        application = FinancingApplication.objects.get()
        self.assertEqual(application.car, car)
        self.assertEqual(application.price, Decimal('3000000'))
        self.assertIn('Toyota', application.vehicle_label())

    def test_a_car_or_a_description_is_required(self):
        response = self.apply(car_label='')
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Tell us which vehicle', status_code=400)
        self.assertFalse(FinancingApplication.objects.exists())

    def test_the_deposit_must_be_at_least_ten_percent(self):
        response = self.apply(deposit_amount='100000')
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'smallest deposit', status_code=400)
        self.assertFalse(FinancingApplication.objects.exists())

    def test_the_deposit_and_trade_in_must_leave_something_to_finance(self):
        response = self.apply(deposit_amount='2500000', trade_in_value='600000')
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'must be less than the price', status_code=400)
        self.assertFalse(FinancingApplication.objects.exists())

    def test_a_repayment_over_a_third_of_income_is_refused(self):
        response = self.apply(monthly_income='100000')
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'more than a third of your', status_code=400)
        self.assertFalse(FinancingApplication.objects.exists())

    def test_a_larger_deposit_brings_the_repayment_within_reach(self):
        response = self.apply(monthly_income='100000', deposit_amount='2100000')
        self.assertRedirects(response, reverse('cars:financing_thank_you'))
        self.assertTrue(FinancingApplication.objects.exists())

    def test_staff_are_emailed_about_a_new_application(self):
        self.apply()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Financing', mail.outbox[0].subject)
        self.assertIn('FIN-', mail.outbox[0].body)

    def test_the_thank_you_page_shows_the_reference(self):
        response = self.client.post(
            reverse('cars:financing_apply'), financing_data(), follow=True,
        )
        application = FinancingApplication.objects.get()
        self.assertContains(response, application.reference)
        self.assertContains(response, 'Thank you')

    def test_my_financing_needs_a_signed_in_customer(self):
        response = self.client.get(reverse('cars:my_financing_applications'))
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('cars:my_financing_applications')}",
        )

    def test_a_customer_only_sees_their_own_application(self):
        self.client.force_login(self.user)
        self.apply()
        application = FinancingApplication.objects.get()

        response = self.client.get(
            reverse('cars:financing_application_detail', args=[application.pk])
        )
        self.assertEqual(response.status_code, 200)

        self.client.force_login(self.other)
        response = self.client.get(
            reverse('cars:financing_application_detail', args=[application.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_the_customer_can_follow_their_applications(self):
        self.client.force_login(self.user)
        self.apply()
        response = self.client.get(reverse('cars:my_financing_applications'))
        self.assertContains(response, FinancingApplication.objects.get().reference)


class FinancingStaffTests(StaffBaseTest):
    """The staff side: reading the application and recording a decision."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client.force_login(self.customer_user)
        self.client.post(reverse('cars:financing_apply'), financing_data())
        self.client.force_login(self.staff)
        self.application = FinancingApplication.objects.get()
        # The application itself emailed staff; these tests look at the
        # emails the decision sends.
        mail.outbox = []

    def decide(self, **overrides):
        payload = {
            'status': 'approved',
            'approved_amount': '',
            'approved_term_months': '',
            'decision_notes': 'Checked the payslips.',
            'decline_reason': '',
        }
        payload.update(overrides)
        return self.client.post(
            reverse('cars:financing_application_update', args=[self.application.pk]),
            payload,
        )

    def test_the_staff_list_needs_staff(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:financing_applications_list'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_the_staff_list_shows_the_application(self):
        response = self.client.get(reverse('cars:financing_applications_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.application.reference)
        self.assertContains(response, 'Jane Doe')

    def test_the_review_page_shows_the_quote_ladder(self):
        response = self.client.get(
            reverse('cars:financing_application_review', args=[self.application.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.application.reference)
        self.assertContains(response, '12 months')
        self.assertContains(response, '72 months')

    def test_approving_defaults_to_the_amount_requested(self):
        self.decide()
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'approved')
        self.assertEqual(self.application.approved_amount, self.application.requested_amount)
        self.assertEqual(self.application.reviewed_by, self.staff)
        self.assertIsNotNone(self.application.reviewed_at)

    def test_approving_emails_the_customer(self):
        self.decide()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('approved', mail.outbox[0].subject)
        self.assertIn('jane@example.com', mail.outbox[0].to)

    def test_declining_needs_a_reason(self):
        response = self.decide(status='declined', decline_reason='   ')
        self.assertEqual(response.status_code, 400)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'submitted')

    def test_declining_records_the_reason_and_emails_the_customer(self):
        self.decide(status='declined', decline_reason='Income too low.')
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'declined')
        self.assertEqual(self.application.decline_reason, 'Income too low.')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Income too low.', mail.outbox[0].body)

    def test_leaving_the_status_alone_keeps_it_where_it_was(self):
        self.decide(status='reviewing')
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'reviewing')
        # 'reviewing' is internal, so the customer is not emailed.
        self.assertEqual(len(mail.outbox), 0)

        self.decide(status='')
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'reviewing')

    def test_the_update_view_needs_staff(self):
        self.client.force_login(self.customer_user)
        self.decide()
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'submitted')


def structured_data_blocks(response):
    """Every JSON-LD block on a rendered page, parsed."""
    import re

    html = response.content.decode()
    return [
        json.loads(match)
        for match in re.findall(
            r'<script type="application/ld\+json">(.*?)</script>',
            html,
            re.S,
        )
    ]


class VehicleStructuredDataTests(TestCase):
    """schema.org Vehicle/Offer data on a car detail page."""

    def setUp(self):
        self.car = create_car()

    def test_detail_page_emits_a_vehicle_with_an_offer(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.car.id]))
        vehicle = next(
            block for block in structured_data_blocks(response)
            if block['@type'] == 'Vehicle'
        )
        self.assertEqual(vehicle['name'], '2021 Toyota Camry')
        self.assertEqual(vehicle['vehicleIdentificationNumber'], self.car.vin)
        self.assertEqual(vehicle['offers']['price'], '24000.00')
        self.assertEqual(vehicle['offers']['priceCurrency'], 'KES')
        self.assertEqual(
            vehicle['offers']['availability'], 'https://schema.org/InStock'
        )
        self.assertTrue(vehicle['offers']['url'].startswith('http'))
        self.assertEqual(vehicle['itemCondition'], 'https://schema.org/UsedCondition')

    def test_a_sold_car_is_advertised_as_sold_out(self):
        self.car.status = 'sold'
        self.car.save(update_fields=['status'])
        response = self.client.get(reverse('cars:car_detail', args=[self.car.id]))
        vehicle = next(
            block for block in structured_data_blocks(response)
            if block['@type'] == 'Vehicle'
        )
        self.assertEqual(
            vehicle['offers']['availability'], 'https://schema.org/SoldOut'
        )

    def test_the_breadcrumb_lists_home_browse_and_the_car(self):
        response = self.client.get(reverse('cars:car_detail', args=[self.car.id]))
        crumbs = next(
            block for block in structured_data_blocks(response)
            if block['@type'] == 'BreadcrumbList'
        )
        names = [item['name'] for item in crumbs['itemListElement']]
        self.assertEqual(names, ['Home', 'Browse Cars', '2021 Toyota Camry'])

    def test_a_description_cannot_break_out_of_the_script_tag(self):
        self.car.description = '</script><script>alert(1)</script>'
        self.car.save(update_fields=['description'])
        response = self.client.get(reverse('cars:car_detail', args=[self.car.id]))
        self.assertNotIn(b'</script><script>alert(1)', response.content)
        vehicle = next(
            block for block in structured_data_blocks(response)
            if block['@type'] == 'Vehicle'
        )
        self.assertEqual(vehicle['description'], self.car.description)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class VehicleStructuredDataImageTests(TestCase):
    def test_photos_are_absolute_urls(self):
        car = create_car()
        CarImage.objects.create(
            car=car, image=make_image_file('front.png'), is_primary=True,
        )
        response = self.client.get(reverse('cars:car_detail', args=[car.id]))
        vehicle = next(
            block for block in structured_data_blocks(response)
            if block['@type'] == 'Vehicle'
        )
        self.assertEqual(len(vehicle['image']), 1)
        self.assertTrue(vehicle['image'][0].startswith('http'))


class DealerStructuredDataTests(TestCase):
    def test_home_emits_the_dealership(self):
        response = self.client.get(reverse('cars:home'))
        dealer = next(
            block for block in structured_data_blocks(response)
            if block['@type'] == 'AutoDealer'
        )
        self.assertEqual(dealer['@context'], 'https://schema.org')
        self.assertTrue(dealer['name'])

    def test_reviews_page_carries_the_aggregate_rating(self):
        Testimonial.objects.create(
            customer_name='Sandra M.', quote='Great service.', rating=5,
        )
        Testimonial.objects.create(
            customer_name='John K.', quote='Fair price.', rating=4,
        )
        response = self.client.get(reverse('cars:reviews'))
        dealer = next(
            block for block in structured_data_blocks(response)
            if block['@type'] == 'AutoDealer'
        )
        visible = Testimonial.objects.filter(is_visible=True)
        self.assertEqual(dealer['aggregateRating']['reviewCount'], visible.count())
        self.assertEqual(
            len(dealer['review']), min(visible.count(), 10),
        )


class BlogStructuredDataTests(TestCase):
    def test_article_page_emits_a_blog_posting(self):
        post = Post.objects.create(
            title='New Arrivals', slug='new-arrivals', body='Some cars arrived.',
            excerpt='Fresh stock.',
        )
        response = self.client.get(
            reverse('cars:blog_detail', args=[post.slug])
        )
        article = next(
            block for block in structured_data_blocks(response)
            if block['@type'] == 'BlogPosting'
        )
        self.assertEqual(article['headline'], 'New Arrivals')
        self.assertEqual(article['description'], 'Fresh stock.')
        self.assertTrue(article['url'].endswith('/news/new-arrivals/'))


class VehicleFeedTests(TestCase):
    def setUp(self):
        self.available = create_car(vin='AVAIL000000000001')
        self.sold = create_car(vin='SOLD0000000000002', status='sold')
        self.reserved = create_car(vin='RES00000000000003', status='reserved')

    def test_json_feed_lists_only_available_cars(self):
        response = self.client.get(reverse('cars:vehicle_feed_json'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('application/json'))
        payload = response.json()
        self.assertEqual(payload['count'], 1)
        self.assertEqual(payload['currency'], 'KES')
        self.assertEqual(
            [vehicle['vin'] for vehicle in payload['vehicles']],
            ['AVAIL000000000001'],
        )

    def test_json_feed_has_the_fields_a_partner_needs(self):
        vehicle = self.client.get(
            reverse('cars:vehicle_feed_json')
        ).json()['vehicles'][0]
        for key in (
            'id', 'vin', 'make', 'model', 'year', 'condition', 'body_type',
            'transmission', 'fuel_type', 'mileage', 'color', 'price',
            'currency', 'availability', 'url', 'images', 'date_modified',
        ):
            self.assertIn(key, vehicle)
        self.assertEqual(vehicle['price'], '24000.00')
        self.assertEqual(vehicle['availability'], 'in stock')
        self.assertTrue(vehicle['url'].startswith('http'))
        self.assertTrue(vehicle['url'].endswith(f'/car/{self.available.pk}/'))

    def test_feed_is_cacheable_and_supports_conditional_get(self):
        first = self.client.get(reverse('cars:vehicle_feed_json'))
        self.assertIn('max-age', first['Cache-Control'])
        second = self.client.get(
            reverse('cars:vehicle_feed_json'),
            HTTP_IF_NONE_MATCH=first['ETag'],
        )
        self.assertEqual(second.status_code, 304)

    def test_xml_feed_is_well_formed_and_matches_the_json(self):
        import xml.etree.ElementTree as ET

        response = self.client.get(reverse('cars:vehicle_feed_xml'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('application/xml'))
        root = ET.fromstring(response.content)
        self.assertEqual(root.get('count'), '1')
        self.assertEqual(root.get('currency'), 'KES')
        self.assertEqual(root.find('vehicle/vin').text, 'AVAIL000000000001')
        self.assertEqual(root.find('vehicle/price').text, '24000.00')

    def test_the_sitemap_still_includes_sold_cars(self):
        response = self.client.get('/sitemap.xml')
        self.assertContains(response, f'/car/{self.sold.pk}/')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class VehicleFeedImageTests(TestCase):
    def test_feed_images_are_absolute(self):
        car = create_car()
        CarImage.objects.create(
            car=car, image=make_image_file('front.png'), is_primary=True,
        )
        payload = self.client.get(reverse('cars:vehicle_feed_json')).json()
        self.assertEqual(len(payload['vehicles'][0]['images']), 1)
        self.assertTrue(payload['vehicles'][0]['images'][0].startswith('http'))


# ---------------------------------------------------------------------------
# Lead follow-up
# ---------------------------------------------------------------------------

def make_inquiry(car, **overrides):
    data = {
        'car': car,
        'customer_name': 'Jane Doe',
        'customer_email': 'jane@example.com',
        'customer_phone': '555-123-4567',
        'message': 'Interested in this car',
    }
    data.update(overrides)
    return Inquiry.objects.create(**data)


def make_contact_message(**overrides):
    data = {
        'name': 'Grace W.',
        'email': 'grace@example.com',
        'subject': 'Question about financing',
        'message': 'Do you offer financing?',
    }
    data.update(overrides)
    return ContactMessage.objects.create(**data)


def make_order(car, **overrides):
    data = {
        'car': car,
        'customer_name': 'Jane Doe',
        'customer_email': 'jane@example.com',
        'customer_phone': '555-123-4567',
        'customer_address': '1 Main Street',
        'price': Decimal('2400000.00'),
        'deposit_amount': Decimal('50000.00'),
    }
    data.update(overrides)
    return Order.objects.create(**data)


class LeadFollowUpTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.other_staff = User.objects.create_user(
            'agent', email='agent@example.com', password='pass-12345',
        )
        self.other_staff.is_staff = True
        self.other_staff.save()
        self.car = create_car()
        self.inquiry = make_inquiry(self.car)

    def test_staff_assigns_an_owner_and_a_date(self):
        response = self.client.post(
            reverse('cars:lead_assign', args=['inquiry', self.inquiry.pk]),
            {
                'assigned_to': self.other_staff.pk,
                'follow_up_date': '2026-12-01',
                'note': 'Call after lunch',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.assigned_to, self.other_staff)
        self.assertEqual(str(self.inquiry.follow_up_date), '2026-12-01')
        self.assertIn('Call after lunch', self.inquiry.notes)
        self.assertIn('staff', self.inquiry.notes)

    def test_assigning_to_someone_else_notifies_them(self):
        from notifications.models import Notification

        self.client.post(
            reverse('cars:lead_assign', args=['inquiry', self.inquiry.pk]),
            {'assigned_to': self.other_staff.pk},
        )

        notification = Notification.objects.get(user=self.other_staff)
        self.assertIn('assigned', notification.title.lower())
        self.assertIn(f'#lead-{self.inquiry.pk}', notification.url)

    def test_assigning_to_yourself_does_not_notify(self):
        from notifications.models import Notification

        self.client.post(
            reverse('cars:lead_assign', args=['inquiry', self.inquiry.pk]),
            {'assigned_to': self.staff.pk},
        )

        self.assertFalse(Notification.objects.filter(user=self.staff).exists())

    def test_clearing_the_date_is_allowed(self):
        self.inquiry.follow_up_date = timezone.localdate()
        self.inquiry.save(update_fields=['follow_up_date'])

        self.client.post(
            reverse('cars:lead_assign', args=['inquiry', self.inquiry.pk]),
            {'assigned_to': self.staff.pk, 'follow_up_date': ''},
        )

        self.inquiry.refresh_from_db()
        self.assertIsNone(self.inquiry.follow_up_date)

    def test_an_unreadable_date_is_rejected(self):
        response = self.client.post(
            reverse('cars:lead_assign', args=['inquiry', self.inquiry.pk]),
            {'assigned_to': self.staff.pk, 'follow_up_date': 'next tuesday'},
        )

        self.assertEqual(response.status_code, 302)
        self.inquiry.refresh_from_db()
        self.assertIsNone(self.inquiry.follow_up_date)
        self.assertIsNone(self.inquiry.assigned_to)

    def test_logging_a_contact_moves_a_new_lead_to_contacted(self):
        response = self.client.post(
            reverse('cars:lead_contact', args=['inquiry', self.inquiry.pk]),
            {'note': 'Spoke to Jane, calling back Friday.'},
        )

        self.assertEqual(response.status_code, 302)
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, 'contacted')
        self.assertIsNotNone(self.inquiry.last_contacted_at)
        self.assertIn('calling back Friday', self.inquiry.notes)

    def test_the_overdue_filter_only_returns_past_dates(self):
        today = timezone.localdate()
        late = make_inquiry(
            self.car, customer_name='Late', follow_up_date=today - timedelta(days=1),
        )
        make_inquiry(
            self.car, customer_name='Future', follow_up_date=today + timedelta(days=2),
        )

        response = self.client.get(
            reverse('cars:inquiries_list'), {'follow_up': 'overdue'},
        )

        self.assertContains(response, 'Late')
        self.assertNotContains(response, 'Future')
        self.assertIn(late, response.context['inquiries'])

    def test_the_assignee_filter_finds_my_leads(self):
        mine = make_inquiry(self.car, customer_name='Mine', assigned_to=self.staff)
        make_inquiry(self.car, customer_name='Theirs', assigned_to=self.other_staff)

        response = self.client.get(
            reverse('cars:inquiries_list'), {'assignee': 'me'},
        )

        self.assertIn(mine, response.context['inquiries'])
        self.assertEqual(len(response.context['inquiries']), 1)

    def test_the_unassigned_filter_finds_unowned_leads(self):
        self.inquiry.assigned_to = self.staff
        self.inquiry.save(update_fields=['assigned_to'])
        make_inquiry(self.car, customer_name='Owned', assigned_to=self.staff)
        unowned = make_inquiry(self.car, customer_name='Unowned')

        response = self.client.get(
            reverse('cars:inquiries_list'), {'assignee': 'unassigned'},
        )

        self.assertIn(unowned, response.context['inquiries'])
        self.assertEqual(len(response.context['inquiries']), 1)

    def test_the_list_page_renders_the_lead_controls(self):
        response = self.client.get(reverse('cars:inquiries_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Owner &amp; follow-up')
        self.assertContains(response, 'Overdue')
        self.assertContains(response, 'Nobody owns')

    def test_non_staff_cannot_assign(self):
        self.client.force_login(self.customer_user)
        self.client.post(
            reverse('cars:lead_assign', args=['inquiry', self.inquiry.pk]),
            {'assigned_to': self.staff.pk},
        )

        self.inquiry.refresh_from_db()
        self.assertIsNone(self.inquiry.assigned_to)

    def test_an_unknown_lead_kind_is_a_404(self):
        response = self.client.post(
            reverse('cars:lead_assign', args=['widget', self.inquiry.pk]),
            {'assigned_to': self.staff.pk},
        )
        self.assertEqual(response.status_code, 404)


class ContactMessageLeadTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.message = make_contact_message()

    def test_the_staff_page_lists_contact_messages(self):
        response = self.client.get(reverse('cars:contact_messages_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Question about financing')

    def test_contact_messages_can_be_assigned(self):
        self.client.post(
            reverse('cars:lead_assign', args=['message', self.message.pk]),
            {'assigned_to': self.staff.pk, 'follow_up_date': '2026-12-05'},
        )

        self.message.refresh_from_db()
        self.assertEqual(self.message.assigned_to, self.staff)
        self.assertEqual(str(self.message.follow_up_date), '2026-12-05')

    def test_contact_message_status_can_be_changed(self):
        self.client.post(
            reverse('cars:contact_message_status_update', args=[self.message.pk]),
            {'status': 'closed'},
        )

        self.message.refresh_from_db()
        self.assertEqual(self.message.status, 'closed')

    def test_logging_contact_on_a_message_moves_it_forward(self):
        self.client.post(
            reverse('cars:lead_contact', args=['message', self.message.pk]),
        )

        self.message.refresh_from_db()
        self.assertEqual(self.message.status, 'contacted')
        self.assertIsNotNone(self.message.last_contacted_at)

    def test_non_staff_cannot_open_the_contact_message_queue(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('cars:contact_messages_list'))
        self.assertRedirects(response, reverse('cars:home'))


class LeadReminderTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.car = create_car()

    def test_a_due_lead_notifies_its_owner(self):
        from notifications.models import Notification

        lead = make_inquiry(
            self.car,
            assigned_to=self.staff,
            follow_up_date=timezone.localdate() - timedelta(days=1),
        )

        from cars.leads import send_lead_reminders
        sent, _ = send_lead_reminders()

        self.assertEqual(sent, 1)
        notification = Notification.objects.get(user=self.staff)
        self.assertIn('Follow up', notification.title)
        lead.refresh_from_db()
        self.assertIsNotNone(lead.reminder_sent_at)

    def test_the_same_lead_is_not_reminded_twice_in_a_day(self):
        from notifications.models import Notification

        make_inquiry(
            self.car,
            assigned_to=self.staff,
            follow_up_date=timezone.localdate(),
        )

        from cars.leads import send_lead_reminders
        send_lead_reminders()
        send_lead_reminders()

        self.assertEqual(
            Notification.objects.filter(user=self.staff).count(), 1,
        )

    def test_closed_leads_are_not_reminded(self):
        from notifications.models import Notification

        make_inquiry(
            self.car,
            status='closed',
            assigned_to=self.staff,
            follow_up_date=timezone.localdate() - timedelta(days=1),
        )

        from cars.leads import send_lead_reminders
        sent, _ = send_lead_reminders()

        self.assertEqual(sent, 0)
        self.assertFalse(Notification.objects.exists())

    def test_unowned_leads_are_announced_to_staff_once(self):
        from notifications.models import Notification

        old = make_inquiry(self.car)
        Inquiry.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=2),
        )

        from cars.leads import send_lead_reminders
        _, digest = send_lead_reminders()
        send_lead_reminders()

        self.assertEqual(digest, 1)
        self.assertEqual(
            Notification.objects.filter(
                user=self.staff, title='Leads nobody owns',
            ).count(),
            1,
        )

    def test_a_new_owner_gets_a_fresh_reminder(self):
        from notifications.models import Notification

        lead = make_inquiry(
            self.car,
            assigned_to=self.staff,
            follow_up_date=timezone.localdate(),
            reminder_sent_at=timezone.now(),
        )

        from cars.leads import assign, send_lead_reminders
        assign(lead, self.staff, follow_up_date=timezone.localdate())

        send_lead_reminders()

        self.assertTrue(
            Notification.objects.filter(
                user=self.staff, title__startswith='Follow up',
            ).exists()
        )


class LeadDashboardTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.car = create_car()

    def test_the_dashboard_counts_overdue_and_unowned_leads(self):
        make_inquiry(
            self.car,
            follow_up_date=timezone.localdate() - timedelta(days=3),
        )
        make_inquiry(self.car)

        response = self.client.get(reverse('cars:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['lead_counts']['overdue'], 1)
        self.assertEqual(response.context['lead_counts']['unassigned'], 2)
        self.assertContains(response, 'Needs attention')


# ---------------------------------------------------------------------------
# Abandoned orders
# ---------------------------------------------------------------------------

class AwaitingDepositTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.car = create_car()

    def test_a_new_pending_order_is_awaiting_deposit(self):
        from cars.orders import awaiting_deposit

        order = make_order(self.car)
        self.assertIn(order, awaiting_deposit())

    def test_a_paid_order_is_not_awaiting_deposit(self):
        from cars.orders import awaiting_deposit

        order = make_order(self.car)
        order.deposit_paid_at = timezone.now()
        order.payment_status = 'partial'
        order.save(update_fields=['deposit_paid_at', 'payment_status'])

        self.assertNotIn(order, awaiting_deposit())

    def test_a_cancelled_or_confirmed_order_is_not_awaiting_deposit(self):
        from cars.orders import awaiting_deposit

        cancelled = make_order(self.car, status='cancelled')
        confirmed = make_order(self.car, status='confirmed')

        queryset = awaiting_deposit()
        self.assertNotIn(cancelled, queryset)
        self.assertNotIn(confirmed, queryset)

    def test_only_old_orders_are_stale(self):
        from cars.orders import stale_orders

        fresh = make_order(self.car)
        old = make_order(self.car)
        Order.objects.filter(pk=old.pk).update(
            order_date=timezone.now() - timedelta(days=10),
        )

        stale = stale_orders()
        self.assertIn(old, stale)
        self.assertNotIn(fresh, stale)


class DepositReminderTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.car = create_car()

    def test_an_old_unpaid_order_is_emailed_once(self):
        from cars.orders import send_deposit_reminders

        order = make_order(self.car)
        Order.objects.filter(pk=order.pk).update(
            order_date=timezone.now() - timedelta(days=2),
        )

        self.assertEqual(send_deposit_reminders(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('deposit', mail.outbox[0].subject.lower())
        self.assertIn('jane@example.com', mail.outbox[0].to)

        order.refresh_from_db()
        self.assertIsNotNone(order.deposit_reminder_sent_at)
        self.assertEqual(send_deposit_reminders(), 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_a_fresh_order_is_not_reminded_yet(self):
        from cars.orders import send_deposit_reminders

        make_order(self.car)

        self.assertEqual(send_deposit_reminders(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_paid_order_is_never_reminded(self):
        from cars.orders import send_deposit_reminders

        order = make_order(self.car)
        order.deposit_paid_at = timezone.now()
        order.payment_status = 'partial'
        order.save(update_fields=['deposit_paid_at', 'payment_status'])
        Order.objects.filter(pk=order.pk).update(
            order_date=timezone.now() - timedelta(days=5),
        )

        self.assertEqual(send_deposit_reminders(), 0)


class ReleaseOrderTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.car = create_car()
        self.car.status = 'reserved'
        self.car.save(update_fields=['status'])
        self.order = make_order(self.car, user=self.customer_user)

    def test_release_cancels_the_order_and_frees_the_car(self):
        from cars.orders import release_order

        self.assertTrue(release_order(self.order, actor=self.staff, reason='No deposit'))

        self.order.refresh_from_db()
        self.car.refresh_from_db()
        self.assertEqual(self.order.status, 'cancelled')
        self.assertIsNotNone(self.order.released_at)
        self.assertEqual(self.order.release_reason, 'No deposit')
        self.assertEqual(self.car.status, 'available')

    def test_release_notifies_the_customer_and_staff(self):
        from notifications.models import Notification
        from cars.orders import release_order

        other_staff = User.objects.create_user(
            'agent', email='agent@example.com', password='pass-12345',
        )
        other_staff.is_staff = True
        other_staff.save()

        release_order(self.order, actor=self.staff)

        self.assertTrue(
            Notification.objects.filter(
                user=self.customer_user, title__contains='released',
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=other_staff, title__contains='released',
            ).exists()
        )
        # The staff member who did it does not need telling.
        self.assertFalse(
            Notification.objects.filter(
                user=self.staff, title__contains='released',
            ).exists()
        )

    def test_release_emails_the_customer_the_cancellation(self):
        from cars.orders import release_order

        release_order(self.order, actor=self.staff)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('cancelled', mail.outbox[0].subject.lower())

    def test_a_confirmed_order_cannot_be_released(self):
        from cars.orders import release_order

        self.order.status = 'confirmed'
        self.order.save(update_fields=['status'])

        self.assertFalse(release_order(self.order, actor=self.staff))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'confirmed')

    def test_the_car_stays_reserved_while_another_order_holds_it(self):
        from cars.orders import release_order

        make_order(self.car, status='confirmed')

        release_order(self.order, actor=self.staff)

        self.car.refresh_from_db()
        self.assertEqual(self.car.status, 'reserved')

    def test_the_release_view_needs_staff(self):
        self.client.force_login(self.customer_user)
        response = self.client.post(
            reverse('cars:order_release', args=[self.order.pk]),
        )

        self.assertRedirects(response, reverse('cars:home'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')

    def test_the_release_view_needs_a_post(self):
        response = self.client.get(
            reverse('cars:order_release', args=[self.order.pk]),
        )

        self.assertRedirects(response, reverse('cars:orders_list'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')

    def test_the_staff_view_releases_the_order(self):
        response = self.client.post(
            reverse('cars:order_release', args=[self.order.pk]),
            {'reason': 'Customer went quiet'},
        )

        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'cancelled')


class OrdersRecoveryPageTests(StaffBaseTest):
    def setUp(self):
        super().setUp()
        self.car = create_car()
        self.order = make_order(self.car)
        Order.objects.filter(pk=self.order.pk).update(
            order_date=timezone.now() - timedelta(days=10),
        )

    def test_the_stale_filter_finds_old_orders(self):
        response = self.client.get(
            reverse('cars:orders_list'), {'filter': 'stale'},
        )

        self.assertIn(self.order, response.context['orders'])
        self.assertContains(response, 'Stale')

    def test_the_page_shows_the_awaiting_deposit_count(self):
        response = self.client.get(reverse('cars:orders_list'))

        self.assertEqual(response.context['awaiting_deposit_count'], 1)
        self.assertContains(response, 'Awaiting deposit')

    def test_the_dashboard_counts_orders_needing_attention(self):
        response = self.client.get(reverse('cars:dashboard'))

        self.assertEqual(response.context['awaiting_deposit_orders'], 1)
        self.assertEqual(response.context['stale_orders'], 1)


