from django.test import TestCase
from django.urls import reverse

from .models import User

PASSWORD = 'gizli-parola-123'


class RegisterTests(TestCase):
    def test_register_creates_user_and_logs_in(self):
        response = self.client.post(reverse('register'), {
            'email': 'Ali@Example.com', 'password1': PASSWORD, 'password2': PASSWORD,
        })
        self.assertRedirects(response, reverse('home'))
        self.assertTrue(User.objects.filter(email='ali@example.com').exists())
        self.assertIn('_auth_user_id', self.client.session)

    def test_duplicate_email_is_rejected_case_insensitively(self):
        User.objects.create_user('ali@example.com', PASSWORD)
        response = self.client.post(reverse('register'), {
            'email': 'ALI@example.com', 'password1': PASSWORD, 'password2': PASSWORD,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 1)
        self.assertContains(response, 'zaten var')

    def test_password_mismatch_is_rejected(self):
        response = self.client.post(reverse('register'), {
            'email': 'ali@example.com', 'password1': PASSWORD, 'password2': 'baska-parola-456',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_short_password_is_rejected(self):
        response = self.client.post(reverse('register'), {
            'email': 'ali@example.com', 'password1': 'k1', 'password2': 'k1',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_password_rule_errors_appear_on_password1_not_confirmation(self):
        response = self.client.post(reverse('register'), {
            'email': 'ali@example.com', 'password1': 'k1', 'password2': 'k1',
        })
        form = response.context['form']
        self.assertTrue(form.errors.get('password1'))
        self.assertFalse(form.errors.get('password2'))

    def test_password_mismatch_error_stays_on_confirmation(self):
        response = self.client.post(reverse('register'), {
            'email': 'ali@example.com', 'password1': PASSWORD, 'password2': 'baska-parola-456',
        })
        form = response.context['form']
        self.assertTrue(form.errors.get('password2'))
        self.assertFalse(form.errors.get('password1'))


class ErrorPageTests(TestCase):
    def test_unknown_url_renders_custom_404(self):
        response = self.client.get('/olmayan-sayfa/')
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Bu sayfayı bulamadık', status_code=404)

    def test_500_template_is_standalone(self):
        from django.template.loader import render_to_string
        html = render_to_string('500.html')
        self.assertIn('Bir sorun oluştu', html)


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)

    def test_login_with_email_case_insensitive(self):
        response = self.client.post(reverse('login'), {'username': 'ALI@example.com', 'password': PASSWORD})
        self.assertRedirects(response, reverse('home'))

    def test_login_with_wrong_password_fails(self):
        response = self.client.post(reverse('login'), {'username': 'ali@example.com', 'password': 'yanlis'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_logout_requires_post_and_ends_session(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        response = self.client.post(reverse('logout'))
        self.assertRedirects(response, reverse('login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_authenticated_user_is_redirected_away_from_auth_pages(self):
        self.client.force_login(self.user)
        for name in ('login', 'register'):
            self.assertRedirects(self.client.get(reverse(name)), reverse('home'))


class AccessControlTests(TestCase):
    def test_home_redirects_anonymous_to_login(self):
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('home')}")

    def test_home_is_available_for_logged_in_user(self):
        self.client.force_login(User.objects.create_user('ali@example.com', PASSWORD))
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Henüz phrase')
