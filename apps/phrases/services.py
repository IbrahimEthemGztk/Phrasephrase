"""Çalışma (kart yığını) mantığı: kuyruk kurma, swipe kayıtları ve aralıklı tekrar.

Aralıklı tekrar kuralları:
- "Ezberledim" kartı hemen kalıcı yapmaz; kart `reviewing` olur ve REVIEW_INTERVAL_MINUTES (24 saat)
  sonra Kartlar ekranına geri döner. İlk "ezberledim" 3 başarının ilkidir.
- Üst üste REVIEW_TARGET (3) başarıda kart kalıcı `learned` olur.
- "Henüz değil" başarı sayacını sıfırlar; kart `learning` olarak baştan başlar.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Min, Q, Sum, Value, When
from django.utils import timezone

from .models import Phrase, PhraseProgress

RIGHT = 'right'
LEFT = 'left'
DIRECTIONS = (RIGHT, LEFT)

STUDY_QUEUE_LIMIT = 50
REVIEW_TARGET = 3   # kalıcı öğrenilmiş sayılmak için gereken üst üste başarı


def review_interval():
    return timedelta(minutes=settings.REVIEW_INTERVAL_MINUTES)


def review_interval_label():
    """Aralığın okunaklı hali: "24 saat", "90 dakika"."""
    minutes = settings.REVIEW_INTERVAL_MINUTES
    return f'{minutes // 60} saat' if minutes % 60 == 0 else f'{minutes} dakika'


def is_due(progress, now=None):
    """Kart şu an çalışılabilir mi: öğreniliyor ya da tekrar zamanı gelmiş."""
    now = now or timezone.now()
    if progress.status == PhraseProgress.Status.LEARNING:
        return True
    return (
        progress.status == PhraseProgress.Status.REVIEWING
        and progress.next_review_at is not None
        and progress.next_review_at <= now
    )


def get_study_queue(user, language, limit=STUDY_QUEUE_LIMIT):
    """Kullanıcının `language` (hedef dil kodu) için çalışma kuyruğunu döndürür (PhraseProgress listesi).

    Girenler: `learning` kartlar ve tekrar zamanı gelmiş `reviewing` kartlar. Sıra: önce zamanı gelmiş
    tekrarlar (en çok geciken önce), sonra görülüp öğrenilememiş kartlar (en eski gözden geçirilen önce),
    en sonda hiç görülmemişler (eklenme sırasıyla). "Hiç görülmemiş" = iki swipe sayacı da sıfır.
    """
    Status = PhraseProgress.Status
    rank = Case(
        When(status=Status.REVIEWING, then=Value(0)),
        When(swipe_left_count=0, swipe_right_count=0, then=Value(2)),
        default=Value(1),
        output_field=IntegerField(),
    )
    queryset = (
        PhraseProgress.objects
        .filter(Q(status=Status.LEARNING) | Q(status=Status.REVIEWING, next_review_at__lte=timezone.now()))
        .filter(user=user, phrase__target_language=language)
        .select_related('phrase')
        .annotate(rank=rank)
        .order_by(
            'rank', F('next_review_at').asc(nulls_last=True), F('last_reviewed_at').asc(nulls_last=True),
            'phrase__created_at', 'phrase_id',
        )
    )
    return list(queryset[:limit])


def get_progress_summary(user, language):
    """`language` (hedef dil kodu) için phrase sayıları: toplam, durumlara göre dağılım, sıradaki tekrar zamanı."""
    Status = PhraseProgress.Status
    now = timezone.now()
    summary = user.phrase_progress.filter(phrase__target_language=language).aggregate(
        total=Count('id'),
        learning=Count('id', filter=Q(status=Status.LEARNING)),
        reviewing=Count('id', filter=Q(status=Status.REVIEWING)),
        learned=Count('id', filter=Q(status=Status.LEARNED)),
        due_reviews=Count('id', filter=Q(status=Status.REVIEWING, next_review_at__lte=now)),
        next_review_at=Min('next_review_at', filter=Q(status=Status.REVIEWING, next_review_at__gt=now)),
        right_total=Sum('swipe_right_count'),
        left_total=Sum('swipe_left_count'),
    )
    summary['right_total'] = summary['right_total'] or 0
    summary['left_total'] = summary['left_total'] or 0
    summary['queue_size'] = summary['learning'] + summary['due_reviews']
    return summary


def get_source_counts(user, language):
    """`language` (hedef dil kodu) için kaynağa göre phrase sayısı: {'manual': n, 'ai_generated': m}."""
    counts = user.phrases.filter(target_language=language).aggregate(
        manual=Count('id', filter=Q(source=Phrase.Source.MANUAL)),
        ai_generated=Count('id', filter=Q(source=Phrase.Source.AI_GENERATED)),
    )
    return counts


@transaction.atomic
def record_swipe(user, phrase_id, direction):
    """Swipe'ı kaydeder. Güncel PhraseProgress'i döndürür, kayıt yoksa None.

    Sağ ("ezberledim"): başarı sayacı 1 artar; 3'e ulaşınca `learned`, aksi halde `reviewing` ve
    `next_review_at = şimdi + aralık`. Yalnızca çalışılabilir (due) kart ilerler: aynı isteğin tekrarı
    ya da eski bir sayfadan gelen istek sayacı iki kez artırmaz, hiçbir şey değişmez.
    Sol ("henüz değil"): sayaç sıfırlanır, kart `learning` olarak baştan başlar.
    """
    if direction not in DIRECTIONS:
        raise ValueError(f'Geçersiz yön: {direction!r}')

    progress = PhraseProgress.objects.select_for_update().filter(user=user, phrase_id=phrase_id).first()
    if progress is None:
        return None

    now = timezone.now()
    if direction == RIGHT:
        if not is_due(progress, now):
            return progress
        progress.swipe_right_count += 1
        progress.review_streak += 1
        if progress.review_streak >= REVIEW_TARGET:
            progress.status = PhraseProgress.Status.LEARNED
            progress.next_review_at = None
        else:
            progress.status = PhraseProgress.Status.REVIEWING
            progress.next_review_at = now + review_interval()
    else:
        progress.swipe_left_count += 1
        progress.review_streak = 0
        progress.status = PhraseProgress.Status.LEARNING
        progress.next_review_at = None

    progress.last_reviewed_at = now
    progress.save()
    return progress


def restudy(user, phrase_id):
    """Öğrenilmiş bir phrase'i baştan çalışmaya alır: `learning`, başarı sayacı sıfır.

    Swipe sayaçları ve geçmiş korunur; phrase öğrenilmiş değilse (öğreniliyor / tekrarda) bir şey değişmez.
    Kullanıcının böyle bir phrase'i yoksa False döndürür.
    """
    own = PhraseProgress.objects.filter(user=user, phrase_id=phrase_id)
    if not own.exists():
        return False
    own.filter(status=PhraseProgress.Status.LEARNED).update(
        status=PhraseProgress.Status.LEARNING, review_streak=0, next_review_at=None,
    )
    return True


@transaction.atomic
def undo_swipe(user, phrase_id):
    """Son "ezberledim"i geri alır. Geri alınacak bir şey yoksa None döndürür.

    Başarı sayacı 1 azalır: 0'a inerse kart `learning`, değilse zamanı gelmiş `reviewing` olur
    (kartlar ekranındaki kuyruğun başına dönebilsin diye). Sayaçlar sıfırın altına inmez.
    Kart hiç görülmemiş haline dönerse (iki sayaç da sıfır) `last_reviewed_at` de temizlenir.
    "Henüz değil" geri alınamaz: sıfırlanan sayacın önceki değeri saklanmaz.
    """
    progress = PhraseProgress.objects.select_for_update().filter(user=user, phrase_id=phrase_id).first()
    if (
        progress is None
        or progress.swipe_right_count <= 0
        or progress.review_streak <= 0
        or progress.status == PhraseProgress.Status.LEARNING
    ):
        return None

    progress.swipe_right_count -= 1
    progress.review_streak -= 1
    if progress.review_streak == 0:
        progress.status = PhraseProgress.Status.LEARNING
        progress.next_review_at = None
    else:
        progress.status = PhraseProgress.Status.REVIEWING
        progress.next_review_at = timezone.now()
    if progress.swipe_left_count == 0 and progress.swipe_right_count == 0:
        progress.last_reviewed_at = None
    progress.save()
    return progress
