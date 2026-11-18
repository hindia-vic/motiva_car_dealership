from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .context_processors import notification_center
from .models import Notification
from .services import notify, notify_staff


class NotifyServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('jane', password='pass-12345')

    def test_notify_creates_a_row_for_the_user(self):
        notification = notify(
            self.user, 'Hello', 'Something happened.', url='/orders/',
        )
        self.assertEqual(notification.user, self.user)
        self.assertFalse(notification.is_read)
        self.assertEqual(notification.url, '/orders/')

    def test_guest_and_inactive_users_are_skipped(self):
        self.assertIsNone(notify(None, 'Hello', 'Nobody home.'))
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self.assertIsNone(notify(self.user, 'Hello', 'Nobody home.'))
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_staff_reaches_only_active_staff(self):
        staff = User.objects.create_user('staff', password='pass-12345')
        staff.is_staff = True
        staff.save(update_fields=['is_staff'])
        inactive = User.objects.create_user('gone', password='pass-12345')
        inactive.is_staff = True
        inactive.is_active = False
        inactive.save(update_fields=['is_staff', 'is_active'])

        notify_staff('New order', 'A customer ordered a car.')

        recipients = set(
            Notification.objects.values_list('user__username', flat=True)
        )
        self.assertEqual(recipients, {'staff'})


class NotificationContextProcessorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user('jane', password='pass-12345')

    def _request(self, user=None):
        request = self.factory.get('/')
        request.user = user
        return request

    def test_guests_get_an_empty_bell(self):
        context = notification_center(self._request())
        self.assertEqual(context['unread_notification_count'], 0)
        self.assertEqual(context['recent_notifications'], [])

    def test_only_the_signed_in_users_notifications_are_counted(self):
        other = User.objects.create_user('other', password='pass-12345')
        notify(self.user, 'Mine', 'One.')
        notify(other, 'Theirs', 'Two.')

        context = notification_center(self._request(self.user))

        self.assertEqual(context['unread_notification_count'], 1)
        self.assertEqual(
            [item.title for item in context['recent_notifications']], ['Mine'],
        )

    def test_recent_list_is_capped_at_five(self):
        for number in range(7):
            notify(self.user, f'Item {number}', 'Body.')
        context = notification_center(self._request(self.user))
        self.assertEqual(context['unread_notification_count'], 7)
        self.assertEqual(len(context['recent_notifications']), 5)


class NotificationViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('jane', password='pass-12345')
        self.other = User.objects.create_user('other', password='pass-12345')
        self.client.force_login(self.user)

    def test_the_list_only_shows_your_own_notifications(self):
        mine = notify(self.user, 'Mine', 'One.')
        notify(self.other, 'Theirs', 'Two.')

        response = self.client.get(reverse('notifications:list'))

        self.assertEqual(response.status_code, 200)
        self.assertIn(mine, response.context['notifications'])
        self.assertEqual(len(response.context['notifications']), 1)

    def test_opening_a_notification_marks_it_read_and_follows_the_link(self):
        notification = notify(
            self.user, 'Mine', 'One.', url=reverse('cars:browse_cars'),
        )

        response = self.client.get(
            reverse('notifications:open', args=[notification.pk])
        )

        self.assertRedirects(response, reverse('cars:browse_cars'))
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)
        self.assertIsNotNone(notification.read_at)

    def test_an_offsite_link_is_not_followed(self):
        notification = notify(
            self.user, 'Suspicious', 'Click me.', url='https://evil.example.com/',
        )

        response = self.client.get(
            reverse('notifications:open', args=[notification.pk])
        )

        self.assertRedirects(response, reverse('notifications:list'))

    def test_another_users_notification_cannot_be_opened(self):
        notification = notify(self.other, 'Theirs', 'Two.')

        response = self.client.get(
            reverse('notifications:open', args=[notification.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_mark_read_needs_a_post(self):
        notification = notify(self.user, 'Mine', 'One.')

        self.client.get(reverse('notifications:mark_read', args=[notification.pk]))

        notification.refresh_from_db()
        self.assertFalse(notification.is_read)

    def test_mark_all_read_clears_the_badge(self):
        notify(self.user, 'One', 'Body.')
        notify(self.user, 'Two', 'Body.')
        notify(self.other, 'Theirs', 'Body.')

        self.client.post(reverse('notifications:mark_all_read'))

        self.assertEqual(
            self.user.notifications.filter(is_read=False).count(), 0,
        )
        self.assertEqual(
            self.other.notifications.filter(is_read=False).count(), 1,
        )

    def test_guests_are_sent_to_the_login_page(self):
        self.client.logout()
        response = self.client.get(reverse('notifications:list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response['Location'])

    def test_the_navbar_shows_the_unread_count(self):
        notify(self.user, 'One', 'Body.')
        notify(self.user, 'Two', 'Body.')

        response = self.client.get(reverse('cars:home'))

        self.assertContains(response, 'aria-label="Notifications"')
        self.assertContains(response, '>2</span>')
        self.assertContains(response, 'View all notifications')

    def test_guests_do_not_get_the_bell(self):
        self.client.logout()
        response = self.client.get(reverse('cars:home'))
        self.assertNotContains(response, 'aria-label="Notifications"')
