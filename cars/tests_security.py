"""Tests for the pre-deployment security work: headers, CORS, backups."""

import os
import sqlite3
import tempfile
import time
import unittest
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse


class SecurityHeaderTests(TestCase):
    def test_csp_blocks_plugins_and_framing(self):
        response = self.client.get(reverse('cars:home'))
        policy = response['Content-Security-Policy']
        self.assertIn("default-src 'self'", policy)
        self.assertIn("object-src 'none'", policy)
        self.assertIn("base-uri 'self'", policy)
        self.assertIn("form-action 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)

    def test_hardening_headers_are_present(self):
        response = self.client.get(reverse('cars:home'))
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')
        self.assertEqual(response['Cross-Origin-Opener-Policy'], 'same-origin')
        self.assertEqual(response['Cross-Origin-Resource-Policy'], 'same-origin')
        self.assertIn('camera=()', response['Permissions-Policy'])
        self.assertIn('microphone=()', response['Permissions-Policy'])

    def test_admin_responses_are_noindexed(self):
        response = self.client.get(reverse('admin:login'))
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')

    @override_settings(CONTENT_SECURITY_POLICY='default-src none')
    def test_policy_can_be_replaced(self):
        response = self.client.get(reverse('cars:home'))
        self.assertEqual(response['Content-Security-Policy'], 'default-src none')

    @override_settings(CONTENT_SECURITY_POLICY_ENABLED=False)
    def test_policy_can_be_switched_off(self):
        response = self.client.get(reverse('cars:home'))
        self.assertNotIn('Content-Security-Policy', response)

    @override_settings(CONTENT_SECURITY_POLICY_REPORT_ONLY=True)
    def test_report_only_mode_uses_the_report_header(self):
        response = self.client.get(reverse('cars:home'))
        self.assertIn('Content-Security-Policy-Report-Only', response)
        self.assertNotIn('Content-Security-Policy', response)


@override_settings(CORS_ALLOWED_ORIGINS=['https://partner.example'])
class CorsTests(TestCase):
    def test_an_allowed_origin_gets_the_header(self):
        response = self.client.get(
            reverse('health'), HTTP_ORIGIN='https://partner.example',
        )
        self.assertEqual(
            response['Access-Control-Allow-Origin'], 'https://partner.example',
        )
        self.assertIn('Origin', response['Vary'])

    def test_an_unknown_origin_gets_nothing(self):
        response = self.client.get(
            reverse('health'), HTTP_ORIGIN='https://evil.example',
        )
        self.assertNotIn('Access-Control-Allow-Origin', response)

    def test_preflight_is_answered_without_hitting_the_view(self):
        response = self.client.options(
            reverse('health'),
            HTTP_ORIGIN='https://partner.example',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='GET',
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response['Access-Control-Allow-Origin'], 'https://partner.example',
        )
        self.assertEqual(response['Access-Control-Allow-Methods'], 'GET, HEAD, OPTIONS')

    def test_credentials_are_never_allowed(self):
        response = self.client.get(
            reverse('health'), HTTP_ORIGIN='https://partner.example',
        )
        self.assertNotIn('Access-Control-Allow-Credentials', response)


class BackupCommandTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.backup_dir = Path(self.temp_dir.name)

    def test_creates_a_backup_file(self):
        with override_settings(BACKUP_DIR=str(self.backup_dir)):
            call_command('backup_db')

        backups = [
            path for path in self.backup_dir.glob('db_backup_*')
            if path.is_file()
        ]
        self.assertEqual(len(backups), 1)
        self.assertGreater(backups[0].stat().st_size, 0)

    @unittest.skipUnless(connection.vendor == 'sqlite', 'SQLite snapshot check')
    def test_creates_a_readable_sqlite_snapshot(self):
        with override_settings(BACKUP_DIR=str(self.backup_dir)):
            call_command('backup_db')

        backups = list(self.backup_dir.glob('db_backup_*.sqlite3'))
        self.assertEqual(len(backups), 1)

        snapshot = sqlite3.connect(backups[0])
        try:
            tables = {
                row[0]
                for row in snapshot.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            snapshot.close()
        self.assertIn('cars_car', tables)

    def test_output_option_writes_to_an_explicit_path(self):
        target = self.backup_dir / 'snapshot.backup'
        call_command('backup_db', output=str(target), no_prune=True)
        self.assertTrue(target.exists())
        self.assertGreater(target.stat().st_size, 0)

    def test_old_backups_are_pruned(self):
        old = self.backup_dir / 'db_backup_20000101_000000.sqlite3'
        old.write_bytes(b'old backup')
        old_time = time.time() - (10 * 24 * 60 * 60)
        os.utime(old, (old_time, old_time))

        with override_settings(
            BACKUP_DIR=str(self.backup_dir), BACKUP_RETENTION_DAYS=7,
        ):
            call_command('backup_db')

        self.assertFalse(old.exists())
        self.assertEqual(len(list(self.backup_dir.glob('db_backup_*'))), 1)


class SecurityCheckCommandTests(TestCase):
    def test_development_settings_fail_the_audit(self):
        output = StringIO()
        with self.assertRaises(SystemExit):
            call_command('security_check', stdout=output)
        report = output.getvalue()
        self.assertIn('DEBUG is off', report)
        self.assertIn('[FAIL]', report)
