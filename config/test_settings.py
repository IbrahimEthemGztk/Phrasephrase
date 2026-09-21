"""Üretim ayarlarının güvenlik korumaları: ayarlar import edilirken hesaplandığı için ayrı bir süreçte denenir."""

import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import Client, SimpleTestCase, TestCase, override_settings

BASE_DIR = Path(__file__).resolve().parent.parent

PROBE = (
    'import json, config.settings as s;'
    'g = lambda name, default=None: getattr(s, name, default);'   # DEBUG'ta üretim ayarları hiç tanımlanmaz
    'print(json.dumps({'
    '"debug": s.DEBUG, "session_secure": g("SESSION_COOKIE_SECURE", False), "csrf_secure": g("CSRF_COOKIE_SECURE", False),'
    '"ssl_redirect": g("SECURE_SSL_REDIRECT", False), "hsts": g("SECURE_HSTS_SECONDS", 0),'
    '"proxy": g("SECURE_PROXY_SSL_HEADER"), "trusted": s.CSRF_TRUSTED_ORIGINS,'
    '"options": s.DATABASES["default"].get("OPTIONS", {})}))'
)


def load_settings(**env):
    """Ayarları verilen ortam değişkenleriyle taze bir süreçte yükler; (çıkış kodu, çıktı, hata) döndürür."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith(('DJANGO_', 'VERCEL', 'DATABASE'))}
    environment.update({
        'DJANGO_SECRET_KEY': 'test-only-secret-key',
        'DATABASE_URL': 'postgresql://user:pass@localhost:6543/db',
        'PYTHONIOENCODING': 'utf-8',
        **env,
    })
    result = subprocess.run(
        [sys.executable, '-c', PROBE], cwd=BASE_DIR, env=environment, capture_output=True, text=True, timeout=60,
    )
    return result.returncode, result.stdout, result.stderr


class ProductionSettingsTests(SimpleTestCase):
    def test_production_enables_secure_cookies_https_redirect_and_hsts(self):
        code, out, err = load_settings(DJANGO_DEBUG='false')
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertTrue(data['session_secure'] and data['csrf_secure'] and data['ssl_redirect'])
        self.assertGreater(data['hsts'], 0)
        self.assertEqual(data['proxy'], ['HTTP_X_FORWARDED_PROTO', 'https'])

    def test_no_wildcard_csrf_origin_by_default(self):
        code, out, err = load_settings(DJANGO_DEBUG='false')
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['trusted'], [])

    def test_ssl_redirect_and_hsts_can_be_tuned_from_the_environment(self):
        code, out, err = load_settings(DJANGO_DEBUG='false', DJANGO_SSL_REDIRECT='false', DJANGO_HSTS_SECONDS='60')
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data['ssl_redirect'])
        self.assertEqual(data['hsts'], 60)

    def test_local_debug_keeps_secure_only_features_off(self):
        code, out, err = load_settings(DJANGO_DEBUG='true')
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data['session_secure'] or data['csrf_secure'] or data['ssl_redirect'])

    def test_database_options_disable_prepared_statements_for_the_pooler(self):
        code, out, err = load_settings(DJANGO_DEBUG='false')
        self.assertEqual(code, 0, err)
        self.assertIn('prepare_threshold', json.loads(out)['options'])
        self.assertIsNone(json.loads(out)['options']['prepare_threshold'])

    def test_debug_is_refused_on_vercel(self):
        code, _, err = load_settings(DJANGO_DEBUG='true', VERCEL='1')
        self.assertNotEqual(code, 0)
        self.assertIn('Vercel', err)

    def test_production_on_vercel_starts_normally(self):
        code, _, err = load_settings(DJANGO_DEBUG='false', VERCEL='1')
        self.assertEqual(code, 0, err)


@override_settings(
    SECURE_SSL_REDIRECT=True, SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'),
    SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, SECURE_HSTS_SECONDS=60, CSRF_TRUSTED_ORIGINS=[],
)
class ProxyBehaviourTests(TestCase):
    """Vercel gibi TLS'i sonlandıran bir proxy'nin arkasında üretim ayarlarının davranışı."""

    # Gerçek istekte Host başlığı portsuz gelir; test istemcisi SERVER_PORT=80'i host'a eklemesin diye açıkça verilir.
    HTTPS = {'X-Forwarded-Proto': 'https', 'Host': 'testserver'}

    def test_plain_http_is_redirected_to_https(self):
        response = Client().get('/giris/')
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response['Location'].startswith('https://'))

    def test_https_behind_the_proxy_is_served_with_secure_cookies_and_hsts(self):
        response = Client().get('/giris/', headers=self.HTTPS)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies['csrftoken']['secure'])
        self.assertEqual(response['Strict-Transport-Security'], 'max-age=60')

    def test_login_form_post_passes_the_csrf_origin_check_without_a_trusted_origin_list(self):
        client = Client(enforce_csrf_checks=True)
        page = client.get('/giris/', headers=self.HTTPS)
        token = page.cookies['csrftoken'].value
        response = client.post(
            '/giris/', {'username': 'yok@example.com', 'password': 'x', 'csrfmiddlewaretoken': token},
            headers={**self.HTTPS, 'Origin': 'https://testserver'},
        )
        self.assertEqual(response.status_code, 200)   # 403 (CSRF) değil; hatalı giriş formu yeniden gösterilir

    def test_post_from_a_foreign_origin_is_still_rejected(self):
        client = Client(enforce_csrf_checks=True)
        token = client.get('/giris/', headers=self.HTTPS).cookies['csrftoken'].value
        response = client.post(
            '/giris/', {'username': 'a@b.co', 'password': 'x', 'csrfmiddlewaretoken': token},
            headers={**self.HTTPS, 'Origin': 'https://kotu.vercel.app'},
        )
        self.assertEqual(response.status_code, 403)
