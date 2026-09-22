"""Aralıklı tekrar (24 saat aralık, üst üste 3 başarı), sesli okuma düğmesi ve istatistik ekranı testleri."""

from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.users.models import User

from .models import PhraseProgress
from .services import get_progress_summary, get_study_queue, record_swipe, restudy, review_interval_label, undo_swipe
from .templatetags.phrase_extras import until_text
from .tests import make_phrase

PASSWORD = 'gizli-parola-123'
Status = PhraseProgress.Status
DAY = timedelta(hours=24)


def progress_of(phrase):
    return PhraseProgress.objects.get(phrase=phrase)


def set_progress(phrase, **fields):
    PhraseProgress.objects.filter(phrase=phrase).update(**fields)


class ReviewCycleTests(TestCase):
    """record_swipe: kullanıcının tarif ettiği tekrar kuralları."""

    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.phrase = make_phrase(self.user)
        self.t0 = timezone.now()

    def swipe(self, direction, at):
        with patch('django.utils.timezone.now', return_value=at):
            return record_swipe(self.user, self.phrase.pk, direction)

    def test_first_success_is_the_first_of_three_and_comes_back_after_24_hours(self):
        progress = self.swipe('right', self.t0)
        self.assertEqual((progress.status, progress.review_streak), (Status.REVIEWING, 1))
        self.assertEqual(progress.next_review_at, self.t0 + DAY)
        self.assertEqual(progress.swipe_right_count, 1)

    def test_card_is_out_of_the_queue_until_24_hours_have_passed(self):
        self.swipe('right', self.t0)
        with patch('django.utils.timezone.now', return_value=self.t0 + DAY - timedelta(minutes=1)):
            self.assertEqual(get_study_queue(self.user, 'en'), [])
        with patch('django.utils.timezone.now', return_value=self.t0 + DAY):
            self.assertEqual([item.phrase_id for item in get_study_queue(self.user, 'en')], [self.phrase.pk])

    def test_three_successes_in_a_row_make_the_card_permanently_learned(self):
        self.swipe('right', self.t0)
        self.swipe('right', self.t0 + DAY)
        progress = self.swipe('right', self.t0 + 2 * DAY)
        self.assertEqual((progress.status, progress.review_streak), (Status.LEARNED, 3))
        self.assertIsNone(progress.next_review_at)
        self.assertEqual(progress.swipe_right_count, 3)
        with patch('django.utils.timezone.now', return_value=self.t0 + 30 * DAY):
            self.assertEqual(get_study_queue(self.user, 'en'), [])

    def test_second_success_keeps_it_in_review_with_a_new_24_hour_wait(self):
        self.swipe('right', self.t0)
        progress = self.swipe('right', self.t0 + DAY)
        self.assertEqual((progress.status, progress.review_streak), (Status.REVIEWING, 2))
        self.assertEqual(progress.next_review_at, self.t0 + 2 * DAY)

    def test_user_example_day0_success_day1_success_day2_fail_resets_and_needs_three_again(self):
        self.swipe('right', self.t0)                       # gün 0: 1/3
        self.swipe('right', self.t0 + DAY)                 # gün 1: 2/3
        failed = self.swipe('left', self.t0 + 2 * DAY)     # gün 2: henüz değil
        self.assertEqual((failed.status, failed.review_streak), (Status.LEARNING, 0))
        self.assertIsNone(failed.next_review_at)
        self.assertEqual(failed.swipe_left_count, 1)
        # Kart hemen normal çalışma kuyruğuna döner.
        with patch('django.utils.timezone.now', return_value=self.t0 + 2 * DAY):
            self.assertEqual([item.phrase_id for item in get_study_queue(self.user, 'en')], [self.phrase.pk])

        self.swipe('right', self.t0 + 2 * DAY)
        self.swipe('right', self.t0 + 3 * DAY)
        self.assertEqual(progress_of(self.phrase).status, Status.REVIEWING)   # 2/3: henüz kalıcı değil
        done = self.swipe('right', self.t0 + 4 * DAY)
        self.assertEqual(done.status, Status.LEARNED)

    def test_left_swipe_in_the_same_session_also_resets_to_zero(self):
        self.swipe('right', self.t0)
        progress = self.swipe('left', self.t0 + timedelta(minutes=1))
        self.assertEqual((progress.status, progress.review_streak), (Status.LEARNING, 0))

    def test_success_on_a_card_that_is_not_due_yet_is_ignored(self):
        """Aynı isteğin tekrarı ya da eski bir sayfa, başarı sayacını iki kez artırmaz."""
        self.swipe('right', self.t0)
        progress = self.swipe('right', self.t0 + timedelta(hours=1))
        self.assertEqual((progress.status, progress.review_streak, progress.swipe_right_count), (Status.REVIEWING, 1, 1))
        self.assertEqual(progress.next_review_at, self.t0 + DAY)

    def test_success_on_a_learned_card_changes_nothing(self):
        set_progress(self.phrase, status=Status.LEARNED, review_streak=3, swipe_right_count=3)
        progress = record_swipe(self.user, self.phrase.pk, 'right')
        self.assertEqual((progress.status, progress.review_streak, progress.swipe_right_count), (Status.LEARNED, 3, 3))

    def test_interval_is_configurable(self):
        with override_settings(REVIEW_INTERVAL_MINUTES=1):
            progress = self.swipe('right', self.t0)
        self.assertEqual(progress.next_review_at, self.t0 + timedelta(minutes=1))

    def test_interval_label_is_human_readable(self):
        self.assertEqual(review_interval_label(), '24 saat')
        with override_settings(REVIEW_INTERVAL_MINUTES=90):
            self.assertEqual(review_interval_label(), '90 dakika')
        with override_settings(REVIEW_INTERVAL_MINUTES=1):
            self.assertEqual(review_interval_label(), '1 dakika')

    def test_invalid_direction_and_unknown_phrase(self):
        with self.assertRaises(ValueError):
            record_swipe(self.user, self.phrase.pk, 'up')
        self.assertIsNone(record_swipe(self.user, 999999, 'right'))
        other = User.objects.create_user('veli@example.com', PASSWORD)
        self.assertIsNone(record_swipe(other, self.phrase.pk, 'right'))
        self.assertEqual(progress_of(self.phrase).status, Status.LEARNING)


class ReviewUndoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.phrase = make_phrase(self.user)

    def test_undo_first_success_returns_to_unseen_learning(self):
        record_swipe(self.user, self.phrase.pk, 'right')
        progress = undo_swipe(self.user, self.phrase.pk)
        self.assertEqual((progress.status, progress.review_streak, progress.swipe_right_count), (Status.LEARNING, 0, 0))
        self.assertIsNone(progress.next_review_at)
        self.assertIsNone(progress.last_reviewed_at)

    def test_undo_second_success_returns_to_first_and_the_card_is_due_immediately(self):
        set_progress(
            self.phrase, status=Status.REVIEWING, review_streak=1, swipe_right_count=1,
            next_review_at=timezone.now() - timedelta(minutes=1),
        )
        record_swipe(self.user, self.phrase.pk, 'right')   # 2/3, 24 saat bekler
        self.assertEqual(get_study_queue(self.user, 'en'), [])

        progress = undo_swipe(self.user, self.phrase.pk)
        self.assertEqual((progress.status, progress.review_streak, progress.swipe_right_count), (Status.REVIEWING, 1, 1))
        self.assertEqual([item.phrase_id for item in get_study_queue(self.user, 'en')], [self.phrase.pk])

    def test_undo_the_third_success_reopens_a_learned_card_as_second(self):
        set_progress(
            self.phrase, status=Status.REVIEWING, review_streak=2, swipe_right_count=2,
            next_review_at=timezone.now() - timedelta(minutes=1),
        )
        record_swipe(self.user, self.phrase.pk, 'right')
        self.assertEqual(progress_of(self.phrase).status, Status.LEARNED)

        progress = undo_swipe(self.user, self.phrase.pk)
        self.assertEqual((progress.status, progress.review_streak), (Status.REVIEWING, 2))
        self.assertEqual([item.phrase_id for item in get_study_queue(self.user, 'en')], [self.phrase.pk])

    def test_nothing_to_undo_for_a_learning_card_or_other_users(self):
        self.assertIsNone(undo_swipe(self.user, self.phrase.pk))
        record_swipe(self.user, self.phrase.pk, 'right')
        self.assertIsNone(undo_swipe(User.objects.create_user('veli@example.com', PASSWORD), self.phrase.pk))
        self.assertEqual(progress_of(self.phrase).review_streak, 1)


class ReviewQueueTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)

    def titles(self):
        return [item.phrase.original_phrase for item in get_study_queue(self.user, 'en')]

    def test_due_reviews_come_first_most_overdue_first_then_seen_then_unseen(self):
        now = timezone.now()
        make_phrase(self.user, original_phrase='Yeni')
        seen = make_phrase(self.user, original_phrase='Görülmüş')
        old_review = make_phrase(self.user, original_phrase='Eski tekrar')
        recent_review = make_phrase(self.user, original_phrase='Yeni tekrar')
        set_progress(seen, swipe_left_count=1, last_reviewed_at=now - timedelta(hours=1))
        set_progress(
            old_review, status=Status.REVIEWING, review_streak=1, swipe_right_count=1,
            last_reviewed_at=now - 2 * DAY, next_review_at=now - timedelta(hours=10),
        )
        set_progress(
            recent_review, status=Status.REVIEWING, review_streak=1, swipe_right_count=1,
            last_reviewed_at=now - DAY, next_review_at=now - timedelta(hours=1),
        )
        self.assertEqual(self.titles(), ['Eski tekrar', 'Yeni tekrar', 'Görülmüş', 'Yeni'])

    def test_reviews_that_are_not_due_and_learned_cards_stay_out(self):
        waiting = make_phrase(self.user, original_phrase='Bekleyen')
        learned = make_phrase(self.user, original_phrase='Öğrenilmiş')
        make_phrase(self.user, original_phrase='Çalışılacak')
        set_progress(waiting, status=Status.REVIEWING, review_streak=1, next_review_at=timezone.now() + timedelta(hours=3))
        set_progress(learned, status=Status.LEARNED, review_streak=3)
        self.assertEqual(self.titles(), ['Çalışılacak'])


class RestudyTests(TestCase):
    def test_restudy_resets_the_streak_so_three_new_successes_are_needed(self):
        user = User.objects.create_user('ali@example.com', PASSWORD)
        phrase = make_phrase(user)
        set_progress(phrase, status=Status.LEARNED, review_streak=3, swipe_right_count=3)
        self.assertTrue(restudy(user, phrase.pk))
        progress = progress_of(phrase)
        self.assertEqual((progress.status, progress.review_streak, progress.swipe_right_count), (Status.LEARNING, 0, 3))
        record_swipe(user, phrase.pk, 'right')
        self.assertEqual(progress_of(phrase).status, Status.REVIEWING)


class ReviewPagesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)

    def test_swipe_endpoint_reports_the_streak_and_next_review_time(self):
        phrase = make_phrase(self.user)
        url = reverse('phrase_swipe', args=[phrase.pk])
        first = self.client.post(url, {'direction': 'right'}).json()
        self.assertEqual((first['status'], first['review_streak']), ('reviewing', 1))
        self.assertTrue(first['next_review_at'])
        left = self.client.post(url, {'direction': 'left'}).json()
        self.assertEqual((left['status'], left['review_streak'], left['next_review_at']), ('learning', 0, None))

    def test_home_shows_review_counter_badge_and_done_message(self):
        reviewing = make_phrase(self.user, original_phrase='Tekrar cümlesi')
        waiting = make_phrase(self.user, original_phrase='Bekleyen cümle')
        set_progress(reviewing, status=Status.REVIEWING, review_streak=2, next_review_at=timezone.now() - timedelta(minutes=1))
        set_progress(waiting, status=Status.REVIEWING, review_streak=1, next_review_at=timezone.now() + timedelta(hours=5))

        response = self.client.get(reverse('home'))
        self.assertEqual([item.phrase_id for item in response.context['queue']], [reviewing.pk])
        self.assertEqual(response.context['reviewing_count'], 2)
        self.assertContains(response, 'Tekrar · 2/3')
        self.assertContains(response, 'data-status="reviewing"')
        self.assertNotContains(response, 'Bekleyen cümle')

    def test_home_done_state_mentions_reviews_when_cards_are_waiting(self):
        phrase = make_phrase(self.user)
        set_progress(phrase, status=Status.REVIEWING, review_streak=1, next_review_at=timezone.now() + timedelta(hours=5))
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Bugünlük bu kadar')
        self.assertNotContains(response, 'Hepsini öğrendin')
        self.assertTrue(response.context['next_review_at'])

    def test_list_shows_the_review_badge_with_progress_and_wait(self):
        phrase = make_phrase(self.user)
        set_progress(phrase, status=Status.REVIEWING, review_streak=1, next_review_at=timezone.now() + timedelta(hours=5, minutes=30))
        response = self.client.get(reverse('phrase_list'))
        self.assertContains(response, 'Tekrarda 1/3 · 6 sa sonra')
        self.assertNotContains(response, reverse('phrase_relearn', args=[phrase.pk]))

    def test_list_shows_due_review_as_ready(self):
        phrase = make_phrase(self.user)
        set_progress(phrase, status=Status.REVIEWING, review_streak=2, next_review_at=timezone.now() - timedelta(minutes=5))
        self.assertContains(self.client.get(reverse('phrase_list')), 'Tekrarda 2/3 · zamanı geldi')


