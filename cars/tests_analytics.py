"""Tests for the optional Google Analytics 4 integration."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.template import Context, Template
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .models import Car, Order

GA_SETTINGS = {
    'GOOGLE_ANALYTICS_ID': 'G-TEST12345',
    'GOOGLE_ANALYTICS_ENABLED': True,
}


def create_car(vin='1HGCM82633A004352'):
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
        status='available',
    )


class AnalyticsOffTests(TestCase):
    """Without a Measurement ID the site must stay third-party free."""

    def test_no_snippet_without_measurement_id(self):
        response = self.client.get(reverse('cars:home'))

        self.assertNotContains(response, 'googletagmanager.com')
        self.assertNotContains(response, 'dealershipTrack')

    def test_no_events_without_measurement_id(self):
        car = create_car()

        response = self.client.get(reverse('cars:car_detail', args=[car.pk]))
        self.assertNotContains(response, '"view_item"')

        response = self.client.get(reverse('cars:browse_cars'), {'search': 'Toyota'})
        self.assertNotContains(response, 'dealershipTrack("search"')

        response = self.client.get(reverse('cars:inquiry_thank_you'))
        self.assertNotContains(response, '"generate_lead"')

    def test_csp_does_not_allow_analytics_hosts(self):
        response = self.client.get(reverse('cars:home'))

        policy = response['Content-Security-Policy']
        self.assertNotIn('googletagmanager.com', policy)
        self.assertNotIn('google-analytics.com', policy)

    def test_enabled_flag_can_switch_tracking_off(self):
        with override_settings(
            GOOGLE_ANALYTICS_ID='G-TEST12345',
            GOOGLE_ANALYTICS_ENABLED=False,
        ):
            response = self.client.get(reverse('cars:home'))

        self.assertNotContains(response, 'googletagmanager.com')
        self.assertNotIn(
            'googletagmanager.com', response['Content-Security-Policy'],
        )


@override_settings(**GA_SETTINGS)
class AnalyticsOnTests(TestCase):
    def setUp(self):
        # Tracking is opt-in, so the snippet only renders once the visitor has
        # accepted the banner.
        self.client.cookies['cookie_consent'] = 'granted'

    def test_snippet_is_rendered_on_public_pages(self):
        response = self.client.get(reverse('cars:home'))

        self.assertContains(response, 'googletagmanager.com/gtag/js?id=G-TEST12345')
        # ``escapejs`` renders the hyphen as a unicode escape inside the JS
        # string, which is valid JavaScript and keeps the ID inert in HTML.
        self.assertContains(response, "gtag('config', 'G\\u002DTEST12345'")
        self.assertContains(response, 'window.dealershipTrack')

    def test_csp_allows_analytics_hosts(self):
        response = self.client.get(reverse('cars:home'))

        policy = response['Content-Security-Policy']
        self.assertIn('https://www.googletagmanager.com', policy)
        self.assertIn('https://*.google-analytics.com', policy)

    def test_car_page_emits_view_item(self):
        car = create_car()

        response = self.client.get(reverse('cars:car_detail', args=[car.pk]))

        self.assertContains(response, '"view_item"')
        self.assertContains(response, '"item_name":"2021 Toyota Camry"')
        self.assertContains(response, '"item_brand":"Toyota"')
        self.assertContains(response, '"price":24000.0')
        # The VIN identifies the individual vehicle and must not be shipped to
        # a third party, so only the display name is used in the payload.
        event_line = next(
            line for line in response.content.decode().splitlines()
            if '"view_item"' in line
        )
        self.assertNotIn(car.vin, event_line)

    def test_browse_page_emits_search(self):
        response = self.client.get(reverse('cars:browse_cars'), {'search': 'Toyota'})

        self.assertContains(response, '"search"')
        self.assertContains(response, '"search_term":"Toyota"')

    def test_browse_page_without_search_emits_nothing(self):
        response = self.client.get(reverse('cars:browse_cars'))

        self.assertNotContains(response, '"search_term"')

    def test_paginated_search_is_not_counted_again(self):
        response = self.client.get(
            reverse('cars:browse_cars'), {'search': 'Toyota', 'page': '1'},
        )

        self.assertNotContains(response, 'dealershipTrack("search"')

    def test_inquiry_thank_you_emits_generate_lead(self):
        response = self.client.get(reverse('cars:inquiry_thank_you'))

        self.assertContains(response, '"generate_lead"')
        self.assertContains(response, '"lead_type":"inquiry"')

    def test_appointment_thank_you_emits_generate_lead(self):
        response = self.client.get(reverse('cars:car_appointment_thank_you'))

        self.assertContains(response, '"generate_lead"')
        self.assertContains(response, '"lead_type":"test_drive"')

    def test_order_thank_you_emits_begin_checkout(self):
        car = create_car()
        order = Order.objects.create(
            car=car,
            customer_name='Jane Doe',
            customer_email='jane@example.com',
            customer_phone='555-123-4567',
            customer_address='123 Main St',
            price=Decimal('24000.00'),
        )
        session = self.client.session
        session['order_id'] = order.pk
        session.save()

        response = self.client.get(reverse('cars:order_thank_you'))

        self.assertContains(response, '"begin_checkout"')
        self.assertContains(response, '"value":24000.0')
        self.assertContains(response, '"item_name":"2021 Toyota Camry"')

    def test_order_thank_you_without_order_emits_no_checkout(self):
        response = self.client.get(reverse('cars:order_thank_you'))

        self.assertNotContains(response, '"begin_checkout"')


@override_settings(**GA_SETTINGS)
class AnalyticsExclusionTests(TestCase):
    def setUp(self):
        self.client.cookies['cookie_consent'] = 'granted'

    def test_staff_do_not_get_the_snippet(self):
        staff = User.objects.create_user('staff', password='pass-12345')
        staff.is_staff = True
        staff.save()
        self.client.force_login(staff)

        response = self.client.get(reverse('cars:home'))

        self.assertNotContains(response, 'googletagmanager.com')

    def test_logged_in_customers_still_get_the_snippet(self):
        customer = User.objects.create_user('customer', password='pass-12345')
        self.client.force_login(customer)

        response = self.client.get(reverse('cars:home'))

        self.assertContains(response, 'googletagmanager.com')

    def test_admin_paths_are_excluded(self):
        from config.context_processors import analytics

        factory = RequestFactory()
        factory.cookies['cookie_consent'] = 'granted'
        request = factory.get('/secret-admin/')
        request.user = User.objects.create_user('anon', password='pass-12345')

        with override_settings(ADMIN_URL='/secret-admin/'):
            self.assertEqual(analytics(request)['google_analytics_id'], '')

    def test_public_paths_are_included(self):
        from config.context_processors import analytics

        factory = RequestFactory()
        factory.cookies['cookie_consent'] = 'granted'
        request = factory.get(reverse('cars:home'))
        request.user = User.objects.create_user('anon', password='pass-12345')

        self.assertEqual(
            analytics(request)['google_analytics_id'], 'G-TEST12345',
        )


@override_settings(**GA_SETTINGS)
class AnalyticsConsentTests(TestCase):
    """GA4 is opt-in: no third-party request before the banner is accepted."""

    def test_no_ga_before_a_decision_and_the_banner_is_shown(self):
        response = self.client.get(reverse('cars:home'))

        self.assertNotContains(response, 'googletagmanager.com')
        self.assertContains(response, 'id="cookie-consent"')
        self.assertContains(response, 'Accept analytics')

    def test_accepting_loads_ga_and_hides_the_banner(self):
        self.client.cookies['cookie_consent'] = 'granted'

        response = self.client.get(reverse('cars:home'))

        self.assertContains(
            response, 'googletagmanager.com/gtag/js?id=G-TEST12345',
        )
        self.assertNotContains(response, 'id="cookie-consent"')

    def test_declining_keeps_ga_off_and_hides_the_banner(self):
        self.client.cookies['cookie_consent'] = 'denied'

        response = self.client.get(reverse('cars:home'))

        self.assertNotContains(response, 'googletagmanager.com')
        self.assertNotContains(response, 'id="cookie-consent"')
        # The footer link lets the visitor change their mind later.
        self.assertContains(response, 'Cookie Settings')

    def test_consent_can_be_disabled_for_non_gdpr_deployments(self):
        with override_settings(GOOGLE_ANALYTICS_REQUIRE_CONSENT=False):
            response = self.client.get(reverse('cars:home'))

        self.assertContains(response, 'googletagmanager.com')
        self.assertNotContains(response, 'id="cookie-consent"')

    def test_staff_do_not_see_the_banner(self):
        staff = User.objects.create_user('banner-staff', password='pass-12345')
        staff.is_staff = True
        staff.save()
        self.client.force_login(staff)

        response = self.client.get(reverse('cars:home'))

        self.assertNotContains(response, 'id="cookie-consent"')
        self.assertNotContains(response, 'googletagmanager.com')

    def test_no_banner_without_a_measurement_id(self):
        with override_settings(
            GOOGLE_ANALYTICS_ID='', GOOGLE_ANALYTICS_ENABLED=False,
        ):
            response = self.client.get(reverse('cars:home'))

        self.assertNotContains(response, 'id="cookie-consent"')


class AnalyticsEventTagTests(TestCase):
    def render(self, template, context):
        return Template(template).render(Context(context))

    def test_tag_renders_nothing_without_id(self):
        html = self.render(
            '{% load analytics %}{% analytics_event "generate_lead" lead_type="x" %}',
            {},
        )

        self.assertEqual(html, '')

    def test_tag_encodes_params(self):
        html = self.render(
            '{% load analytics %}{% analytics_event "search" search_term=term %}',
            {'google_analytics_id': 'G-TEST', 'term': 'Toyota Camry'},
        )

        self.assertIn('dealershipTrack("search"', html)
        self.assertIn('{"search_term":"Toyota Camry"}', html)

    def test_tag_escapes_closing_script_tags(self):
        html = self.render(
            '{% load analytics %}{% analytics_event "search" search_term=term %}',
            {'google_analytics_id': 'G-TEST', 'term': '</script><script>alert(1)'},
        )

        self.assertNotIn('</script><script>alert(1)', html)
        self.assertIn('\\u003C/script', html)

    def test_tag_serialises_decimals(self):
        html = self.render(
            '{% load analytics %}{% analytics_event "begin_checkout" value=amount %}',
            {'google_analytics_id': 'G-TEST', 'amount': Decimal('1500.50')},
        )

        self.assertIn('"value":1500.5', html)


class CarDisplayNameTests(TestCase):
    def test_display_name_omits_the_vin(self):
        car = create_car()

        self.assertEqual(car.display_name, '2021 Toyota Camry')
        self.assertNotIn(car.vin, car.display_name)
