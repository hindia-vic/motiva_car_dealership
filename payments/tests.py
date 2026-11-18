"""Tests for M-Pesa payments.

The rules that matter most here are the ones that protect money:

* the deposit is arithmetic, not something typed in by staff;
* a callback can only settle the amount that was actually requested;
* a replay or a late failure cannot change what has already happened;
* a guest reaches their own payment page only with a signed token;
* staff can ask Safaricom what happened, but cannot mark a payment paid.

The Safaricom client itself is never called: ``MpesaClient.query_status`` is
patched wherever a test needs a result.
"""

import json
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cars.deposits import amount_payable, order_deposit
from cars.models import Car, ListingRequest, Order
from hiring.models import HireBooking, HireCar

from . import services
from .models import MpesaTransaction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def create_car(vin=None):
    return Car.objects.create(
        make='Toyota',
        model='Camry',
        year=2021,
        vin=vin or uuid.uuid4().hex[:17].upper(),
        color='Blue',
        body_type='sedan',
        transmission='automatic',
        fuel_type='gasoline',
        purchase_price=Decimal('20000.00'),
        asking_price=Decimal('24000.00'),
        status='available',
    )


def create_order(**kwargs):
    defaults = dict(
        car=create_car(),
        customer_name='Jane Doe',
        customer_email='jane@example.com',
        customer_phone='0700000000',
        customer_address='1 Main St',
        price=Decimal('3000000.00'),
        trade_in_value=Decimal('0.00'),
    )
    defaults.update(kwargs)
    order = Order.objects.create(**defaults)
    order.deposit_amount = order_deposit(order.price, order.trade_in_value)
    order.save(update_fields=['deposit_amount'])
    return order


def create_listing(**kwargs):
    defaults = dict(
        owner_name='Jane Doe',
        owner_email='jane@example.com',
        owner_phone='0700000000',
        make='Toyota',
        model='Hilux',
        year=2019,
        vin=uuid.uuid4().hex[:17].upper(),
        asking_price=Decimal('2500000.00'),
        fee_amount=Decimal('2500.00'),
    )
    defaults.update(kwargs)
    return ListingRequest.objects.create(**defaults)


