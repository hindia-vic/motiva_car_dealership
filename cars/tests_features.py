"""Tests for the pre-launch SEO, performance and booking features."""
import tempfile
from datetime import datetime, time, timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .bookings import send_booking_reminders
from .models import (
    Appointment, BookingReminder, CarImage, DealershipInfo, Post, ServiceRecord,
)
from .sitemaps import PUBLIC_PAGES, StaticViewSitemap
from .tests import create_car, make_image_file, structured_data_blocks
from hiring.models import HireBooking, HireCar


def _local_datetime(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone()
    )


class SitemapFreshnessTests(TestCase):
    def test_static_pages_borrow_the_newest_public_content_date(self):
        car = create_car()
        self.assertEqual(
            StaticViewSitemap().lastmod('cars:home'), car.last_updated
        )

    def test_an_empty_site_has_no_static_lastmod(self):
        self.assertIsNone(StaticViewSitemap().lastmod('cars:home'))

    def test_sitemap_publishes_a_lastmod_for_static_pages(self):
        create_car()
        response = self.client.get('/sitemap.xml')
        # One lastmod for every static page plus the single test car.
        self.assertContains(response, '<lastmod>', count=len(PUBLIC_PAGES) + 1)


class WebsiteAndFaqSchemaTests(TestCase):
    def test_home_exposes_a_site_search_action(self):
        response = self.client.get(reverse('cars:home'))
        website = next(
            block for block in structured_data_blocks(response)
            if block['@type'] == 'WebSite'
        )
        self.assertEqual(website['@context'], 'https://schema.org')
        action = website['potentialAction']
        self.assertEqual(action['@type'], 'SearchAction')
        self.assertIn(reverse('cars:advanced_search'), action['target'])
        self.assertIn('{search_term_string}', action['target'])

    def test_faq_page_emits_an_faq_page(self):
        response = self.client.get(reverse('cars:faq'))
        faq = next(
            block for block in structured_data_blocks(response)
            if block['@type'] == 'FAQPage'
        )
        self.assertGreaterEqual(len(faq['mainEntity']), 5)
        first = faq['mainEntity'][0]
        self.assertEqual(first['@type'], 'Question')
        self.assertEqual(first['acceptedAnswer']['@type'], 'Answer')
        self.assertTrue(first['name'])


class VerificationMetaTests(TestCase):
    def test_tokens_are_rendered_when_configured(self):
        with override_settings(
            GOOGLE_SITE_VERIFICATION='google-token',
            BING_SITE_VERIFICATION='bing-token',
        ):
            response = self.client.get(reverse('cars:home'))
        self.assertContains(
            response, '<meta name="google-site-verification" content="google-token">'
        )
        self.assertContains(
            response, '<meta name="msvalidate.01" content="bing-token">'
        )

    def test_no_verification_tags_by_default(self):
        response = self.client.get(reverse('cars:home'))
        self.assertNotContains(response, 'google-site-verification')
        self.assertNotContains(response, 'msvalidate.01')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SocialImageTests(TestCase):
    def test_vehicle_page_has_an_absolute_og_image_and_twitter_card(self):
        car = create_car()
        CarImage.objects.create(
            car=car, image=make_image_file('share.png'), is_primary=True,
        )
        response = self.client.get(reverse('cars:car_detail', args=[car.pk]))
        self.assertContains(response, 'property="og:image" content="http')
        self.assertContains(response, 'name="twitter:card"')

    def test_dealership_logo_is_the_default_og_image(self):
        info = DealershipInfo.get_solo()
        info.logo = make_image_file('logo.png')
        info.save()
        response = self.client.get(reverse('cars:about'))
        self.assertContains(response, 'property="og:image" content="http')
        self.assertContains(response, 'name="twitter:card"')


class RobotsExtraRulesTests(TestCase):
    def test_private_and_preview_paths_are_disallowed(self):
        response = self.client.get('/robots.txt')
        for path in ('/404-preview/', '/payments/', '/notifications/', '/health'):
            self.assertContains(response, f'Disallow: {path}')


