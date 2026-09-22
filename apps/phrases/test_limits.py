"""Kötüye kullanım sınırları: hikaye uzunluğu, kullanıcı başına phrase üst sınırı ve genel günlük AI sınırı."""

from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.users.models import User

from . import ai
from .models import AIGeneration, Phrase
from .tests import form_data, make_phrase

PASSWORD = 'gizli-parola-123'


class StoryLengthTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)
        self.url = reverse('phrase_create_manual')

    def post_story(self, story):
        return self.client.post(self.url, form_data(association_story=story))

    def test_story_at_the_limit_is_accepted(self):
        response = self.post_story('h' * ai.MAX_STORY_LENGTH)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(Phrase.objects.get().association_story), ai.MAX_STORY_LENGTH)

    def test_story_over_the_limit_is_rejected_with_a_message(self):
        response = self.post_story('h' * (ai.MAX_STORY_LENGTH + 1))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Phrase.objects.exists())
        self.assertContains(response, f'en fazla {ai.MAX_STORY_LENGTH}')

    def test_a_huge_story_is_rejected_and_never_stored(self):
        self.assertEqual(self.post_story('h' * 2_000_000).status_code, 200)
        self.assertFalse(Phrase.objects.exists())

    def test_form_page_tells_the_browser_the_limit(self):
        self.assertContains(self.client.get(self.url), f'maxlength="{ai.MAX_STORY_LENGTH}"')

    def test_editing_enforces_the_same_limit(self):
        phrase = make_phrase(self.user)
        url = reverse('phrase_update', args=[phrase.pk])
        self.client.post(url, form_data(association_story='u' * (ai.MAX_STORY_LENGTH + 1)))
        phrase.refresh_from_db()
        self.assertEqual(phrase.association_story, 'Hikaye')

    def test_saving_an_ai_preview_enforces_the_same_limit(self):
        response = self.client.post(
            reverse('phrase_create_ai_save'), form_data(association_story='h' * (ai.MAX_STORY_LENGTH + 1)),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Phrase.objects.exists())


@override_settings(MAX_PHRASES_PER_USER=2, GEMINI_API_KEY='test-key')
class PhraseCountLimitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)
        make_phrase(self.user, original_phrase='Bir')
        make_phrase(self.user, original_phrase='İki')

    def test_manual_add_is_blocked_at_the_limit_with_a_clear_message(self):
        response = self.client.post(reverse('phrase_create_manual'), form_data(original_phrase='Üç'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'En fazla 2 phrase ekleyebilirsin')
        self.assertEqual(self.user.phrases.count(), 2)

    def test_saving_an_ai_preview_is_blocked_at_the_limit(self):
        response = self.client.post(reverse('phrase_create_ai_save'), form_data(original_phrase='Üç'))
        self.assertContains(response, 'En fazla 2 phrase ekleyebilirsin')
        self.assertEqual(self.user.phrases.count(), 2)

    def test_ai_generation_is_blocked_before_calling_the_model_so_no_quota_is_wasted(self):
        for url_name, data in (
            ('phrase_create_ai', {'target_language': 'en', 'original_phrase': 'Break a leg'}),
            ('phrase_create_ai_auto', {'target_language': 'en', 'category': 'idiom'}),
        ):
            with self.subTest(url_name), mock.patch('apps.phrases.ai.generate_phrase') as one, \
                    mock.patch('apps.phrases.ai.generate_auto_phrase') as auto:
                response = self.client.post(reverse(url_name), data)
                self.assertContains(response, 'En fazla 2 phrase ekleyebilirsin')
                one.assert_not_called()
                auto.assert_not_called()
        self.assertFalse(AIGeneration.objects.exists())

    def test_deleting_a_phrase_frees_a_slot(self):
        self.client.post(reverse('phrase_delete', args=[self.user.phrases.first().pk]))
        response = self.client.post(reverse('phrase_create_manual'), form_data(original_phrase='Üç'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.user.phrases.count(), 2)

    def test_editing_an_existing_phrase_still_works_at_the_limit(self):
        phrase = self.user.phrases.first()
        response = self.client.post(
            reverse('phrase_update', args=[phrase.pk]), form_data(original_phrase='Değişti'),
        )
        self.assertEqual(response.status_code, 302)
        phrase.refresh_from_db()
        self.assertEqual(phrase.original_phrase, 'Değişti')

    def test_limit_is_per_user(self):
        other = User.objects.create_user('veli@example.com', PASSWORD)
        self.client.force_login(other)
        response = self.client.post(reverse('phrase_create_manual'), form_data(original_phrase='Veli'))
        self.assertEqual(response.status_code, 302)


@override_settings(GEMINI_API_KEY='test-key', AI_DAILY_LIMIT=3, AI_GLOBAL_DAILY_LIMIT=4)
class GlobalAIQuotaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.other = User.objects.create_user('veli@example.com', PASSWORD)
        self.client.force_login(self.user)

    def use(self, user, count, when=None):
        for _ in range(count):
            record = AIGeneration.objects.create(user=user, prompt_text='x', model_name='m')
            if when:
                AIGeneration.objects.filter(pk=record.pk).update(created_at=when)

    def test_other_users_usage_counts_toward_the_global_limit(self):
        self.use(self.other, 3)
        self.assertEqual(ai.remaining_generations(self.user), 1)   # kendi hakkı 3 ama genel sınıra 1 kaldı
        self.use(self.other, 1)
        self.assertEqual(ai.remaining_generations(self.user), 0)
        self.assertEqual(ai.quota_error(self.user), ai.GLOBAL_LIMIT_MESSAGE)

    def test_own_limit_still_applies_when_the_global_limit_has_room(self):
        self.use(self.user, 3)
        self.assertEqual(ai.remaining_generations(self.user), 0)
        self.assertEqual(ai.quota_error(self.user), ai.USER_LIMIT_MESSAGE)
        self.assertIsNone(ai.quota_error(self.other))

    def test_both_generation_pages_are_blocked_without_calling_the_model(self):
        self.use(self.other, 4)
        for url_name, data in (
            ('phrase_create_ai', {'target_language': 'en', 'original_phrase': 'Break a leg'}),
            ('phrase_create_ai_auto', {'target_language': 'en', 'category': 'idiom'}),
        ):
            with self.subTest(url_name), mock.patch('apps.phrases.ai.generate_phrase') as one, \
                    mock.patch('apps.phrases.ai.generate_auto_phrase') as auto:
                response = self.client.post(reverse(url_name), data)
                self.assertContains(response, 'günlük sınıra ulaştı')
                one.assert_not_called()
                auto.assert_not_called()
        self.assertEqual(AIGeneration.objects.count(), 4)

    def test_yesterdays_usage_does_not_count(self):
        self.use(self.other, 4, when=timezone.now() - timedelta(days=1, hours=1))
        self.assertEqual(ai.generations_today_total(), 0)
        self.assertEqual(ai.remaining_generations(self.user), 3)
        self.assertIsNone(ai.quota_error(self.user))

    def test_pages_show_the_remaining_allowance_within_the_global_limit(self):
        self.use(self.other, 3)
        self.assertContains(self.client.get(reverse('phrase_create_ai')), 'Bugün kalan hak: 1 / 3')
