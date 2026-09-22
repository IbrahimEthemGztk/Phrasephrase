from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.users.models import User

from .models import Phrase, PhraseProgress
from .validators import MAX_WORDS, build_word_breakdown, validate_word_breakdown

PASSWORD = 'gizli-parola-123'


def breakdown(*pairs):
    return [
        {'order': index, 'original_word': word, 'sound_hint': hint}
        for index, (word, hint) in enumerate(pairs, start=1)
    ]


def form_data(words=('Break', 'a', 'leg'), hints=('breyk', 'ey', 'leg'), **overrides):
    data = {
        'target_language': 'en',
        'original_phrase': 'Break a leg',
        'translation': 'Bol şans',
        'example_sentence': 'Break a leg tonight.',
        'example_sentence_translation': 'Bu gece bol şanslar.',
        'association_story': 'Bir bacağı kırıp bol şans diledi.',
        'original_word': list(words),
        'sound_hint': list(hints),
    }
    data.update(overrides)
    return data


def make_phrase(user, **kwargs):
    defaults = {
        'original_phrase': 'Break a leg',
        'translation': 'Bol şans',
        'word_breakdown': breakdown(('Break', 'breyk'), ('a', 'ey'), ('leg', 'leg')),
        'association_story': 'Hikaye',
    }
    defaults.update(kwargs)
    return Phrase.objects.create(user=user, **defaults)


class BreakdownValidatorTests(TestCase):
    def test_build_assigns_order_from_row_position(self):
        result = build_word_breakdown(['How', 'are', 'you'], ['hau', 'ar', 'yu'])
        self.assertEqual(result, breakdown(('How', 'hau'), ('are', 'ar'), ('you', 'yu')))

    def test_build_strips_whitespace_and_drops_trailing_blank_rows(self):
        result = build_word_breakdown(['  How ', '', ''], [' hau  ', '', ' '])
        self.assertEqual(result, breakdown(('How', 'hau')))

    def test_build_rejects_mismatched_lengths(self):
        with self.assertRaises(ValidationError):
            build_word_breakdown(['a', 'b'], ['x'])

    def test_validate_accepts_valid_breakdown(self):
        validate_word_breakdown(breakdown(('a', 'x'), ('b', 'y')))

    def test_validate_rejects_empty_and_non_list(self):
        for value in ([], None, {}, 'text'):
            with self.assertRaises(ValidationError):
                validate_word_breakdown(value)

    def test_validate_rejects_broken_order(self):
        value = breakdown(('a', 'x'), ('b', 'y'))
        value[0]['order'], value[1]['order'] = 2, 1
        with self.assertRaises(ValidationError):
            validate_word_breakdown(value)

    def test_validate_rejects_missing_or_extra_keys(self):
        with self.assertRaises(ValidationError):
            validate_word_breakdown([{'order': 1, 'original_word': 'a'}])
        with self.assertRaises(ValidationError):
            validate_word_breakdown([{'order': 1, 'original_word': 'a', 'sound_hint': 'x', 'extra': 1}])

    def test_validate_rejects_blank_text_and_too_many_words(self):
        with self.assertRaises(ValidationError):
            validate_word_breakdown(breakdown(('a', ' ')))
        with self.assertRaises(ValidationError):
            validate_word_breakdown(breakdown(*[('w', 'h')] * (MAX_WORDS + 1)))


class PhraseModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)

    def test_saving_phrase_creates_learning_progress(self):
        phrase = make_phrase(self.user)
        progress = PhraseProgress.objects.get(phrase=phrase)
        self.assertEqual(progress.user, self.user)
        self.assertEqual(progress.status, PhraseProgress.Status.LEARNING)
        self.assertEqual((progress.swipe_left_count, progress.swipe_right_count), (0, 0))

    def test_resaving_phrase_does_not_duplicate_progress(self):
        phrase = make_phrase(self.user)
        phrase.translation = 'Başarılar'
        phrase.save()
        self.assertEqual(PhraseProgress.objects.filter(phrase=phrase).count(), 1)

    def test_progress_is_unique_per_user_and_phrase(self):
        phrase = make_phrase(self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PhraseProgress.objects.create(user=self.user, phrase=phrase)

    def test_source_defaults_to_manual(self):
        self.assertEqual(make_phrase(self.user).source, Phrase.Source.MANUAL)

    def test_deleting_phrase_deletes_progress(self):
        phrase = make_phrase(self.user)
        phrase.delete()
        self.assertFalse(PhraseProgress.objects.exists())


class PhraseCreateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)
        self.url = reverse('phrase_create_manual')

    def test_create_saves_breakdown_in_row_order(self):
        response = self.client.post(self.url, form_data())
        phrase = Phrase.objects.get()
        self.assertRedirects(response, reverse('phrase_detail', args=[phrase.pk]))
        self.assertEqual(phrase.user, self.user)
        self.assertEqual(phrase.source, Phrase.Source.MANUAL)
        self.assertEqual(phrase.word_breakdown, breakdown(('Break', 'breyk'), ('a', 'ey'), ('leg', 'leg')))
        self.assertEqual(PhraseProgress.objects.get().status, PhraseProgress.Status.LEARNING)

    def test_client_supplied_order_values_are_ignored(self):
        data = form_data(order=['3', '2', '1'])
        self.client.post(self.url, data)
        orders = [item['order'] for item in Phrase.objects.get().word_breakdown]
        words = [item['original_word'] for item in Phrase.objects.get().word_breakdown]
        self.assertEqual(orders, [1, 2, 3])
        self.assertEqual(words, ['Break', 'a', 'leg'])

    def test_trailing_blank_rows_are_dropped(self):
        self.client.post(self.url, form_data(words=('Break', 'leg', ''), hints=('breyk', 'leg', '')))
        self.assertEqual(len(Phrase.objects.get().word_breakdown), 2)

    def test_row_with_only_a_word_is_rejected(self):
        response = self.client.post(self.url, form_data(words=('Break', 'leg'), hints=('breyk', '')))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2. satırda ses karşılığı boş olamaz')
        self.assertFalse(Phrase.objects.exists())

    def test_blank_row_in_the_middle_is_rejected(self):
        response = self.client.post(self.url, form_data(words=('Break', '', 'leg'), hints=('breyk', '', 'leg')))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2. satırda kelime boş olamaz')
        self.assertFalse(Phrase.objects.exists())

    def test_no_rows_is_rejected(self):
        response = self.client.post(self.url, form_data(words=('',), hints=('',)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'En az bir kelime')
        self.assertFalse(Phrase.objects.exists())

    def test_too_many_rows_is_rejected(self):
        words = [f'w{i}' for i in range(MAX_WORDS + 1)]
        response = self.client.post(self.url, form_data(words=words, hints=words))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Phrase.objects.exists())

    def test_mismatched_word_and_hint_lists_are_rejected(self):
        response = self.client.post(self.url, form_data(words=('a', 'b'), hints=('x',)))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Phrase.objects.exists())

    def test_missing_required_fields_are_rejected(self):
        response = self.client.post(self.url, form_data(original_phrase='', translation=''))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Phrase.objects.exists())

    def test_invalid_submission_keeps_entered_rows(self):
        response = self.client.post(self.url, form_data(words=('Break', 'leg'), hints=('breyk', '')))
        self.assertContains(response, 'value="Break"')
        self.assertContains(response, 'value="breyk"')

    def test_form_page_renders_one_empty_row(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-split')
        self.assertEqual(len(response.context['form'].rows), 1)


class PhraseUpdateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)
        self.phrase = make_phrase(self.user)
        self.url = reverse('phrase_update', args=[self.phrase.pk])

    def test_edit_form_is_prefilled_in_saved_order(self):
        response = self.client.get(self.url)
        self.assertEqual(
            [row['original_word'] for row in response.context['form'].rows], ['Break', 'a', 'leg'],
        )

    def test_update_replaces_breakdown_and_keeps_new_order(self):
        data = form_data(words=('leg', 'Break'), hints=('leg', 'breyk'), translation='Başarılar')
        response = self.client.post(self.url, data)
        self.assertRedirects(response, reverse('phrase_detail', args=[self.phrase.pk]))
        self.phrase.refresh_from_db()
        self.assertEqual(self.phrase.translation, 'Başarılar')
        self.assertEqual(self.phrase.word_breakdown, breakdown(('leg', 'leg'), ('Break', 'breyk')))

    def test_update_does_not_duplicate_progress(self):
        self.client.post(self.url, form_data())
        self.assertEqual(PhraseProgress.objects.filter(phrase=self.phrase).count(), 1)

    def test_invalid_update_does_not_change_phrase(self):
        self.client.post(self.url, form_data(words=('',), hints=('',), translation='Değişti'))
        self.phrase.refresh_from_db()
        self.assertEqual(self.phrase.translation, 'Bol şans')
        self.assertEqual(len(self.phrase.word_breakdown), 3)


class PhraseDetailAndDeleteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)
        self.phrase = make_phrase(self.user)

    def test_detail_shows_words_and_hints_in_order(self):
        content = self.client.get(reverse('phrase_detail', args=[self.phrase.pk])).content.decode()
        positions = [content.index(text) for text in ('>Break<', '>breyk<', '>a<', '>ey<', '>leg<')]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('Hikaye', content)

    def test_delete_get_asks_for_confirmation_without_deleting(self):
        response = self.client.get(reverse('phrase_delete', args=[self.phrase.pk]))
        self.assertContains(response, 'silinsin mi')
        self.assertTrue(Phrase.objects.filter(pk=self.phrase.pk).exists())

    def test_delete_post_removes_phrase_and_progress(self):
        response = self.client.post(reverse('phrase_delete', args=[self.phrase.pk]))
        self.assertRedirects(response, reverse('phrase_list'))
        self.assertFalse(Phrase.objects.exists())
        self.assertFalse(PhraseProgress.objects.exists())


class PhraseListTests(TestCase):
    def test_list_shows_only_own_phrases(self):
        me = User.objects.create_user('ali@example.com', PASSWORD)
        other = User.objects.create_user('veli@example.com', PASSWORD)
        make_phrase(me, original_phrase='Benim cümlem')
        make_phrase(other, original_phrase='Başkasının cümlesi')
        self.client.force_login(me)
        response = self.client.get(reverse('phrase_list'))
        self.assertContains(response, 'Benim cümlem')
        self.assertNotContains(response, 'Başkasının cümlesi')

    def test_home_shows_empty_state_without_phrases(self):
        self.client.force_login(User.objects.create_user('ali@example.com', PASSWORD))
        self.assertContains(self.client.get(reverse('home')), 'Henüz phrase')


class AccessControlTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('ali@example.com', PASSWORD)
        self.intruder = User.objects.create_user('veli@example.com', PASSWORD)
        self.phrase = make_phrase(self.owner)

    def test_anonymous_users_are_redirected_to_login(self):
        urls = [
            reverse('phrase_create'),
            reverse('phrase_detail', args=[self.phrase.pk]),
            reverse('phrase_update', args=[self.phrase.pk]),
            reverse('phrase_delete', args=[self.phrase.pk]),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertRedirects(response, f"{reverse('login')}?next={url}", msg_prefix=url)

    def test_other_users_get_404_and_cannot_modify(self):
        self.client.force_login(self.intruder)
        for name in ('phrase_detail', 'phrase_update', 'phrase_delete'):
            url = reverse(name, args=[self.phrase.pk])
            self.assertEqual(self.client.get(url).status_code, 404, name)

        self.assertEqual(self.client.post(reverse('phrase_update', args=[self.phrase.pk]), form_data()).status_code, 404)
        self.assertEqual(self.client.post(reverse('phrase_delete', args=[self.phrase.pk])).status_code, 404)
        self.assertTrue(Phrase.objects.filter(pk=self.phrase.pk).exists())
        self.phrase.refresh_from_db()
        self.assertEqual(self.phrase.translation, 'Bol şans')
