"""Çoklu hedef dil desteği: dil kayıt defteri (languages.py), aktif dil oturumu, dile göre filtreleme
ve dillerin birbirine karışmadığının (ayrı desteler) doğrulanması."""

import re
from unittest import mock

from django.contrib.sessions.middleware import SessionMiddleware
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.users.models import User

from . import ai, languages
from .language_state import get_active_language, set_active_language
from .models import Phrase, PhraseProgress
from .services import get_progress_summary, get_source_counts, get_study_queue
from .test_ai import fake_generation
from .test_ai_auto import fake_auto
from .tests import form_data, make_phrase

PASSWORD = 'gizli-parola-123'
LOCALE_RE = re.compile(r'^[a-z]{2}-[A-Z]{2}$')


class LanguageRegistryTests(TestCase):
    """Kayıt defterinin her girdisi eksiksiz olmalı: yeni bir dil eklenirken bir şey unutulmasın."""

    def test_at_most_a_handful_of_languages_are_registered(self):
        # Kullanıcı en fazla birkaç dil istiyor (8'i geçmez); bu bir üst sınır değil, bir hatırlatma.
        self.assertLessEqual(len(languages.TARGET_LANGUAGES), 8)

    def test_default_language_is_registered(self):
        self.assertIn(languages.DEFAULT_LANGUAGE_CODE, languages.TARGET_LANGUAGES)

    def test_every_language_has_a_name_and_a_valid_speech_locale(self):
        for code, language in languages.TARGET_LANGUAGES.items():
            with self.subTest(code):
                self.assertEqual(language.code, code)
                self.assertTrue(language.name.strip())
                self.assertRegex(language.speech_locale, LOCALE_RE)

    def test_every_language_has_at_least_one_complete_example(self):
        for code, language in languages.TARGET_LANGUAGES.items():
            with self.subTest(code):
                self.assertGreaterEqual(len(language.examples), 1)
                for example in language.examples:
                    self.assertTrue(example.phrase.strip())
                    self.assertTrue(example.translation.strip())
                    self.assertTrue(example.story.strip())
                    self.assertGreaterEqual(len(example.words), 1)
                    for word in example.words:
                        self.assertTrue(word.word.strip())
                        self.assertTrue(word.hint.strip())

    def test_example_phrases_are_derived_from_examples(self):
        for language in languages.TARGET_LANGUAGES.values():
            self.assertEqual(language.example_phrases, tuple(example.phrase for example in language.examples))

    def test_choices_lists_every_language_by_code(self):
        self.assertEqual(languages.choices(), [(code, lang.name) for code, lang in languages.TARGET_LANGUAGES.items()])

    def test_get_returns_none_for_an_unknown_code(self):
        self.assertIsNone(languages.get('xx'))
        self.assertIs(languages.get('xx', languages.TARGET_LANGUAGES['en']), languages.TARGET_LANGUAGES['en'])


class LanguageStateTests(TestCase):
    """Aktif dilin oturumdaki seçim mantığı (bkz. language_state.py)."""

    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.factory = RequestFactory()

    def request(self):
        request = self.factory.get('/')
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        request.user = self.user
        return request

    def test_defaults_to_the_registrys_default_language_with_no_session_or_phrases(self):
        self.assertEqual(get_active_language(self.request()), languages.DEFAULT_LANGUAGE_CODE)

    def test_falls_back_to_the_language_of_the_most_recently_added_phrase(self):
        make_phrase(self.user, original_phrase='Old one', target_language='en')
        make_phrase(self.user, original_phrase='Nueva', target_language='es')
        self.assertEqual(get_active_language(self.request()), 'es')

    def test_session_choice_overrides_the_phrase_based_fallback(self):
        make_phrase(self.user, original_phrase='Nueva', target_language='es')
        request = self.request()
        set_active_language(request, 'en')
        self.assertEqual(get_active_language(request), 'en')

    def test_setting_an_unknown_language_is_rejected(self):
        with self.assertRaises(ValueError):
            set_active_language(self.request(), 'xx')


class SetLanguageViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)

    def test_switching_updates_the_session_and_redirects_to_next(self):
        response = self.client.post(reverse('set_language', args=['es']), {'next': reverse('phrase_list')})
        self.assertRedirects(response, reverse('phrase_list'))
        self.assertEqual(self.client.session['study_language'], 'es')

    def test_missing_next_redirects_home(self):
        response = self.client.post(reverse('set_language', args=['en']))
        self.assertRedirects(response, reverse('home'))

    def test_an_external_next_is_ignored_to_avoid_an_open_redirect(self):
        response = self.client.post(reverse('set_language', args=['en']), {'next': 'https://evil.example/'})
        self.assertRedirects(response, reverse('home'))

    def test_unknown_language_is_404(self):
        self.assertEqual(self.client.post(reverse('set_language', args=['xx'])).status_code, 404)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(reverse('set_language', args=['en'])).status_code, 405)

    def test_anonymous_is_redirected_to_login(self):
        url = reverse('set_language', args=['en'])
        self.assertRedirects(Client().post(url), f"{reverse('login')}?next={url}")