def create_hire_car():
    return HireCar.objects.create(
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


def create_booking(**kwargs):
    today = timezone.localdate()
    defaults = dict(
        hire_car=create_hire_car(),
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
        security_deposit=Decimal('0.00'),
        status='confirmed',
        payment_status='pending',
    )
    defaults.update(kwargs)
    return HireBooking.objects.create(**defaults)


def make_txn(**kwargs):
    defaults = dict(
        phone_number='0700000000',
        amount=Decimal('50000.00'),
        purpose=MpesaTransaction.PURPOSE_ORDER,
        reference='MP-' + uuid.uuid4().hex[:12],
    )
    defaults.update(kwargs)
    return MpesaTransaction.objects.create(**defaults)


def callback_payload(checkout_id, amount='50000', receipt='ABC123XYZ', code=0):
    return {
        'Body': {
            'stkCallback': {
                'MerchantRequestID': 'merchant-1',
                'CheckoutRequestID': checkout_id,
                'ResultCode': code,
                'ResultDesc': 'The service request is processed successfully.'
                if code == 0 else 'Request cancelled by the user',
                'CallbackMetadata': {
                    'Item': [
                        {'Name': 'Amount', 'Value': amount},
                        {'Name': 'MpesaReceiptNumber', 'Value': receipt},
                        {'Name': 'TransactionDate', 'Value': '20260101120000'},
                        {'Name': 'PhoneNumber', 'Value': '0700000000'},
                    ],
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# The deposit rule
# ---------------------------------------------------------------------------

class DepositRuleTests(TestCase):
    def test_ten_percent_of_the_amount_payable(self):
        self.assertEqual(order_deposit(Decimal('3000000')), Decimal('300000.00'))

    def test_rounds_up_to_the_next_thousand(self):
        # 10% of 1,234,567 is 123,456.70 -> 124,000
        self.assertEqual(order_deposit(Decimal('1234567')), Decimal('124000.00'))

    def test_minimum_is_fifty_thousand(self):
        self.assertEqual(order_deposit(Decimal('400000')), Decimal('50000.00'))

    def test_exact_minimum_is_left_alone(self):
        self.assertEqual(order_deposit(Decimal('500000')), Decimal('50000.00'))

    def test_never_more_than_the_amount_payable(self):
        # A KSh 40,000 car cannot ask for the KSh 50,000 floor.
        self.assertEqual(order_deposit(Decimal('40000')), Decimal('40000.00'))

    def test_trade_in_reduces_the_payable_and_the_deposit(self):
        self.assertEqual(
            order_deposit(Decimal('3000000'), Decimal('2000000')),
            Decimal('100000.00'),
        )

    def test_trade_in_above_the_price_means_nothing_to_pay(self):
        self.assertEqual(
            amount_payable(Decimal('1000000'), Decimal('1500000')),
            Decimal('0.00'),
        )
        self.assertEqual(
            order_deposit(Decimal('1000000'), Decimal('1500000')),
            Decimal('0.00'),
        )

    def test_blank_values_are_treated_as_zero(self):
        self.assertEqual(amount_payable(None, None), Decimal('0.00'))
        self.assertEqual(order_deposit(None), Decimal('0.00'))

    @override_settings(ORDER_DEPOSIT_MINIMUM='100000')
    def test_minimum_is_env_overridable(self):
        self.assertEqual(order_deposit(Decimal('600000')), Decimal('100000.00'))


class OrderPaymentModelTests(TestCase):
    def test_new_order_is_not_paid(self):
        order = create_order()
        self.assertEqual(order.payment_status, 'pending')
        self.assertFalse(order.is_deposit_paid())
        self.assertFalse(order.is_settled())
        self.assertEqual(order.balance_due(), Decimal('3000000.00'))

    def test_deposit_payment_leaves_the_order_partial(self):
        order = create_order()
        order.record_payment(order.deposit_due(), reference='RECEIPT1')

        self.assertEqual(order.payment_status, 'partial')
        self.assertTrue(order.is_deposit_paid())
        self.assertFalse(order.is_settled())
        self.assertIsNotNone(order.deposit_paid_at)
        self.assertEqual(order.payment_reference, 'RECEIPT1')
        self.assertEqual(order.balance_due(), Decimal('2700000.00'))

    def test_balance_payment_settles_the_order(self):
        order = create_order()
        order.record_payment(order.deposit_due())
        order.record_payment(order.balance_due())

        self.assertEqual(order.payment_status, 'paid')
        self.assertTrue(order.is_settled())
        self.assertEqual(order.balance_due(), Decimal('0.00'))

    def test_deposit_due_falls_back_to_the_rule_for_old_orders(self):
        order = create_order()
        order.deposit_amount = Decimal('0.00')
        order.save(update_fields=['deposit_amount'])
        self.assertEqual(order.deposit_due(), Decimal('300000.00'))


# ---------------------------------------------------------------------------
# Starting a payment
# ---------------------------------------------------------------------------

class StartPaymentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('jane', password='pass-12345')

    def _request(self):
        request = mock.Mock()
        request.user = self.user
        return request

    def test_refuses_a_non_positive_amount(self):
        txn, result, error = services.start_payment(
            self._request(), '0700000000', 0, 'order',
        )
        self.assertIsNone(txn)
        self.assertIn('nothing to pay', error)

    def test_refuses_a_blank_phone_number(self):
        txn, result, error = services.start_payment(
            self._request(), '   ', 50000, 'order',
        )
        self.assertIsNone(txn)
        self.assertIn('phone number', error)

    def test_refuses_an_order_that_is_already_paid(self):
        order = create_order(payment_status='paid')
        txn, result, error = services.start_payment(
            self._request(), '0700000000', 50000, 'order', order=order,
        )
        self.assertIsNone(txn)
        self.assertIn('already been paid', error)

    def test_refuses_a_listing_that_is_already_paid(self):
        listing = create_listing(payment_status='paid')
        txn, result, error = services.start_payment(
            self._request(), '0700000000', 2500, 'listing',
            listing_request=listing,
        )
        self.assertIsNone(txn)
        self.assertIn('already been settled', error)

    def test_refuses_a_hire_booking_that_is_already_paid(self):
        booking = create_booking(payment_status='paid')
        txn, result, error = services.start_payment(
            self._request(), '0700000000', 24000, 'hire',
            hire_booking=booking,
        )
        self.assertIsNone(txn)
        self.assertIn('already been paid', error)

    def test_starts_a_payment_for_an_unpaid_order(self):
        order = create_order()
        txn = make_txn(order=order, amount=order.deposit_due())
        with mock.patch(
            'payments.services.initiate_payment',
            return_value=(txn, {'CheckoutRequestID': 'checkout-1'}, None),
        ):
            started, result, error = services.start_payment(
                self._request(), '0700000000', order.deposit_due(), 'order',
                order=order,
            )
        self.assertIs(started, txn)
        self.assertIsNone(error)
        self.assertEqual(result['CheckoutRequestID'], 'checkout-1')


# ---------------------------------------------------------------------------
# The callback
# ---------------------------------------------------------------------------

class CallbackTests(TestCase):
    def setUp(self):
        self.order = create_order()
        self.txn = make_txn(
            order=self.order,
            amount=self.order.deposit_due(),
            checkout_request_id='checkout-123',
        )

    def _post(self, payload):
        return self.client.post(
            reverse('payments:mpesa_callback'),
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_success_marks_the_order_partial_and_emails_a_receipt(self):
        response = self._post(callback_payload('checkout-123', amount='300000'))
        self.assertEqual(response.status_code, 200)

        self.txn.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.txn.status, MpesaTransaction.STATUS_SUCCESS)
        self.assertEqual(self.txn.mpesa_receipt_number, 'ABC123XYZ')
        self.assertEqual(self.order.payment_status, 'partial')
        self.assertTrue(self.order.is_deposit_paid())
        self.assertEqual(self.order.amount_paid, self.order.deposit_due())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('jane@example.com', mail.outbox[0].to)
        self.assertIn('Payment received', mail.outbox[0].subject)

    def test_replayed_success_is_not_applied_twice(self):
        payload = callback_payload('checkout-123', amount='300000')
        self._post(payload)
        self._post(payload)

        self.order.refresh_from_db()
        self.assertEqual(self.order.amount_paid, self.order.deposit_due())
        # Only the first callback sent a receipt.
        self.assertEqual(len(mail.outbox), 1)

    def test_failure_leaves_the_order_unpaid(self):
        response = self._post(callback_payload('checkout-123', code=1032))
        self.assertEqual(response.status_code, 200)

        self.txn.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.txn.status, MpesaTransaction.STATUS_FAILED)
        self.assertEqual(self.txn.result_code, 1032)
        self.assertEqual(self.order.payment_status, 'pending')
        self.assertEqual(self.order.amount_paid, Decimal('0.00'))

    def test_late_failure_does_not_undo_a_success(self):
        self._post(callback_payload('checkout-123', amount='300000'))
        self._post(callback_payload('checkout-123', code=1032))

        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, MpesaTransaction.STATUS_SUCCESS)

    def test_amount_short_of_the_request_is_not_marked_paid(self):
        response = self._post(callback_payload('checkout-123', amount='1000'))
        self.assertEqual(response.status_code, 200)

        self.txn.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.txn.status, MpesaTransaction.STATUS_PENDING)
        self.assertIn('less than', self.txn.result_desc)
        self.assertEqual(self.order.payment_status, 'pending')
        self.assertEqual(self.order.amount_paid, Decimal('0.00'))

    def test_unknown_checkout_id_is_acknowledged(self):
        response = self._post(callback_payload('not-a-real-checkout'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['ResultCode'], 0)

    def test_unreadable_body_is_acknowledged(self):
        response = self.client.post(
            reverse('payments:mpesa_callback'),
            data='not json',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['ResultCode'], 0)


# ---------------------------------------------------------------------------
# Listing and hire payments
# ---------------------------------------------------------------------------

class RelatedPaymentTests(TestCase):
    def test_listing_fee_success_marks_the_listing_paid(self):
        listing = create_listing()
        txn = make_txn(
            purpose=MpesaTransaction.PURPOSE_LISTING,
            listing_request=listing,
            amount=listing.fee_amount,
        )
        txn, outcome = services.apply_success(txn, receipt_number='LIST1')

        listing.refresh_from_db()
        self.assertEqual(outcome, 'applied')
        self.assertEqual(listing.payment_status, 'paid')
        self.assertEqual(listing.payment_reference, 'LIST1')
        self.assertIsNotNone(listing.payment_received_at)
        self.assertEqual(len(mail.outbox), 1)

    def test_listing_fee_shortfall_leaves_it_unpaid(self):
        listing = create_listing()
        txn = make_txn(
            purpose=MpesaTransaction.PURPOSE_LISTING,
            listing_request=listing,
            amount=listing.fee_amount,
        )
        services.apply_success(txn, receipt_number='LIST1', amount='1000')

        listing.refresh_from_db()
        self.assertEqual(listing.payment_status, 'pending')
        self.assertEqual(len(mail.outbox), 0)

    def test_hire_payment_part_then_full(self):
        booking = create_booking()
        first = make_txn(
            purpose=MpesaTransaction.PURPOSE_HIRE,
            hire_booking=booking,
            amount=Decimal('10000.00'),
        )
        services.apply_success(first, receipt_number='HIRE1')

        booking.refresh_from_db()
        self.assertEqual(booking.payment_status, 'partial')
        self.assertEqual(len(mail.outbox), 1)

        second = make_txn(
            purpose=MpesaTransaction.PURPOSE_HIRE,
            hire_booking=booking,
            amount=Decimal('14000.00'),
        )
        services.apply_success(second, receipt_number='HIRE2')

        booking.refresh_from_db()
        self.assertEqual(booking.payment_status, 'paid')
        self.assertTrue(booking.is_settled())
        self.assertEqual(len(mail.outbox), 2)

    def test_failure_does_not_overwrite_a_successful_hire_payment(self):
        booking = create_booking()
        txn = make_txn(
            purpose=MpesaTransaction.PURPOSE_HIRE,
            hire_booking=booking,
            amount=booking.total_due(),
        )
        services.apply_success(txn, receipt_number='HIRE1')
        services.apply_failure(txn, result_code=1032, result_desc='late')

        txn.refresh_from_db()
        self.assertEqual(txn.status, MpesaTransaction.STATUS_SUCCESS)


# ---------------------------------------------------------------------------
# Signed tokens and access control
# ---------------------------------------------------------------------------

class TokenTests(TestCase):
    def test_status_token_round_trips(self):
        txn = make_txn()
        token = services.payment_status_token(txn)
        self.assertEqual(services.read_status_token(token), txn.reference)

    def test_invalid_status_token_is_rejected(self):
        self.assertIsNone(services.read_status_token('not-a-token'))
        self.assertIsNone(services.read_status_token(''))

    def test_expired_status_token_is_rejected(self):
        txn = make_txn()
        token = services.payment_status_token(txn)
        with mock.patch('payments.services._status_token_max_age', return_value=-1):
            self.assertIsNone(services.read_status_token(token))

    def test_order_token_round_trips(self):
        order = create_order()
        token = services.order_token(order)
        self.assertEqual(services.read_order_token(token), order.pk)

    def test_invalid_order_token_is_rejected(self):
        self.assertIsNone(services.read_order_token('nonsense'))


class PaymentStatusAccessTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', password='pass-12345')
        self.other = User.objects.create_user('other', password='pass-12345')
        self.staff = User.objects.create_user('staff', password='pass-12345')
        self.staff.is_staff = True
        self.staff.save()

        self.order = create_order(user=self.owner)
        self.txn = make_txn(order=self.order, user=self.owner)
        self.url = reverse('payments:payment_status', args=[self.txn.reference])

    def test_anonymous_without_a_token_is_sent_home(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('cars:home'))

    def test_anonymous_with_a_token_can_see_it(self):
        token = services.payment_status_token(self.txn)
        response = self.client.get(self.url, {'token': token})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.txn.reference)

    def test_owner_can_see_it(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_another_customer_cannot_see_it(self):
        self.client.force_login(self.other)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('cars:home'))

    def test_staff_can_see_it(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


class OrderPaymentAccessTests(TestCase):
    def setUp(self):
        self.order = create_order()
        self.url = reverse('cars:order_pay_deposit', args=[self.order.pk])

    def test_anonymous_without_a_token_cannot_start_a_payment(self):
        response = self.client.post(self.url, {'phone_number': '0700000000'})
        self.assertRedirects(response, reverse('cars:home'))

    def test_a_valid_token_authorises_the_deposit_payment(self):
        token = services.order_token(self.order)
        txn = make_txn(order=self.order, amount=self.order.deposit_due())
        with mock.patch(
            'payments.services.start_payment',
            return_value=(txn, {'CheckoutRequestID': 'c1'}, None),
        ) as start:
            response = self.client.post(
                self.url,
                {'phone_number': '0700000000', 'token': token},
            )
        self.assertTrue(start.called)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith(
                reverse('payments:payment_status', args=[txn.reference])
            )
        )

    def test_a_deposit_already_paid_is_not_charged_again(self):
        self.order.payment_status = 'partial'
        self.order.amount_paid = self.order.deposit_due()
        self.order.deposit_paid_at = timezone.now()
        self.order.save(update_fields=[
            'payment_status', 'amount_paid', 'deposit_paid_at',
        ])
        token = services.order_token(self.order)
        response = self.client.post(
            self.url, {'phone_number': '0700000000', 'token': token},
        )
        self.assertRedirects(response, reverse('cars:home'))


# ---------------------------------------------------------------------------
# Staff reconciliation
# ---------------------------------------------------------------------------

class StaffReconciliationTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff', password='pass-12345')
        self.staff.is_staff = True
        self.staff.save()
        self.customer = User.objects.create_user('customer', password='pass-12345')
        self.txn = make_txn(checkout_request_id='checkout-staff')

    def test_non_staff_cannot_open_the_transaction_list(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse('payments:transactions_list'))
        self.assertRedirects(response, reverse('cars:home'))

    def test_staff_can_open_the_transaction_list(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('payments:transactions_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.txn.reference)

    def test_non_staff_cannot_query_a_transaction(self):
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse('payments:transaction_query', args=[self.txn.reference]),
        )
        self.assertRedirects(response, reverse('cars:home'))

    def test_staff_query_applies_a_successful_result(self):
        self.client.force_login(self.staff)
        with mock.patch(
            'payments.mpesa.MpesaClient.query_status',
            return_value={
                'ResultCode': '0',
                'ResultDesc': 'ok',
                'MpesaReceiptNumber': 'QUERY1',
                'TransactionDate': '20260101120000',
            },
        ):
            response = self.client.post(
                reverse('payments:transaction_query', args=[self.txn.reference]),
                {'next': reverse('payments:transactions_list')},
            )
        self.assertRedirects(response, reverse('payments:transactions_list'))
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, MpesaTransaction.STATUS_SUCCESS)
        self.assertEqual(self.txn.mpesa_receipt_number, 'QUERY1')

    def test_staff_query_marks_a_cancelled_payment_failed(self):
        self.client.force_login(self.staff)
        with mock.patch(
            'payments.mpesa.MpesaClient.query_status',
            return_value={'ResultCode': '1032', 'ResultDesc': 'cancelled'},
        ):
            self.client.post(
                reverse('payments:transaction_query', args=[self.txn.reference]),
            )
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, MpesaTransaction.STATUS_FAILED)

    def test_staff_can_export_the_filtered_list(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('payments:transactions_export'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn(self.txn.reference, response.content.decode())


# ---------------------------------------------------------------------------
# The fallback query command
# ---------------------------------------------------------------------------

class CheckMpesaPaymentsCommandTests(TestCase):
    def setUp(self):
        self.order = create_order()
        self.txn = make_txn(
            order=self.order,
            amount=self.order.deposit_due(),
            checkout_request_id='checkout-old',
        )
        # auto_now_add ignores an explicit value, so move it into the past.
        MpesaTransaction.objects.filter(pk=self.txn.pk).update(
            created_at=timezone.now() - timedelta(minutes=30),
        )

    def test_fresh_payments_are_not_queried(self):
        MpesaTransaction.objects.filter(pk=self.txn.pk).update(
            created_at=timezone.now(),
        )
        with mock.patch(
            'payments.mpesa.MpesaClient.query_status',
        ) as query:
            call_command('check_mpesa_payments')
        query.assert_not_called()

    def test_old_pending_payment_is_queried_and_applied(self):
        with mock.patch(
            'payments.mpesa.MpesaClient.query_status',
            return_value={
                'ResultCode': '0',
                'ResultDesc': 'ok',
                'MpesaReceiptNumber': 'FALLBACK1',
                'TransactionDate': '20260101120000',
            },
        ):
            call_command('check_mpesa_payments')

        self.txn.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.txn.status, MpesaTransaction.STATUS_SUCCESS)
        self.assertEqual(self.order.payment_status, 'partial')
        self.assertEqual(self.order.amount_paid, self.order.deposit_due())

    def test_transactions_without_a_checkout_id_are_skipped(self):
        self.txn.checkout_request_id = ''
        self.txn.save(update_fields=['checkout_request_id'])
        with mock.patch(
            'payments.mpesa.MpesaClient.query_status',
        ) as query:
            call_command('check_mpesa_payments')
        query.assert_not_called()
