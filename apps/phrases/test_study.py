from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.users.models import User

from .models import PhraseProgress
from .services import STUDY_QUEUE_LIMIT, get_study_queue
from .tests import make_phrase

PASSWORD = 'gizli-parola-123'


def progress_of(phrase):
    return PhraseProgress.objects.get(phrase=phrase)


def set_progress(phrase, **fields):
    PhraseProgress.objects.filter(phrase=phrase).update(**fields)


class StudyQueueTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)

    def queue_titles(self, user=None):
        return [item.phrase.original_phrase for item in get_study_queue(user or self.user)]

    def test_seen_cards_come_first_oldest_review_first_then_unseen_by_creation(self):
        now = timezone.now()
        make_phrase(self.user, original_phrase='A yeni-1')
        b = make_phrase(self.user, original_phrase='B görülmüş-yeni')
        c = make_phrase(self.user, original_phrase='C görülmüş-eski')
        make_phrase(self.user, original_phrase='E yeni-2')
        set_progress(b, swipe_left_count=1, last_reviewed_at=now - timedelta(minutes=5))
        set_progress(c, swipe_left_count=2, last_reviewed_at=now - timedelta(hours=2))

        self.assertEqual(
            self.queue_titles(), ['C görülmüş-eski', 'B görülmüş-yeni', 'A yeni-1', 'E yeni-2'],
        )

    def test_learned_cards_are_excluded(self):
        learned = make_phrase(self.user, original_phrase='Öğrenilmiş')
        make_phrase(self.user, original_phrase='Öğreniliyor')
        set_progress(learned, status=PhraseProgress.Status.LEARNED, swipe_right_count=1)
        self.assertEqual(self.queue_titles(), ['Öğreniliyor'])

    def test_other_users_cards_are_excluded(self):
        other = User.objects.create_user('veli@example.com', PASSWORD)
        make_phrase(self.user, original_phrase='Benim')
        make_phrase(other, original_phrase='Onun')
        self.assertEqual(self.queue_titles(), ['Benim'])

    def test_queue_is_limited(self):
        for index in range(STUDY_QUEUE_LIMIT + 5):
            make_phrase(self.user, original_phrase=f'Phrase {index}')
        self.assertEqual(len(get_study_queue(self.user)), STUDY_QUEUE_LIMIT)


class SwipeEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)
        self.phrase = make_phrase(self.user)
        self.url = reverse('phrase_swipe', args=[self.phrase.pk])

    def test_swipe_right_marks_learned(self):
        response = self.client.post(self.url, {'direction': 'right'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'learned')
        progress = progress_of(self.phrase)
        self.assertEqual(progress.status, PhraseProgress.Status.LEARNED)
        self.assertEqual((progress.swipe_right_count, progress.swipe_left_count), (1, 0))
        self.assertIsNotNone(progress.last_reviewed_at)

    def test_swipe_left_keeps_learning_and_counts_up(self):
        self.client.post(self.url, {'direction': 'left'})
        response = self.client.post(self.url, {'direction': 'left'})
        self.assertEqual(response.json()['swipe_left_count'], 2)
        progress = progress_of(self.phrase)
        self.assertEqual(progress.status, PhraseProgress.Status.LEARNING)
        self.assertEqual((progress.swipe_left_count, progress.swipe_right_count), (2, 0))
        self.assertIsNotNone(progress.last_reviewed_at)

    def test_invalid_or_missing_direction_is_rejected(self):
        for data in ({'direction': 'up'}, {}):
            self.assertEqual(self.client.post(self.url, data).status_code, 400)
        progress = progress_of(self.phrase)
        self.assertEqual((progress.swipe_left_count, progress.swipe_right_count), (0, 0))

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_anonymous_gets_401_json_instead_of_redirect(self):
        response = Client().post(self.url, {'direction': 'right'})
        self.assertEqual(response.status_code, 401)
        self.assertIn('error', response.json())
        self.assertEqual(progress_of(self.phrase).status, PhraseProgress.Status.LEARNING)

    def test_other_users_phrase_is_404_and_unchanged(self):
        other = User.objects.create_user('veli@example.com', PASSWORD)
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url, {'direction': 'right'}).status_code, 404)
        progress = progress_of(self.phrase)
        self.assertEqual(progress.status, PhraseProgress.Status.LEARNING)
        self.assertEqual(progress.swipe_right_count, 0)

    def test_unknown_phrase_is_404(self):
        url = reverse('phrase_swipe', args=[999999])
        self.assertEqual(self.client.post(url, {'direction': 'right'}).status_code, 404)

    def test_csrf_is_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, {'direction': 'right'}).status_code, 403)
        self.assertEqual(progress_of(self.phrase).swipe_right_count, 0)


class SwipeUndoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)
        self.phrase = make_phrase(self.user)
        self.swipe_url = reverse('phrase_swipe', args=[self.phrase.pk])
        self.undo_url = reverse('phrase_swipe_undo', args=[self.phrase.pk])

    def test_undo_right_returns_card_to_learning_and_unseen(self):
        self.client.post(self.swipe_url, {'direction': 'right'})
        response = self.client.post(self.undo_url, {'direction': 'right'})
        self.assertEqual(response.status_code, 200)
        progress = progress_of(self.phrase)
        self.assertEqual(progress.status, PhraseProgress.Status.LEARNING)
        self.assertEqual((progress.swipe_right_count, progress.swipe_left_count), (0, 0))
        self.assertIsNone(progress.last_reviewed_at)

    def test_undo_left_decrements_only_the_left_count(self):
        self.client.post(self.swipe_url, {'direction': 'left'})
        self.client.post(self.swipe_url, {'direction': 'left'})
        self.client.post(self.undo_url, {'direction': 'left'})
        progress = progress_of(self.phrase)
        self.assertEqual(progress.swipe_left_count, 1)
        self.assertIsNotNone(progress.last_reviewed_at)

    def test_undo_left_back_to_zero_makes_card_unseen_again(self):
        self.client.post(self.swipe_url, {'direction': 'left'})
        self.client.post(self.undo_url, {'direction': 'left'})
        self.assertIsNone(progress_of(self.phrase).last_reviewed_at)

    def test_undo_with_nothing_to_undo_is_409_and_never_goes_negative(self):
        for direction in ('right', 'left'):
            self.assertEqual(self.client.post(self.undo_url, {'direction': direction}).status_code, 409)
        self.client.post(self.swipe_url, {'direction': 'right'})
        self.client.post(self.undo_url, {'direction': 'right'})
        self.assertEqual(self.client.post(self.undo_url, {'direction': 'right'}).status_code, 409)
        progress = progress_of(self.phrase)
        self.assertEqual((progress.swipe_right_count, progress.swipe_left_count), (0, 0))

    def test_undo_right_requires_learned_status(self):
        set_progress(self.phrase, swipe_right_count=1)   # sayaç var ama kart öğrenilmiş değil
        self.assertEqual(self.client.post(self.undo_url, {'direction': 'right'}).status_code, 409)

    def test_invalid_direction_is_rejected(self):
        self.assertEqual(self.client.post(self.undo_url, {'direction': 'up'}).status_code, 400)

    def test_anonymous_and_other_users(self):
        self.assertEqual(Client().post(self.undo_url, {'direction': 'right'}).status_code, 401)
        self.client.post(self.swipe_url, {'direction': 'right'})
        self.client.force_login(User.objects.create_user('veli@example.com', PASSWORD))
        self.assertEqual(self.client.post(self.undo_url, {'direction': 'right'}).status_code, 404)
        self.assertEqual(progress_of(self.phrase).status, PhraseProgress.Status.LEARNED)

    def test_swipe_then_undo_restores_queue_position(self):
        second = make_phrase(self.user, original_phrase='İkinci')
        self.assertEqual([i.phrase_id for i in get_study_queue(self.user)], [self.phrase.pk, second.pk])
        self.client.post(self.swipe_url, {'direction': 'right'})
        self.assertEqual([i.phrase_id for i in get_study_queue(self.user)], [second.pk])
        self.client.post(self.undo_url, {'direction': 'right'})
        self.assertEqual([i.phrase_id for i in get_study_queue(self.user)], [self.phrase.pk, second.pk])


class CardsPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)

    def test_cards_are_rendered_in_queue_order_with_all_stages(self):
        make_phrase(self.user, original_phrase='Birinci cümle', association_story='Birinci hikaye')
        second = make_phrase(self.user, original_phrase='İkinci cümle', association_story='İkinci hikaye')
        set_progress(second, swipe_left_count=1, last_reviewed_at=timezone.now())

        response = self.client.get(reverse('home'))
        content = response.content.decode()
        self.assertLess(content.index('İkinci cümle'), content.index('Birinci cümle'))
        self.assertEqual(content.count('class="study-card"'), 2)
        for text in ('Sesli parçalama', 'Çağrışım hikayesi', 'İkinci hikaye', 'data-reveal', '>breyk<'):
            self.assertContains(response, text)
        self.assertContains(response, reverse('phrase_swipe', args=[second.pk]))
        self.assertContains(response, reverse('phrase_swipe_undo', args=[second.pk]))

    def test_learned_and_foreign_cards_are_not_rendered(self):
        learned = make_phrase(self.user, original_phrase='Öğrenilmiş cümle')
        make_phrase(self.user, original_phrase='Çalışılacak cümle')
        make_phrase(User.objects.create_user('veli@example.com', PASSWORD), original_phrase='Yabancı cümle')
        set_progress(learned, status=PhraseProgress.Status.LEARNED, swipe_right_count=1)

        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Çalışılacak cümle')
        self.assertNotContains(response, 'Öğrenilmiş cümle')
        self.assertNotContains(response, 'Yabancı cümle')
        self.assertEqual((response.context['learned_count'], response.context['total_count']), (1, 2))

    def test_all_learned_shows_done_state_without_cards(self):
        phrase = make_phrase(self.user)
        set_progress(phrase, status=PhraseProgress.Status.LEARNED, swipe_right_count=1)
        response = self.client.get(reverse('home'))
        self.assertEqual(response.context['queue'], [])
        self.assertNotContains(response, 'class="study-card"')
        self.assertContains(response, 'Hepsini öğrendin')

    def test_no_phrases_shows_onboarding_without_deck(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Henüz phrase')
        self.assertNotContains(response, 'data-deck-root')


class PhraseListPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)

    def test_list_shows_status_badges_and_only_own_phrases(self):
        learned = make_phrase(self.user, original_phrase='Öğrenilmiş cümle')
        make_phrase(self.user, original_phrase='Öğrenilen cümle-2')
        make_phrase(User.objects.create_user('veli@example.com', PASSWORD), original_phrase='Yabancı cümle')
        set_progress(learned, status=PhraseProgress.Status.LEARNED)

        response = self.client.get(reverse('phrase_list'))
        self.assertContains(response, 'Öğrenildi')
        self.assertContains(response, 'Öğreniliyor')
        self.assertNotContains(response, 'Yabancı cümle')

    def test_list_requires_login_and_shows_empty_state(self):
        self.assertEqual(Client().get(reverse('phrase_list')).status_code, 302)
        self.assertContains(self.client.get(reverse('phrase_list')), 'Henüz phrase')

    def test_undo_button_is_shown_only_for_learned_phrases(self):
        learned = make_phrase(self.user, original_phrase='Öğrenilmiş cümle')
        learning = make_phrase(self.user, original_phrase='Öğrenilen cümle-2')
        set_progress(learned, status=PhraseProgress.Status.LEARNED)

        response = self.client.get(reverse('phrase_list'))
        self.assertContains(response, reverse('phrase_relearn', args=[learned.pk]))
        self.assertNotContains(response, reverse('phrase_relearn', args=[learning.pk]))
        self.assertContains(response, 'Geri al', count=1)


class RelearnTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)
        self.phrase = make_phrase(self.user)
        self.url = reverse('phrase_relearn', args=[self.phrase.pk])

    def learn(self):
        set_progress(
            self.phrase, status=PhraseProgress.Status.LEARNED, swipe_left_count=2, swipe_right_count=3,
            last_reviewed_at=timezone.now(),
        )

    def test_relearn_puts_learned_phrase_back_into_the_queue_and_keeps_history(self):
        self.learn()
        self.assertEqual(get_study_queue(self.user), [])

        response = self.client.post(self.url)
        self.assertRedirects(response, reverse('phrase_list'))
        progress = progress_of(self.phrase)
        self.assertEqual(progress.status, PhraseProgress.Status.LEARNING)
        self.assertEqual((progress.swipe_left_count, progress.swipe_right_count), (2, 3))
        self.assertEqual([item.phrase_id for item in get_study_queue(self.user)], [self.phrase.pk])

    def test_relearn_shows_confirmation_message(self):
        self.learn()
        response = self.client.post(self.url, follow=True)
        self.assertContains(response, 'tekrar çalışma kuyruğuna alındı')

    def test_relearn_on_a_learning_phrase_changes_nothing(self):
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse('phrase_list'))
        self.assertEqual(progress_of(self.phrase).status, PhraseProgress.Status.LEARNING)

    def test_relearn_requires_post(self):
        self.learn()
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(progress_of(self.phrase).status, PhraseProgress.Status.LEARNED)

    def test_anonymous_is_redirected_to_login_and_nothing_changes(self):
        self.learn()
        response = Client().post(self.url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.url}")
        self.assertEqual(progress_of(self.phrase).status, PhraseProgress.Status.LEARNED)

    def test_other_users_phrase_is_404_and_unchanged(self):
        self.learn()
        self.client.force_login(User.objects.create_user('veli@example.com', PASSWORD))
        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.assertEqual(progress_of(self.phrase).status, PhraseProgress.Status.LEARNED)

    def test_unknown_phrase_is_404(self):
        self.assertEqual(self.client.post(reverse('phrase_relearn', args=[999999])).status_code, 404)

    def test_csrf_is_enforced(self):
        self.learn()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url).status_code, 403)
        self.assertEqual(progress_of(self.phrase).status, PhraseProgress.Status.LEARNED)
