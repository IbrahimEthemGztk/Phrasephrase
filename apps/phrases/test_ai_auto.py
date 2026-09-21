"""Tamamen AI modu: ifadeyi de AI seçer (kullanıcının zaten bildikleri hariç)."""

import json
from unittest import mock

from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.users.models import User

from . import ai
from .models import AIGeneration, Phrase
from .test_ai import FakeAPIError, fake_generation, model_reply
from .tests import make_phrase
from .validators import MAX_TEXT_LENGTH

PASSWORD = 'gizli-parola-123'
PHRASE = 'Actions speak louder than words'


def auto_json(phrase=PHRASE, translation='İşler sözden yüksek konuşur', story='Komik bir hikaye.', hints=None,
              **overrides):
    words = phrase.split()
    hints = hints or [f'ses{index}' for index in range(1, len(words) + 1)]
    data = {
        'phrase': phrase,
        'translation': translation,
        'words': [{'original_word': word, 'sound_hint': hint} for word, hint in zip(words, hints)],
        'association_story': story,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


class ParseAutoReplyTests(SimpleTestCase):
    def test_valid_reply_returns_phrase_and_server_assigned_order(self):
        phrase, translation, breakdown, story = ai.parse_auto_reply(auto_json(), [])
        self.assertEqual(phrase, PHRASE)
        self.assertEqual(translation, 'İşler sözden yüksek konuşur')
        self.assertEqual(story, 'Komik bir hikaye.')
        self.assertEqual([item['order'] for item in breakdown], [1, 2, 3, 4, 5])
        self.assertEqual([item['original_word'] for item in breakdown], PHRASE.split())

    def test_phrase_whitespace_is_normalized_and_words_follow_the_same_split(self):
        phrase, _, breakdown, _ = ai.parse_auto_reply(auto_json(phrase='  Actions   speak louder than words '), [])
        self.assertEqual(phrase, PHRASE)
        self.assertEqual(len(breakdown), 5)

    def test_phrase_the_user_already_knows_is_rejected_ignoring_case_and_punctuation(self):
        for known in (PHRASE, 'actions speak LOUDER than words!', '  Actions  speak louder, than words.  '):
            with self.subTest(known), self.assertRaises(ai.AIOutputError):
                ai.parse_auto_reply(auto_json(), [known])

    def test_other_known_phrases_do_not_block(self):
        ai.parse_auto_reply(auto_json(), ['Under the weather', 'Once in a blue moon'])

    def test_prompt_example_phrases_are_rejected_even_when_the_user_knows_nothing(self):
        for example in ai.EXAMPLE_PHRASES:
            with self.subTest(example), self.assertRaises(ai.AIOutputError):
                ai.parse_auto_reply(auto_json(phrase=example), [])
        with self.assertRaises(ai.AIOutputError):
            ai.parse_auto_reply(auto_json(phrase='break a leg.'), [])

    def test_length_limits(self):
        eight = ' '.join(['word'] * ai.AUTO_MAX_WORDS)
        ai.parse_auto_reply(auto_json(phrase=eight), [])   # sınırda kabul edilir
        with self.assertRaises(ai.AIOutputError):
            ai.parse_auto_reply(auto_json(phrase=eight + ' extra'), [])
        with self.assertRaises(ai.AIOutputError):
            ai.parse_auto_reply(auto_json(phrase='a' * (ai.MAX_PHRASE_LENGTH + 1)), [])

    def test_invalid_replies_are_rejected(self):
        def with_overrides(**changes):
            data = json.loads(auto_json())
            data.update(changes)
            return json.dumps(data)

        bad_replies = {
            'json değil': 'bozuk',
            'ifade yok': with_overrides(phrase=None),
            'ifade string değil': with_overrides(phrase=42),
            'ifade boş': with_overrides(phrase='   '),
            'çeviri yok': with_overrides(translation=''),
            'hikaye yok': with_overrides(association_story=''),
            'kelime sayısı ifadeyle uyuşmuyor': auto_json(phrase='Actions speak louder', words=[
                {'original_word': 'Actions', 'sound_hint': 'a'},
                {'original_word': 'speak', 'sound_hint': 'b'},
            ]),
            'kelimeler ifadeyle eşleşmiyor': auto_json(phrase='Actions speak louder', words=[
                {'original_word': 'Actions', 'sound_hint': 'a'},
                {'original_word': 'talk', 'sound_hint': 'b'},
                {'original_word': 'louder', 'sound_hint': 'c'},
            ]),
            'ses karşılığı boş': auto_json(hints=['a', 'b', ' ', 'd', 'e']),
            'ses karşılığı çok uzun': auto_json(hints=['a', 'b', 'x' * (MAX_TEXT_LENGTH + 1), 'd', 'e']),
        }
        for label, text in bad_replies.items():
            with self.subTest(label), self.assertRaises(ai.AIOutputError):
                ai.parse_auto_reply(text, [])


class BuildAutoInputTests(SimpleTestCase):
    def test_input_lists_kind_theme_and_known_phrases_including_examples(self):
        text = ai.build_auto_input('idiom', ['Under the weather', 'How are you?'], 'hayvanlar')
        self.assertIn('Bir İngilizce deyim', text)
        self.assertIn('Tema ipucu: hayvanlar', text)
        for phrase in ('Under the weather', 'How are you?', *ai.EXAMPLE_PHRASES):
            self.assertIn(f'- {phrase}', text)

    def test_known_phrases_are_deduplicated_and_capped(self):
        many = [f'Phrase {index}' for index in range(ai.AUTO_AVOID_IN_PROMPT * 3)]
        text = ai.build_auto_input('random', ['Break a leg', *many], 'yemek')
        self.assertEqual(text.count('- Break a leg'), 1)
        listed = [line for line in text.splitlines() if line.startswith('- ')]
        self.assertEqual(len(listed), ai.AUTO_AVOID_IN_PROMPT + len(ai.EXAMPLE_PHRASES))

    def test_every_category_has_a_prompt_description(self):
        for key, label in ai.CATEGORY_CHOICES:
            self.assertIn('İstenen tür:', ai.build_auto_input(key, [], 'zaman'))
            self.assertTrue(label)


class CreateCallTests(SimpleTestCase):
    def test_auto_call_uses_the_auto_prompt_schema_and_a_random_theme(self):
        with mock.patch('apps.phrases.ai._call_model') as call_model:
            ai._create_auto_interaction('proverb', ['Break a leg'])
        system_instruction, input_text, schema = call_model.call_args.args
        self.assertEqual(system_instruction, ai.AUTO_SYSTEM_INSTRUCTION)
        self.assertEqual(schema, ai.AUTO_RESPONSE_SCHEMA)
        self.assertIn('İngilizce atasözü', input_text)
        self.assertTrue(any(f'Tema ipucu: {theme}' in input_text for theme in ai.THEMES))

    def test_given_phrase_call_still_uses_the_original_prompt_and_schema(self):
        with mock.patch('apps.phrases.ai._call_model') as call_model:
            ai._create_interaction(['Break', 'a', 'leg'])
        system_instruction, input_text, schema = call_model.call_args.args
        self.assertEqual(system_instruction, ai.SYSTEM_INSTRUCTION)
        self.assertEqual(schema, ai.RESPONSE_SCHEMA)
        self.assertIn('İfade: Break a leg', input_text)

    def test_auto_schema_requires_phrase_and_reuses_the_other_fields(self):
        self.assertIn('phrase', ai.AUTO_RESPONSE_SCHEMA['required'])
        for name in ai.RESPONSE_SCHEMA['required']:
            self.assertIn(name, ai.AUTO_RESPONSE_SCHEMA['required'])
        self.assertNotIn('phrase', ai.RESPONSE_SCHEMA['properties'])   # verilen ifade modu değişmedi


@override_settings(GEMINI_API_KEY='test-key')
class GenerateAutoPhraseTests(SimpleTestCase):
    def generate(self, side_effect, category='random', avoid=()):
        with mock.patch('apps.phrases.ai._create_auto_interaction', side_effect=side_effect) as create:
            try:
                return ai.generate_auto_phrase(category, avoid), create
            except ai.AIError as error:
                return error, create

    def test_success_returns_the_ai_chosen_phrase_with_usage(self):
        result, create = self.generate([model_reply(auto_json())], category='idiom', avoid=['Under the weather'])
        create.assert_called_once_with('idiom', ['Under the weather'])
        self.assertEqual(result.phrase, PHRASE)
        self.assertEqual(result.translation, 'İşler sözden yüksek konuşur')
        self.assertEqual([item['order'] for item in result.word_breakdown], [1, 2, 3, 4, 5])
        self.assertEqual((result.input_tokens, result.output_tokens, result.thought_tokens), (100, 50, 20))

    def test_duplicate_of_a_known_phrase_is_retried_and_the_new_one_is_used(self):
        second = 'Better late than never'
        result, create = self.generate(
            [model_reply(auto_json()), model_reply(auto_json(phrase=second))], avoid=[PHRASE],
        )
        self.assertEqual(create.call_count, 2)
        self.assertEqual(result.phrase, second)
        self.assertEqual((result.input_tokens, result.output_tokens), (200, 100))

    def test_gives_up_when_the_model_keeps_repeating_known_phrases(self):
        error, create = self.generate([model_reply(auto_json()), model_reply(auto_json())], avoid=[PHRASE])
        self.assertEqual(create.call_count, ai.MAX_ATTEMPTS)
        self.assertEqual(error.reason, 'invalid_output')

    def test_invalid_category_is_rejected_before_calling_the_model(self):
        error, create = self.generate([model_reply(auto_json())], category='hack')
        create.assert_not_called()
        self.assertEqual(error.reason, 'invalid_input')

    @override_settings(GEMINI_API_KEY='')
    def test_not_configured_raises_without_calling_the_model(self):
        error, create = self.generate([model_reply(auto_json())])
        create.assert_not_called()
        self.assertIsInstance(error, ai.AINotConfigured)

    def test_api_errors_are_translated_and_not_retried(self):
        with self.assertLogs('apps.phrases.ai', level='WARNING'):
            error, create = self.generate(FakeAPIError(429))
        self.assertEqual(create.call_count, 1)
        self.assertEqual(error.reason, 'rate_limit')


def fake_auto(phrase=PHRASE):
    return fake_generation(phrase)


@override_settings(GEMINI_API_KEY='test-key', AI_DAILY_LIMIT=3)
class AutoViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)
        self.url = reverse('phrase_create_ai_auto')
        self.save_url = reverse('phrase_create_ai_save')

    def generate_patch(self, **kwargs):
        return mock.patch('apps.phrases.ai.generate_auto_phrase', **kwargs)

    # -- seçim ve giriş sayfaları --

    def test_chooser_offers_all_three_ways(self):
        response = self.client.get(reverse('phrase_create'))
        for name in ('phrase_create_manual', 'phrase_create_ai', 'phrase_create_ai_auto'):
            self.assertContains(response, f'href="{reverse(name)}"')
        self.assertContains(response, 'Tamamen AI ile üret')

    @override_settings(GEMINI_API_KEY='')
    def test_chooser_disables_both_ai_options_without_a_key(self):
        response = self.client.get(reverse('phrase_create'))
        self.assertContains(response, f'href="{reverse("phrase_create_manual")}"')
        for name in ('phrase_create_ai', 'phrase_create_ai_auto'):
            self.assertNotContains(response, f'href="{reverse(name)}"')
        self.assertContains(response, 'yapılandırılmamış', count=2)

    def test_input_page_shows_categories_and_quota(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for label in ('Rastgele', 'Günlük konuşma kalıbı', 'Deyim', 'Atasözü'):
            self.assertContains(response, label)
        self.assertContains(response, 'Bugün kalan hak: 3 / 3')
        self.assertContains(response, reverse('phrase_create_ai'))   # cümleyi kendim yazmak için bağlantı

    # -- üretim --

    def test_success_shows_a_preview_of_the_ai_chosen_phrase_without_saving(self):
        with self.generate_patch(return_value=fake_auto()) as generate:
            response = self.client.post(self.url, {'category': 'idiom'})
        generate.assert_called_once_with('idiom', [])
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        for text in (f'value="{PHRASE}"', 'value="Bol şans"', 'Komik bir hikaye.', 'AI tarafından üretildi'):
            self.assertIn(text, content)
        self.assertContains(response, f'action="{self.save_url}"')
        self.assertFalse(Phrase.objects.exists())
        self.assertEqual(AIGeneration.objects.get().prompt_text, PHRASE)

    def test_preview_regenerates_a_different_phrase_and_keeps_the_category(self):
        with self.generate_patch(return_value=fake_auto()):
            response = self.client.post(self.url, {'category': 'proverb'})
        self.assertContains(response, '<input type="hidden" name="category" value="proverb">', html=True)
        self.assertContains(response, f'formaction="{self.url}"')
        self.assertContains(response, 'Başka bir phrase üret')
        self.assertContains(response, f'href="{self.url}"')   # geri bağlantısı

    def test_known_phrases_and_the_shown_one_are_passed_as_phrases_to_avoid(self):
        make_phrase(self.user, original_phrase='Break a leg')
        make_phrase(self.user, original_phrase='Under the weather')
        other = User.objects.create_user('veli@example.com', PASSWORD)
        make_phrase(other, original_phrase='Başkasının ifadesi')

        with self.generate_patch(return_value=fake_auto()) as generate:
            self.client.post(self.url, {'category': 'idiom', 'original_phrase': '  Shown   phrase '})
        (category, avoid), _ = generate.call_args
        self.assertEqual(category, 'idiom')
        self.assertEqual(avoid, ['Shown phrase', 'Under the weather', 'Break a leg'])   # gösterilen + kayıtlılar (yeni önce)
        self.assertNotIn('Başkasının ifadesi', avoid)

    def test_invalid_category_never_reaches_the_model(self):
        with self.generate_patch() as generate:
            response = self.client.post(self.url, {'category': 'hack'})
        generate.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AIGeneration.objects.exists())

    def test_ai_error_is_shown_and_does_not_use_quota(self):
        with self.generate_patch(side_effect=ai.AIError('AI servisi şu an çok yoğun.', 'rate_limit')):
            response = self.client.post(self.url, {'category': 'random'})
        self.assertContains(response, 'AI servisi şu an çok yoğun.')
        self.assertContains(response, 'Bugün kalan hak: 3 / 3')
        self.assertContains(response, reverse('phrase_create_manual'))   # manuel yol açık kalır
        self.assertFalse(AIGeneration.objects.exists())

    def test_uses_the_same_daily_quota_as_the_other_ai_mode(self):
        AIGeneration.objects.create(user=self.user, prompt_text='x', model_name='m')
        with self.generate_patch(return_value=fake_auto()):
            response = self.client.post(self.url, {'category': 'random'})
        self.assertContains(response, 'Bugün kalan hak: 1')
        self.assertEqual(AIGeneration.objects.count(), 2)

    def test_daily_limit_blocks_generation(self):
        for _ in range(3):
            AIGeneration.objects.create(user=self.user, prompt_text='x', model_name='m')
        with self.generate_patch() as generate:
            response = self.client.post(self.url, {'category': 'random'})
        generate.assert_not_called()
        self.assertContains(response, 'Bugünlük AI üretim hakkın doldu')

    @override_settings(GEMINI_API_KEY='')
    def test_without_a_key_it_is_rejected_gracefully(self):
        with self.generate_patch() as generate:
            response = self.client.post(self.url, {'category': 'random'})
        generate.assert_not_called()
        self.assertContains(response, 'yapılandırılmamış')

    # -- kaydetme --

    def save_data(self, **overrides):
        data = {
            'original_phrase': PHRASE, 'translation': 'İşler sözden yüksek konuşur',
            'association_story': 'Komik bir hikaye.', 'category': 'random',
            'original_word': PHRASE.split(), 'sound_hint': ['a', 'b', 'c', 'd', 'e'],
        }
        data.update(overrides)
        return data

    def test_saving_a_fully_ai_preview_creates_an_ai_generated_phrase(self):
        response = self.client.post(self.save_url, self.save_data())
        phrase = Phrase.objects.get()
        self.assertRedirects(response, reverse('phrase_detail', args=[phrase.pk]))
        self.assertEqual((phrase.source, phrase.user), (Phrase.Source.AI_GENERATED, self.user))
        self.assertEqual([item['order'] for item in phrase.word_breakdown], [1, 2, 3, 4, 5])
        self.assertFalse(AIGeneration.objects.exists())   # kaydetmek hak harcamaz

    def test_invalid_save_keeps_the_fully_ai_mode_for_regeneration(self):
        response = self.client.post(self.save_url, self.save_data(sound_hint=['a', '', 'c', 'd', 'e']))
        self.assertContains(response, '2. satırda ses karşılığı boş olamaz')
        self.assertContains(response, f'formaction="{self.url}"')
        self.assertContains(response, '<input type="hidden" name="category" value="random">', html=True)
        self.assertFalse(Phrase.objects.exists())

    def test_invalid_save_without_or_with_a_tampered_category_uses_the_given_phrase_mode(self):
        for extra in ({}, {'category': 'hack'}):
            data = self.save_data(sound_hint=['a', '', 'c', 'd', 'e'])
            data.pop('category')
            data.update(extra)
            with self.subTest(extra):
                response = self.client.post(self.save_url, data)
                self.assertContains(response, f'formaction="{reverse("phrase_create_ai")}"')
                self.assertNotContains(response, 'name="category"')

    # -- erişim --

    def test_anonymous_users_are_redirected_to_login(self):
        anonymous = Client()
        self.assertRedirects(anonymous.get(self.url), f"{reverse('login')}?next={self.url}")
        with self.generate_patch() as generate:
            self.assertEqual(anonymous.post(self.url, {'category': 'random'}).status_code, 302)
            generate.assert_not_called()
