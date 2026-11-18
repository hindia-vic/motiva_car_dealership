"""Tests for the traffic analytics app."""

from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from io import StringIO

from cars.models import (
    Appointment, Car, Customer, Inquiry, Order, SalesTransaction,
)
from traffic.analytics import (
    classify_source, is_bot, normalize_source, parse_browser, parse_device,
)
from traffic.conversion import (
    conversion_rows, funnel_report, source_for_visitor, visitor_id_from,
)
from traffic.models import PageView


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


@override_settings(TRAFFIC_TRACKING_ENABLED=True)
class TrafficMiddlewareTests(TestCase):
    """The tracking middleware records the right requests and nothing else."""

    def test_public_page_is_recorded(self):
        response = self.client.get(reverse('cars:home'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PageView.objects.count(), 1)

        view = PageView.objects.get()
        self.assertEqual(view.path, '/')
        self.assertEqual(view.url_name, 'home')
        self.assertEqual(view.source, 'Direct')
        self.assertEqual(view.device, 'Unknown')
        self.assertEqual(view.status_code, 200)

    def test_visitor_cookie_is_set_and_reused(self):
        first = self.client.get(reverse('cars:home'))
        self.assertIn('vid', first.cookies)

        visitor_id = PageView.objects.get().visitor_id
        self.assertTrue(visitor_id)

        self.client.get(reverse('cars:browse_cars'))
        self.assertEqual(PageView.objects.count(), 2)
        self.assertEqual(
            PageView.objects.values_list('visitor_id', flat=True).distinct().count(), 1
        )

    def test_separate_clients_are_separate_visitors(self):
        from django.test import Client

        Client().get(reverse('cars:home'))
        Client().get(reverse('cars:home'))

        self.assertEqual(PageView.objects.count(), 2)
        self.assertEqual(
            PageView.objects.values_list('visitor_id', flat=True).distinct().count(), 2
        )

    def test_post_requests_are_not_recorded(self):
        self.client.post(reverse('cars:newsletter_subscribe'), {'email': 'a@example.com'})
        self.assertEqual(PageView.objects.count(), 0)

    def test_staff_browsing_is_not_recorded(self):
        staff = User.objects.create_user('staff', email='s@example.com', password='pass-12345')
        staff.is_staff = True
        staff.save()
        self.client.force_login(staff)

        self.client.get(reverse('cars:home'))
        self.assertEqual(PageView.objects.count(), 0)

    def test_static_and_admin_paths_are_not_recorded(self):
        self.client.get('/static/css/site.css')
        self.client.get(reverse('admin:index'))
        self.assertEqual(PageView.objects.count(), 0)

    def test_health_endpoint_is_not_recorded(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PageView.objects.count(), 0)

    def test_bot_user_agents_are_not_recorded(self):
        self.client.get(
            reverse('cars:home'),
            HTTP_USER_AGENT='Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
        )
        self.assertEqual(PageView.objects.count(), 0)

    def test_xhr_requests_are_not_recorded(self):
        self.client.get(
            reverse('cars:home'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(PageView.objects.count(), 0)

    def test_redirects_are_not_recorded(self):
        response = self.client.get(reverse('cars:dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PageView.objects.count(), 0)

    def test_referrer_is_classified_as_google(self):
        self.client.get(
            reverse('cars:home'),
            HTTP_REFERER='https://www.google.com/search?q=toyota+camo',
        )
        self.assertEqual(PageView.objects.get().source, 'Google')

    def test_internal_referrer_is_classified_as_internal(self):
        self.client.get(
            reverse('cars:home'),
            HTTP_REFERER='http://testserver/browse/',
        )
        self.assertEqual(PageView.objects.get().source, 'Internal')

    def test_utm_source_overrides_the_referrer(self):
        self.client.get(
            reverse('cars:home') + '?utm_source=facebook&utm_medium=cpc&utm_campaign=spring',
            HTTP_REFERER='https://www.google.com/',
        )
        view = PageView.objects.get()
        self.assertEqual(view.source, 'Facebook')
        self.assertEqual(view.utm_source, 'facebook')
        self.assertEqual(view.utm_medium, 'cpc')
        self.assertEqual(view.utm_campaign, 'spring')

    def test_car_detail_page_links_the_vehicle(self):
        car = create_car()
        self.client.get(reverse('cars:car_detail', args=[car.pk]))
        view = PageView.objects.get()
        self.assertEqual(view.url_name, 'car_detail')
        self.assertEqual(view.car_id, car.pk)

    def test_device_and_browser_are_parsed(self):
        self.client.get(
            reverse('cars:home'),
            HTTP_USER_AGENT=(
                'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
                'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
            ),
        )
        view = PageView.objects.get()
        self.assertEqual(view.device, 'Mobile')
        self.assertEqual(view.browser, 'Safari')

    def test_client_ip_is_stored(self):
        self.client.get(reverse('cars:home'), REMOTE_ADDR='203.0.113.7')
        self.assertEqual(PageView.objects.get().ip_address, '203.0.113.7')

    def test_logged_in_user_is_linked_to_the_view(self):
        user = User.objects.create_user('buyer', email='b@example.com', password='pass-12345')
        self.client.force_login(user)
        self.client.get(reverse('cars:home'))
        self.assertEqual(PageView.objects.get().user_id, user.pk)

    def test_tracking_can_be_switched_off(self):
        with override_settings(TRAFFIC_TRACKING_ENABLED=False):
            self.client.get(reverse('cars:home'))
        self.assertEqual(PageView.objects.count(), 0)

    def test_tracking_failure_does_not_break_the_page(self):
        # A database error while writing the page view must never take the
        # page down with it.
        with mock.patch(
            'traffic.middleware.PageView.objects.create',
            side_effect=RuntimeError('database is down'),
        ):
            response = self.client.get(reverse('cars:home'))
        self.assertEqual(response.status_code, 200)


class TrafficViewTests(TestCase):
    """The staff traffic report."""

    def setUp(self):
        self.staff = User.objects.create_user('staff', email='s@example.com', password='pass-12345')
        self.staff.is_staff = True
        self.staff.save()
        self.customer = User.objects.create_user('buyer', email='b@example.com', password='pass-12345')

    def record(self, visitor='visitor-1', path='/browse/', source='Google',
               days_ago=0, **extra):
        created = timezone.now() - timedelta(days=days_ago)
        view = PageView.objects.create(
            path=path,
            visitor_id=visitor,
            source=source,
            device=extra.pop('device', 'Desktop'),
            browser=extra.pop('browser', 'Chrome'),
            **extra,
        )
        # created_at is auto_now_add, so it has to be back-dated afterwards.
        PageView.objects.filter(pk=view.pk).update(created_at=created)
        return view

    def test_anonymous_user_is_redirected_home(self):
        response = self.client.get(reverse('traffic:traffic'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_non_staff_user_is_redirected_home(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse('traffic:traffic'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_staff_sees_the_report(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('traffic:traffic'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Traffic')

    def test_counts_are_reported(self):
        self.record(visitor='a', path='/browse/')
        self.record(visitor='a', path='/car/1/')
        self.record(visitor='b', path='/browse/')

        self.client.force_login(self.staff)
        response = self.client.get(reverse('traffic:traffic'))
        context = response.context

        self.assertEqual(context['total_views'], 3)
        self.assertEqual(context['unique_visitors'], 2)
        self.assertEqual(context['avg_pages_per_visit'], 1.5)
        # One of the two visitors only ever saw a single page.
        self.assertEqual(context['bounce_rate'], 50.0)

    def test_period_filter_limits_the_window(self):
        self.record(visitor='recent', days_ago=1)
        self.record(visitor='old', days_ago=40)

        self.client.force_login(self.staff)

        response = self.client.get(reverse('traffic:traffic'), {'days': 7})
        self.assertEqual(response.context['total_views'], 1)

        response = self.client.get(reverse('traffic:traffic'), {'days': 90})
        self.assertEqual(response.context['total_views'], 2)

    def test_unknown_period_falls_back_to_the_default(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('traffic:traffic'), {'days': 'nonsense'})
        self.assertEqual(response.context['days'], 30)

    def test_top_pages_and_sources_are_reported(self):
        self.record(visitor='a', path='/browse/', source='Google', url_name='browse_cars')
        self.record(visitor='b', path='/browse/', source='Facebook', url_name='browse_cars')
        self.record(visitor='c', path='/contact/', source='Direct', url_name='contact')

        self.client.force_login(self.staff)
        response = self.client.get(reverse('traffic:traffic'))
        context = response.context

        top = context['top_pages']
        self.assertEqual(top[0]['path'], '/browse/')
        self.assertEqual(top[0]['count'], 2)
        self.assertEqual(top[0]['label'], 'Browse cars')

        sources = {row['source']: row['count'] for row in context['sources']}
        self.assertEqual(sources['Google'], 1)
        self.assertEqual(sources['Facebook'], 1)

    def test_most_viewed_vehicles_are_reported(self):
        car = create_car()
        self.record(visitor='a', car=car)
        self.record(visitor='b', car=car)
        self.record(visitor='c', path='/contact/')

        self.client.force_login(self.staff)
        response = self.client.get(reverse('traffic:traffic'))
        rows = response.context['top_cars']

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['car__id'], car.pk)
        self.assertEqual(rows[0]['views'], 2)
        self.assertEqual(rows[0]['visitors'], 2)

    def test_landing_pages_use_the_first_view_of_each_visitor(self):
        self.record(visitor='a', path='/browse/')
        self.record(visitor='a', path='/contact/')
        self.record(visitor='b', path='/contact/')

        self.client.force_login(self.staff)
        response = self.client.get(reverse('traffic:traffic'))
        landings = {row['path']: row['count'] for row in response.context['landing_pages']}

        self.assertEqual(landings.get('/browse/'), 1)
        self.assertEqual(landings.get('/contact/'), 1)

    def test_daily_series_covers_every_day_in_the_period(self):
        self.record(visitor='a', days_ago=0)
        self.client.force_login(self.staff)
        response = self.client.get(reverse('traffic:traffic'), {'days': 7})

        series = response.context['daily_traffic']
        self.assertEqual(len(series), 7)
        self.assertEqual(series[-1]['views'], 1)
        self.assertEqual(series[-1]['visitors'], 1)

    def test_empty_report_renders(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('traffic:traffic'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_views'], 0)
        self.assertEqual(response.context['bounce_rate'], 0)

    def test_staff_dashboard_shows_the_traffic_card(self):
        self.record(visitor='a')
        self.client.force_login(self.staff)
        response = self.client.get(reverse('cars:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Website Traffic')
        self.assertContains(response, reverse('traffic:traffic'))


@override_settings(TRAFFIC_TRACKING_ENABLED=True)
class TrafficNoiseControlTests(TestCase):
    """404s, scanner probes and repeat views."""

    def setUp(self):
        cache.clear()

    def test_404_is_not_recorded_by_default(self):
        response = self.client.get('/no-such-page/')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(PageView.objects.count(), 0)

    @override_settings(TRAFFIC_TRACK_404S=True)
    def test_404_is_recorded_when_enabled(self):
        response = self.client.get('/no-such-page/')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(PageView.objects.count(), 1)

    @override_settings(TRAFFIC_TRACK_404S=True)
    def test_scanner_paths_are_never_recorded(self):
        for path in [
            '/.env',
            '/.git/config',
            '/wp-login.php',
            '/phpmyadmin/',
            '/v1/models',
            '/api/users',
            '/cgi-bin/test',
            '/xmlrpc.php',
            '/.aws/credentials',
        ]:
            with self.subTest(path=path):
                self.client.get(path)
        self.assertEqual(PageView.objects.count(), 0)

    def test_repeat_view_inside_the_window_is_recorded_once(self):
        for _ in range(3):
            self.client.get(reverse('cars:browse_cars'))
        self.assertEqual(PageView.objects.count(), 1)

    def test_repeat_view_after_the_window_is_recorded_again(self):
        self.client.get(reverse('cars:browse_cars'))
        cache.clear()          # the dedupe window has elapsed
        self.client.get(reverse('cars:browse_cars'))
        self.assertEqual(PageView.objects.count(), 2)

    @override_settings(TRAFFIC_DEDUPE_WINDOW=0)
    def test_a_window_of_zero_records_every_view(self):
        self.client.get(reverse('cars:browse_cars'))
        self.client.get(reverse('cars:browse_cars'))
        self.assertEqual(PageView.objects.count(), 2)

    def test_different_pages_are_both_recorded(self):
        self.client.get(reverse('cars:home'))
        self.client.get(reverse('cars:browse_cars'))
        self.assertEqual(PageView.objects.count(), 2)

    def test_separate_visitors_are_not_deduped_against_each_other(self):
        from django.test import Client

        Client().get(reverse('cars:browse_cars'))
        Client().get(reverse('cars:browse_cars'))
        self.assertEqual(PageView.objects.count(), 2)


@override_settings(TRAFFIC_TRACKING_ENABLED=True)
class TrafficAutoPruneTests(TestCase):
    """The automatic prune keeps the table bounded without a cron job."""

    def setUp(self):
        cache.clear()

    def make_expired(self, path):
        view = PageView.objects.create(path=path, visitor_id='expired')
        PageView.objects.filter(pk=view.pk).update(
            created_at=timezone.now() - timedelta(days=200)
        )
        return view

    def test_expired_rows_are_pruned_automatically(self):
        self.make_expired('/old/')

        self.client.get(reverse('cars:home'))

        self.assertFalse(PageView.objects.filter(path='/old/').exists())
        self.assertTrue(PageView.objects.filter(path='/').exists())

    def test_the_prune_runs_at_most_once_a_day(self):
        self.make_expired('/old/')
        self.client.get(reverse('cars:home'))
        self.assertFalse(PageView.objects.filter(path='/old/').exists())

        # Another expired row appears later the same day.
        self.make_expired('/later/')
        self.client.get(reverse('cars:browse_cars'))
        self.assertTrue(PageView.objects.filter(path='/later/').exists())

    @override_settings(TRAFFIC_AUTO_PRUNE=False)
    def test_the_auto_prune_can_be_switched_off(self):
        self.make_expired('/old/')
        self.client.get(reverse('cars:home'))
        self.assertTrue(PageView.objects.filter(path='/old/').exists())

    def test_recent_rows_are_never_pruned(self):
        self.client.get(reverse('cars:home'))
        self.assertEqual(PageView.objects.count(), 1)


class SqliteWalTests(TestCase):
    """The WAL pragma must never break a connection."""

    def test_the_pragma_does_not_raise(self):
        from django.db import connection
        from traffic.signals import enable_sqlite_wal

        # Whether or not the filesystem supports WAL, this must not raise.
        enable_sqlite_wal(sender=None, connection=connection)

    def test_the_receiver_is_registered(self):
        from django.db.backends.signals import connection_created

        self.assertTrue(connection_created.receivers)

    def test_non_sqlite_connections_are_ignored(self):
        from traffic.signals import enable_sqlite_wal

        class FakeConnection:
            vendor = 'postgresql'

        # Must not raise for a connection that is not SQLite.
        enable_sqlite_wal(sender=None, connection=FakeConnection())


class AnalyticsHelperTests(TestCase):
    """The referrer and user agent helpers."""

    def test_classify_source(self):
        cases = [
            ('', 'Google', 'Direct'),
            ('https://www.google.com/search?q=car', 'Google', 'Google'),
            ('https://www.bing.com/search?q=car', 'Google', 'Bing'),
            ('https://duckduckgo.com/?q=car', 'Google', 'DuckDuckGo'),
            ('https://www.facebook.com/', 'Google', 'Facebook'),
            ('https://l.facebook.com/l.php?u=1', 'Google', 'Facebook'),
            ('https://t.co/abc', 'Google', 'X (Twitter)'),
            ('https://www.youtube.com/watch?v=1', 'Google', 'YouTube'),
            ('https://mail.google.com/mail/u/0', 'Google', 'Gmail'),
            ('https://my-site.com/browse/', 'my-site.com', 'Internal'),
            ('https://www.my-site.com/browse/', 'my-site.com', 'Internal'),
            ('https://some-random-blog.example/post', 'Google', 'Referral'),
            ('android-app://com.google.android.gm', 'Google', 'App'),
        ]
        for referrer, host, expected in cases:
            with self.subTest(referrer=referrer):
                self.assertEqual(classify_source(referrer, host), expected)

    def test_normalize_source(self):
        self.assertEqual(normalize_source('facebook'), 'Facebook')
        self.assertEqual(normalize_source('google'), 'Google')
        self.assertEqual(normalize_source('newsletter'), 'newsletter')
        self.assertEqual(normalize_source(''), '')

    def test_parse_device(self):
        self.assertEqual(parse_device(''), 'Unknown')
        self.assertEqual(
            parse_device('Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120'), 'Desktop'
        )
        self.assertEqual(
            parse_device('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'),
            'Mobile',
        )
        self.assertEqual(
            parse_device('Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) Safari/604.1'),
            'Tablet',
        )

    def test_parse_browser(self):
        self.assertEqual(parse_browser(''), 'Unknown')
        self.assertEqual(
            parse_browser('Mozilla/5.0 (Windows NT 10.0) Chrome/120.0.0.0 Safari/537.36'),
            'Chrome',
        )
        self.assertEqual(
            parse_browser('Mozilla/5.0 (Windows NT 10.0) Chrome/120 Safari/537.36 Edg/120'),
            'Edge',
        )
        self.assertEqual(
            parse_browser('Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0'),
            'Firefox',
        )

    def test_is_bot(self):
        self.assertTrue(is_bot('Googlebot/2.1 (+http://www.google.com/bot.html)'))
        self.assertTrue(is_bot('Mozilla/5.0 (compatible; bingbot/2.0)'))
        self.assertTrue(is_bot('curl/8.0.1'))
        self.assertFalse(is_bot(
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120 Safari/537.36'
        ))
        self.assertFalse(is_bot(''))


class ConversionFunnelTests(TestCase):
    """The funnel: who arrived, what they did, and what it was worth."""

    def setUp(self):
        self.car = create_car()
        self.customer = Customer.objects.create(
            first_name='Jane',
            last_name='Doe',
            email='jane@example.com',
            phone_number='555-0100',
            address='1 Main St',
            city='Springfield',
            state='IL',
            zip_code='62701',
        )

    def record(self, visitor='visitor-1', path='/browse/', source='Google',
               car=None, days_ago=0):
        created = timezone.now() - timedelta(days=days_ago)
        view = PageView.objects.create(
            path=path,
            visitor_id=visitor,
            source=source,
            car=car,
        )
        # created_at is auto_now_add, so it has to be back-dated afterwards.
        PageView.objects.filter(pk=view.pk).update(created_at=created)
        return view

    def make_order(self, source='Google', visitor_id='visitor-1', **extra):
        return Order.objects.create(
            car=self.car,
            customer_name='John Smith',
            customer_email='john@example.com',
            customer_phone='555-987-6543',
            customer_address='456 Oak Ave',
            price=24000,
            source=source,
            visitor_id=visitor_id,
            **extra,
        )

    def make_inquiry(self, car=None, source='Google', visitor_id='visitor-1'):
        return Inquiry.objects.create(
            car=car or self.car,
            customer_name='Jane Doe',
            customer_email='jane@example.com',
            customer_phone='555-0100',
            message='Is this still available?',
            source=source,
            visitor_id=visitor_id,
        )

    def make_sale(self, order=None, amount=24000, status='completed'):
        return SalesTransaction.objects.create(
            car=self.car,
            customer=self.customer,
            order=order,
            invoice_number=f'INV-{amount}-{status}',
            sale_price=amount,
            total_amount=amount,
            payment_method='cash',
            status=status,
        )

    # -- the source a visitor arrived from ----------------------------

    def test_source_for_visitor_uses_the_first_external_source(self):
        self.record(visitor='a', source='Google')
        self.record(visitor='a', source='Internal')
        self.assertEqual(source_for_visitor('a'), 'Google')

    def test_source_for_visitor_skips_internal_jumps(self):
        self.record(visitor='a', source='Internal')
        self.record(visitor='a', source='Facebook')
        self.assertEqual(source_for_visitor('a'), 'Facebook')

    def test_source_for_visitor_falls_back_to_the_first_view(self):
        self.record(visitor='a', source='Internal')
        self.assertEqual(source_for_visitor('a'), 'Internal')

    def test_source_for_an_unknown_visitor_is_empty(self):
        self.assertEqual(source_for_visitor('nobody'), '')
        self.assertEqual(source_for_visitor(''), '')

    def test_visitor_id_is_read_from_the_cookie(self):
        request = mock.Mock(COOKIES={'vid': 'abc123'})
        self.assertEqual(visitor_id_from(request), 'abc123')

    def test_visitor_id_is_empty_without_a_cookie(self):
        request = mock.Mock(COOKIES={})
        self.assertEqual(visitor_id_from(request), '')

    # -- the funnel ---------------------------------------------------

    def test_the_funnel_counts_visitors_leads_and_sales(self):
        self.record(visitor='a')
        self.record(visitor='b')
        self.make_inquiry(visitor_id='a')
        self.make_order(visitor_id='b')
        self.make_sale(self.make_order(visitor_id='b'))

        report = funnel_report(timezone.now() - timedelta(days=30))

        self.assertEqual(report['visitors'], 2)
        self.assertEqual(report['inquiries'], 1)
        self.assertEqual(report['orders'], 2)
        self.assertEqual(report['sales'], 1)
        self.assertEqual(report['order_rate'], 100.0)

    def test_the_funnel_ignores_leads_outside_the_period(self):
        self.record(visitor='a', days_ago=40)
        self.make_inquiry(visitor_id='a')
        Inquiry.objects.update(created_at=timezone.now() - timedelta(days=40))

        report = funnel_report(timezone.now() - timedelta(days=30))

        self.assertEqual(report['visitors'], 0)
        self.assertEqual(report['inquiries'], 0)

    def test_the_funnel_steps_are_in_order(self):
        self.record(visitor='a')
        report = funnel_report(timezone.now() - timedelta(days=30))

        labels = [step['label'] for step in report['steps']]
        self.assertEqual(labels, ['Visitors', 'Inquiries', 'Orders', 'Sales'])
        self.assertEqual(report['steps'][0]['rate'], 100.0)

    def test_the_funnel_groups_by_source(self):
        self.record(visitor='a', source='Google')
        self.record(visitor='b', source='Facebook')
        self.make_inquiry(source='Google', visitor_id='a')

        report = funnel_report(timezone.now() - timedelta(days=30))
        rows = {row['source']: row for row in report['by_source']}

        self.assertEqual(rows['Google']['visitors'], 1)
        self.assertEqual(rows['Google']['inquiries'], 1)
        self.assertEqual(rows['Google']['leads'], 1)
        self.assertEqual(rows['Google']['conversion_rate'], 100.0)
        self.assertEqual(rows['Facebook']['visitors'], 1)
        self.assertEqual(rows['Facebook']['leads'], 0)

    def test_a_visitor_is_credited_to_the_source_they_arrived_from(self):
        self.record(visitor='a', source='Google')
        self.record(visitor='a', source='Internal')

        report = funnel_report(timezone.now() - timedelta(days=30))
        rows = {row['source']: row for row in report['by_source']}

        self.assertEqual(rows['Google']['visitors'], 1)
        self.assertNotIn('Internal', rows)

    def test_one_visitor_who_inquires_and_orders_converts_once(self):
        self.record(visitor='a', source='Google')
        self.make_inquiry(source='Google', visitor_id='a')
        self.make_order(source='Google', visitor_id='a')

        report = funnel_report(timezone.now() - timedelta(days=30))
        rows = {row['source']: row for row in report['by_source']}

        self.assertEqual(rows['Google']['leads'], 2)
        self.assertEqual(rows['Google']['converting_visitors'], 1)
        self.assertEqual(rows['Google']['conversion_rate'], 100.0)

    def test_a_lead_without_a_visitor_token_still_counts_as_a_conversion(self):
        self.record(visitor='a', source='Google')
        self.make_inquiry(source='Google', visitor_id='')

        report = funnel_report(timezone.now() - timedelta(days=30))
        rows = {row['source']: row for row in report['by_source']}

        self.assertEqual(rows['Google']['leads'], 1)
        self.assertEqual(rows['Google']['converting_visitors'], 1)
        self.assertEqual(rows['Google']['conversion_rate'], 100.0)

    def test_revenue_is_counted_for_sales_linked_to_an_order(self):
        self.record(visitor='a', source='Google')
        order = self.make_order(source='Google', visitor_id='a')
        self.make_sale(order, amount=24000)

        report = funnel_report(timezone.now() - timedelta(days=30))
        rows = {row['source']: row for row in report['by_source']}

        self.assertEqual(rows['Google']['revenue'], 24000.0)
        self.assertEqual(rows['Google']['sales'], 1)

    def test_a_sale_without_an_order_has_no_source(self):
        self.record(visitor='a', source='Google')
        self.make_sale(None, amount=24000)

        report = funnel_report(timezone.now() - timedelta(days=30))

        self.assertEqual(report['sales'], 1)
        self.assertEqual(sum(row['revenue'] for row in report['by_source']), 0.0)

    def test_the_funnel_reports_per_car_conversion(self):
        self.record(visitor='a', car=self.car)
        self.record(visitor='b', car=self.car)
        self.make_inquiry(car=self.car, visitor_id='a')

        report = funnel_report(timezone.now() - timedelta(days=30))

        self.assertEqual(len(report['by_car']), 1)
        row = report['by_car'][0]
        self.assertEqual(row['car'], self.car)
        self.assertEqual(row['views'], 2)
        self.assertEqual(row['visitors'], 2)
        self.assertEqual(row['leads'], 1)
        self.assertEqual(row['conversion_rate'], 50.0)

    def test_the_export_rows_match_the_report(self):
        self.record(visitor='a', source='Google')
        self.make_inquiry(source='Google', visitor_id='a')

        rows = conversion_rows(timezone.now() - timedelta(days=30))
        google = [row for row in rows if row['source'] == 'Google']

        self.assertEqual(len(google), 1)
        self.assertEqual(google[0]['visitors'], 1)
        self.assertEqual(google[0]['inquiries'], 1)

    def test_an_empty_period_produces_an_empty_funnel(self):
        report = funnel_report(timezone.now() - timedelta(days=30))

        self.assertEqual(report['visitors'], 0)
        self.assertEqual(report['inquiries'], 0)
        self.assertEqual(report['inquiry_rate'], 0.0)
        self.assertEqual(report['by_source'], [])


class ConversionCaptureTests(TestCase):
    """Leads remember where the visitor came from."""

    def setUp(self):
        self.car = create_car()
        self.visitor = 'visitor-abc'
        PageView.objects.create(
            path='/browse/',
            visitor_id=self.visitor,
            source='Google',
        )
        self.client.cookies['vid'] = self.visitor

    def test_an_inquiry_records_the_visitor_and_source(self):
        self.client.post(reverse('cars:inquiry', args=[self.car.pk]), {
            'customer_name': 'Jane Doe',
            'customer_email': 'jane@example.com',
            'customer_phone': '555-0100',
            'message': 'Is this still available?',
        })

        inquiry = Inquiry.objects.get()
        self.assertEqual(inquiry.visitor_id, self.visitor)
        self.assertEqual(inquiry.source, 'Google')

    def test_an_order_records_the_visitor_and_source(self):
        self.client.post(reverse('cars:order', args=[self.car.pk]), {
            'customer_name': 'John Smith',
            'customer_email': 'john@example.com',
            'customer_phone': '555-987-6543',
            'customer_address': '456 Oak Ave',
            'price': '24000.00',
            'trade_in_value': '0.00',
            'down_payment': '0.00',
            'notes': '',
        })

        order = Order.objects.get()
        self.assertEqual(order.visitor_id, self.visitor)
        self.assertEqual(order.source, 'Google')

    def test_an_appointment_records_the_visitor_and_source(self):
        self.client.post(reverse('cars:test_drive', args=[self.car.pk]), {
            'customer_name': 'John Smith',
            'customer_email': 'john@example.com',
            'customer_phone': '555-987-6543',
            'preferred_date': (timezone.now() + timedelta(days=3)).date().isoformat(),
            'preferred_time': '10:00',
        })

        appointment = Appointment.objects.get()
        self.assertEqual(appointment.visitor_id, self.visitor)
        self.assertEqual(appointment.source, 'Google')

    def test_a_visitor_without_tracking_has_no_source(self):
        self.client.cookies['vid'] = 'someone-else'

        self.client.post(reverse('cars:inquiry', args=[self.car.pk]), {
            'customer_name': 'Jane Doe',
            'customer_email': 'jane@example.com',
            'customer_phone': '555-0100',
            'message': 'Is this still available?',
        })

        inquiry = Inquiry.objects.get()
        self.assertEqual(inquiry.visitor_id, 'someone-else')
        self.assertEqual(inquiry.source, '')


class ConversionReportTests(TestCase):
    """The funnel on the staff dashboard, and its CSV export."""

    def setUp(self):
        self.staff = User.objects.create_user('staff', email='s@example.com', password='pass-12345')
        self.staff.is_staff = True
        self.staff.save()
        self.customer = User.objects.create_user('buyer', email='b@example.com', password='pass-12345')
        self.car = create_car()

    def test_the_dashboard_shows_the_funnel(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('traffic:traffic'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Conversion funnel')
        self.assertIn('funnel', response.context)
        self.assertEqual(response.context['funnel']['visitors'], 0)

    def test_the_staff_lists_show_the_source(self):
        Inquiry.objects.create(
            car=self.car,
            customer_name='Jane Doe',
            customer_email='jane@example.com',
            customer_phone='555-0100',
            message='Hello',
            source='Google',
        )
        Order.objects.create(
            car=self.car,
            customer_name='John Smith',
            customer_email='john@example.com',
            customer_phone='555-987-6543',
            customer_address='456 Oak Ave',
            price=24000,
            source='Facebook',
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse('cars:inquiries_list'))
        self.assertContains(response, 'Google')

        response = self.client.get(reverse('cars:orders_list'))
        self.assertContains(response, 'Facebook')

    def test_the_export_is_staff_only(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse('cars:traffic_export'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_anonymous_users_are_redirected_from_the_export(self):
        response = self.client.get(reverse('cars:traffic_export'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_the_export_downloads_a_csv(self):
        PageView.objects.create(path='/browse/', visitor_id='a', source='Google')
        self.client.force_login(self.staff)

        response = self.client.get(reverse('cars:traffic_export'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        content = response.content.decode()
        self.assertIn('Source', content)
        self.assertIn('Google', content)


class PurgeTrafficDataTests(TestCase):
    """The retention command."""

    def setUp(self):
        self.old = PageView.objects.create(path='/old/', visitor_id='a')
        PageView.objects.filter(pk=self.old.pk).update(
            created_at=timezone.now() - timedelta(days=120)
        )
        self.recent = PageView.objects.create(path='/recent/', visitor_id='b')

    def test_old_rows_are_deleted(self):
        call_command('purge_traffic_data', days=90, stdout=StringIO())
        remaining = list(PageView.objects.values_list('path', flat=True))
        self.assertEqual(remaining, ['/recent/'])

    def test_dry_run_deletes_nothing(self):
        call_command('purge_traffic_data', days=90, dry_run=True, stdout=StringIO())
        self.assertEqual(PageView.objects.count(), 2)

    def test_retention_comes_from_the_settings(self):
        with override_settings(TRAFFIC_RETENTION_DAYS=90):
            call_command('purge_traffic_data', stdout=StringIO())
        self.assertEqual(PageView.objects.count(), 1)