class UntilTextTests(TestCase):
    def test_formats_short_turkish_waits(self):
        now = timezone.now()
        self.assertEqual(until_text(None), '')
        self.assertEqual(until_text(now - timedelta(minutes=1)), 'şimdi')
        self.assertEqual(until_text(now + timedelta(minutes=12)), '12 dk sonra')
        self.assertEqual(until_text(now + timedelta(hours=5, minutes=1)), '6 sa sonra')
        self.assertEqual(until_text(now + timedelta(hours=24)), '1 gün sonra')
        self.assertEqual(until_text(now + timedelta(hours=49)), '3 gün sonra')


class SpeakButtonTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)
        self.phrase = make_phrase(self.user, original_phrase='Break the ice')

    def test_card_and_detail_have_a_speak_button_with_the_english_text(self):
        for url in (reverse('home'), reverse('phrase_detail', args=[self.phrase.pk])):
            response = self.client.get(url)
            self.assertContains(response, 'data-speak="Break the ice"')
            self.assertContains(response, 'js/speak.js')

    def test_speak_text_is_escaped(self):
        make_phrase(self.user, original_phrase='Say "hi" & <b>go</b>')
        content = self.client.get(reverse('home')).content.decode()
        self.assertIn('data-speak="Say &quot;hi&quot; &amp; &lt;b&gt;go&lt;/b&gt;"', content)

    def test_speak_button_include_does_not_leak_its_own_template_comment(self):
        # Django {# #} yorumları birden fazla satıra bölünemez; bölünürse yorum metni sayfada görünür kalır.
        for url in (reverse('home'), reverse('phrase_detail', args=[self.phrase.pk])):
            self.assertNotContains(self.client.get(url), '{#')


class StatsPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali@example.com', PASSWORD)
        self.client.force_login(self.user)

    def build(self):
        now = timezone.now()
        learning = make_phrase(self.user, original_phrase='A', source='manual')
        due = make_phrase(self.user, original_phrase='B', source='ai_generated')
        waiting = make_phrase(self.user, original_phrase='C', source='ai_generated')
        learned = make_phrase(self.user, original_phrase='D')
        set_progress(learning, swipe_left_count=2)
        set_progress(due, status=Status.REVIEWING, review_streak=1, swipe_right_count=1, next_review_at=now - timedelta(hours=1))
        set_progress(waiting, status=Status.REVIEWING, review_streak=2, swipe_right_count=2, next_review_at=now + timedelta(hours=7))
        set_progress(learned, status=Status.LEARNED, review_streak=3, swipe_right_count=3)

    def test_summary_counts(self):
        self.build()
        summary = get_progress_summary(self.user, 'en')
        self.assertEqual(
            {key: summary[key] for key in ('total', 'learning', 'reviewing', 'learned', 'due_reviews', 'queue_size')},
            {'total': 4, 'learning': 1, 'reviewing': 2, 'learned': 1, 'due_reviews': 1, 'queue_size': 2},
        )
        self.assertEqual((summary['right_total'], summary['left_total']), (6, 2))
        self.assertGreater(summary['next_review_at'], timezone.now())

    def test_stats_page_shows_counts_sources_and_next_review(self):
        self.build()
        response = self.client.get(reverse('stats'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '1</strong> / 4 phrase kalıcı öğrenildi')
        for label in ('Öğreniliyor', 'Tekrarda', 'Öğrenildi', 'Şu an çalışılacak', 'AI ile üretilen', 'Sıradaki tekrar'):
            self.assertContains(response, label)
        self.assertContains(response, '<dt>AI ile üretilen</dt><dd>2</dd>')
        self.assertContains(response, '<dt>Manuel eklenen</dt><dd>2</dd>')
        self.assertContains(response, '<strong>1</strong> kartın tekrar zamanı geldi')

    def test_stats_are_per_user(self):
        make_phrase(User.objects.create_user('veli@example.com', PASSWORD), original_phrase='Yabancı')
        self.assertContains(self.client.get(reverse('stats')), 'Henüz phrase')

    def test_stats_requires_login_and_topbar_links_to_it(self):
        self.assertEqual(Client().get(reverse('stats')).status_code, 302)
        self.assertContains(self.client.get(reverse('phrase_list')), reverse('stats'))