class ServiceFilteringTests(TestCase):
    """Kuyruk, özet ve kaynak sayıları hedef dile göre ayrılır; diller birbirine karışmaz."""

    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.en = make_phrase(self.user, original_phrase='Break a leg', target_language='en')
        self.es = make_phrase(
            self.user, original_phrase='Dar en el clavo', target_language='es', source=Phrase.Source.AI_GENERATED,
        )

    def test_study_queue_only_returns_the_requested_languages_phrases(self):
        self.assertEqual([item.phrase_id for item in get_study_queue(self.user, 'en')], [self.en.pk])
        self.assertEqual([item.phrase_id for item in get_study_queue(self.user, 'es')], [self.es.pk])

    def test_progress_summary_counts_are_scoped_to_the_language(self):
        PhraseProgress.objects.filter(phrase=self.es).update(status=PhraseProgress.Status.LEARNED, review_streak=3)
        en_summary = get_progress_summary(self.user, 'en')
        es_summary = get_progress_summary(self.user, 'es')
        self.assertEqual((en_summary['total'], en_summary['learned']), (1, 0))
        self.assertEqual((es_summary['total'], es_summary['learned']), (1, 1))

    def test_source_counts_are_scoped_to_the_language(self):
        self.assertEqual(get_source_counts(self.user, 'en'), {'manual': 1, 'ai_generated': 0})
        self.assertEqual(get_source_counts(self.user, 'es'), {'manual': 0, 'ai_generated': 1})