@override_settings(
    GOOGLE_ANALYTICS_ID='G-TESTFEATURES', GOOGLE_ANALYTICS_ENABLED=True,
)
class ConsentEventTests(TestCase):
    def test_opt_in_is_reported_after_consent(self):
        self.client.cookies['cookie_consent'] = 'granted'
        response = self.client.get(reverse('cars:home'))
        self.assertContains(response, 'cookie_consent')
        self.assertContains(response, 'sessionStorage')

    def test_no_gtag_before_consent(self):
        response = self.client.get(reverse('cars:home'))
        self.assertNotContains(response, 'googletagmanager.com')
        # The banner itself still offers a way to opt in.
        self.assertContains(response, 'data-consent="granted"')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ResponsiveImageTests(TestCase):
    def test_srcset_offers_thumbnail_and_full_photo(self):
        car = create_car()
        image = CarImage.objects.create(
            car=car, image=make_image_file('photo.png'), is_primary=True,
        )
        srcset = image.srcset()
        self.assertIn(f'{image.thumbnail.url} 600w', srcset)
        self.assertIn(f'{image.image.url} 1600w', srcset)

    def test_cards_request_both_sizes_lazily(self):
        car = create_car()
        CarImage.objects.create(
            car=car, image=make_image_file('card.png'), is_primary=True,
        )
        response = self.client.get(reverse('cars:browse_cars'))
        self.assertContains(response, 'srcset=')
        self.assertContains(response, 'loading="lazy"')
        self.assertContains(response, 'decoding="async"')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class BookingReminderTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.tomorrow = timezone.localdate(self.now) + timedelta(days=1)
        self.car = create_car()

    def test_sends_one_reminder_for_each_upcoming_booking(self):
        ServiceRecord.objects.create(
            car=self.car, customer_name='Jane', customer_email='jane@example.com',
            service_type='maintenance',
            service_date=_local_datetime(self.tomorrow, 9),
        )
        Appointment.objects.create(
            car=self.car, customer_name='John', customer_email='john@example.com',
            customer_phone='555-0100', preferred_date=self.tomorrow,
            preferred_time=time(11, 0), status='approved',
        )
        hire_car = HireCar.objects.create(
            make='Toyota', model='Rav4', year=2022, body_type='suv',
            transmission='automatic', fuel_type='petrol', hire_daily_rate=9000,
        )
        HireBooking.objects.create(
            hire_car=hire_car, customer_name='Asha',
            customer_email='asha@example.com', customer_phone='555-0200',
            id_number='ID123', start_date=self.tomorrow,
            end_date=self.tomorrow + timedelta(days=3), status='confirmed',
        )

        counts = send_booking_reminders(now=self.now)

        self.assertEqual(counts['total'], 3)
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(BookingReminder.objects.count(), 3)

    def test_running_twice_does_not_duplicate_reminders(self):
        ServiceRecord.objects.create(
            car=self.car, customer_name='Jane', customer_email='jane@example.com',
            service_type='maintenance',
            service_date=_local_datetime(self.tomorrow, 9),
        )
        send_booking_reminders(now=self.now)
        second = send_booking_reminders(now=self.now)
        self.assertEqual(second['total'], 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_bookings_without_an_email_are_skipped(self):
        ServiceRecord.objects.create(
            car=self.car, customer_name='Walk-in',
            service_type='inspection',
            service_date=_local_datetime(self.tomorrow, 9),
        )
        counts = send_booking_reminders(now=self.now)
        self.assertEqual(counts['total'], 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_moving_a_booking_to_a_new_date_allows_a_new_reminder(self):
        booking = ServiceRecord.objects.create(
            car=self.car, customer_name='Jane', customer_email='jane@example.com',
            service_type='maintenance',
            service_date=_local_datetime(self.tomorrow, 9),
        )
        send_booking_reminders(now=self.now)
        booking.service_date = _local_datetime(self.tomorrow + timedelta(days=1), 9)
        booking.save(update_fields=['service_date'])
        # On the following day the moved booking is "tomorrow" again and gets
        # its own reminder for the new date.
        send_booking_reminders(now=self.now + timedelta(days=1))
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(BookingReminder.objects.count(), 2)

    def test_a_cancelled_booking_is_not_reminded(self):
        ServiceRecord.objects.create(
            car=self.car, customer_name='Jane', customer_email='jane@example.com',
            service_type='maintenance', status='cancelled',
            service_date=_local_datetime(self.tomorrow, 9),
        )
        self.assertEqual(send_booking_reminders(now=self.now)['total'], 0)
