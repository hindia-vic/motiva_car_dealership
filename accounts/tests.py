from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
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