@override_settings(GEMINI_API_KEY='test-key')
class ViewIntegrationTests(TestCase):
    """Kartlar/Phrase'lerim/İstatistik ekranlarının ve ekleme akışlarının dile göre davranışı."""

    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)

    def test_switcher_shows_every_registered_language_and_marks_the_active_one(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'lang-switch')
        self.assertContains(response, '<button type="submit" class="lang-pill is-active" aria-current="true">İngilizce</button>', html=True)
        self.assertContains(response, '<button type="submit" class="lang-pill">İspanyolca</button>', html=True)

    def test_switcher_is_hidden_when_only_one_language_is_registered(self):
        from django.template import Context, Template
        template = Template("{% include 'includes/language_switcher.html' %}")
        html = template.render(Context({
            'target_languages': {'en': languages.TARGET_LANGUAGES['en']}, 'active_language': 'en', 'request': None,
        }))
        self.assertNotIn('lang-switch', html)

    def test_home_and_list_only_show_the_active_languages_cards(self):
        make_phrase(self.user, original_phrase='Break a leg', target_language='en')
        make_phrase(self.user, original_phrase='Dar en el clavo', target_language='es')

        self.client.post(reverse('set_language', args=['en']))
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Break a leg')
        self.assertNotContains(response, 'Dar en el clavo')

        self.client.post(reverse('set_language', args=['es']))
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Dar en el clavo')
        self.assertNotContains(response, 'Break a leg')

        response = self.client.get(reverse('phrase_list'))
        self.assertContains(response, 'Dar en el clavo')
        self.assertNotContains(response, 'Break a leg')

    def test_speak_button_uses_the_phrases_own_locale_not_the_active_language(self):
        make_phrase(self.user, original_phrase='Break a leg', target_language='en')
        make_phrase(self.user, original_phrase='Dar en el clavo', target_language='es')

        self.client.post(reverse('set_language', args=['es']))
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'data-speak-lang="es-ES"')
        self.assertNotContains(response, 'data-speak-lang="en-US"')

    def test_manual_create_tags_the_chosen_language_and_makes_it_active(self):
        self.client.post(reverse('set_language', args=['en']))
        data = form_data(target_language='es', original_phrase='Dar en el clavo',
                          words=('Dar', 'en', 'el', 'clavo'), hints=('dar', 'en', 'el', 'klavye'))
        response = self.client.post(reverse('phrase_create_manual'), data)
        phrase = Phrase.objects.get()
        self.assertRedirects(response, reverse('phrase_detail', args=[phrase.pk]))
        self.assertEqual(phrase.target_language, 'es')
        self.assertEqual(self.client.session['study_language'], 'es')

    def test_manual_form_defaults_the_language_field_to_the_active_language(self):
        self.client.post(reverse('set_language', args=['es']))
        response = self.client.get(reverse('phrase_create_manual'))
        self.assertContains(response, '<input type="hidden" name="target_language" value="es" id="id_target_language">', html=True)
        # Dil ayrıca sorulmaz: görünür bir seçim kutusu yok, yalnızca üstteki dil anahtarı kullanılır.
        self.assertNotContains(response, '<select name="target_language"')

    def test_ai_given_phrase_flow_never_asks_and_uses_the_active_language(self):
        self.client.post(reverse('set_language', args=['es']))
        response_get = self.client.get(reverse('phrase_create_ai'))
        self.assertNotContains(response_get, 'name="target_language"')   # dil ayrıca sorulmaz

        with mock.patch('apps.phrases.ai.generate_phrase', return_value=fake_generation('Dar en el clavo')) as generate:
            response = self.client.post(reverse('phrase_create_ai'), {'original_phrase': 'Dar en el clavo'})
        generate.assert_called_once_with('Dar en el clavo', 'es')
        self.assertContains(response, 'name="target_language" value="es"')

        save_data = {
            'target_language': 'es', 'original_phrase': 'Dar en el clavo', 'translation': 'Tam on ikiden vurmak',
            'example_sentence': 'Con esa respuesta, diste en el clavo.',
            'example_sentence_translation': 'O cevapla tam on ikiden vurdun.',
            'association_story': 'Hikaye.', 'original_word': ['Dar', 'en', 'el', 'clavo'],
            'sound_hint': ['ses1', 'ses2', 'ses3', 'ses4'],
        }
        response = self.client.post(reverse('phrase_create_ai_save'), save_data)
        phrase = Phrase.objects.get()
        self.assertRedirects(response, reverse('phrase_detail', args=[phrase.pk]))
        self.assertEqual(phrase.target_language, 'es')
        self.assertEqual(self.client.session['study_language'], 'es')

    def test_auto_mode_never_asks_and_only_avoids_phrases_in_the_same_language(self):
        make_phrase(self.user, original_phrase='Break a leg', target_language='en')
        make_phrase(self.user, original_phrase='Ya conocida', target_language='es')
        self.client.post(reverse('set_language', args=['es']))

        response_get = self.client.get(reverse('phrase_create_ai_auto'))
        self.assertNotContains(response_get, 'name="target_language"')   # dil ayrıca sorulmaz

        with mock.patch('apps.phrases.ai.generate_auto_phrase', return_value=fake_auto('Nueva frase')) as generate:
            self.client.post(reverse('phrase_create_ai_auto'), {'category': 'idiom'})
        (category, language_code, avoid), _ = generate.call_args
        self.assertEqual((category, language_code), ('idiom', 'es'))
        self.assertIn('Ya conocida', avoid)
        self.assertNotIn('Break a leg', avoid)

    def test_ai_record_generation_stores_the_active_language(self):
        self.client.post(reverse('set_language', args=['es']))
        with mock.patch('apps.phrases.ai.generate_phrase', return_value=fake_generation('Dar en el clavo')):
            self.client.post(reverse('phrase_create_ai'), {'original_phrase': 'Dar en el clavo'})
        from .models import AIGeneration
        self.assertEqual(AIGeneration.objects.get().target_language, 'es')

    def test_regenerating_keeps_using_the_same_active_language_even_if_it_changes_meanwhile(self):
        """Önizlemedeki gizli target_language alanı yalnızca kaydederken kullanılır; yeniden üretme oturumdaki
        güncel aktif dili kullanır (iki farklı sekmede farklı diller açıksa bu böyle davranması beklenir)."""
        self.client.post(reverse('set_language', args=['es']))
        with mock.patch('apps.phrases.ai.generate_phrase', return_value=fake_generation('Dar en el clavo')):
            self.client.post(reverse('phrase_create_ai'), {'original_phrase': 'Dar en el clavo'})

        self.client.post(reverse('set_language', args=['en']))
        with mock.patch('apps.phrases.ai.generate_phrase', return_value=fake_generation('Break a leg')) as generate:
            self.client.post(reverse('phrase_create_ai'), {'original_phrase': 'Break a leg'})
        generate.assert_called_once_with('Break a leg', 'en')

    def test_stats_page_counts_only_the_active_languages_phrases(self):
        make_phrase(self.user, original_phrase='Break a leg', target_language='en')
        make_phrase(self.user, original_phrase='Dar en el clavo', target_language='es')
        make_phrase(self.user, original_phrase='Tirar la toalla', target_language='es')

        self.client.post(reverse('set_language', args=['en']))
        response = self.client.get(reverse('stats'))
        self.assertContains(response, '0</strong> / 1 phrase kalıcı öğrenildi')

        self.client.post(reverse('set_language', args=['es']))
        response = self.client.get(reverse('stats'))
        self.assertContains(response, '0</strong> / 2 phrase kalıcı öğrenildi')
