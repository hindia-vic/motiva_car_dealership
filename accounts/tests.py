import json
import re
import tempfile
from io import BytesIO
from unittest import mock

from PIL import Image
from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from cars.models import Car

from .models import Favorite


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
    )


class RegisterTest(TestCase):
    def test_register_creates_inactive_user_and_sends_verification(self):
        data = {
            'username': 'alice',
            'first_name': 'Alice',
            'last_name': 'Smith',
            'email': 'alice@example.com',
            'password1': 'strong-pass-123',
            'password2': 'strong-pass-123',
        }
        response = self.client.post(reverse('accounts:register'), data)
        self.assertRedirects(response, reverse('accounts:verify_email_sent'))
        user = User.objects.get(username='alice')
        self.assertEqual(user.email, 'alice@example.com')
        self.assertEqual(user.first_name, 'Alice')
        self.assertFalse(user.is_active)
        self.assertNotIn('_auth_user_id', self.client.session)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('alice@example.com', mail.outbox[0].to)
        self.assertIn('/accounts/verify/', mail.outbox[0].body)

    def test_register_rejects_duplicate_email(self):
        User.objects.create_user('existing', email='alice@example.com', password='pass-12345')
        data = {
            'username': 'alice',
            'first_name': 'Alice',
            'last_name': 'Smith',
            'email': 'alice@example.com',
            'password1': 'strong-pass-123',
            'password2': 'strong-pass-123',
        }
        response = self.client.post(reverse('accounts:register'), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')


def verification_path_from_outbox():
    """Extract the /accounts/verify/... path from the latest email."""
    return mail.outbox[-1].body.split('http://testserver', 1)[1].splitlines()[0].strip()


class EmailVerificationTest(TestCase):
    def register(self, **overrides):
        data = {
            'username': 'vera',
            'first_name': 'Vera',
            'last_name': 'Ng',
            'email': 'vera@example.com',
            'password1': 'strong-pass-123',
            'password2': 'strong-pass-123',
        }
        data.update(overrides)
        return self.client.post(reverse('accounts:register'), data)

    def test_verification_link_activates_and_logs_in(self):
        self.register()
        user = User.objects.get(username='vera')
        self.assertFalse(user.is_active)

        path = verification_path_from_outbox()
        response = self.client.get(path)
        self.assertRedirects(response, reverse('cars:home'))

        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.profile.email_verified)
        self.assertEqual(str(user.id), self.client.session.get('_auth_user_id'))

    def test_verification_link_is_single_use(self):
        self.register()
        path = verification_path_from_outbox()
        self.client.get(path)
        self.client.logout()

        response = self.client.get(path)
        self.assertRedirects(response, reverse('accounts:verify_email_invalid'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_invalid_token_shows_error_page(self):
        response = self.client.get(reverse('accounts:verify_email', kwargs={
            'uidb64': 'MQ', 'token': 'not-a-real-token',
        }))
        self.assertRedirects(response, reverse('accounts:verify_email_invalid'))
        response = self.client.get(reverse('accounts:verify_email_invalid'))
        self.assertContains(response, 'invalid or has expired')

    def test_unverified_user_cannot_login_with_custom_message(self):
        self.register()
        response = self.client.post(reverse('accounts:login'), {
            'username': 'vera',
            'password': 'strong-pass-123',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'verify your email address')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_wrong_password_still_gets_generic_error(self):
        self.register()
        response = self.client.post(reverse('accounts:login'), {
            'username': 'vera',
            'password': 'wrong-password',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'correct username and password')
        self.assertNotContains(response, 'Please verify your email address')

    def test_resend_sends_new_email_for_pending_account(self):
        self.register()
        response = self.client.post(reverse('accounts:resend_verification'), {
            'email': 'vera@example.com',
        })
        self.assertRedirects(response, reverse('accounts:verify_email_sent'))
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn('vera@example.com', mail.outbox[1].to)

    def test_resend_for_unknown_email_sends_nothing(self):
        response = self.client.post(reverse('accounts:resend_verification'), {
            'email': 'nobody@example.com',
        })
        self.assertRedirects(response, reverse('accounts:verify_email_sent'))
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_ignores_get_requests(self):
        response = self.client.get(reverse('accounts:resend_verification'))
        self.assertRedirects(response, reverse('accounts:login'))
        self.assertEqual(len(mail.outbox), 0)


class LoginLogoutTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('bob', email='bob@example.com', password='pass-12345')

    def test_login_redirects_home(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'bob',
            'password': 'pass-12345',
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('cars:home'))

    def test_logout_redirects_home(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('accounts:logout'))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('cars:home'))


class FavoritesTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('carol', email='carol@example.com', password='pass-12345')
        self.car = create_car()

    def test_favorites_page_requires_login(self):
        response = self.client.get(reverse('accounts:favorites'))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('accounts:favorites')}")

    def test_toggle_favorite_adds(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('accounts:toggle_favorite', args=[self.car.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Favorite.objects.filter(user=self.user, car=self.car).exists())

    def test_toggle_favorite_removes_and_is_idempotent(self):
        Favorite.objects.create(user=self.user, car=self.car)
        self.client.force_login(self.user)
        response = self.client.post(reverse('accounts:toggle_favorite', args=[self.car.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Favorite.objects.filter(user=self.user, car=self.car).exists())

    def test_anonymous_toggle_redirects_to_login(self):
        response = self.client.post(reverse('accounts:toggle_favorite', args=[self.car.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_toggle_respects_next(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('accounts:toggle_favorite', args=[self.car.id]),
            {'next': reverse('cars:browse_cars')},
        )
        self.assertRedirects(response, reverse('cars:browse_cars'))

    def test_favorites_page_lists_favorited_cars(self):
        Favorite.objects.create(user=self.user, car=self.car)
        self.client.force_login(self.user)
        response = self.client.get(reverse('accounts:favorites'))
        self.assertContains(response, 'Toyota')
        self.assertContains(response, 'Camry')


def password_from_outbox():
    """Extract the temporary password from the last email in the test outbox."""
    for line in mail.outbox[-1].body.splitlines():
        if line.strip().startswith('Password:'):
            return line.split(':', 1)[1].strip()
    raise AssertionError('No "Password:" line in email body')


STAFF_CREATE_DATA = {
    'username': 'newstaff',
    'first_name': 'New',
    'last_name': 'Staffer',
    'email': 'newstaff@example.com',
}


class StaffAccountTest(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            'admin', email='admin@example.com', password='staff-pass-123', is_staff=True)
        self.customer = User.objects.create_user(
            'janedoe', email='janedoe@example.com', password='pass-12345')

    def test_create_page_requires_staff(self):
        response = self.client.get(reverse('accounts:staff_create'))
        self.assertRedirects(response, reverse('cars:home'))

        self.client.force_login(self.customer)
        response = self.client.get(reverse('accounts:staff_create'))
        self.assertRedirects(response, reverse('cars:home'))

        self.client.force_login(self.staff)
        response = self.client.get(reverse('accounts:staff_create'))
        self.assertEqual(response.status_code, 200)

    def test_staff_list_requires_staff(self):
        response = self.client.get(reverse('accounts:staff_list'))
        self.assertRedirects(response, reverse('cars:home'))

        self.client.force_login(self.customer)
        response = self.client.get(reverse('accounts:staff_list'))
        self.assertRedirects(response, reverse('cars:home'))

        self.client.force_login(self.staff)
        response = self.client.get(reverse('accounts:staff_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'admin')

    def test_staff_can_create_staff_account_and_email_sent(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse('accounts:staff_create'), STAFF_CREATE_DATA)
        self.assertRedirects(response, reverse('accounts:staff_list'))

        user = User.objects.get(username='newstaff')
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_active)
        self.assertEqual(user.email, 'newstaff@example.com')
        self.assertTrue(user.profile.must_change_password)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('newstaff@example.com', mail.outbox[0].to)
        body = mail.outbox[0].body
        self.assertIn('Username:', body)
        self.assertIn('Password:', body)
        self.assertIn(reverse('accounts:login'), body)
        self.assertIn('must change', body.lower())

    def test_staff_list_shows_must_change_flag(self):
        self.client.force_login(self.staff)
        self.client.post(reverse('accounts:staff_create'), STAFF_CREATE_DATA)
        response = self.client.get(reverse('accounts:staff_list'))
        self.assertContains(response, 'newstaff')
        self.assertContains(response, 'Must change on login')

    def test_login_with_temp_password_forces_change_page(self):
        self.client.force_login(self.staff)
        self.client.post(reverse('accounts:staff_create'), STAFF_CREATE_DATA)
        temporary_password = password_from_outbox()

        self.client.logout()
        response = self.client.post(reverse('accounts:login'), {
            'username': 'newstaff',
            'password': temporary_password,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('cars:home'))

        response = self.client.get(reverse('cars:home'))
        self.assertRedirects(response, reverse('accounts:password_change'))

    def test_password_change_clears_forced_change_flag(self):
        user = User.objects.create_user(
            'forced', email='forced@example.com', password='temp-pass-123', is_staff=True)
        user.profile.must_change_password = True
        user.profile.save(update_fields=['must_change_password'])

        self.client.force_login(user)
        response = self.client.get(reverse('cars:home'))
        self.assertRedirects(response, reverse('accounts:password_change'))

        response = self.client.post(reverse('accounts:password_change'), {
            'old_password': 'temp-pass-123',
            'new_password1': 'my-new-pass-123',
            'new_password2': 'my-new-pass-123',
        })
        self.assertRedirects(response, reverse('accounts:password_change_done'))

        user.refresh_from_db()
        self.assertFalse(user.profile.must_change_password)

        response = self.client.get(reverse('cars:home'))
        self.assertEqual(response.status_code, 200)

    def test_customer_registration_is_not_forced_to_change(self):
        data = {
            'username': 'customer',
            'first_name': 'Ann',
            'last_name': 'Other',
            'email': 'ann@example.com',
            'password1': 'strong-pass-123',
            'password2': 'strong-pass-123',
        }
        response = self.client.post(reverse('accounts:register'), data)
        self.assertRedirects(response, reverse('accounts:verify_email_sent'))
        user = User.objects.get(username='customer')
        self.assertFalse(user.profile.must_change_password)

        response = self.client.get(reverse('cars:home'))
        self.assertEqual(response.status_code, 200)

    def test_toggle_requires_staff_and_post(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('accounts:toggle_staff_active', args=[self.staff.pk]))
        self.assertRedirects(response, reverse('accounts:staff_list'))

        self.client.force_login(self.customer)
        response = self.client.post(reverse('accounts:toggle_staff_active', args=[self.staff.pk]))
        self.assertRedirects(response, reverse('cars:home'))

    def test_staff_can_deactivate_then_reactivate_colleague(self):
        colleague = User.objects.create_user(
            'colleague', email='colleague@example.com', password='pass-123', is_staff=True)
        self.client.force_login(self.staff)

        response = self.client.post(reverse('accounts:toggle_staff_active', args=[colleague.pk]))
        self.assertRedirects(response, reverse('accounts:staff_list'))
        colleague.refresh_from_db()
        self.assertFalse(colleague.is_active)

        response = self.client.post(reverse('accounts:toggle_staff_active', args=[colleague.pk]))
        colleague.refresh_from_db()
        self.assertTrue(colleague.is_active)

    def test_cannot_deactivate_self(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse('accounts:toggle_staff_active', args=[self.staff.pk]))
        self.assertRedirects(response, reverse('accounts:staff_list'))
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)

    def test_deactivated_staff_cannot_log_in(self):
        colleague = User.objects.create_user(
            'gone', email='gone@example.com', password='pass-123', is_staff=True)
        self.client.force_login(self.staff)
        self.client.post(reverse('accounts:toggle_staff_active', args=[colleague.pk]))
        self.client.logout()

        response = self.client.post(reverse('accounts:login'), {
            'username': 'gone',
            'password': 'pass-123',
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_staff_list_renders_activate_button(self):
        User.objects.create_user(
            'gone', email='gone@example.com', password='pass-123', is_staff=True, is_active=False)
        User.objects.create_user(
            'activecol', email='activecol@example.com', password='pass-123', is_staff=True)
        self.client.force_login(self.staff)
        response = self.client.get(reverse('accounts:staff_list'))
        self.assertContains(response, 'gone')
        self.assertContains(response, 'Activate')
        self.assertContains(response, 'Deactivate')


class PasswordResetTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'resetuser', email='resetuser@example.com', password='old-pass-123')

    def test_reset_page_renders_for_anonymous(self):
        response = self.client.get(reverse('accounts:password_reset'))
        self.assertEqual(response.status_code, 200)

    def test_reset_email_sent_with_link(self):
        response = self.client.post(reverse('accounts:password_reset'), {
            'email': 'resetuser@example.com',
        })
        self.assertRedirects(response, reverse('accounts:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('resetuser@example.com', mail.outbox[0].to)
        self.assertIn('/reset/', mail.outbox[0].body)

    def test_unknown_email_no_outbox_but_redirects_anyway(self):
        response = self.client.post(reverse('accounts:password_reset'), {
            'email': 'nobody@example.com',
        })
        self.assertRedirects(response, reverse('accounts:password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_full_reset_flow_changes_password(self):
        self.client.post(reverse('accounts:password_reset'), {
            'email': 'resetuser@example.com',
        })
        body = mail.outbox[0].body
        reset_path = body.split('http://testserver', 1)[1].splitlines()[0].strip()

        response = self.client.get(reset_path, follow=True)
        self.assertEqual(response.status_code, 200)
        confirm_url = response.redirect_chain[-1][0]

        response = self.client.post(confirm_url, {
            'new_password1': 'brand-new-pass-123',
            'new_password2': 'brand-new-pass-123',
        })
        self.assertRedirects(response, reverse('accounts:password_reset_complete'))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('brand-new-pass-123'))

    def test_new_password_logs_in(self):
        self.client.post(reverse('accounts:password_reset'), {
            'email': 'resetuser@example.com',
        })
        reset_path = mail.outbox[0].body.split('http://testserver', 1)[1].splitlines()[0].strip()
        response = self.client.get(reset_path, follow=True)
        self.client.post(response.redirect_chain[-1][0], {
            'new_password1': 'brand-new-pass-123',
            'new_password2': 'brand-new-pass-123',
        })
        response = self.client.post(reverse('accounts:login'), {
            'username': 'resetuser',
            'password': 'brand-new-pass-123',
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('cars:home'))

    def test_invalid_reset_link_shows_error(self):
        response = self.client.get(reverse('accounts:password_reset_confirm', kwargs={
            'uidb64': 'abc', 'token': '123-abc',
        }))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'invalid')


class _FakeResponse:
    """Minimal stand-in for the object urlopen() returns as a context manager"""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode('utf-8')

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _patch_google(token_payload, userinfo_payload):
    """Patch urlopen so the token call returns one payload and userinfo the next"""
    return mock.patch(
        'urllib.request.urlopen',
        side_effect=[_FakeResponse(token_payload), _FakeResponse(userinfo_payload)],
    )


GOOGLE_SETTINGS = dict(
    GOOGLE_OAUTH_CLIENT_ID='test-client-id',
    GOOGLE_OAUTH_CLIENT_SECRET='test-client-secret',
)


@override_settings(GOOGLE_OAUTH_CLIENT_ID='', GOOGLE_OAUTH_CLIENT_SECRET='')
class GoogleSignInUnconfiguredTest(TestCase):
    def test_button_hidden_when_not_configured(self):
        for url_name in ('accounts:login', 'accounts:register'):
            response = self.client.get(reverse(url_name))
            self.assertNotContains(response, 'with Google')
            self.assertNotContains(response, reverse('accounts:google_login'))

    def test_start_view_messages_and_redirects_when_not_configured(self):
        response = self.client.get(reverse('accounts:google_login'))
        self.assertRedirects(response, reverse('accounts:login'))


@override_settings(**GOOGLE_SETTINGS)
class GoogleSignInTest(TestCase):
    def start(self, next_url=None):
        url = reverse('accounts:google_login')
        if next_url:
            url = f'{url}?next={next_url}'
        response = self.client.get(url)
        return response

    def callback_url(self):
        state = self.client.session['google_oauth_state']
        return f"{reverse('accounts:google_callback')}?state={state}&code=auth-code"

    def test_button_visible_when_configured(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertContains(response, 'Sign in with Google')
        response = self.client.get(reverse('accounts:register'))
        self.assertContains(response, 'Sign up with Google')

    def test_start_redirects_to_google_with_state(self):
        response = self.start()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('https://accounts.google.com/o/oauth2/v2/auth?'))
        self.assertIn('client_id=test-client-id', response.url)
        self.assertIn('scope=openid+email+profile', response.url)
        self.assertIn(f'state={self.client.session["google_oauth_state"]}', response.url)

    def test_start_stores_safe_next(self):
        self.start(reverse('accounts:favorites'))
        self.assertEqual(self.client.session['google_oauth_next'], reverse('accounts:favorites'))

    def test_callback_rejects_missing_state(self):
        self.start()
        url = f"{reverse('accounts:google_callback')}?state=wrong&code=auth-code"
        response = self.client.get(url)
        self.assertRedirects(response, reverse('accounts:login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_callback_handles_cancelled_consent(self):
        response = self.client.get(reverse('accounts:google_callback') + '?error=access_denied')
        self.assertRedirects(response, reverse('accounts:login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_callback_creates_active_user_and_logs_in(self):
        self.start()
        url = self.callback_url()
        with _patch_google(
            {'access_token': 'token-123'},
            {'email': 'NewGuy@Example.com', 'email_verified': True,
             'given_name': 'New', 'family_name': 'Guy'},
        ):
            response = self.client.get(url)

        self.assertRedirects(response, reverse('cars:home'))
        user = User.objects.get(email='newguy@example.com')
        self.assertTrue(user.is_active)
        self.assertEqual(user.first_name, 'New')
        self.assertEqual(user.last_name, 'Guy')
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.profile.email_verified)
        self.assertFalse(user.profile.must_change_password)
        self.assertEqual(str(user.id), self.client.session.get('_auth_user_id'))

    def test_callback_links_and_activates_existing_email(self):
        existing = User.objects.create_user(
            'olduser', email='old@example.com', password='pass-12345')
        existing.is_active = False
        existing.save(update_fields=['is_active'])

        self.start()
        url = self.callback_url()
        with _patch_google(
            {'access_token': 'token-123'},
            {'email': 'old@example.com', 'email_verified': True},
        ):
            response = self.client.get(url)

        self.assertRedirects(response, reverse('cars:home'))
        existing.refresh_from_db()
        self.assertTrue(existing.is_active)
        self.assertEqual(User.objects.filter(email='old@example.com').count(), 1)
        self.assertEqual(str(existing.id), self.client.session.get('_auth_user_id'))

    def test_callback_rejects_unverified_email(self):
        self.start()
        url = self.callback_url()
        with _patch_google(
            {'access_token': 'token-123'},
            {'email': 'sneaky@example.com', 'email_verified': False},
        ):
            response = self.client.get(url)

        self.assertRedirects(response, reverse('accounts:login'))
        self.assertFalse(User.objects.filter(email='sneaky@example.com').exists())
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_callback_redirects_to_stored_next(self):
        self.start(reverse('accounts:favorites'))
        url = self.callback_url()
        with _patch_google(
            {'access_token': 'token-123'},
            {'email': 'nextuser@example.com', 'email_verified': True},
        ):
            response = self.client.get(url)

        self.assertRedirects(response, reverse('accounts:favorites'))

    def test_callback_network_failure_shows_error(self):
        self.start()
        url = self.callback_url()
        with mock.patch('urllib.request.urlopen', side_effect=OSError('boom')):
            response = self.client.get(url)

        self.assertRedirects(response, reverse('accounts:login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_unique_username_avoids_collisions(self):
        User.objects.create_user('newguy', email='taken@example.com', password='pass-12345')

        self.start()
        url = self.callback_url()
        with _patch_google(
            {'access_token': 'token-123'},
            {'email': 'newguy@example.com', 'email_verified': True},
        ):
            response = self.client.get(url)

        self.assertRedirects(response, reverse('cars:home'))
        self.assertTrue(User.objects.filter(username='newguy').exists())
        self.assertTrue(User.objects.filter(username='newguy2').exists())


class AdminAccessTest(TestCase):
    """Only superusers may reach the Django admin; staff may not."""

    def test_admin_url_is_configurable(self):
        self.assertEqual(reverse('admin:index'), settings.ADMIN_URL)

    def test_staff_cannot_access_admin(self):
        staff = User.objects.create_user('staffx', password='pass-12345', is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('admin:login')))

    def test_staff_cannot_log_in_via_admin(self):
        User.objects.create_user('staffy', password='pass-12345', is_staff=True)
        response = self.client.post(
            reverse('admin:login'), {'username': 'staffy', 'password': 'pass-12345'})
        self.assertEqual(response.status_code, 200)  # form redisplayed with an error
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_superuser_can_access_admin(self):
        su = User.objects.create_superuser(
            'root', email='root@example.com', password='pass-12345')
        self.client.force_login(su)
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 200)

    @override_settings(STAFF_2FA_ENABLED=True)
    def test_admin_login_is_routed_through_the_site_two_factor_login(self):
        response = self.client.get(reverse('admin:login'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('accounts:login')))
        self.assertIn('next=', response.url)

    @override_settings(STAFF_2FA_ENABLED=True)
    def test_admin_login_post_cannot_skip_two_factor(self):
        User.objects.create_superuser(
            'root2', email='root2@example.com', password='pass-12345')
        response = self.client.post(
            reverse('admin:login'),
            {'username': 'root2', 'password': 'pass-12345'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('accounts:login')))
        self.assertNotIn('_auth_user_id', self.client.session)


def make_image(name='avatar.png'):
    """Build a tiny in-memory PNG for upload tests."""
    buffer = BytesIO()
    Image.new('RGB', (10, 10), 'red').save(buffer, 'PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


class ProfileTest(TestCase):
    """Users can edit their name, email and profile picture."""

    def setUp(self):
        self.user = User.objects.create_user(
            'pat', email='pat@example.com', password='strong-pass-123',
        )
        self.client.force_login(self.user)

    def test_profile_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('accounts:login')))

    def test_updates_name_and_email(self):
        response = self.client.post(reverse('accounts:profile'), {
            'first_name': 'Patricia',
            'last_name': 'Ng',
            'email': 'patricia@example.com',
        })
        self.assertRedirects(response, reverse('accounts:profile'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Patricia')
        self.assertEqual(self.user.last_name, 'Ng')
        self.assertEqual(self.user.email, 'patricia@example.com')

    def test_rejects_duplicate_email(self):
        User.objects.create_user(
            'other', email='taken@example.com', password='pass-12345',
        )
        response = self.client.post(reverse('accounts:profile'), {
            'first_name': 'Pat',
            'last_name': 'Ng',
            'email': 'taken@example.com',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'pat@example.com')

    def test_email_change_marks_unverified_and_sends_link(self):
        profile = self.user.profile
        profile.email_verified = True
        profile.save(update_fields=['email_verified'])

        response = self.client.post(reverse('accounts:profile'), {
            'first_name': 'Pat',
            'last_name': 'Ng',
            'email': 'newpat@example.com',
        })
        self.assertRedirects(response, reverse('accounts:profile'))

        self.user.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(self.user.email, 'newpat@example.com')
        self.assertFalse(profile.email_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('newpat@example.com', mail.outbox[0].to)

    def test_verification_link_reverifies_active_user(self):
        profile = self.user.profile
        profile.email_verified = False
        profile.save(update_fields=['email_verified'])

        self.client.post(reverse('accounts:profile'), {
            'first_name': 'Pat',
            'last_name': 'Ng',
            'email': 'newpat@example.com',
        })
        path = verification_path_from_outbox()
        self.client.logout()

        response = self.client.get(path)
        self.assertRedirects(response, reverse('cars:home'))
        profile.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertTrue(profile.email_verified)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_avatar_upload(self):
        response = self.client.post(reverse('accounts:profile'), {
            'first_name': 'Pat',
            'last_name': 'Ng',
            'email': 'pat@example.com',
            'avatar': make_image(),
        })
        self.assertRedirects(response, reverse('accounts:profile'))
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.avatar)
        self.assertIn('avatars/user_', self.user.profile.avatar.name)


class ChangePasswordTest(TestCase):
    """Signed-in users can change their own password."""

    def setUp(self):
        self.user = User.objects.create_user(
            'carl', email='carl@example.com', password='strong-pass-123',
        )
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('accounts:change_password'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('accounts:login')))

    def test_change_password_success(self):
        response = self.client.post(reverse('accounts:change_password'), {
            'old_password': 'strong-pass-123',
            'new_password1': 'brand-new-pass-456',
            'new_password2': 'brand-new-pass-456',
        })
        self.assertRedirects(response, reverse('accounts:profile'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('brand-new-pass-456'))
        self.assertIn('_auth_user_id', self.client.session)

    def test_wrong_current_password_rejected(self):
        response = self.client.post(reverse('accounts:change_password'), {
            'old_password': 'wrong-pass-999',
            'new_password1': 'brand-new-pass-456',
            'new_password2': 'brand-new-pass-456',
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('strong-pass-123'))

@override_settings(STAFF_2FA_ENABLED=True)
class StaffTwoFactorTests(TestCase):
    """Staff sign-in pauses for a code emailed to the account."""

    def setUp(self):
        self.staff = User.objects.create_user(
            'staffer', email='staff@example.com', password='staff-pass-123',
            is_staff=True,
        )

    def _start_login(self):
        return self.client.post(reverse('accounts:login'), {
            'username': 'staffer',
            'password': 'staff-pass-123',
        })

    def _last_code(self):
        body = mail.outbox[-1].body
        return re.search(r'\b(\d{6})\b', body).group(1)

    def _wrong_code(self, code):
        return '000000' if code != '000000' else '111111'

    def test_staff_login_is_not_complete_until_the_code_is_entered(self):
        response = self._start_login()
        self.assertRedirects(response, reverse('accounts:staff_2fa'))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('staff@example.com', mail.outbox[0].to)

    def test_correct_code_completes_the_login(self):
        self._start_login()
        response = self.client.post(
            reverse('accounts:staff_2fa'), {'code': self._last_code()},
        )
        self.assertRedirects(response, reverse('cars:home'))
        self.assertEqual(
            int(self.client.session['_auth_user_id']), self.staff.pk,
        )

    def test_wrong_code_is_rejected(self):
        self._start_login()
        code = self._last_code()
        response = self.client.post(
            reverse('accounts:staff_2fa'), {'code': self._wrong_code(code)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_expired_code_returns_to_login(self):
        self._start_login()
        session = self.client.session
        challenge = session['staff_2fa']
        challenge['expires_at'] = 0
        session['staff_2fa'] = challenge
        session.save()

        response = self.client.post(
            reverse('accounts:staff_2fa'), {'code': self._last_code()},
        )
        self.assertRedirects(response, reverse('accounts:login'))
        self.assertNotIn('staff_2fa', self.client.session)

    def test_too_many_attempts_returns_to_login(self):
        self._start_login()
        code = self._last_code()
        for _ in range(5):
            self.client.post(
                reverse('accounts:staff_2fa'), {'code': self._wrong_code(code)},
            )
        response = self.client.post(
            reverse('accounts:staff_2fa'), {'code': self._wrong_code(code)},
        )
        self.assertRedirects(response, reverse('accounts:login'))
        self.assertNotIn('staff_2fa', self.client.session)

    def test_resend_sends_a_new_code_after_the_cooldown(self):
        self._start_login()
        response = self.client.post(
            reverse('accounts:staff_2fa'), {'action': 'resend'},
        )
        self.assertRedirects(response, reverse('accounts:staff_2fa'))
        self.assertEqual(len(mail.outbox), 1)

        session = self.client.session
        challenge = session['staff_2fa']
        challenge['sent_at'] = 0
        session['staff_2fa'] = challenge
        session.save()

        self.client.post(reverse('accounts:staff_2fa'), {'action': 'resend'})
        self.assertEqual(len(mail.outbox), 2)

    def test_verify_page_shows_the_masked_address(self):
        self._start_login()
        response = self.client.get(reverse('accounts:staff_2fa'))
        self.assertContains(response, 's***@example.com')

    def test_verify_page_without_a_challenge_redirects_to_login(self):
        response = self.client.get(reverse('accounts:staff_2fa'))
        self.assertRedirects(response, reverse('accounts:login'))

    def test_non_staff_login_is_unaffected(self):
        User.objects.create_user(
            'customer', email='customer@example.com', password='cust-pass-123',
        )
        response = self.client.post(reverse('accounts:login'), {
            'username': 'customer',
            'password': 'cust-pass-123',
        })
        self.assertRedirects(response, reverse('cars:home'))
        self.assertEqual(len(mail.outbox), 0)

    def test_staff_without_an_email_skips_the_second_factor(self):
        self.staff.email = ''
        self.staff.save(update_fields=['email'])
        response = self._start_login()
        self.assertRedirects(response, reverse('cars:home'))
        self.assertEqual(len(mail.outbox), 0)
