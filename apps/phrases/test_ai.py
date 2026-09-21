import json
from datetime import timedelta
from unittest import mock

import httpx
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.users.models import User

from . import ai
from .models import AIGeneration, Phrase, PhraseProgress
from .validators import MAX_TEXT_LENGTH, MAX_WORDS

PASSWORD = 'gizli-parola-123'
WORDS = ['Break', 'a', 'leg']
HINTS = ['Bırak', 'Ey', 'Lig']


def reply_json(words=WORDS, hints=HINTS, translation='Bol şans', story='Antrenör bağırdı: bırak, ey, lig!', **overrides):
    data = {
        'translation': translation,
        'words': [{'original_word': word, 'sound_hint': hint} for word, hint in zip(words, hints)],
        'association_story': story,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def model_reply(text=None, status='completed', **tokens):
    return ai.ModelReply(
        status=status,
        text=reply_json() if text is None else text,
        input_tokens=tokens.get('input_tokens', 100),
        output_tokens=tokens.get('output_tokens', 50),
        thought_tokens=tokens.get('thought_tokens', 20),
    )


class FakeAPIError(Exception):
    def __init__(self, status_code):
        super().__init__(f'HTTP {status_code}')
        self.status_code = status_code


class APIConnectionError(Exception):
    """SDK'nın ağ hatası sarmalayıcısını taklit eder (sınıf adı gerçeğiyle aynıdır)."""


class APITimeoutError(Exception):
    """SDK'nın zaman aşımı sarmalayıcısını taklit eder."""


def wrapped(wrapper_class, cause):
    try:
        raise cause
    except Exception as original:
        try:
            raise wrapper_class('sarmalanmış') from original
        except Exception as error:
            return error


class ParseReplyTests(SimpleTestCase):
    def test_valid_reply_is_parsed_and_order_is_assigned_by_the_server(self):
        text = json.dumps({
            'translation': ' Bol şans ',
            'words': [
                {'original_word': 'Break', 'sound_hint': 'Bırak', 'order': 3},   # modelin order alanı yok sayılır
                {'original_word': 'a', 'sound_hint': 'Ey', 'order': 1},
                {'original_word': 'leg', 'sound_hint': 'Lig', 'order': 2},
            ],
            'association_story': ' Hikaye ',
        })
        translation, breakdown, story = ai.parse_reply(text, WORDS)
        self.assertEqual(translation, 'Bol şans')
        self.assertEqual(story, 'Hikaye')
        self.assertEqual(breakdown, [
            {'order': 1, 'original_word': 'Break', 'sound_hint': 'Bırak'},
            {'order': 2, 'original_word': 'a', 'sound_hint': 'Ey'},
            {'order': 3, 'original_word': 'leg', 'sound_hint': 'Lig'},
        ])

    def test_original_words_come_from_the_servers_own_split_not_from_the_model(self):
        text = reply_json(words=['break', 'A', 'LEG'])   # model büyük/küçük harfi değiştirmiş
        _, breakdown, _ = ai.parse_reply(text, WORDS)
        self.assertEqual([item['original_word'] for item in breakdown], WORDS)

    def test_punctuation_stays_on_the_word(self):
        words = ['How', 'are', 'you?']
        _, breakdown, _ = ai.parse_reply(reply_json(words=words), words)
        self.assertEqual(breakdown[2]['original_word'], 'you?')

    def test_invalid_replies_are_rejected(self):
        def with_overrides(**changes):
            data = json.loads(reply_json())
            data.update(changes)
            return json.dumps(data)

        long_hint = 'x' * (MAX_TEXT_LENGTH + 1)
        bad_replies = {
            'json değil': 'bu json değil',
            'nesne değil': '[1, 2, 3]',
            'boş metin': '',
            'çeviri yok': with_overrides(translation=''),
            'çeviri çok uzun': with_overrides(translation='a' * 301),
            'hikaye yok': with_overrides(association_story='  '),
            'hikaye çok uzun': with_overrides(association_story='a' * (ai.MAX_STORY_LENGTH + 1)),
            'kelimeler liste değil': with_overrides(words='Break a leg'),
            'eksik kelime': with_overrides(words=[{'original_word': 'Break', 'sound_hint': 'Bırak'}]),
            'fazla kelime': reply_json(words=WORDS + ['x'], hints=HINTS + ['y']),
            'kelime eşleşmiyor': reply_json(words=['Break', 'the', 'leg']),
            'sıra karışık': reply_json(words=['leg', 'a', 'Break'], hints=HINTS),
            'ses karşılığı boş': reply_json(hints=['Bırak', ' ', 'Lig']),
            'ses karşılığı çok uzun': reply_json(hints=['Bırak', 'Ey', long_hint]),
            'ses karşılığı string değil': with_overrides(words=[
                {'original_word': 'Break', 'sound_hint': 1},
                {'original_word': 'a', 'sound_hint': 'Ey'},
                {'original_word': 'leg', 'sound_hint': 'Lig'},
            ]),
            'öğe nesne değil': with_overrides(words=['Break', 'a', 'leg']),
        }
        for label, text in bad_replies.items():
            with self.subTest(label), self.assertRaises(ai.AIOutputError):
                ai.parse_reply(text, WORDS)


class HelperTests(SimpleTestCase):
    def test_split_phrase_uses_whitespace(self):
        self.assertEqual(ai.split_phrase('  Break   a\tleg '), ['Break', 'a', 'leg'])

    def test_build_input_lists_numbered_words_in_order(self):
        text = ai.build_input(WORDS)
        self.assertIn('İfade: Break a leg', text)
        self.assertLess(text.index('1. Break'), text.index('2. a'))
        self.assertLess(text.index('2. a'), text.index('3. leg'))


@override_settings(GEMINI_API_KEY='test-key')
class GeneratePhraseTests(SimpleTestCase):
    def generate(self, side_effect, phrase='Break a leg'):
        with mock.patch('apps.phrases.ai._create_interaction', side_effect=side_effect) as create:
            try:
                return ai.generate_phrase(phrase), create
            except ai.AIError as error:
                return error, create

    def test_success_on_first_try(self):
        result, create = self.generate([model_reply()])
        self.assertEqual(create.call_count, 1)
        self.assertEqual(result.phrase, 'Break a leg')
        self.assertEqual(result.translation, 'Bol şans')
        self.assertEqual([item['order'] for item in result.word_breakdown], [1, 2, 3])
        self.assertEqual((result.input_tokens, result.output_tokens, result.thought_tokens), (100, 50, 20))

    def test_phrase_is_normalized_and_words_are_passed_to_the_model(self):
        result, create = self.generate([model_reply()], phrase='  Break   a leg ')
        create.assert_called_once_with(WORDS)
        self.assertEqual(result.phrase, 'Break a leg')

    def test_invalid_output_is_retried_once_and_tokens_are_summed(self):
        result, create = self.generate([model_reply('bozuk'), model_reply()])
        self.assertEqual(create.call_count, 2)
        self.assertEqual(result.translation, 'Bol şans')
        self.assertEqual((result.input_tokens, result.output_tokens, result.thought_tokens), (200, 100, 40))

    def test_gives_up_after_two_invalid_outputs(self):
        error, create = self.generate([model_reply('bozuk'), model_reply(reply_json(hints=['', '', '']))])
        self.assertEqual(create.call_count, ai.MAX_ATTEMPTS)
        self.assertIsInstance(error, ai.AIError)
        self.assertEqual(error.reason, 'invalid_output')

    def test_incomplete_status_is_retried(self):
        result, create = self.generate([model_reply('', status='incomplete'), model_reply()])
        self.assertEqual(create.call_count, 2)
        self.assertEqual(result.translation, 'Bol şans')

    def test_failed_status_is_not_retried(self):
        error, create = self.generate([model_reply('', status='failed')])
        self.assertEqual(create.call_count, 1)
        self.assertEqual(error.reason, 'invalid_output')

    def test_api_errors_are_translated_to_user_messages(self):
        cases = [
            (httpx.ReadTimeout('zaman aşımı'), 'timeout'),
            (httpx.ConnectError('bağlanılamadı'), 'connection'),
            (wrapped(APITimeoutError, httpx.ReadTimeout('zaman aşımı')), 'timeout'),      # SDK sarmalayıcısı
            (wrapped(APIConnectionError, httpx.ConnectError('bağlanılamadı')), 'connection'),
            (APIConnectionError('sadece sınıf adı'), 'connection'),
            (APITimeoutError('sadece sınıf adı'), 'timeout'),
            (FakeAPIError(429), 'rate_limit'),
            (FakeAPIError(401), 'auth'),
            (FakeAPIError(403), 'auth'),
            (FakeAPIError(400), 'bad_request'),
            (FakeAPIError(503), 'server'),
            (RuntimeError('beklenmeyen'), 'unknown'),
        ]
        for exception, reason in cases:
            with self.subTest(reason), self.assertLogs('apps.phrases.ai', level='WARNING') as logs:
                error, create = self.generate(exception)
                self.assertIn(reason, logs.output[0])
                self.assertNotIn('test-key', logs.output[0])
                self.assertEqual(create.call_count, 1)   # API hatasında yeniden denenmez
                self.assertIsInstance(error, ai.AIError)
                self.assertEqual(error.reason, reason)
                self.assertTrue(error.user_message)
                self.assertNotIn('test-key', error.user_message)

    @override_settings(GEMINI_API_KEY='')
    def test_not_configured_raises_without_calling_the_model(self):
        error, create = self.generate([model_reply()])
        create.assert_not_called()
        self.assertIsInstance(error, ai.AINotConfigured)
        self.assertFalse(ai.is_configured())

    def test_invalid_input_is_rejected_before_calling_the_model(self):
        for phrase in ('', '   ', ' '.join(['w'] * (MAX_WORDS + 1)), 'a' * (ai.MAX_PHRASE_LENGTH + 1)):
            with self.subTest(phrase[:20]):
                error, create = self.generate([model_reply()], phrase=phrase)
                create.assert_not_called()
                self.assertEqual(error.reason, 'invalid_input')


@override_settings(GEMINI_API_KEY='test-key', AI_DAILY_LIMIT=3)
class QuotaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)

    def make(self, user=None, **kwargs):
        return AIGeneration.objects.create(user=user or self.user, prompt_text='x', model_name='m', **kwargs)

    def test_remaining_counts_only_todays_generations_of_the_user(self):
        other = User.objects.create_user('veli@example.com', PASSWORD)
        self.make()
        self.make(other)
        yesterday = self.make()
        AIGeneration.objects.filter(pk=yesterday.pk).update(created_at=timezone.now() - timedelta(days=1, hours=1))
        self.assertEqual(ai.generations_today(self.user), 1)
        self.assertEqual(ai.remaining_generations(self.user), 2)

    def test_remaining_never_goes_below_zero(self):
        for _ in range(5):
            self.make()
        self.assertEqual(ai.remaining_generations(self.user), 0)

    @override_settings(AI_DAILY_LIMIT=0)
    def test_zero_limit_means_no_generations(self):
        self.assertEqual(ai.remaining_generations(self.user), 0)

    def test_record_generation_stores_usage(self):
        result = ai.GeneratedPhrase('Break a leg', 'Bol şans', [], 'Hikaye', 10, 20, 30)
        record = ai.record_generation(self.user, result)
        self.assertEqual((record.input_tokens, record.output_tokens, record.thought_tokens), (10, 20, 30))
        self.assertEqual(record.prompt_text, 'Break a leg')


