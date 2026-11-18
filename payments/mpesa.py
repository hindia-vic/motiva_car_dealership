"""Safaricom M-Pesa Daraja API helper."""
import base64
import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import requests
from django.conf import settings


class MpesaError(Exception):
    pass


class MpesaClient:
    def __init__(self):
        self.consumer_key = getattr(settings, 'MPESA_CONSUMER_KEY', '')
        self.consumer_secret = getattr(settings, 'MPESA_CONSUMER_SECRET', '')
        self.shortcode = getattr(settings, 'MPESA_SHORTCODE', '')
        self.passkey = getattr(settings, 'MPESA_PASSKEY', '')
        self.callback_url = getattr(settings, 'MPESA_CALLBACK_URL', '')
        self.environment = getattr(settings, 'MPESA_ENVIRONMENT', 'sandbox').lower()
        self.timeout = getattr(settings, 'MPESA_TIMEOUT', 30)

        if self.environment == 'production':
            self.base_url = 'https://api.safaricom.co.ke'
        else:
            self.base_url = 'https://sandbox.safaricom.co.ke'

    def get_access_token(self):
        url = f'{self.base_url}/oauth/v1/generate?grant_type=client_credentials'
        try:
            response = requests.get(
                url,
                auth=(self.consumer_key, self.consumer_secret),
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            return data.get('access_token')
        except Exception as e:
            raise MpesaError(f'Failed to get access token: {e}')

    def generate_password(self):
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        data_to_encode = f'{self.shortcode}{self.passkey}{timestamp}'
        encoded = base64.b64encode(data_to_encode.encode()).decode('utf-8')
        return encoded, timestamp

    def stk_push(self, phone_number, amount, account_reference, transaction_desc='Payment'):
        if not all([self.consumer_key, self.consumer_secret, self.shortcode, self.passkey]):
            raise MpesaError('M-Pesa credentials not configured')

        access_token = self.get_access_token()
        password, timestamp = self.generate_password()

        # Normalize phone number to 254XXXXXXXXX
        phone = str(phone_number).strip().replace('+', '').replace(' ', '')
        if phone.startswith('0'):
            phone = '254' + phone[1:]
        elif phone.startswith('7') and len(phone) == 9:
            phone = '254' + phone
        elif phone.startswith('1') and len(phone) == 9:
            phone = '254' + phone

        url = f'{self.base_url}/mpesa/stkpush/v1/processrequest'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }
        payload = {
            'BusinessShortCode': self.shortcode,
            'Password': password,
            'Timestamp': timestamp,
            'TransactionType': 'CustomerPayBillOnline',
            'Amount': int(
                Decimal(str(amount)).to_integral_value(rounding=ROUND_HALF_UP)
            ),
            'PartyA': phone,
            'PartyB': self.shortcode,
            'PhoneNumber': phone,
            'CallBackURL': self.callback_url,
            'AccountReference': account_reference[:12],
            'TransactionDesc': transaction_desc[:13],
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise MpesaError(f'STK Push failed: {e}')
        except Exception as e:
            raise MpesaError(f'STK Push error: {e}')

    def query_status(self, checkout_request_id):
        """Ask Safaricom what happened to an STK push.

        Used when the callback never arrives (a lost callback, a network
        problem on their side). The response carries a ``ResultCode``:
        ``0`` means paid, ``1032``/``1037`` mean the customer cancelled or
        timed out, and ``1037`` can also mean "still waiting" on some
        sandbox responses, so callers treat unknown codes as pending.
        """
        if not all([self.consumer_key, self.consumer_secret, self.shortcode, self.passkey]):
            raise MpesaError('M-Pesa credentials not configured')
        if not checkout_request_id:
            raise MpesaError('No checkout request id to query')

        access_token = self.get_access_token()
        password, timestamp = self.generate_password()
        url = f'{self.base_url}/mpesa/stkpushquery/v1/query'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }
        payload = {
            'BusinessShortCode': self.shortcode,
            'Password': password,
            'Timestamp': timestamp,
            'CheckoutRequestID': checkout_request_id,
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise MpesaError(f'STK query failed: {e}')
        except Exception as e:
            raise MpesaError(f'STK query error: {e}')