def fake_generation(phrase='Break a leg'):
    words = phrase.split()
    hints = [f'ses{index}' for index in range(1, len(words) + 1)]
    return ai.GeneratedPhrase(
        phrase=' '.join(words),
        translation='Bol şans',
        word_breakdown=[
            {'order': index, 'original_word': word, 'sound_hint': hint}
            for index, (word, hint) in enumerate(zip(words, hints), start=1)
        ],
        association_story='Komik bir hikaye.',
        input_tokens=100, output_tokens=50, thought_tokens=20,
    )


@override_settings(GEMINI_API_KEY='test-key', AI_DAILY_LIMIT=3)
class AIViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)
        self.url = reverse('phrase_create_ai')
        self.save_url = reverse('phrase_create_ai_save')

    def generate_patch(self, **kwargs):
        return mock.patch('apps.phrases.ai.generate_phrase', **kwargs)

    # -- seçim ve giriş sayfaları --

    def test_chooser_shows_both_options(self):
        response = self.client.get(reverse('phrase_create'))
        self.assertContains(response, reverse('phrase_create_manual'))
        self.assertContains(response, reverse('phrase_create_ai'))
        self.assertNotContains(response, 'yapılandırılmamış')

    @override_settings(GEMINI_API_KEY='')
    def test_chooser_disables_ai_when_not_configured(self):
        response = self.client.get(reverse('phrase_create'))
        self.assertContains(response, reverse('phrase_create_manual'))
        self.assertNotContains(response, f'href="{reverse("phrase_create_ai")}"')
        self.assertContains(response, 'yapılandırılmamış')

    def test_input_page_shows_remaining_quota(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Bugün kalan hak: 3 / 3')

    # -- üretim --

    def test_successful_generation_shows_an_editable_preview_without_saving(self):
        with self.generate_patch(return_value=fake_generation()) as generate:
            response = self.client.post(self.url, {'original_phrase': '  Break   a leg '})
        generate.assert_called_once_with('Break a leg')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'AI tarafından üretildi')
        self.assertContains(response, f'action="{self.save_url}"')
        self.assertContains(response, 'Yeniden üret')
        self.assertContains(response, 'Bugün kalan hak: 2')
        content = response.content.decode()
        for text in ('value="Break a leg"', 'value="Bol şans"', 'Komik bir hikaye.'):
            self.assertIn(text, content)
        positions = [content.index(f'value="{value}"') for value in ('Break', 'ses1', 'ses2', 'ses3')]
        self.assertEqual(positions, sorted(positions))
        self.assertFalse(Phrase.objects.exists())
        record = AIGeneration.objects.get()
        self.assertEqual((record.user, record.input_tokens, record.output_tokens, record.thought_tokens),
                         (self.user, 100, 50, 20))

    def test_invalid_input_never_reaches_the_model(self):
        too_many_words = ' '.join(['kelime'] * (MAX_WORDS + 1))
        for phrase in ('', '   ', too_many_words, 'a' * 301):
            with self.subTest(phrase[:15]), self.generate_patch() as generate:
                response = self.client.post(self.url, {'original_phrase': phrase})
                self.assertEqual(response.status_code, 200)
                generate.assert_not_called()
        self.assertFalse(AIGeneration.objects.exists())

    def test_ai_error_is_shown_and_does_not_use_quota(self):
        with self.generate_patch(side_effect=ai.AIError('AI servisi şu an çok yoğun.', 'rate_limit')):
            response = self.client.post(self.url, {'original_phrase': 'Break a leg'})
        self.assertContains(response, 'AI servisi şu an çok yoğun.')
        self.assertContains(response, reverse('phrase_create_manual'))   # manuel yol açık kalır
        self.assertFalse(AIGeneration.objects.exists())
        self.assertContains(response, 'Bugün kalan hak: 3 / 3')

    def test_daily_limit_blocks_generation(self):
        for _ in range(3):
            AIGeneration.objects.create(user=self.user, prompt_text='x', model_name='m')
        with self.generate_patch() as generate:
            response = self.client.post(self.url, {'original_phrase': 'Break a leg'})
        generate.assert_not_called()
        self.assertContains(response, 'Bugünlük AI üretim hakkın doldu')
        self.assertEqual(AIGeneration.objects.count(), 3)

    def test_limit_is_per_user(self):
        other = User.objects.create_user('veli@example.com', PASSWORD)
        for _ in range(3):
            AIGeneration.objects.create(user=other, prompt_text='x', model_name='m')
        with self.generate_patch(return_value=fake_generation()) as generate:
            self.client.post(self.url, {'original_phrase': 'Break a leg'})
        generate.assert_called_once()

    @override_settings(GEMINI_API_KEY='')
    def test_post_without_api_key_is_rejected_gracefully(self):
        with self.generate_patch() as generate:
            response = self.client.post(self.url, {'original_phrase': 'Break a leg'})
        generate.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'yapılandırılmamış')

    def test_regenerating_uses_one_more_generation_each_time(self):
        with self.generate_patch(return_value=fake_generation()):
            self.client.post(self.url, {'original_phrase': 'Break a leg'})
            response = self.client.post(self.url, {
                'original_phrase': 'Break a leg', 'translation': 'düzenlenmiş', 'association_story': 'x',
                'original_word': ['Break'], 'sound_hint': ['bozuk'],   # önizleme formunun diğer alanları yok sayılır
            })
        self.assertContains(response, 'Bugün kalan hak: 1')
        self.assertEqual(AIGeneration.objects.count(), 2)

    # -- kaydetme --

    def save_data(self, **overrides):
        data = {
            'original_phrase': 'Break a leg',
            'translation': 'Bol şans',
            'association_story': 'Komik bir hikaye.',
            'original_word': ['Break', 'a', 'leg'],
            'sound_hint': ['Bırak', 'Ey', 'Lig'],
        }
        data.update(overrides)
        return data

    def test_saving_creates_an_ai_generated_phrase_with_progress(self):
        response = self.client.post(self.save_url, self.save_data())
        phrase = Phrase.objects.get()
        self.assertRedirects(response, reverse('phrase_detail', args=[phrase.pk]))
        self.assertEqual(phrase.user, self.user)
        self.assertEqual(phrase.source, Phrase.Source.AI_GENERATED)
        self.assertEqual(phrase.word_breakdown, [
            {'order': 1, 'original_word': 'Break', 'sound_hint': 'Bırak'},
            {'order': 2, 'original_word': 'a', 'sound_hint': 'Ey'},
            {'order': 3, 'original_word': 'leg', 'sound_hint': 'Lig'},
        ])
        self.assertEqual(PhraseProgress.objects.get().status, PhraseProgress.Status.LEARNING)

    def test_saving_keeps_the_users_edits_and_ignores_client_order_values(self):
        data = self.save_data(translation='Başarılar', order=['3', '2', '1'],
                              original_word=['Break', 'leg'], sound_hint=['Kır', 'Bacak'])
        self.client.post(self.save_url, data)
        phrase = Phrase.objects.get()
        self.assertEqual(phrase.translation, 'Başarılar')
        self.assertEqual([item['order'] for item in phrase.word_breakdown], [1, 2])
        self.assertEqual([item['sound_hint'] for item in phrase.word_breakdown], ['Kır', 'Bacak'])

    def test_saving_does_not_use_quota(self):
        self.client.post(self.save_url, self.save_data())
        self.assertFalse(AIGeneration.objects.exists())

    def test_invalid_save_rerenders_the_preview_with_errors_and_saves_nothing(self):
        response = self.client.post(self.save_url, self.save_data(sound_hint=['Bırak', '', 'Lig']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2. satırda ses karşılığı boş olamaz')
        self.assertContains(response, 'AI tarafından üretildi')
        self.assertContains(response, 'value="Bırak"')   # kullanıcının girdisi korunur
        self.assertFalse(Phrase.objects.exists())

    def test_save_via_get_redirects_to_the_input_page(self):
        self.assertRedirects(self.client.get(self.save_url), self.url)

    # -- erişim --

    def test_anonymous_users_are_redirected_to_login(self):
        anonymous = Client()
        for url in (reverse('phrase_create'), reverse('phrase_create_manual'), self.url, self.save_url):
            with self.subTest(url):
                self.assertRedirects(anonymous.get(url), f"{reverse('login')}?next={url}")
        with self.generate_patch() as generate:
            response = anonymous.post(self.url, {'original_phrase': 'Break a leg'})
            self.assertEqual(response.status_code, 302)
            generate.assert_not_called()
        self.assertEqual(anonymous.post(self.save_url, self.save_data()).status_code, 302)
        self.assertFalse(Phrase.objects.exists())
